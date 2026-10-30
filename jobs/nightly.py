"""Nightly job: solve the policy for the whole book and publish one decision per customer.

    python jobs/nightly.py --model-version <git sha> [--dry-run] [--chunk 5000]

Environment: PGHOST (server), PGUSER (the Postgres role: the managed identity's name on Azure ML,
your Entra UPN locally), AZURE_CLIENT_ID on Azure ML (selects the user-assigned identity).
There is no password: DefaultAzureCredential gets an Entra token (managed identity on Azure ML,
the az CLI sign-in locally) and the token is the password.

Steps:
  1. read the active parameter set and customer_state (short read transaction);
  2. calibrate, find the capital price lambda* by bisection, solve the book in chunks at lambda*;
  3. write the run and its decisions, then publish it, all in ONE transaction: the API sees the
     previous run until the commit and the complete new run after it, never anything in between.
--dry-run does everything and rolls back step 3 (nothing is published).
"""

import argparse
import hashlib
import os

import pandas as pd
import psycopg
from azure.identity import DefaultAzureCredential
from psycopg.rows import dict_row

from lending import Book, Model, capital, find_lambda, solve
from lending.decisions import first_window, params_from_row

try:  # MLflow is in the Azure ML environment, not needed locally.
    import mlflow
except ImportError:  # ponytail: local runs print metrics instead
    mlflow = None

TOKEN_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"  # Entra resource for Azure Postgres
BOOK_SQL = """
    SELECT customer_id, loan_amount::float8, days_since_last_loan, ontime_pct::float8, n_increases
    FROM customer_state ORDER BY customer_id
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
    args = ap.parse_args()

    # --- 1. Inputs ---------------------------------------------------------------------------------
    with connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        active = cur.execute("SELECT * FROM parameter_sets WHERE status = 'active'").fetchall()
        if len(active) != 1:  # the unique index allows at most one; zero means nothing is approved
            raise SystemExit(f"expected exactly one active parameter set, found {len(active)}")
        param_row = active[0]
        df = pd.DataFrame(cur.execute(BOOK_SQL).fetchall())

    # Fingerprint of the exact rows solved: customer_state changes over time, so the run records which state it saw.
    md5 = hashlib.md5(df.to_csv(index=False).encode()).hexdigest()
    data_version = f"customer_state:n={len(df)}:md5={md5}"

    # --- 2. Solve ----------------------------------------------------------------------------------
    book = Book.from_frame(df)  # data contract enforced here
    model = Model.calibrate(book, params_from_row(param_row))
    lam = find_lambda(book, model, chunk=args.chunk)
    decisions = pd.concat([first_window(part, solve(part, model, lam)[0]) for part in book.chunks(args.chunk)])
    metrics = {
        "lambda": lam,
        "customers": len(decisions),
        "offers": int((decisions.action == "offer").sum()),
        "capital_used": capital(book, model, lam, chunk=args.chunk),
        "capital_budget": model.p.budget,
        **{f"offer_rate_bucket_{b}": float((g.action == "offer").mean()) for b, g in decisions.groupby("bucket")},
    }

    # --- 3. Write and publish (one transaction) ------------------------------------------------------
    pv, mv = param_row["param_version"], args.model_version
    with connect() as conn, conn.cursor() as cur:
        run_id = cur.execute(
            "INSERT INTO runs (param_version, model_version, data_version, lambda) VALUES (%s, %s, %s, %s)"
            " RETURNING run_id",
            (pv, mv, data_version, lam),
        ).fetchone()[0]
        # COPY streams all rows in one round trip (30k INSERTs would be 30k).
        with cur.copy("COPY decisions (run_id, customer_id, param_version, model_version, action) FROM STDIN") as cp:
            for cid, action in zip(decisions.customer_id, decisions.action, strict=True):
                cp.write_row((run_id, int(cid), pv, mv, action))
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
