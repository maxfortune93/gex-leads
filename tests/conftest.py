import copy
import threading

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.broker import BrokerUnavailable
from app.config import Settings
from app.crypto import encrypt_payload
from app.repository import DatabaseUnavailable

KEY = bytes(range(32))
IV = bytes(range(16))

VALID = {
    "transaction_id": "tx-1",
    "transaction_time": "2025-01-10T12:00:00-03:00",
    "event": "order.approved",
    "customer": {"email": "  Ana@Example.COM ", "first_name": "", "phone": "+1 (415) 555-0100", "country": "us"},
    "product": {"id": "p1", "name": "Fit Burn"},
    "payment": {"amount_usd": 49.9, "status": "approved"},
}


def make_payload(**overrides) -> dict:
    p = copy.deepcopy(VALID)
    for k, v in overrides.items():
        p[k] = v
    return p


def encrypted(payload: dict) -> dict:
    return encrypt_payload(payload, KEY, IV)


class FakeRepo:
    """Imita o contrato do Repository (inclusive a serializacao por chave) sem MySQL."""

    def __init__(self):
        self.raw: list[dict] = []
        self.keys: set[tuple] = set()
        self.lock = threading.Lock()
        self.db_down = False
        self.leads: list[dict] = []
        self.fail_persist = 0  # quantas chamadas a persist_lead devem falhar

    def save_raw(self, correlation_id, headers, body):
        if self.db_down:
            raise DatabaseUnavailable("down")
        self.raw.append({"correlation_id": correlation_id, "result": None})
        return len(self.raw) - 1

    def finish_raw(self, raw_id, result, transaction_id=None, event=None, error=None):
        self.raw[raw_id].update(result=result, transaction_id=transaction_id, event=event, error=error)

    def publish_once(self, transaction_id, event, correlation_id, publish):
        with self.lock:
            if (transaction_id, event) in self.keys:
                return False
            publish()  # se levantar, a chave nao e registrada (igual ao rollback real)
            self.keys.add((transaction_id, event))
            return True

    def persist_lead(self, msg):
        if self.fail_persist > 0:
            self.fail_persist -= 1
            raise RuntimeError("erro temporario")
        self.leads.append(msg)


class FakePublisher:
    def __init__(self):
        self.sent: list[tuple[str, dict, dict | None]] = []
        self.down = False

    def publish(self, queue, message, headers=None):
        if self.down:
            raise BrokerUnavailable("down")
        self.sent.append((queue, message, headers))


@pytest.fixture
def repo():
    return FakeRepo()


@pytest.fixture
def publisher():
    return FakePublisher()


@pytest.fixture
def client(repo, publisher):
    settings = Settings("h", 1, "u", "p", "d", "h", 1, "u", "p", KEY)
    return TestClient(create_app(settings, repo, publisher))
