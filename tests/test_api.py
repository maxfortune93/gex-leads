import uuid
from concurrent.futures import ThreadPoolExecutor

from tests.conftest import encrypted, make_payload

H = {"X-GR-Encrypted": "true"}


def post(client, payload):
    return client.post("/webhooks/grummer", json=encrypted(payload), headers=H)


def test_valid_encrypted_payload_is_accepted_and_normalized(client, publisher, repo):
    r = post(client, make_payload())
    assert r.status_code == 202 and r.json() == {"status": "accepted"}
    uuid.UUID(r.headers["X-Correlation-ID"])

    queue, msg, _ = publisher.sent[0]
    assert queue == "lead.received"
    assert msg["correlation_id"] == r.headers["X-Correlation-ID"]
    assert msg["customer"] == {"email": "ana@example.com", "first_name": "Customer",
                               "phone": "+14155550100", "country": "US"}
    assert repo.raw[0]["result"] == "accepted"


def test_decrypt_failure(client, publisher, repo):
    r = client.post("/webhooks/grummer", json={"iv": "AAAA", "ciphertext": "AAAA"}, headers=H)
    assert r.status_code == 400 and r.json() == {"status": "decrypt_failed"}
    assert publisher.sent == [] and repo.raw[0]["result"] == "decrypt_failed"


def test_missing_encrypted_header_is_decrypt_failure(client):
    r = client.post("/webhooks/grummer", json=encrypted(make_payload()))
    assert r.status_code == 400


def test_invalid_schema(client, publisher):
    for bad in (
        make_payload(customer={"email": "nao-e-email", "first_name": "A", "phone": "+14155550100", "country": "US"}),
        make_payload(customer={"email": "a@b.co", "first_name": "A", "phone": "123", "country": "US"}),
        make_payload(payment={"amount_usd": 0, "status": "approved"}),
        make_payload(transaction_time="2025-01-10T12:00:00"),  # sem timezone
        make_payload(transaction_id="  "),
    ):
        r = post(client, bad)
        assert r.status_code == 422 and r.json() == {"status": "schema_failed"}
    assert publisher.sent == []


def test_valid_but_not_approved_is_ignored(client, publisher):
    r = post(client, make_payload(event="order.refunded"))
    assert r.status_code == 200 and r.json() == {"status": "ignored"}
    r = post(client, make_payload(transaction_id="tx-2", payment={"amount_usd": 10, "status": "pending"}))
    assert r.json() == {"status": "ignored"}
    assert publisher.sent == []


def test_sequential_duplicate(client, publisher, repo):
    assert post(client, make_payload()).status_code == 202
    r = post(client, make_payload())
    assert r.status_code == 200 and r.json() == {"status": "duplicate"}
    assert len(publisher.sent) == 1
    assert len(repo.raw) == 2  # a entrega bruta e auditada novamente


def test_concurrent_duplicates_publish_once(client, publisher):
    with ThreadPoolExecutor(8) as pool:
        codes = list(pool.map(lambda _: post(client, make_payload()).status_code, range(16)))
    assert codes.count(202) == 1 and codes.count(200) == 15
    assert len(publisher.sent) == 1


def test_broker_down_returns_503_and_retry_is_safe(client, publisher):
    publisher.down = True
    r = post(client, make_payload())
    assert r.status_code == 503 and r.json() == {"status": "unavailable"}
    assert publisher.sent == []

    publisher.down = False  # nova tentativa publica normalmente
    assert post(client, make_payload()).status_code == 202
    assert len(publisher.sent) == 1


def test_db_down_returns_503(client, repo):
    repo.db_down = True
    r = post(client, make_payload())
    assert r.status_code == 503
