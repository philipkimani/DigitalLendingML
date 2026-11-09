"""Decision API: serves the nightly job's precomputed decisions. It never solves anything on request.

    GET /decisions/{customer_id}  today's action from the published run, with what produced it
    GET /portfolio                published run: offers, holds, reasons, capital, active parameters
    GET /portfolio/scenarios      precomputed what-if results for the published run (jobs/scenarios.py)
    GET /customers/{id}/account   a customer's next payment, review date and limit decision, in their own terms
    POST /events                  partner event ingest, idempotent on the partner's event_id
    GET /parameter-sets           parameter sets awaiting a decision or in force (proposed, approved, active)
    POST /parameter-sets          propose a new budget, step or fee as the signed-in person (copy of the active set)
    POST /parameter-sets/{v}/{approve|reject|activate}   maker-checker step, run as the signed-in person
    GET /healthz                  liveness (no database call, so a database blip doesn't restart the app)

Callers authenticate with an Entra ID access token (Authorization: Bearer ...) for the lending-api app
(infra/entra.bicep), and each endpoint needs an app role in it: Decisions.Read for /decisions, Events.Write
for /events, Parameters.Approve to review sets and Parameters.Propose to propose one (either may list them).
AUTH_TENANT_ID and AUTH_AUDIENCE (the app's client id) are set on the Container App; without them protected
endpoints answer 503 rather than run unauthenticated. /healthz needs no token.

/parameter-sets talks to Postgres as the person, not as the API: the API trades their token for a Postgres
token on their behalf (OAuth on-behalf-of) and logs in as their own database role. So the maker-checker
trigger (migration 002) sees who really approved, and an admin still can't approve their own proposal. The
exchange authenticates the API app with its managed identity (a federated credential, no client secret).

Connection settings come from the standard libpq variables PGHOST, PGDATABASE, PGUSER (set on the
Container App). There is no stored password: each new connection gets a fresh Entra token from the
managed identity (DefaultAzureCredential; AZURE_CLIENT_ID picks the identity). Azure Postgres only checks
the token at connect time, so pooled connections are recycled every 30 minutes, well inside its lifetime.

Run locally against the dev database, signed in with the az CLI:
    PGHOST=... PGDATABASE=lending PGUSER=<your Entra UPN> AUTH_TENANT_ID=... AUTH_AUDIENCE=... \\
        uv run --group api uvicorn api.main:app --port 8000
Call it with a token: az account get-access-token --scope <AUTH_AUDIENCE>/.default --query accessToken -o tsv
"""

import os
from collections.abc import Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime, timedelta
from functools import cache
from typing import Annotated, Any, Literal

import jwt
import psycopg
from azure.identity import DefaultAzureCredential, OnBehalfOfCredential
from fastapi import Body, Depends, FastAPI, HTTPException, Path
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

TOKEN_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"  # Entra resource for Azure Postgres
credential = DefaultAzureCredential()  # caches the token and refreshes it before expiry

