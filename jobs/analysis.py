"""Analysis job: the report's tables for the published run, for Power BI (roadmap 2.6).

    python jobs/analysis.py [--chunk 5000]

Environment: as jobs/scenarios.py (PGHOST, PGUSER, AZURE_CLIENT_ID on Azure ML). Reads the published run's parameter
set and the book, then writes in one transaction, replacing that run's earlier rows:
  run_strategies + run_forecast: five strategies in the base, adverse and benign macro scenarios (plus the base
                                 policy run in the other two), with monthly increases;
  run_sensitivity:               lending.scenarios.sensitivity_grid, each re-solved at its own capital price.
Started by hand, like the nightly job. Takes about half an hour on one DS2_v2 node.
"""

import argparse

import pandas as pd
from psycopg.rows import dict_row
from scenarios import BOOK_SQL, connect  # same directory; run as `python jobs/analysis.py`

from lending import Book
from lending.contract import split_valid
from lending.decisions import params_from_row
from lending.scenarios import evaluate, sensitivity_grid, strategies

STRATEGY_SQL = """
    INSERT INTO run_strategies (run_id, scenario, strategy, lambda, npv_mean, npv_p5, npv_p95, increases,
                                default_rate, churn_rate, capital)
    VALUES (%(run_id)s, %(scenario)s, %(strategy)s, %(lambda)s, %(npv_mean)s, %(npv_p5)s, %(npv_p95)s,
            %(increases)s, %(default_rate)s, %(churn_rate)s, %(capital)s)
"""
FORECAST_SQL = """
    INSERT INTO run_forecast (run_id, scenario, strategy, month, increases)
    VALUES (%(run_id)s, %(scenario)s, %(strategy)s, %(month)s, %(increases)s)
"""
SENSITIVITY_SQL = """
    INSERT INTO run_sensitivity (run_id, param, value, lambda, offers, capital_used, npv, default_rate)
    VALUES (%(run_id)s, %(param)s, %(value)s, %(lambda)s, %(offers)s, %(capital_used)s, %(npv)s, %(default_rate)s)
"""


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
    book, params, run_id = Book.from_frame(df), params_from_row(row), row["run_id"]

    rows, months = strategies(book, params, "base", chunk=args.chunk)
    base_lambda = next(r["lambda"] for r in rows if r["strategy"] == "optimal")
    for scenario in ("adverse", "benign"):
        more_rows, more_months = strategies(book, params, scenario, base_lambda=base_lambda, chunk=args.chunk)
        rows, months = rows + more_rows, months + more_months
    for r in rows:
        print(r)

    sens = []
    for param, value in sensitivity_grid(params):
        try:
            res = evaluate(book, params, param, value, chunk=args.chunk)
        except ValueError as exc:  # no capital price fits: skip the row, keep the others
            print(f"skipped {param}={value}: {exc}")
            continue
        sens.append({**res, "param": res.pop("lever")})
        print(sens[-1])

    tag = {"run_id": run_id}
    with connect() as conn, conn.cursor() as cur:  # one transaction: the run's old rows go, the new ones land
        cur.execute("DELETE FROM run_strategies WHERE run_id = %s", (run_id,))  # cascades to run_forecast
        cur.execute("DELETE FROM run_sensitivity WHERE run_id = %s", (run_id,))
        cur.executemany(STRATEGY_SQL, [r | tag for r in rows])
        cur.executemany(FORECAST_SQL, [m | tag for m in months])
        cur.executemany(SENSITIVITY_SQL, [s | tag for s in sens])
    print(f"run {run_id}: {len(rows)} strategies, {len(months)} forecast rows, {len(sens)} sensitivities written")


if __name__ == "__main__":
    main()
