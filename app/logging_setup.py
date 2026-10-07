"""Logs JSON estruturados. Nunca passe e-mail, telefone, chave ou payload decriptado em `extra`."""

import json
import logging
import sys

# Unicos campos de `extra` que chegam ao JSON final (allowlist evita vazar PII por engano).
_ALLOWED = ("correlation_id", "transaction_id", "event", "step", "result", "duration_ms", "attempt", "error")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in _ALLOWED:
            if hasattr(record, key):
                data[key] = getattr(record, key)
        return json.dumps(data, ensure_ascii=False)


def setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    logging.getLogger("pika").setLevel(logging.WARNING)