# Index-backed lookup: one published run (partial unique index), then the (run_id, customer_id) primary key.
DECISION_SQL = """
    SELECT d.customer_id, d.action, d.run_id, d.param_version, d.model_version, r.published_at,
           d.q_hold, d.q_offer, d.reason_code
    FROM decisions d JOIN runs r ON r.run_id = d.run_id
    WHERE r.status = 'published' AND d.customer_id = %s
"""
PUBLISHED_RUN_SQL = """
    SELECT r.run_id, r.param_version, r.model_version, r.published_at, r.lambda AS capital_price, r.capital_used,
           p.budget AS capital_budget
    FROM runs r JOIN parameter_sets p USING (param_version) WHERE r.status = 'published'
"""
RUN_COUNTS_SQL = "SELECT action, reason_code, count(*) AS n FROM decisions WHERE run_id = %s GROUP BY 1, 2"
ACTIVE_SET_SQL = (
    "SELECT param_version, to_jsonb(p) - %s::text[] AS params FROM parameter_sets p WHERE status = 'active'"
)
SCENARIOS_SQL = """
    SELECT s.lever, s.value, s.lambda AS capital_price, s.offers, s.capital_used, s.npv, s.default_rate
    FROM run_scenarios s WHERE s.run_id = %s ORDER BY s.lever, s.value
"""
ACCOUNT_SQL = """
    SELECT s.customer_id, s.loan_amount::float8 AS loan_amount, s.ontime_pct::float8 AS ontime_pct,
           d.action, d.reason_code, p.step, p.cycle
    FROM customer_state s
    JOIN decisions d USING (customer_id)
    JOIN runs r ON r.run_id = d.run_id AND r.status = 'published'
    JOIN parameter_sets p ON p.param_version = r.param_version
    WHERE s.customer_id = %s
"""
LATEST_LOAN_SQL = """
    SELECT e.occurred_at, e.payload ->> 'loan_id' AS loan_id, (e.payload ->> 'amount')::float8 AS amount,
           (e.payload ->> 'due_at')::timestamptz AS due_at,
           EXISTS (SELECT FROM events x WHERE x.customer_id = e.customer_id AND x.event_type = 'repay'
                   AND x.payload ->> 'loan_id' = e.payload ->> 'loan_id') AS repaid
    FROM events e WHERE e.customer_id = %s AND e.event_type = 'disburse'
    ORDER BY e.occurred_at DESC, e.event_id DESC LIMIT 1
"""

# One statement for the whole batch (unnest turns the column arrays back into rows). Ids that already
# exist are skipped, and RETURNING lists only the rows this request actually inserted.
INSERT_EVENTS_SQL = """
    INSERT INTO events (event_id, customer_id, event_type, occurred_at, payload)
    SELECT * FROM unnest(%s::text[], %s::bigint[], %s::text[], %s::timestamptz[], %s::jsonb[])
    ON CONFLICT (event_id) DO NOTHING
    RETURNING event_id
"""
STORED_EVENTS_SQL = """
    SELECT event_id, customer_id, event_type, occurred_at, payload FROM events WHERE event_id = ANY(%s)
"""
EVENT_FIELDS = ("customer_id", "event_type", "occurred_at", "payload")  # what must match on a retry

# The Postgres role Entra mapped to this user: Azure Postgres stores the mapping as a security label
# 'aadauth,oid=<object id>,type=user[,admin]' on the role (db/bootstrap_identity.sql).
LOGIN_ROLE_SQL = """
    SELECT r.rolname FROM pg_shseclabel s JOIN pg_roles r ON r.oid = s.objoid
    WHERE s.classoid = 'pg_authid'::regclass AND s.provider = 'pgaadauth'
      AND %s = ANY(string_to_array(s.label, ','))
"""
GOVERNANCE = ("param_version", "status", "note", "maker", "created_at", "checker", "checked_at")
PARAMETER_SETS_SQL = f"""
    SELECT {", ".join(GOVERNANCE)}, to_jsonb(p) - %s::text[] AS params
    FROM parameter_sets p WHERE status IN ('proposed', 'approved', 'active') ORDER BY param_version DESC
"""
MOVE_SQL = f"""
    UPDATE parameter_sets p SET status = %s WHERE param_version = %s
    RETURNING {", ".join(GOVERNANCE)}, to_jsonb(p) - %s::text[] AS params
"""
TARGET = {"approve": "approved", "reject": "rejected", "activate": "active"}
MODEL_COLUMNS = (
    "n0", "kappa", "early", "early_fee", "gamma", "step", "lgd", "m", "fee", "c0", "c_deny", "k_prime", "k_near",
    "k_sub", "budget", "disc", "fixed_cost", "fatigue", "horizon", "cycle", "max_k",
)  # fmt: skip
# Business choices a person may change through the API. Estimates (LGD, kappa, ...) come from the monthly estimation:
# lowering one raises projected profit without changing real losses.
LEVERS = ("budget", "step", "fee")
_COPY = ", ".join(f"coalesce(%s::float8, a.{c})" if c in LEVERS else f"a.{c}" for c in MODEL_COLUMNS)
PROPOSE_SQL = f"""
    INSERT INTO parameter_sets AS p (status, note, {", ".join(MODEL_COLUMNS)})
    SELECT 'proposed', %s, {_COPY}
    FROM parameter_sets a WHERE a.status = 'active'
    RETURNING {", ".join(GOVERNANCE)}, to_jsonb(p) - %s::text[] AS params
"""
ASSERTION_SCOPE = "api://AzureADTokenExchange/.default"  # managed identity token the app presents as its credential
CLOCK_SKEW = timedelta(minutes=5)  # tolerated difference between the partner's clock and ours
MAX_BATCH = 1000


