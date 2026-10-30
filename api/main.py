"""Decision API: serves the nightly job's precomputed decisions. It never solves anything on request.

    GET /decisions/{customer_id}  today's action from the published run, with what produced it
    POST /events                  partner event ingest, idempotent on the partner's event_id
    GET /healthz                  liveness (no database call, so a database blip doesn't restart the app)

Connection settings come from the standard libpq variables PGHOST, PGDATABASE, PGUSER (set on the
Container App). There is no stored password: each new connection gets a fresh Entra token from the
managed identity (DefaultAzureCredential; AZURE_CLIENT_ID picks the identity). Azure Postgres only checks
the token at connect time, so pooled connections are recycled every 30 minutes, well inside its lifetime.

Run locally against the dev database, signed in with the az CLI:
    PGHOST=... PGDATABASE=lending PGUSER=<your Entra UPN> uv run --group api uvicorn api.main:app --port 8000
"""

from collections.abc import Callable, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

import psycopg
from azure.identity import DefaultAzureCredential
from fastapi import Body, Depends, FastAPI, HTTPException, Path
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

TOKEN_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"  # Entra resource for Azure Postgres
credential = DefaultAzureCredential()  # caches the token and refreshes it before expiry

# Index-backed lookup: one published run (partial unique index), then the (run_id, customer_id) primary key.
DECISION_SQL = """
    SELECT d.customer_id, d.action, d.run_id, d.param_version, d.model_version, r.published_at
    FROM decisions d JOIN runs r ON r.run_id = d.run_id
    WHERE r.status = 'published' AND d.customer_id = %s
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
            k: v.astimezone(UTC).isoformat() if isinstance(v, datetime) else v for k, v in parsed.model_dump().items()
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


def decision_store() -> Iterator[Callable[[int], dict | None]]:
    """Dependency: a lookup function (tests swap in a fake, so no database is needed)."""

    def lookup(customer_id: int) -> dict | None:
        with pool.connection() as conn:
            return conn.execute(DECISION_SQL, (customer_id,)).fetchone()  # type: ignore[return-value]

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


@app.post("/events", response_model=IngestResult)
def post_events(
    events: Annotated[list[Event], Body(min_length=1, max_length=MAX_BATCH)],
    ingest: Annotated[Callable[[list[Event]], IngestResult], Depends(event_store)],
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
) -> dict:
    row = lookup(customer_id)
    if row is None:
        raise HTTPException(status_code=404, detail="no decision for this customer in the published run")
    return row
