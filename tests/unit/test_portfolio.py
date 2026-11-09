"""Portfolio and scenario endpoints, with the database swapped for a fake."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from api.main import app, portfolio_store, scenario_store
from tests.unit.tokens import auth, install

PORTFOLIO = {
    "run_id": 29,
    "param_version": 85,
    "model_version": "abcdef0",
    "published_at": datetime(2026, 11, 3, tzinfo=UTC),
    "capital_price": 0.68,
    "offers": 5672,
    "holds": 24328,
    "by_reason": {"npv_positive": 5672, "capital_limit": 20000, "risk_return": 4328},
    "capital_used": 249000.0,
    "capital_budget": 250000.0,
    "active_param_version": 85,
    "active_params": {"budget": 250000.0, "lgd": 0.65},
}
SCENARIOS = {
    "run_id": 29,
    "scenarios": [
        {
            "lever": "baseline",
            "value": 250000,
            "capital_price": 0.68,
            "offers": 5672,
            "capital_used": 249000,
            "npv": 11000000,
            "default_rate": 0.1,
        }
    ],
}
install()
client = TestClient(app, headers=auth())


@pytest.fixture(autouse=True)
def fakes():
    app.dependency_overrides[portfolio_store] = lambda: lambda: PORTFOLIO
    app.dependency_overrides[scenario_store] = lambda: lambda: SCENARIOS
    yield
    app.dependency_overrides.clear()


def test_portfolio_reports_capital_left():
    r = client.get("/portfolio")
    assert r.status_code == 200
    assert r.json()["capital_left"] == 1000.0
    assert r.json()["by_reason"]["capital_limit"] == 20000


def test_capital_left_is_null_for_older_runs():
    app.dependency_overrides[portfolio_store] = lambda: lambda: PORTFOLIO | {"capital_used": None}
    assert client.get("/portfolio").json()["capital_left"] is None


def test_no_published_run_is_404():
    app.dependency_overrides[portfolio_store] = lambda: lambda: None
    app.dependency_overrides[scenario_store] = lambda: lambda: None
    assert client.get("/portfolio").status_code == 404
    assert client.get("/portfolio/scenarios").status_code == 404


def test_scenarios_are_returned():
    r = client.get("/portfolio/scenarios")
    assert r.status_code == 200
    assert r.json()["scenarios"][0]["lever"] == "baseline"


def test_both_need_decisions_read():
    no_role = auth(["Events.Write"])
    assert client.get("/portfolio", headers=no_role).status_code == 403
    assert client.get("/portfolio/scenarios", headers=no_role).status_code == 403