class TokenConnection(psycopg.Connection):
    """A psycopg connection whose password is a fresh Entra access token."""

    @classmethod
    def connect(cls, conninfo: str = "", **kwargs):
        kwargs["password"] = credential.get_token(TOKEN_SCOPE).token
        return super().connect(conninfo, **kwargs)


class Decision(BaseModel):
    customer_id: int
    action: Literal["offer", "hold"]
    run_id: int  # the nightly run that produced it
    param_version: int  # approved parameter set it used
    model_version: str  # git SHA of the code it ran
    published_at: datetime
    # Why (NULL for runs published before reason codes existed):
    reason_code: Literal["npv_positive", "capital_limit", "risk_return"] | None
    reason: str | None = None  # the code in plain words, for people
    q_hold: float | None  # first-window value of holding, present-value USD net of the capital charge
    q_offer: float | None  # ... and of offering; the decision is whichever is larger

    @model_validator(mode="after")
    def describe(self) -> "Decision":
        self.reason = REASONS[self.reason_code] if self.reason_code else None
        return self


REASONS = {
    "npv_positive": "An increase is expected to add value: margin and fee outweigh the extra risk and capital.",
    "capital_limit": "An increase would add value, but this cycle's capital budget went where it adds more.",
    "risk_return": "Expected losses and churn on a larger limit outweigh its margin and fee for now.",
}


class Portfolio(BaseModel):
    run_id: int
    param_version: int  # the set this run used
    model_version: str
    published_at: datetime
    capital_price: float | None  # lambda*: the value of one more dollar of capital
    offers: int
    holds: int
    by_reason: dict[str, int]
    capital_used: float | None  # simulated mean over 100 paths; null for runs before this was recorded
    capital_budget: float
    capital_left: float | None = None
    active_param_version: int | None  # may be newer than the run: it takes effect at the next nightly run
    active_params: dict[str, Any] | None

    @model_validator(mode="after")
    def left(self) -> "Portfolio":
        self.capital_left = None if self.capital_used is None else self.capital_budget - self.capital_used
        return self


class Scenario(BaseModel):
    lever: Literal["baseline", "budget", "step", "fee"]
    value: float
    capital_price: float
    offers: int
    capital_used: float
    npv: float
    default_rate: float


class ScenarioSet(BaseModel):
    run_id: int
    scenarios: list[Scenario]  # empty until jobs/scenarios.py has run for this run


ONTIME_BANDS = (85, 95)  # on-time percentages where the risk band changes (lending.params.CUTS; a test ties them)
OFFER_MESSAGE = "You're in line for a limit increase at your next review date, if you keep repaying on time."
# Customer wording, one per hold reason. It never mentions capital: that is the lender's policy, not their record.
HOLD_MESSAGES = {
    "capital_limit": "An increase isn't available this cycle. This doesn't reflect your repayment record.",
    "risk_return": "An increase isn't available yet. Repaying on time is the best way to improve your chances.",
}
HOLD_DEFAULT = "An increase isn't available at the moment."


class NextPayment(BaseModel):
    loan_id: str
    amount: float
    due_at: datetime
    status: Literal["upcoming", "overdue"]


