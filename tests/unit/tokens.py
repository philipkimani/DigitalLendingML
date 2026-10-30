"""Real RS256 access tokens for the API's tests, signed with a throwaway key generated per test run.

install() points the API at that key and at a test tenant/audience, so tests exercise the actual validation
(signature, issuer, tenant, audience, expiry, roles) with no network and no Entra.
"""

import os
import time

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

import api.main

TENANT = "00000000-0000-0000-0000-00000000000a"
AUDIENCE = "00000000-0000-0000-0000-00000000000b"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def install() -> None:
    os.environ["AUTH_TENANT_ID"], os.environ["AUTH_AUDIENCE"] = TENANT, AUDIENCE
    api.main.signing_key = lambda token, tenant: KEY.public_key()


def token(roles=("Decisions.Read", "Events.Write"), key=KEY, **claims) -> str:
    now = int(time.time())
    body = {
        "aud": AUDIENCE,
        "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0",
        "tid": TENANT,
        "iat": now,
        "nbf": now,
        "exp": now + 3600,
        "roles": list(roles),
    } | claims
    return jwt.encode({k: v for k, v in body.items() if v is not None}, key, algorithm="RS256")


def auth(roles=("Decisions.Read", "Events.Write"), **claims) -> dict:
    return {"Authorization": f"Bearer {token(roles, **claims)}"}
