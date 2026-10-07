"""Validacao e normalizacao do payload decriptado."""

import re
from datetime import datetime, timezone
from typing import Any

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
COUNTRY_RE = re.compile(r"^[A-Za-z]{2}$")


class SchemaError(Exception):
    pass


def _text(value: Any, field: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise SchemaError(f"{field}: texto obrigatorio")
    value = value.strip()
    if not value and not allow_empty:
        raise SchemaError(f"{field}: vazio")
    return value


def _obj(data: Any, field: str) -> dict:
    if not isinstance(data, dict):
        raise SchemaError(f"{field}: objeto obrigatorio")
    return data


def _parse_time(value: Any) -> datetime:
    raw = _text(value, "transaction_time")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SchemaError("transaction_time: ISO 8601 invalido") from exc
    if parsed.tzinfo is None:
        raise SchemaError("transaction_time: timezone obrigatorio")
    return parsed.astimezone(timezone.utc)


def _normalize_phone(value: Any) -> str:
    raw = _text(value, "customer.phone")
    cleaned = re.sub(r"[\s()\-]", "", raw)
    digits = cleaned[1:] if cleaned.startswith("+") else cleaned
    if not digits.isascii() or not digits.isdigit() or not 8 <= len(digits) <= 15:
        raise SchemaError("customer.phone: invalido")
    return cleaned


def validate_and_normalize(data: Any) -> dict:
    """Retorna o dict normalizado (tambem e a mensagem publicada, sem correlation_id)."""
    data = _obj(data, "payload")
    customer = _obj(data.get("customer"), "customer")
    product = _obj(data.get("product"), "product")
    payment = _obj(data.get("payment"), "payment")

    email = _text(customer.get("email"), "customer.email").lower()
    if not EMAIL_RE.match(email):
        raise SchemaError("customer.email: formato invalido")

    country = _text(customer.get("country"), "customer.country")
    if not COUNTRY_RE.match(country):
        raise SchemaError("customer.country: codigo ISO de 2 letras")

    amount = payment.get("amount_usd")
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount <= 0:
        raise SchemaError("payment.amount_usd: numero > 0")

    first_name = _text(customer.get("first_name", ""), "customer.first_name", allow_empty=True)

    return {
        "transaction_id": _text(data.get("transaction_id"), "transaction_id"),
        "transaction_time": _parse_time(data.get("transaction_time")).isoformat(),
        "event": _text(data.get("event"), "event"),
        "customer": {
            "email": email,
            "first_name": first_name or "Customer",
            "phone": _normalize_phone(customer.get("phone")),
            "country": country.upper(),
        },
        "product": {
            "id": _text(str(product["id"]) if isinstance(product.get("id"), (int, str)) else None, "product.id"),
            "name": _text(product.get("name"), "product.name"),
        },
        "payment": {
            "amount_usd": amount,
            "status": _text(payment.get("status"), "payment.status"),
        },
    }


def is_approved_sale(msg: dict) -> bool:
    return msg["event"] == "order.approved" and msg["payment"]["status"] == "approved"
