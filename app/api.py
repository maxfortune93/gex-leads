import json
import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.broker import BrokerUnavailable, Publisher
from app.config import QUEUE_RECEIVED, Settings
from app.crypto import DecryptError, decrypt_payload
from app.logging_setup import setup_logging
from app.repository import DatabaseUnavailable, Repository
from app.schema import SchemaError, is_approved_sale, validate_and_normalize

log = logging.getLogger("api")

STATUS_CODES = {
    "accepted": 202,
    "duplicate": 200,
    "ignored": 200,
    "decrypt_failed": 400,
    "schema_failed": 422,
    "unavailable": 503,
}


def create_app(settings: Settings, repo, publisher) -> FastAPI:
    """`repo` e `publisher` sao injetados para permitir fakes nos testes."""
    app = FastAPI(title="GEX lead ingestion")

    def respond(status: str, correlation_id: str) -> JSONResponse:
        return JSONResponse({"status": status}, STATUS_CODES[status], {"X-Correlation-ID": correlation_id})

    # Precisa do body bruto (auditoria), entao a rota e async para ler o stream;
    # o trabalho bloqueante (pymysql/pika) vai para a threadpool.
    @app.post("/webhooks/grummer")
    async def grummer_endpoint(request: Request) -> JSONResponse:
        raw_body = (await request.body()).decode("utf-8", errors="replace")
        headers = {k: v for k, v in request.headers.items() if k.lower() in ("x-gr-encrypted", "content-type")}
        return await run_in_threadpool(_handle, raw_body, headers)

    def _handle(raw_body: str, headers: dict) -> JSONResponse:
        correlation_id = str(uuid.uuid4())
        started = time.perf_counter()
        ctx = {"correlation_id": correlation_id}
        raw_id = None
        transaction_id = event = error = None

        def done(result: str) -> JSONResponse:
            ms = round((time.perf_counter() - started) * 1000, 1)
            log.info("request finished", extra={**ctx, "transaction_id": transaction_id, "event": event,
                                                 "step": "api", "result": result, "duration_ms": ms})
            if raw_id is not None:
                try:
                    repo.finish_raw(raw_id, result, transaction_id, event, error)
                except Exception:
                    log.exception("falha ao fechar auditoria", extra={**ctx, "step": "audit"})
            return respond(result, correlation_id)

        try:
            raw_id = repo.save_raw(correlation_id, headers, raw_body)

            # 1) decriptar
            try:
                if headers.get("x-gr-encrypted", "").lower() != "true":
                    raise DecryptError("header X-GR-Encrypted ausente")
                body = json.loads(raw_body)
                payload = decrypt_payload(body, settings.aes_key)
            except (DecryptError, json.JSONDecodeError, TypeError, AttributeError) as exc:
                error = type(exc).__name__
                return done("decrypt_failed")

            # 2) validar + normalizar
            try:
                msg = validate_and_normalize(payload)
            except SchemaError as exc:
                error = str(exc)  # nomeia o campo, nunca o valor
                return done("schema_failed")
            transaction_id, event = msg["transaction_id"], msg["event"]
            ctx["transaction_id"] = transaction_id

            # 3) roteamento
            if not is_approved_sale(msg):
                return done("ignored")

            # 4) publicar exatamente uma vez
            msg["correlation_id"] = correlation_id
            published = repo.publish_once(
                transaction_id, event, correlation_id,
                lambda: publisher.publish(QUEUE_RECEIVED, msg, {"x-attempt": 1}),
            )
            return done("accepted" if published else "duplicate")

        except (DatabaseUnavailable, BrokerUnavailable) as exc:
            error = f"{type(exc).__name__}: {exc}"
            return done("unavailable")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


def build_default_app() -> FastAPI:
    setup_logging()
    settings = Settings.from_env()
    return create_app(settings, Repository(settings), Publisher(settings))