class Account(BaseModel):
    """What a customer may see. Internal values (Q-values, risk band names, run details) are not fields here."""

    customer_id: int
    next_payment: NextPayment | None
    eligible_from: datetime | None  # latest disbursement plus one cycle
    ontime_pct: float
    ontime_target: int | None  # the next band above them; null when already in the top band
    decision: Literal["offer", "hold"]
    message: str
    new_limit: float | None


def account_view(customer: dict, loan: dict | None, now: datetime) -> dict:
    """The customer's account from their state, published decision and latest disbursement."""
    payment = None
    if loan and loan["due_at"] and not loan["repaid"]:
        status = "overdue" if loan["due_at"] < now else "upcoming"
        payment = {"loan_id": loan["loan_id"], "amount": loan["amount"], "due_at": loan["due_at"], "status": status}
    offer = customer["action"] == "offer"
    return {
        "customer_id": customer["customer_id"],
        "next_payment": payment,
        "eligible_from": loan["occurred_at"] + timedelta(days=customer["cycle"]) if loan else None,
        "ontime_pct": customer["ontime_pct"],
        "ontime_target": next((b for b in ONTIME_BANDS if customer["ontime_pct"] < b), None),
        "decision": customer["action"],
        "message": OFFER_MESSAGE if offer else HOLD_MESSAGES.get(customer["reason_code"], HOLD_DEFAULT),
        "new_limit": round(customer["loan_amount"] * (1 + customer["step"]), 2) if offer else None,
    }


class ParameterSet(BaseModel):
    param_version: int
    status: Literal["proposed", "approved", "active", "rejected", "retired"]
    note: str
    maker: str  # database login that proposed it, set by the database
    created_at: datetime
    checker: str | None  # database login that approved or rejected it, set by the database
    checked_at: datetime | None
    params: dict[str, int | float]  # the model assumptions (lending.params.Params fields)


# --- Payload contract per event type ---------------------------------------------------------------
# What state derivation (customer_state_asof in the database) needs from each event, and nothing else.
# An instalment is one (loan_id, due_at): a repay by due_at makes it on time, a miss means it passed unpaid.

Id = Annotated[str, Field(min_length=1, max_length=128)]
Amount = Annotated[float, Field(gt=0, le=1_000_000)]  # USD; the upper bound only rejects typos


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Disburse(Payload):
    loan_id: Id
    amount: Amount
    due_at: AwareDatetime | None = None  # when it must be repaid; absent on older events


class Repay(Payload):
    loan_id: Id
    amount: Amount
    due_at: AwareDatetime  # due date of the instalment this pays


class Miss(Payload):
    loan_id: Id
    due_at: AwareDatetime  # due date that passed unpaid


class Offer(Payload):
    offer_id: Id
    new_limit: Amount


class OfferResponse(Payload):  # accept or decline
    offer_id: Id


PAYLOADS: dict[str, type[Payload]] = {
    "disburse": Disburse,
    "repay": Repay,
    "miss": Miss,
    "offer": Offer,
    "accept": OfferResponse,
    "decline": OfferResponse,
}


class Event(BaseModel):
    """One partner event, same fields and ranges as the events table."""

    model_config = ConfigDict(extra="forbid")  # an unknown field is a contract change, not something to drop

    event_id: str = Field(min_length=1, max_length=128)  # the partner's id: retries reuse it
    customer_id: int = Field(ge=0, le=2**63 - 1)
    event_type: Literal["disburse", "repay", "miss", "offer", "accept", "decline"]
    occurred_at: AwareDatetime  # a timestamp without a time zone is ambiguous, so it is rejected
    payload: dict

    @field_validator("occurred_at")
    @classmethod
    def not_in_future(cls, v: datetime) -> datetime:
        if v > datetime.now(UTC) + CLOCK_SKEW:
            raise ValueError("occurred_at is in the future")
        return v

    @model_validator(mode="after")
    def payload_matches_type(self) -> "Event":
        # Check the payload against its type, then store it in one canonical form (times in UTC, amounts as
        # floats), so a retry that writes the same instant in another time zone is still a duplicate.
        parsed = PAYLOADS[self.event_type].model_validate(self.payload)
        self.payload = {
            k: v.astimezone(UTC).isoformat() if isinstance(v, datetime) else v
            for k, v in parsed.model_dump(exclude_none=True).items()  # unset optionals stay absent, as on older events
        }
        return self


