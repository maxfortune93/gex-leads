import json
import threading

import pika

from app.config import QUEUE_DEAD, QUEUE_RECEIVED, Settings


class BrokerUnavailable(Exception):
    pass


def connection_params(s: Settings) -> pika.ConnectionParameters:
    return pika.ConnectionParameters(
        host=s.rabbit_host,
        port=s.rabbit_port,
        credentials=pika.PlainCredentials(s.rabbit_user, s.rabbit_password),
        heartbeat=30,
        blocked_connection_timeout=10,
        socket_timeout=5,
    )


def declare_queues(channel) -> None:
    channel.queue_declare(queue=QUEUE_RECEIVED, durable=True)
    channel.queue_declare(queue=QUEUE_DEAD, durable=True)


class Publisher:
    """Publica com publisher confirms. Uma conexao reaproveitada, protegida por lock
    (pika.BlockingConnection nao e thread-safe) e recriada se cair."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._lock = threading.Lock()
        self._conn = None
        self._ch = None

    def _channel(self):
        if self._conn is None or self._conn.is_closed or self._ch is None or self._ch.is_closed:
            self._conn = pika.BlockingConnection(connection_params(self._settings))
            self._ch = self._conn.channel()
            self._ch.confirm_delivery()
            declare_queues(self._ch)
        return self._ch

    def publish(self, queue: str, message: dict, headers: dict | None = None) -> None:
        """Retorna somente apos o broker confirmar. Qualquer falha vira BrokerUnavailable."""
        with self._lock:
            try:
                self._channel().basic_publish(
                    exchange="",
                    routing_key=queue,
                    body=json.dumps(message).encode(),
                    properties=pika.BasicProperties(
                        delivery_mode=2,
                        content_type="application/json",
                        correlation_id=message.get("correlation_id"),
                        headers=headers or {},
                    ),
                    mandatory=True,
                )
            except Exception as exc:  # pika levanta varias excecoes (AMQP, nack, unroutable)
                self._reset()
                raise BrokerUnavailable(type(exc).__name__) from exc

    def _reset(self):
        try:
            if self._conn and self._conn.is_open:
                self._conn.close()
        except Exception:
            pass
        self._conn = self._ch = None
