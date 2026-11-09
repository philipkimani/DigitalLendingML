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
    has_active = True

    def in_play(self):
        return [SET]

    def move(self, version, action):
        if self.refusal:
            raise self.refusal
        if version != 23:
            raise LookupError(version)
        return SET | {"status": {"approve": "approved", "reject": "rejected", "activate": "active"}[action]}

    def propose(self, changes, note):
        if self.refusal:
            raise self.refusal
        return SET | {"param_version": 86, "note": note, "params": {"budget": 300000.0}} if self.has_active else None


store = FakeStore()
install()
client = TestClient(app)


@pytest.fixture(autouse=True)
def fake_store():
    store.refusal = None
    store.has_active = True
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


PROPOSE = {"budget": 300000, "note": "more capital for Q1"}


def propose(headers, body=PROPOSE):
    return client.post("/parameter-sets", json=body, headers=headers)


def maker():
    return auth(["Parameters.Propose"], **PERSON)


def test_maker_proposes():
    r = propose(maker())
    assert r.status_code == 201
    assert r.json()["param_version"] == 86


def test_only_business_choices_can_be_proposed():
    assert propose(maker(), {"lgd": 0.3, "note": "x"}).status_code == 422
    assert propose(maker(), {"budget": 300000, "kappa": 0.1, "note": "x"}).status_code == 422


def test_a_proposal_needs_a_change_and_a_note():
    assert propose(maker(), {"note": "nothing changes"}).status_code == 422
    assert propose(maker(), {"budget": 300000}).status_code == 422
    assert propose(maker(), {"budget": -1, "note": "x"}).status_code == 422


def test_proposing_needs_the_role_and_a_person():
    assert propose(auth(["Parameters.Approve"], **PERSON)).status_code == 403
    assert propose(auth(["Parameters.Propose"], oid=PERSON["oid"])).status_code == 403
    assert propose({}).status_code == 401


def test_a_maker_cannot_approve_but_can_list():
    assert approve(maker()).status_code == 403
    assert client.get("/parameter-sets", headers=maker()).status_code == 200


def test_no_active_set_to_copy_is_409():
    store.has_active = False
    assert propose(maker()).status_code == 409


def test_database_refusal_of_a_proposal():
    store.refusal = psycopg.errors.CheckViolation("new row violates check")
    assert propose(maker()).status_code == 409
    store.refusal = psycopg.errors.InsufficientPrivilege("permission denied")
    assert propose(maker()).status_code == 403


def test_propose_sql_copies_every_model_parameter():
    from dataclasses import fields

    from api.main import MODEL_COLUMNS
    from lending.params import Params

    expected = {f.name for f in fields(Params)} - {"K"} | {"k_prime", "k_near", "k_sub"}
    assert set(MODEL_COLUMNS) == expected


def test_agent_connectors_match_the_api_and_hold_no_review_action():
    root = Path(__file__).parents[2] / "api"
    openapi = app.openapi()
    allowed = {"connector.analyst.swagger.json": 5, "connector.customer.swagger.json": 1}
    for name, operations in allowed.items():
        swagger = json.loads((root / name).read_text())
        ops = [(p, m) for p, methods in swagger["paths"].items() for m in methods]
        assert len(ops) == operations, name
        for path, method in ops:
            assert method in openapi["paths"][path], (name, path)
            assert not re.search(r"approve|reject|activate", path), (name, path)


def test_customer_connector_exposes_only_the_account():
    swagger = json.loads((Path(__file__).parents[2] / "api" / "connector.customer.swagger.json").read_text())
    assert list(swagger["paths"]) == ["/customers/{customer_id}/account"]