class IngestResult(BaseModel):
    accepted: int  # newly stored
    duplicate: int  # already stored with identical content: a safe retry


class EventConflict(Exception):
    """Event ids already stored with different content."""

    def __init__(self, event_ids: list[str]):
        self.event_ids = event_ids


def conflicting(sent: list[Event], stored: dict[str, dict]) -> list[str]:
    """Ids whose stored row differs from what was sent. A retry must be identical; a correction needs a new id."""
    return [
        e.event_id
        for e in sent
        if e.event_id in stored and stored[e.event_id] != e.model_dump(include=set(EVENT_FIELDS))
    ]


pool = ConnectionPool(
    connection_class=TokenConnection,
    kwargs={"sslmode": "require", "row_factory": dict_row},
    min_size=1,
    max_size=4,
    max_lifetime=1800,  # seconds: recycle before the token that opened the connection expires
    check=ConnectionPool.check_connection,  # drop a dead connection instead of handing it out
    open=False,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    pool.open()  # doesn't wait for the database: the app starts even if Postgres is briefly unreachable
    yield
    pool.close()


app = FastAPI(title="Lending decisions", version="0.1.0", lifespan=lifespan)


# --- Authentication: Entra ID access tokens, authorisation by app role --------------------------------
bearer = HTTPBearer(auto_error=False)  # missing header -> our own 401 with the standard challenge
UNAUTHORIZED = {"WWW-Authenticate": "Bearer"}


def auth_config() -> tuple[str, str]:
    """(tenant id, audience), or 503: an unconfigured API must refuse, never serve without auth."""
    tenant, audience = os.environ.get("AUTH_TENANT_ID"), os.environ.get("AUTH_AUDIENCE")
    if not (tenant and audience):
        raise HTTPException(status_code=503, detail="authentication is not configured")
    return tenant, audience


@cache
def jwks(tenant: str) -> jwt.PyJWKClient:
    # Entra's signing keys for the tenant, cached; an unknown key id (rotation) triggers a refetch.
    return jwt.PyJWKClient(f"https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys", lifespan=3600)


def signing_key(token: str, tenant: str) -> Any:
    """The public key the token says it was signed with (tests replace this with a local test key)."""
    return jwks(tenant).get_signing_key_from_jwt(token).key


def verify_token(creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> dict:
    """Claims of a valid v2 access token for this API: signature, issuer, tenant, audience, expiry."""
    tenant, audience = auth_config()
    if creds is None:
        raise HTTPException(status_code=401, detail="missing bearer token", headers=UNAUTHORIZED)
    try:
        claims = jwt.decode(
            creds.credentials,
            signing_key(creds.credentials, tenant),
            algorithms=["RS256"],  # never let the token choose its algorithm
            audience=audience,
            issuer=f"https://login.microsoftonline.com/{tenant}/v2.0",
            options={"require": ["exp", "iat", "aud", "iss", "tid"]},
            leeway=60,  # seconds of clock skew
        )
    except (jwt.PyJWTError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="invalid token", headers=UNAUTHORIZED) from exc
    if claims["tid"] != tenant:
        raise HTTPException(status_code=401, detail="invalid token", headers=UNAUTHORIZED)
    return claims


def require_role(role: str) -> Callable[[dict], dict]:
    """Dependency: a valid token that also carries this app role (403 when valid but without it)."""

    def check(claims: Annotated[dict, Depends(verify_token)]) -> dict:
        if role not in claims.get("roles", []):
            raise HTTPException(status_code=403, detail=f"requires the {role} role")
        return claims

    return check


def decision_store() -> Iterator[Callable[[int], dict | None]]:
    """Dependency: a lookup function (tests swap in a fake, so no database is needed)."""

    def lookup(customer_id: int) -> dict | None:
        with pool.connection() as conn:
            return conn.execute(DECISION_SQL, (customer_id,)).fetchone()  # type: ignore[return-value]

    yield lookup


def portfolio_store() -> Iterator[Callable[[], dict | None]]:
    """Dependency: the published run's summary, or None (tests swap in a fake)."""

    def lookup() -> dict | None:
        with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            run = cur.execute(PUBLISHED_RUN_SQL).fetchone()
            if run is None:
                return None
            counts = cur.execute(RUN_COUNTS_SQL, (run["run_id"],)).fetchall()
            active = cur.execute(ACTIVE_SET_SQL, (list(GOVERNANCE),)).fetchone()
        by_reason: dict[str, int] = {}
        for c in counts:
            if c["reason_code"]:
                by_reason[c["reason_code"]] = by_reason.get(c["reason_code"], 0) + c["n"]
        return run | {
            "offers": sum(c["n"] for c in counts if c["action"] == "offer"),
            "holds": sum(c["n"] for c in counts if c["action"] == "hold"),
            "by_reason": by_reason,
            "active_param_version": active["param_version"] if active else None,
            "active_params": active["params"] if active else None,
        }

    yield lookup


def scenario_store() -> Iterator[Callable[[], dict | None]]:
    """Dependency: the published run's precomputed scenarios, or None if nothing is published."""

    def lookup() -> dict | None:
        with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            run = cur.execute("SELECT run_id FROM runs WHERE status = 'published'").fetchone()
            if run is None:
                return None
            rows = cur.execute(SCENARIOS_SQL, (run["run_id"],)).fetchall()
            return {"run_id": run["run_id"], "scenarios": rows}

    yield lookup


def account_store() -> Iterator[Callable[[int], tuple[dict | None, dict | None]]]:
    """Dependency: (customer with their published decision, latest disbursement). Tests swap in a fake."""

    def lookup(customer_id: int) -> tuple[dict | None, dict | None]:
        with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            customer = cur.execute(ACCOUNT_SQL, (customer_id,)).fetchone()
            loan = cur.execute(LATEST_LOAN_SQL, (customer_id,)).fetchone() if customer else None
        return customer, loan

    yield lookup


def event_store() -> Iterator[Callable[[list[Event]], IngestResult]]:
    """Dependency: stores a batch in one transaction, or raises EventConflict and stores nothing."""

    def ingest(events: list[Event]) -> IngestResult:
        cols = [[e.event_id for e in events], [e.customer_id for e in events], [e.event_type for e in events]]
        cols += [[e.occurred_at for e in events], [Jsonb(e.payload) for e in events]]
        with pool.connection() as conn, conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            inserted = {r["event_id"] for r in cur.execute(INSERT_EVENTS_SQL, cols).fetchall()}
            retried = [e.event_id for e in events if e.event_id not in inserted]
            stored = {r.pop("event_id"): r for r in cur.execute(STORED_EVENTS_SQL, (retried,)).fetchall()}
            if bad := conflicting(events, stored):
                raise EventConflict(bad)  # leaving the block rolls back this batch's inserts too
        return IngestResult(accepted=len(inserted), duplicate=len(retried))

    yield ingest


def person_with(*roles: str) -> Callable[[dict], dict]:
    """Dependency: a person's token (delegated: it has scp) holding one of these roles. An app-only token can't act
    for anyone, and the database must see who really did it."""

    def check(claims: Annotated[dict, Depends(verify_token)]) -> dict:
        if not set(roles) & set(claims.get("roles", [])):
            raise HTTPException(status_code=403, detail=f"requires one of the roles: {', '.join(roles)}")
        if "scp" not in claims or "oid" not in claims:
            raise HTTPException(status_code=403, detail="needs a signed-in person's token, not an application's")
        return claims

    return check


approver = person_with("Parameters.Approve")
proposer = person_with("Parameters.Propose")
reviewer = person_with("Parameters.Approve", "Parameters.Propose")  # may see sets, and log in as themselves


@contextmanager
def database_refusals() -> Iterator[None]:
    """The database decides who may do what; its answers become HTTP answers with its reason."""
    try:
        yield
    except psycopg.errors.CheckViolation as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except psycopg.errors.InsufficientPrivilege as exc:
        raise HTTPException(status_code=403, detail="the database refused: you lack the database role") from exc


class ParameterStore:
    """Parameter-set reads and status changes on a connection logged in as the caller's own database role."""

    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def in_play(self) -> list[dict]:
        return self.conn.execute(PARAMETER_SETS_SQL, (list(GOVERNANCE),)).fetchall()  # type: ignore[return-value]

    def move(self, version: int, action: str) -> dict:
        """The set after the change (LookupError if there is none). The database decides who may do what."""
        with self.conn.transaction():
            if action == "activate":  # one active set at a time: retire the current one in the same transaction
                self.conn.execute(
                    "UPDATE parameter_sets SET status = 'retired' WHERE status = 'active' AND param_version <> %s",
                    (version,),
                )
            row = self.conn.execute(MOVE_SQL, (TARGET[action], version, list(GOVERNANCE))).fetchone()
            if row is None:
                raise LookupError(version)  # rolls back the retirement too
        return row  # type: ignore[return-value]

    def propose(self, changes: dict, note: str) -> dict | None:
        """A new proposed set: the active set with these changes. None if nothing is active to copy."""
        values = [changes.get(c) for c in MODEL_COLUMNS if c in LEVERS]
        with self.conn.transaction():
            return self.conn.execute(PROPOSE_SQL, (note, *values, list(GOVERNANCE))).fetchone()  # type: ignore[return-value]


def parameter_store(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    claims: Annotated[dict, Depends(reviewer)],
) -> Iterator[ParameterStore]:
    """Dependency: a store connected to Postgres as the caller (tests swap in a fake)."""
    tenant, audience = auth_config()
    with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        login = cur.execute(LOGIN_ROLE_SQL, (f"oid={claims['oid']}",)).fetchone()
    if login is None:
        raise HTTPException(status_code=403, detail="you have no database login")
    # ponytail: one token exchange per request (fine at approval volumes); cache per user if it ever matters.
    obo = OnBehalfOfCredential(
        tenant,
        audience,
        user_assertion=creds.credentials,  # type: ignore[union-attr]  # approver() guarantees a token
        client_assertion_func=lambda: credential.get_token(ASSERTION_SCOPE).token,
    )
    password = obo.get_token(TOKEN_SCOPE).token
    with psycopg.connect(user=login["rolname"], password=password, sslmode="require", row_factory=dict_row) as user:
        yield ParameterStore(user)  # type: ignore[arg-type]


@app.post("/events", response_model=IngestResult)
def post_events(
    events: Annotated[list[Event], Body(min_length=1, max_length=MAX_BATCH)],
    ingest: Annotated[Callable[[list[Event]], IngestResult], Depends(event_store)],
    _: Annotated[dict, Depends(require_role("Events.Write"))],
) -> IngestResult:
    """Store a batch of partner events. Safe to retry: identical events already stored count as duplicates.

    All or nothing: if any id is already stored with different content, nothing is stored and the response
    is 409 with those ids, so a correction is never silently dropped.
    """
    ids = [e.event_id for e in events]
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=422, detail="duplicate event_id within the batch")
    try:
        return ingest(events)
    except EventConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": "event_id already stored with different content", "event_ids": exc.event_ids},
        ) from exc


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/decisions/{customer_id}", response_model=Decision)
def get_decision(
    customer_id: Annotated[int, Path(ge=0, le=2**63 - 1)],  # bigint range, as in the decisions table
    lookup: Annotated[Callable[[int], dict | None], Depends(decision_store)],
    _: Annotated[dict, Depends(require_role("Decisions.Read"))],
) -> dict:
    row = lookup(customer_id)
    if row is None:
        raise HTTPException(status_code=404, detail="no decision for this customer in the published run")
    return row


