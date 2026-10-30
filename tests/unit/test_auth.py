"""Authentication and authorisation: only a valid Entra token for this API, carrying the endpoint's app role,
gets through. 401 = who are you?, 403 = known, but not allowed. Stores are fakes; no network."""

import base64
import json
import os
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from api.main import IngestResult, app, decision_store, event_store
from tests.unit.tokens import auth, install, token

install()
client = TestClient(app)


@pytest.fixture(autouse=True)
def fake_stores():
    # Set per test and cleared after: the app object is shared by every test module.
    app.dependency_overrides[decision_store] = lambda: lambda cid: None  # 404 means "got past auth"
    app.dependency_overrides[event_store] = lambda: lambda evs: IngestResult(accepted=len(evs), duplicate=0)
    yield
    app.dependency_overrides.clear()


EVENT = [
    {
        "event_id": "a1",
        "customer_id": 1,
        "event_type": "accept",
        "occurred_at": "2026-10-30T08:00:00Z",
        "payload": {"offer_id": "O1"},
    }
]


def get(headers=None):
    return client.get("/decisions/1", headers=headers or {})


def test_valid_token_with_the_role_gets_through():
    assert get(auth(["Decisions.Read"])).status_code == 404  # past auth, fake store has no row
    assert client.post("/events", json=EVENT, headers=auth(["Events.Write"])).status_code == 200


def test_missing_or_malformed_token_is_401_with_a_challenge():
    for headers in ({}, {"Authorization": "Bearer not-a-jwt"}, {"Authorization": "Basic abc"}):
        r = get(headers)
        assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer", headers


def test_tokens_for_someone_else_or_expired_are_401():
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    bad: list[dict[str, Any]] = [
        {"aud": "00000000-0000-0000-0000-0000000000ff"},  # issued for another API
        {"iss": "https://login.microsoftonline.com/00000000-0000-0000-0000-0000000000ff/v2.0"},  # another tenant
        {"tid": "00000000-0000-0000-0000-0000000000ff"},  # issuer right, tenant claim wrong
        {"exp": 1_000_000_000},  # expired in 2001
        {"tid": None},  # required claim missing
    ]
    for claims in bad:
        assert get(auth(**claims)).status_code == 401, claims
    forged = {"Authorization": f"Bearer {token(key=other_key)}"}  # right claims, wrong signer
    assert get(forged).status_code == 401


def test_unsigned_token_with_valid_claims_is_rejected():
    # alg "none" and no signature, every claim otherwise valid: only the signature check can stop it.
    def b64(d: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()

    claims = jwt.decode(token(), options={"verify_signature": False})
    unsigned = f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64(claims)}."
    assert get({"Authorization": f"Bearer {unsigned}"}).status_code == 401


def test_valid_token_without_the_role_is_403():
    assert get(auth(["Events.Write"])).status_code == 403
    assert get(auth([])).status_code == 403
    assert client.post("/events", json=EVENT, headers=auth(["Decisions.Read"])).status_code == 403


def test_unconfigured_api_refuses_instead_of_serving_unauthenticated():
    saved = os.environ.pop("AUTH_AUDIENCE")
    try:
        assert get(auth()).status_code == 503
    finally:
        os.environ["AUTH_AUDIENCE"] = saved


def test_healthz_needs_no_token():
    assert client.get("/healthz").status_code == 200
