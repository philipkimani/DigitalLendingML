"""Decision API: serves the nightly job's precomputed decisions. It never solves anything on request.

    GET /decisions/{customer_id}  today's action from the published run, with what produced it
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
from datetime import datetime
from typing import Annotated, Literal

import psycopg
from azure.identity import DefaultAzureCredential
from fastapi import Depends, FastAPI, HTTPException, Path
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

TOKEN_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"  # Entra resource for Azure Postgres
credential = DefaultAzureCredential()  # caches the token and refreshes it before expiry

# Index-backed lookup: one published run (partial unique index), then the (run_id, customer_id) primary key.
DECISION_SQL = """
    SELECT d.customer_id, d.action, d.run_id, d.param_version, d.model_version, r.published_at
    FROM decisions d JOIN runs r ON r.run_id = d.run_id
    WHERE r.status = 'published' AND d.customer_id = %s
"""


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