@app.get("/portfolio", response_model=Portfolio)
def get_portfolio(
    lookup: Annotated[Callable[[], dict | None], Depends(portfolio_store)],
    _: Annotated[dict, Depends(require_role("Decisions.Read"))],
) -> dict:
    """The published run: offers, holds, reasons and capital, plus the active parameter set."""
    row = lookup()
    if row is None:
        raise HTTPException(status_code=404, detail="no published run")
    return row


@app.get("/portfolio/scenarios", response_model=ScenarioSet)
def get_scenarios(
    lookup: Annotated[Callable[[], dict | None], Depends(scenario_store)],
    _: Annotated[dict, Depends(require_role("Decisions.Read"))],
) -> dict:
    """Precomputed what-if results for the published run: simulated estimates, one change at a time."""
    row = lookup()
    if row is None:
        raise HTTPException(status_code=404, detail="no published run")
    return row


@app.get("/customers/{customer_id}/account", response_model=Account)
def get_account(
    customer_id: Annotated[int, Path(ge=0, le=2**63 - 1)],
    lookup: Annotated[Callable[[int], tuple[dict | None, dict | None]], Depends(account_store)],
    _: Annotated[dict, Depends(require_role("Decisions.Read"))],
) -> dict:
    """A customer's next payment, eligibility date and limit decision, in their own terms."""
    # ponytail: any caller with Decisions.Read can read any id (demo).
    # Real customers need sign-in and an own-record endpoint first.
    customer, loan = lookup(customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="no such customer")
    return account_view(customer, loan, datetime.now(UTC))


