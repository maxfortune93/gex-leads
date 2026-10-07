import json

import pytest

from app.broker import BrokerUnavailable
from app.worker import process_message

MSG = {
    "correlation_id": "11111111-1111-1111-1111-111111111111",
    "transaction_id": "tx-1",
    "transaction_time": "2025-01-10T15:00:00+00:00",
    "event": "order.approved",
    "customer": {"email": "a@b.co", "first_name": "A", "phone": "+14155550100", "country": "US"},
    "product": {"id": "p1", "name": "Fit Burn"},
    "payment": {"amount_usd": 10, "status": "approved"},
}
BODY = json.dumps(MSG).encode()


def test_success_persists(repo, publisher):
    assert process_message(BODY, 1, repo, publisher) == "ok"
    assert len(repo.leads) == 1 and publisher.sent == []


def test_temporary_failure_is_retried_with_incremented_attempt(repo, publisher):
    repo.fail_persist = 1
    assert process_message(BODY, 1, repo, publisher) == "retry"
    queue, msg, headers = publisher.sent[0]
    assert queue == "lead.received" and headers == {"x-attempt": 2} and msg == MSG


def test_third_failure_goes_to_dlq(repo, publisher):
    repo.fail_persist = 99
    results = []
    attempt = 1
    while True:  # simula o broker reentregando as copias republicadas
        results.append(process_message(BODY, attempt, repo, publisher))
        if results[-1] == "dead":
            break
        attempt = publisher.sent[-1][2]["x-attempt"]
    assert results == ["retry", "retry", "dead"]

    queue, dead, _ = publisher.sent[-1]
    assert queue == "lead.dead.processing_failed"
    assert dead["original_message"] == MSG
    assert dead["correlation_id"] == MSG["correlation_id"]
    assert dead["attempts"] == 3 and "RuntimeError" in dead["error"]


def test_unreadable_message_goes_straight_to_dlq(repo, publisher):
    assert process_message(b"not json", 1, repo, publisher) == "dead"
    assert publisher.sent[0][0] == "lead.dead.processing_failed"


def test_broker_failure_while_retrying_propagates_for_requeue(repo, publisher):
    repo.fail_persist = 1
    publisher.down = True
    with pytest.raises(BrokerUnavailable):
        process_message(BODY, 1, repo, publisher)
