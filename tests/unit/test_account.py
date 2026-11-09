"""The customer's view: the facts and wording the API controls, and what must never reach a customer."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.main import ONTIME_BANDS, account_store, account_view, app
from lending.params import CUTS
from tests.unit.tokens import auth, install

NOW = datetime(2026, 11, 4, tzinfo=UTC)
CUSTOMER = {
    "customer_id": 63,
    "loan_amount": 1000.0,
    "ontime_pct": 90.0,
    "action": "hold",
    "reason_code": "capital_limit",
    "step": 0.15,
    "cycle": 60,
}
LOAN: dict[str, Any] = {
    "occurred_at": NOW - timedelta(days=30),
    "loan_id": "L1",
    "amount": 1000.0,
    "due_at": NOW + timedelta(days=30),
    "repaid": False,
}
install()
client = TestClient(app, headers=auth())


@pytest.fixture(autouse=True)
def fake_store():
    app.dependency_overrides[account_store] = lambda: lambda cid: (CUSTOMER, LOAN) if cid == 63 else (None, None)
    yield
    app.dependency_overrides.clear()


def test_bands_match_the_model():
    assert tuple(round(c * 100) for c in CUTS) == ONTIME_BANDS


def test_upcoming_payment_and_eligibility():
    v = account_view(CUSTOMER, LOAN, NOW)
    assert v["next_payment"] == {"loan_id": "L1", "amount": 1000.0, "due_at": LOAN["due_at"], "status": "upcoming"}
    assert v["eligible_from"] == LOAN["occurred_at"] + timedelta(days=60)
    assert v["ontime_target"] == 95


def test_overdue_payment():
    v = account_view(CUSTOMER, LOAN | {"due_at": NOW - timedelta(days=1)}, NOW)
    assert v["next_payment"]["status"] == "overdue"


def test_dates_are_whole_seconds():
    # Power Platform's date-time check rejects microsecond timestamps; a customer never needs them.
    jitter = timedelta(microseconds=587157)
    loan = LOAN | {"occurred_at": LOAN["occurred_at"] + jitter, "due_at": LOAN["due_at"] + jitter}
    v = account_view(CUSTOMER, loan, NOW)
    assert v["next_payment"]["due_at"].microsecond == 0
    assert v["eligible_from"].microsecond == 0


def test_repaid_or_undated_loan_has_no_next_payment():
    assert account_view(CUSTOMER, LOAN | {"repaid": True}, NOW)["next_payment"] is None
    assert account_view(CUSTOMER, LOAN | {"due_at": None}, NOW)["next_payment"] is None
    assert account_view(CUSTOMER, None, NOW)["next_payment"] is None


def test_ontime_targets():
    assert account_view(CUSTOMER | {"ontime_pct": 80.0}, None, NOW)["ontime_target"] == 85
    assert account_view(CUSTOMER | {"ontime_pct": 97.0}, None, NOW)["ontime_target"] is None


def test_offer_shows_the_new_limit():
    v = account_view(CUSTOMER | {"action": "offer", "reason_code": "npv_positive"}, LOAN, NOW)
    assert v["new_limit"] == 1150.0
    assert "next review" in v["message"]


def test_hold_wording_never_reveals_capital_policy():
    v = account_view(CUSTOMER, LOAN, NOW)
    assert v["new_limit"] is None
    assert "capital" not in v["message"].lower()
    assert "budget" not in v["message"].lower()
    assert "record" in v["message"]


def test_endpoint_returns_no_internal_fields():
    r = client.get("/customers/63/account")
    assert r.status_code == 200
    forbidden = {"q_hold", "q_offer", "reason_code", "reason", "run_id", "param_version", "bucket", "step", "cycle"}
    assert not forbidden & set(r.json())


def test_unknown_customer_is_404_and_role_is_needed():
    assert client.get("/customers/64/account").status_code == 404
    assert client.get("/customers/63/account", headers=auth(["Events.Write"])).status_code == 403
