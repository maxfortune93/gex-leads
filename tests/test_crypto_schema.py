import pytest

from app.crypto import DecryptError, decrypt_payload, encrypt_payload
from app.schema import SchemaError, validate_and_normalize
from tests.conftest import IV, KEY, make_payload


def test_crypto_roundtrip():
    assert decrypt_payload(encrypt_payload({"a": 1}, KEY, IV), KEY) == {"a": 1}


def test_wrong_key_or_garbage_raises():
    body = encrypt_payload({"a": 1}, KEY, IV)
    with pytest.raises(DecryptError):
        decrypt_payload(body, bytes(32))
    with pytest.raises(DecryptError):
        decrypt_payload({"iv": "x"}, KEY)
    with pytest.raises(DecryptError):
        decrypt_payload({"iv": "!!!", "ciphertext": "!!!"}, KEY)


def test_normalization():
    msg = validate_and_normalize(make_payload())
    assert msg["customer"]["email"] == "ana@example.com"
    assert msg["customer"]["phone"] == "+14155550100"
    assert msg["customer"]["first_name"] == "Customer"
    assert msg["customer"]["country"] == "US"
    assert msg["transaction_time"] == "2025-01-10T15:00:00+00:00"


@pytest.mark.parametrize("phone", ["1234567", "1234567890123456", "12+3456789", "abc12345678"])
def test_invalid_phone(phone):
    p = make_payload()
    p["customer"]["phone"] = phone
    with pytest.raises(SchemaError):
        validate_and_normalize(p)
