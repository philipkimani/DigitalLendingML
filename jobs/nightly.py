"""Nightly job: solve the policy for the whole book and publish one decision per customer.

    python jobs/nightly.py --model-version <git sha> [--dry-run] [--chunk 5000]
                           [--state-source table|events] [--as-of 2026-01-01T00:00:00Z]

Environment: PGHOST (server), PGUSER (the Postgres role: the managed identity's name on Azure ML,
your Entra UPN locally), AZURE_CLIENT_ID on Azure ML (selects the user-assigned identity).
There is no password: DefaultAzureCredential gets an Entra token (managed identity on Azure ML,
the az CLI sign-in locally) and the token is the password.

Steps:
  1. read the active parameter set and the customers' state (short read transaction), either from the
     customer_state table (dev seed) or derived from the event log as of a moment (customer_state_asof,
     migration 003; the run records that moment, so its input can be rebuilt exactly);
  2. calibrate, find the capital price lambda* by bisection, solve the book in chunks at lambda* and at
     lambda = 0 (the free-capital counterfactual behind each decision's reason code);
  3. write the run and its decisions, then publish it, all in ONE transaction: the API sees the
     previous run until the commit and the complete new run after it, never anything in between.
--dry-run does everything and rolls back step 3 (nothing is published).
"""

import argparse
import hashlib
import os
from datetime import UTC, datetime

import pandas as pd
import psycopg
from azure.identity import DefaultAzureCredential
from psycopg.rows import dict_row

from lending import Book, Model, capital, find_lambda, solve
from lending.contract import split_valid
from lending.decisions import explain, params_from_row

try:  # MLflow is in the Azure ML environment, not needed locally.
    import mlflow
except ImportError:  # ponytail: local runs print metrics instead
    mlflow = None

TOKEN_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"  # Entra resource for Azure Postgres
BOOK_SQL = """
    SELECT customer_id, loan_amount::float8, days_since_last_loan, ontime_pct::float8, n_increases
    FROM customer_state ORDER BY customer_id
"""
EVENTS_SQL = """
    SELECT customer_id, loan_amount::float8, days_since_last_loan, ontime_pct::float8, n_increases
    FROM customer_state_asof(%s) ORDER BY customer_id
"""


def connect() -> psycopg.Connection:
    token = DefaultAzureCredential().get_token(TOKEN_SCOPE).token
    return psycopg.connect(
        host=os.environ["PGHOST"], dbname="lending", user=os.environ["PGUSER"], password=token, sslmode="require"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-version", required=True, help="git SHA of the code being run")
    ap.add_argument("--chunk", type=int, default=5000, help="customers solved at once (memory ~1.6 KB each)")
    ap.add_argument("--dry-run", action="store_true", help="roll back instead of publishing")
    ap.add_argument(
        "--state-source", choices=["table", "events"], default="table", help="where customer state comes from"
    )
    ap.add_argument("--as-of", type=datetime.fromisoformat, help="events only: state as of this moment (default: now)")
    ap.add_argument(
        "--max-dropped", type=float, default=0.01, help="events only: fail if more customers fall outside the contract"
    )
    args = ap.parse_args()
    if args.as_of and args.state_source != "events":
        ap.error("--as-of needs --state-source events")
    as_of = (args.as_of or datetime.now(UTC)) if args.state_source == "events" else None
    if as_of and as_of.tzinfo is None:
        ap.error("--as-of needs a time zone (e.g. 2026-01-01T00:00:00+00:00)")

    # --- 1. Inputs ---------------------------------------------------------------------------------
    with connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        active = cur.execute("SELECT * FROM parameter_sets WHERE status = 'active'").fetchall()
        if len(active) != 1:  # the unique index allows at most one; zero means nothing is approved
            raise SystemExit(f"expected exactly one active parameter set, found {len(active)}")
        param_row = active[0]
        rows = cur.execute(EVENTS_SQL, (as_of,)) if as_of else cur.execute(BOOK_SQL)
        df = pd.DataFrame(rows.fetchall())

    # Fingerprint of the exact rows solved: customer_state changes over time, so the run records which state it saw.
    # Fixed "\n" line endings: pandas defaults to the OS's (\r\n on Windows), which would give the same rows a
    # different fingerprint on a laptop than on Azure ML.
    md5 = hashlib.md5(df.to_csv(index=False, lineterminator="\n").encode()).hexdigest()
    source = f"events_asof={as_of.isoformat()}" if as_of else "customer_state"
    data_version = f"{source}:n={len(df)}:md5={md5}"

    # --- 2. Solve ----------------------------------------------------------------------------------
    df, dropped = split_valid(df)  # customers outside the model's validated ranges get no decision
    if as_of is None and dropped:
        raise SystemExit(f"{dropped} customer_state rows break the data contract")  # the seed table must be clean
    if dropped > args.max_dropped * (len(df) + dropped):
        raise SystemExit(f"{dropped} of {len(df) + dropped} customers break the data contract: check the events")
    book = Book.from_frame(df)  # data contract enforced here
    model = Model.calibrate(book, params_from_row(param_row))
    lam = find_lambda(book, model, chunk=args.chunk)
    parts = []
    for part in book.chunks(args.chunk):
        pol, _, q = solve(part, model, lam)
        parts.append(explain(part, pol, q, solve(part, model, 0.0)[0]))
    decisions = pd.concat(parts)
    metrics = {
        "lambda": lam,
        "customers": len(decisions),
        "customers_dropped": dropped,
        "offers": int((decisions.action == "offer").sum()),
        "capital_used": capital(book, model, lam, chunk=args.chunk),
        "capital_budget": model.p.budget,
        **{f"offer_rate_bucket_{b}": float((g.action == "offer").mean()) for b, g in decisions.groupby("bucket")},
        **{f"reason_{c}": int(n) for c, n in decisions.reason_code.value_counts().items()},
    }

    # --- 3. Write and publish (one transaction) ------------------------------------------------------
    pv, mv = param_row["param_version"], args.model_version
    with connect() as conn, conn.cursor() as cur:
        run_id = cur.execute(
            "INSERT INTO runs (param_version, model_version, data_version, lambda, state_as_of)"
            " VALUES (%s, %s, %s, %s, %s) RETURNING run_id",
            (pv, mv, data_version, lam, as_of),
        ).fetchone()[0]
        # COPY streams all rows in one round trip (30k INSERTs would be 30k).
        cols = "run_id, customer_id, param_version, model_version, action, q_hold, q_offer, reason_code"
        with cur.copy(f"COPY decisions ({cols}) FROM STDIN") as cp:
            for d in decisions.itertuples(index=False):
                cp.write_row(
                    (run_id, int(d.customer_id), pv, mv, d.action, float(d.q_hold), float(d.q_offer), d.reason_code)
                )
        cur.execute("UPDATE runs SET status = 'superseded' WHERE status = 'published'")
        cur.execute("UPDATE runs SET status = 'published', published_at = now() WHERE run_id = %s", (run_id,))
        if args.dry_run:
            conn.rollback()

    print(f"run {run_id} {'rolled back (dry run)' if args.dry_run else 'published'}: {data_version}")
    for k, v in metrics.items():
        print(f"  {k}: {v}")
    if mlflow:
        mlflow.log_params({"param_version": pv, "model_version": mv, "data_version": data_version, "run_id": run_id})
        mlflow.log_metrics(metrics)
        mlflow.set_tag("dry_run", args.dry_run)


if __name__ == "__main__":
    main()
