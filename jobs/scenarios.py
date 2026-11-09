"""Scenarios job: precompute what-if results for the published run, for the internal agent.

    python jobs/scenarios.py [--chunk 5000]

Environment: as jobs/nightly.py (PGHOST, PGUSER, AZURE_CLIENT_ID on Azure ML). Reads the published run's parameter
set and the book it solved, measures each scenario in lending.scenarios.grid, and writes run_scenarios in one
transaction. Re-running replaces that run's rows. Started by hand, like the nightly job.
"""

import argparse
import os

import pandas as pd
import psycopg
from azure.identity import DefaultAzureCredential
from psycopg.rows import dict_row

from lending import Book
from lending.contract import split_valid
from lending.decisions import params_from_row
from lending.scenarios import evaluate, grid

TOKEN_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"
BOOK_SQL = """
    SELECT customer_id, loan_amount::float8, days_since_last_loan, ontime_pct::float8, n_increases
    FROM customer_state ORDER BY customer_id
"""
UPSERT_SQL = """
    INSERT INTO run_scenarios (run_id, lever, value, lambda, offers, capital_used, npv, default_rate)
    VALUES (%(run_id)s, %(lever)s, %(value)s, %(lambda)s, %(offers)s, %(capital_used)s, %(npv)s, %(default_rate)s)
    ON CONFLICT (run_id, lever, value) DO UPDATE SET
        lambda = EXCLUDED.lambda, offers = EXCLUDED.offers, capital_used = EXCLUDED.capital_used,
        npv = EXCLUDED.npv, default_rate = EXCLUDED.default_rate
"""


def connect() -> psycopg.Connection:
    token = DefaultAzureCredential().get_token(TOKEN_SCOPE).token
    return psycopg.connect(
        host=os.environ["PGHOST"], dbname="lending", user=os.environ["PGUSER"], password=token, sslmode="require"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunk", type=int, default=5000, help="customers solved at once")
    args = ap.parse_args()

    with connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            "SELECT r.run_id, p.* FROM runs r JOIN parameter_sets p USING (param_version) WHERE r.status = 'published'"
        ).fetchone()
        if row is None:
            raise SystemExit("no published run")
        df = pd.DataFrame(cur.execute(BOOK_SQL).fetchall())

    df, dropped = split_valid(df)
    if dropped:
        raise SystemExit(f"{dropped} customer_state rows break the data contract")
    book, params = Book.from_frame(df), params_from_row(row)

    results = []
    for lever, value in grid(params):
        try:
            results.append(evaluate(book, params, lever, value, chunk=args.chunk))
        except ValueError as exc:  # no capital price fits this budget: skip the row, keep the others
            print(f"skipped {lever}={value}: {exc}")
            continue
        print(results[-1])

    with connect() as conn, conn.cursor() as cur:
        cur.executemany(UPSERT_SQL, [r | {"run_id": row["run_id"]} for r in results])
    print(f"run {row['run_id']}: {len(results)} scenarios written")


if __name__ == "__main__":
    main()
