"""Worker: consome lead.received, persiste no MySQL e controla retry/DLQ.

Retry: em falha temporaria a mensagem e republicada na mesma fila com x-attempt+1 (confirmado)
e a original recebe ack. Na 3a falha vai para a DLQ. Assim nenhuma mensagem e perdida: so damos
ack depois que a copia (retry ou DLQ) foi confirmada pelo broker; se isso falhar, nack+requeue.
"""

import json
import logging
import time

import pika

from app.broker import BrokerUnavailable, Publisher, connection_params, declare_queues
from app.config import MAX_ATTEMPTS, QUEUE_DEAD, QUEUE_RECEIVED, Settings
from app.logging_setup import setup_logging
from app.repository import Repository

log = logging.getLogger("worker")


class PermanentError(Exception):
    """Falha que nao adianta repetir (mensagem ilegivel/invalida)."""


def process_message(body: bytes, attempt: int, repo, publisher) -> str:
    """Logica pura (testavel com fakes). Retorna: 'ok' | 'retry' | 'dead'.
    Levanta BrokerUnavailable se nao conseguiu republicar -> o chamador faz nack+requeue."""
    started = time.perf_counter()
    msg, correlation_id, transaction_id = None, None, None
    try:
        try:
            msg = json.loads(body)
            correlation_id, transaction_id = msg["correlation_id"], msg["transaction_id"]
        except (ValueError, KeyError, TypeError) as exc:
            raise PermanentError(f"mensagem invalida: {type(exc).__name__}") from exc

        repo.persist_lead(msg)  # transacao unica; commit antes do ack
        _log("persisted", "ok", correlation_id, transaction_id, msg.get("event"), attempt, started)
        return "ok"

    except Exception as exc:
        permanent = isinstance(exc, PermanentError)
        summary = f"{type(exc).__name__}: {exc}"[:300]
        _log("persist failed", "error", correlation_id, transaction_id, (msg or {}).get("event"),
             attempt, started, summary)
        if not permanent and attempt < MAX_ATTEMPTS:
            publisher.publish(QUEUE_RECEIVED, msg, {"x-attempt": attempt + 1})
            return "retry"
        publisher.publish(QUEUE_DEAD, {
            "original_message": msg if msg is not None else body.decode("utf-8", errors="replace"),
            "correlation_id": correlation_id,
            "attempts": attempt,
            "error": summary,
        })
        return "dead"


def _log(message, result, correlation_id, transaction_id, event, attempt, started, error=None):
    extra = {"correlation_id": correlation_id, "transaction_id": transaction_id, "event": event,
             "step": "worker", "result": result, "attempt": attempt,
             "duration_ms": round((time.perf_counter() - started) * 1000, 1)}
    if error:
        extra["error"] = error
    log.info(message, extra=extra)


def run() -> None:
    setup_logging()
    settings = Settings.from_env()
    repo, publisher = Repository(settings), Publisher(settings)

    while True:  # reconecta se o RabbitMQ cair
        try:
            conn = pika.BlockingConnection(connection_params(settings))
            ch = conn.channel()
            declare_queues(ch)
            ch.basic_qos(prefetch_count=10)

            def on_message(channel, method, properties, body):
                attempt = int((properties.headers or {}).get("x-attempt", 1))
                try:
                    process_message(body, attempt, repo, publisher)
                    channel.basic_ack(method.delivery_tag)  # so apos commit / retry / DLQ confirmados
                except BrokerUnavailable:
                    log.error("broker indisponivel ao republicar", extra={"step": "worker", "result": "requeue"})
                    channel.basic_nack(method.delivery_tag, requeue=True)

            ch.basic_consume(QUEUE_RECEIVED, on_message)
            log.info("worker started", extra={"step": "worker", "result": "ready"})
            ch.start_consuming()
        except (pika.exceptions.AMQPError, OSError) as exc:
            log.error("conexao perdida, reconectando", extra={"step": "worker", "error": type(exc).__name__})
            time.sleep(3)


if __name__ == "__main__":
    run()
