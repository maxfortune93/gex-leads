import json
import logging
from contextlib import contextmanager
from datetime import datetime
from typing import Callable

import pymysql
from pymysql.cursors import DictCursor

from app.config import Settings

log = logging.getLogger("repository")


DEADLOCK_CODES = (1213, 1205)  # deadlock / lock wait timeout


class DatabaseUnavailable(Exception):
    pass


class TransientDbError(Exception):
    """Deadlock ou lock timeout: a transacao pode ser repetida."""


class Repository:
    """Acesso ao MySQL. Uma conexao por operacao (simples; troque por pool se precisar de escala)."""

    def __init__(self, settings: Settings):
        self._s = settings

    def _connect(self):
        try:
            return pymysql.connect(
                host=self._s.mysql_host,
                port=self._s.mysql_port,
                user=self._s.mysql_user,
                password=self._s.mysql_password,
                database=self._s.mysql_database,
                charset="utf8mb4",
                cursorclass=DictCursor,
                autocommit=False,
                connect_timeout=5,
            )
        except pymysql.err.OperationalError as exc:
            raise DatabaseUnavailable(str(exc.args[0])) from exc

    @contextmanager
    def _tx(self):
        conn = self._connect()
        try:
            yield conn.cursor()
            conn.commit()
        except pymysql.err.OperationalError as exc:
            conn.rollback()
            if exc.args[0] in DEADLOCK_CODES:
                raise TransientDbError(str(exc.args[0])) from exc
            raise DatabaseUnavailable(str(exc.args[0])) from exc
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ---------------- API ----------------

    def save_raw(self, correlation_id: str, headers: dict, body: str) -> int:
        with self._tx() as cur:
            cur.execute(
                "INSERT INTO raw_requests (correlation_id, headers, body) VALUES (%s, %s, %s)",
                (correlation_id, json.dumps(headers), body),
            )
            return cur.lastrowid

    def finish_raw(self, raw_id: int, result: str, transaction_id=None, event=None, error=None) -> None:
        with self._tx() as cur:
            cur.execute(
                "UPDATE raw_requests SET result=%s, transaction_id=%s, event=%s, error_summary=%s,"
                " processed_at=CURRENT_TIMESTAMP(3) WHERE id=%s",
                (result, transaction_id, event, error, raw_id),
            )

    def publish_once(self, transaction_id: str, event: str, correlation_id: str,
                     publish: Callable[[], None]) -> bool:
        """Garante publicacao unica da chave (transaction_id, event).

        Dentro de UMA transacao: INSERT IGNORE + SELECT ... FOR UPDATE tomam o lock da linha
        (UNIQUE KEY), entao requisicoes concorrentes - de qualquer processo - serializam aqui.
        `publish` roda com o lock; se levantar, a transacao faz rollback e a linha some
        (nada fica 'publicado' sem ter sido publicado) -> retry seguro.
        Retorna True se publicou agora, False se ja estava publicado (duplicado).

        Deadlocks (varios INSERT IGNORE concorrentes seguram lock S e todos pedem X) sao
        repetidos: a vitima faz rollback e na releitura ve 'published'.
        """
        for attempt in range(5):
            try:
                return self._publish_once(transaction_id, event, correlation_id, publish)
            except TransientDbError:
                if attempt == 4:
                    raise DatabaseUnavailable("lock contention")
        raise DatabaseUnavailable("unreachable")  # pragma: no cover

    def _publish_once(self, transaction_id, event, correlation_id, publish) -> bool:
        with self._tx() as cur:
            cur.execute(
                "INSERT IGNORE INTO webhook_events (transaction_id, event, correlation_id) VALUES (%s, %s, %s)",
                (transaction_id, event, correlation_id),
            )
            cur.execute(
                "SELECT status FROM webhook_events WHERE transaction_id=%s AND event=%s FOR UPDATE",
                (transaction_id, event),
            )
            if cur.fetchone()["status"] == "published":
                return False
            publish()  # pode levantar BrokerUnavailable -> rollback
            cur.execute(
                "UPDATE webhook_events SET status='published', published_at=CURRENT_TIMESTAMP(3)"
                " WHERE transaction_id=%s AND event=%s",
                (transaction_id, event),
            )
            return True

    # ---------------- Worker ----------------

    def persist_lead(self, msg: dict) -> None:
        """Cliente + pedido + evento numa transacao. Idempotente por UNIQUE KEYs (redelivery-safe)."""
        customer, product, payment = msg["customer"], msg["product"], msg["payment"]
        when = datetime.fromisoformat(msg["transaction_time"]).replace(tzinfo=None)  # ja em UTC
        with self._tx() as cur:
            cur.execute(
                "INSERT INTO customers (email, first_name, phone, country) VALUES (%s, %s, %s, %s)"
                " ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id)",
                (customer["email"], customer["first_name"], customer["phone"], customer["country"]),
            )
            customer_id = cur.lastrowid
            cur.execute(
                "INSERT IGNORE INTO orders (transaction_id, customer_id, product_id, product_name, country,"
                " amount_usd, transaction_time) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (msg["transaction_id"], customer_id, product["id"], product["name"], customer["country"],
                 payment["amount_usd"], when),
            )
            cur.execute("SELECT id FROM orders WHERE transaction_id=%s", (msg["transaction_id"],))
            order_id = cur.fetchone()["id"]
            cur.execute(
                "INSERT IGNORE INTO order_events (order_id, event, payment_status, correlation_id)"
                " VALUES (%s, %s, %s, %s)",
                (order_id, msg["event"], payment["status"], msg["correlation_id"]),
            )
