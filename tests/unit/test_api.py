"""The decision API's contract, with the database swapped for a fake: status codes, response shape,
input validation. (The real database path is checked by calling the running API.)
"""

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from api.main import app, decision_store

ROW = {
    "customer_id": 1,
    "action": "offer",
    "run_id": 8,
    "param_version": 21,
    "model_version": "2ca2cac",
    "published_at": datetime(2026, 10, 30, 6, 48, tzinfo=UTC),
}
app.dependency_overrides[decision_store] = lambda: lambda cid: ROW if cid == 1 else None
client = TestClient(app)  # not used as a context manager, so the lifespan (real pool) never opens


def test_known_customer_returns_the_published_decision():
    r = client.get("/decisions/1")
    assert r.status_code == 200
    assert r.json() | {"published_at": None} == ROW | {"published_at": None}


def test_unknown_customer_is_404():
    assert client.get("/decisions/2").status_code == 404


def test_invalid_ids_are_rejected_before_any_lookup():
    for bad in ("-1", "abc", str(2**63)):
        assert client.get(f"/decisions/{bad}").status_code == 422


def test_healthz_needs_no_database():
    assert client.get("/healthz").json() == {"status": "ok"}
