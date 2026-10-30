"""Event ingest contract, with the database swapped for an in-memory fake that applies the same
all-or-nothing and conflict rules: retries are no-ops, a changed body under a known id is a 409 that stores
nothing, and malformed events never reach the store. (The real SQL path is checked against the running API.)
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from api.main import EVENT_FIELDS, EventConflict, IngestResult, app, conflicting, event_store
from tests.unit.tokens import auth, install

stored: dict[str, dict] = {}
REPAY = {"loan_id": "L1", "amount": 1200, "due_at": "2026-10-30T23:59:00+03:00"}


def fake_ingest(events):
    existing = {e.event_id: stored[e.event_id] for e in events if e.event_id in stored}
    if bad := conflicting(events, existing):
        raise EventConflict(bad)
    for e in events:
        stored.setdefault(e.event_id, e.model_dump(include=set(EVENT_FIELDS)))
    return IngestResult(accepted=len(events) - len(existing), duplicate=len(existing))


install()
client = TestClient(app, headers=auth())  # a valid token with both roles on every request


@pytest.fixture(autouse=True)
def fake_store():
    # Set per test and cleared after: the app object is shared by every test module.
    app.dependency_overrides[event_store] = lambda: fake_ingest
    yield
    app.dependency_overrides.clear()


def event(event_id="e1", **kw):
    return {
        "event_id": event_id,
        "customer_id": 1,
        "event_type": "repay",
        "occurred_at": "2026-10-30T08:00:00+03:00",
        "payload": REPAY,
    } | kw


def setup_function():
    stored.clear()


def test_new_events_are_accepted():
    r = client.post("/events", json=[event("e1"), event("e2")])
    assert r.status_code == 200 and r.json() == {"accepted": 2, "duplicate": 0}


def test_replaying_a_batch_stores_nothing_twice():
    client.post("/events", json=[event("e1"), event("e2")])
    r = client.post("/events", json=[event("e1"), event("e2"), event("e3")])
    assert r.json() == {"accepted": 1, "duplicate": 2}
    assert len(stored) == 3


def test_same_instant_in_another_time_zone_is_still_a_duplicate():
    client.post("/events", json=[event("e1")])
    r = client.post("/events", json=[event("e1", occurred_at="2026-10-30T05:00:00Z")])
    assert r.json() == {"accepted": 0, "duplicate": 1}


def test_changed_content_under_a_known_id_is_409_and_stores_nothing():
    client.post("/events", json=[event("e1")])
    r = client.post("/events", json=[event("e2"), event("e1", payload=REPAY | {"amount": 999})])
    assert r.status_code == 409
    assert r.json()["detail"]["event_ids"] == ["e1"]
    assert set(stored) == {"e1"} and stored["e1"]["payload"]["amount"] == 1200  # e2 not stored either


def test_malformed_events_are_rejected_before_the_store():
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    bad = [
        [],  # empty batch
        [event(event_type="refund")],  # unknown type
        [event(customer_id=-1)],
        [event(event_id="")],
        [event(event_id="x" * 129)],
        [event(occurred_at="2026-10-30T08:00:00")],  # no time zone
        [event(occurred_at=future)],
        [event(extra="field")],  # unknown field
        [event("e1"), event("e1")],  # same id twice in one batch
        [event(str(i)) for i in range(1001)],  # over the batch limit
        [event(payload={})],  # repay without its fields
        [event(payload=REPAY | {"due_at": "2026-10-30T23:59:00"})],  # due_at without a time zone
        [event(payload=REPAY | {"amount": 0})],
        [event(payload=REPAY | {"note": "x"})],  # unknown payload field
        [event(event_type="accept")],  # accept carries offer_id, not a repayment
    ]
    for body in bad:
        assert client.post("/events", json=body).status_code == 422, body
    assert stored == {}


def test_each_event_type_accepts_its_own_payload():
    payloads = {
        "disburse": {"loan_id": "L1", "amount": 1000},
        "repay": REPAY,
        "miss": {"loan_id": "L1", "due_at": "2026-10-01T00:00:00Z"},
        "offer": {"offer_id": "O1", "new_limit": 1150},
        "accept": {"offer_id": "O1"},
        "decline": {"offer_id": "O2"},
    }
    body = [event(t, event_type=t, payload=p) for t, p in payloads.items()]
    assert client.post("/events", json=body).json() == {"accepted": 6, "duplicate": 0}


def test_payload_is_stored_in_one_canonical_form():
    client.post("/events", json=[event("e1")])
    assert stored["e1"]["payload"]["due_at"] == "2026-10-30T20:59:00+00:00"  # UTC
    same_instant = REPAY | {"due_at": "2026-10-30T20:59:00Z", "amount": 1200.0}
    r = client.post("/events", json=[event("e1", payload=same_instant)])
    assert r.json() == {"accepted": 0, "duplicate": 1}
