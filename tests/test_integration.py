"""Fluxo real: API + worker + MySQL + RabbitMQ.

Pre-requisito: `docker compose up -d --build` e RUN_INTEGRATION=1.
Roda no host, apontando para as portas expostas pelo compose.
"""

import csv
import json
import os
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pymysql
import pytest

pytestmark = pytest.mark.skipif(not os.getenv("RUN_INTEGRATION"), reason="defina RUN_INTEGRATION=1")

ROOT = Path(__file__).resolve().parents[1]
URL = os.getenv("API_URL", "http://localhost:8000/webhooks/grummer")


def db():
    return pymysql.connect(
        host=os.getenv("MYSQL_HOST", "localhost"), port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "gex"), password=os.getenv("MYSQL_PASSWORD", "gex_local_password"),
        database=os.getenv("MYSQL_DATABASE", "gex_backend_test"), autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
    )


def scalar(sql):
    with db().cursor() as cur:
        cur.execute(sql)
        return list(cur.fetchone().values())[0]


@pytest.fixture(scope="module", autouse=True)
def clean_state():
    with db().cursor() as cur:
        cur.execute("SET FOREIGN_KEY_CHECKS=0")
        for t in ("order_events", "orders", "customers", "webhook_events", "raw_requests"):
            cur.execute(f"TRUNCATE TABLE {t}")
        cur.execute("SET FOREIGN_KEY_CHECKS=1")


def send_all(records, workers=1):
    def one(rec):
        r = httpx.post(URL, json=rec["body"], headers=rec["headers"], timeout=15)
        return r.status_code, r.json()["status"]
    with ThreadPoolExecutor(workers) as pool:
        return list(pool.map(one, records))


def wait_for(sql, expected, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if scalar(sql) == expected:
            return
        time.sleep(0.5)
    assert scalar(sql) == expected


def test_full_dataset_matches_expected():
    expected = json.loads((ROOT / "data/expected_results.json").read_text())
    records = json.loads((ROOT / "data/webhook_payloads.json").read_text())

    # concorrencia alta de proposito: duplicados chegam em paralelo
    counts = Counter(status for _, status in send_all(records, workers=8))

    assert counts["accepted"] == expected["accepted_unique"]
    assert counts["duplicate"] == expected["duplicates"]
    assert counts["decrypt_failed"] == expected["decrypt_failed"]
    assert counts["schema_failed"] == expected["schema_failed"]
    assert counts["ignored"] == expected["ignored"]
    assert scalar("SELECT COUNT(*) FROM raw_requests") == expected["raw_payloads"]

    wait_for("SELECT COUNT(*) FROM order_events", expected["accepted_unique"])


def test_audit_query_matches_expected_summary():
    with db().cursor() as cur:
        cur.execute((ROOT / "sql/audit_query.sql").read_text())
        got = {(r["gateway"], r["country"], r["product_name"]): int(r["accepted_count"]) for r in cur.fetchall()}
    with open(ROOT / "data/expected_summary.csv") as f:
        want = {(r["gateway"], r["country"], r["product_name"]): int(r["accepted_count"]) for r in csv.DictReader(f)}
    assert got == want


def test_redelivery_does_not_duplicate_data():
    """Reenvia mensagem ja persistida direto ao worker logica (mesmo repositorio real)."""
    from app.config import Settings
    from app.repository import Repository

    repo = Repository(Settings.from_env())
    with db().cursor() as cur:
        cur.execute("SELECT o.transaction_id, c.email, c.first_name, c.phone, c.country, o.product_id, "
                    "o.product_name, o.amount_usd, o.transaction_time, e.correlation_id "
                    "FROM orders o JOIN customers c ON c.id=o.customer_id JOIN order_events e ON e.order_id=o.id LIMIT 1")
        r = cur.fetchone()
    msg = {"correlation_id": r["correlation_id"], "transaction_id": r["transaction_id"],
           "transaction_time": r["transaction_time"].isoformat() + "+00:00", "event": "order.approved",
           "customer": {k: r[k] for k in ("email", "first_name", "phone", "country")},
           "product": {"id": r["product_id"], "name": r["product_name"]},
           "payment": {"amount_usd": float(r["amount_usd"]), "status": "approved"}}

    before = [scalar(f"SELECT COUNT(*) FROM {t}") for t in ("customers", "orders", "order_events")]
    for _ in range(3):
        repo.persist_lead(msg)
    after = [scalar(f"SELECT COUNT(*) FROM {t}") for t in ("customers", "orders", "order_events")]
    assert before == after
