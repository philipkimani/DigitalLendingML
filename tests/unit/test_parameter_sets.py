"""Approval endpoints: who may call them, and how the database's answers become HTTP answers.

The store is faked; maker-checker itself is the database trigger's job (tests/db/check_schema.sql), and the
on-behalf-of login is checked against the running API.
"""

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from api.main import app, parameter_store
from tests.unit.tokens import auth, install

PERSON = {"scp": "access_as_user", "oid": "00000000-0000-0000-0000-0000000000c1"}
SET = {
    "param_version": 23,
    "status": "proposed",
    "note": "budget 180k",
    "maker": "maker@example.test",
    "created_at": datetime(2026, 10, 30, tzinfo=UTC),
    "checker": None,
    "checked_at": None,
    "params": {"lgd": 0.65, "max_k": 5},
}


class FakeStore:
    refusal: Exception | None = None

    def in_play(self):
        return [SET]

    def move(self, version, action):
        if self.refusal:
            raise self.refusal
        if version != 23:
            raise LookupError(version)
        return SET | {"status": {"approve": "approved", "reject": "rejected", "activate": "active"}[action]}


store = FakeStore()
install()
client = TestClient(app)


@pytest.fixture(autouse=True)
def fake_store():
    store.refusal = None
    app.dependency_overrides[parameter_store] = lambda: store
    yield
    app.dependency_overrides.clear()


def approve(headers, version=23, action="approve"):
    return client.post(f"/parameter-sets/{version}/{action}", headers=headers)


def test_checker_approves():
    r = approve(auth(["Parameters.Approve"], **PERSON))
    assert r.status_code == 200
    assert r.json()["status"] == "approved"
    assert r.json()["params"]["max_k"] == 5


def test_lists_sets_in_play():
    r = client.get("/parameter-sets", headers=auth(["Parameters.Approve"], **PERSON))
    assert r.status_code == 200
    assert [s["param_version"] for s in r.json()] == [23]


def test_needs_the_role():
    assert approve(auth(["Decisions.Read"], **PERSON)).status_code == 403
    assert client.get("/parameter-sets", headers=auth(["Decisions.Read"], **PERSON)).status_code == 403
    assert approve({}).status_code == 401


def test_application_token_cannot_approve():
    # An app-only token (no scp) acts for no person, so the database could not tell who approved.
    assert approve(auth(["Parameters.Approve"], oid=PERSON["oid"])).status_code == 403


def test_database_refusal_is_409_with_its_reason():
    store.refusal = psycopg.errors.CheckViolation("maker@example.test may not move parameter set 23")
    r = approve(auth(["Parameters.Approve"], **PERSON))
    assert r.status_code == 409
    assert "may not move" in r.json()["detail"]


def test_not_a_checker_is_403():
    store.refusal = psycopg.errors.InsufficientPrivilege("permission denied for table parameter_sets")
    assert approve(auth(["Parameters.Approve"], **PERSON)).status_code == 403


def test_unknown_set_and_action():
    assert approve(auth(["Parameters.Approve"], **PERSON), version=99).status_code == 404
    assert approve(auth(["Parameters.Approve"], **PERSON), action="delete").status_code == 422


def test_connector_definition_matches_the_api():
    # The Power Platform connector (api/connector.swagger.json) is hand-kept Swagger 2.0; it must not drift.
    swagger = json.loads((Path(__file__).parents[2] / "api" / "connector.swagger.json").read_text())
    openapi = app.openapi()
    for path, ops in swagger["paths"].items():
        template = re.sub(r"/(approve|reject|activate)$", "/{action}", path)
        assert set(ops) <= set(openapi["paths"][template]), path
    fields = openapi["components"]["schemas"]["ParameterSet"]["properties"]
    assert set(swagger["definitions"]["ParameterSet"]["properties"]) == set(fields)