@app.get("/parameter-sets", response_model=list[ParameterSet])
def list_parameter_sets(
    store: Annotated[ParameterStore, Depends(parameter_store)],
    _: Annotated[dict, Depends(reviewer)],
) -> list[dict]:
    """Parameter sets awaiting a decision or in force, newest first."""
    return store.in_play()


@app.post("/parameter-sets/{version}/{action}", response_model=ParameterSet)
def change_parameter_set(
    version: Annotated[int, Path(ge=1, le=2**31 - 1)],
    action: Literal["approve", "reject", "activate"],
    store: Annotated[ParameterStore, Depends(parameter_store)],
    _: Annotated[dict, Depends(approver)],
) -> dict:
    """Approve or reject a proposed set, reject an approved one, or activate an approved one (retiring the active set).

    The database enforces maker-checker: the caller must be a checker and not the set's maker. A refused
    change is a 409 with the database's reason; repeating a change already made is a no-op.
    """
    try:
        with database_refusals():
            return store.move(version, action)
    except LookupError:
        raise HTTPException(status_code=404, detail="no such parameter set") from None


class Proposal(BaseModel):
    """A change to the active set. Only business choices: any other field is refused."""

    model_config = ConfigDict(extra="forbid")

    note: str = Field(min_length=1, max_length=500)  # why: the checker reads this
    budget: float | None = Field(default=None, gt=0)
    step: float | None = Field(default=None, gt=0, le=1)
    fee: float | None = Field(default=None, ge=0, le=1000)

    @model_validator(mode="after")
    def changes_something(self) -> "Proposal":
        if self.budget is None and self.step is None and self.fee is None:
            raise ValueError("a proposal must change budget, step or fee")
        return self


@app.post("/parameter-sets", response_model=ParameterSet, status_code=201)
def propose_parameter_set(
    proposal: Proposal,
    store: Annotated[ParameterStore, Depends(parameter_store)],
    _: Annotated[dict, Depends(proposer)],
) -> dict:
    """Propose a change, as the caller: a new set copied from the active one. A checker reviews it in the app."""
    with database_refusals():
        row = store.propose(proposal.model_dump(exclude={"note"}, exclude_none=True), proposal.note)
    if row is None:
        raise HTTPException(status_code=409, detail="no active parameter set to copy")
    return row
