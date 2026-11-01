"""Monthly estimation job: estimate parameters from the event log and propose them as a new parameter set.

    python jobs/estimate.py --model-version <git sha> [--year 2024] [--as-of 2026-06-01T00:00:00+00:00] [--dry-run]

Environment and sign-in as for jobs/nightly.py (PGHOST, PGUSER, AZURE_CLIENT_ID on Azure ML; no password).

Steps:
  1. read the active parameter set, the customers' state at the start of the planning year
     (customer_state_asof), and the events from then until as_of (only those received by as_of);
  2. estimate kappa, gamma, fatigue, early and c0 (lending.estimate); a parameter with too little data keeps
     the active value;
  3. if any value changed, insert ONE parameter set with status 'proposed': the active values with the
     estimates swapped in, and a note listing each estimate with its 95% interval and sample size. The database
     records this identity as the maker; a person must approve and activate it (maker-checker).
Nothing goes live here. --dry-run inserts and rolls back, which proves the database would accept the proposal.
"""

import argparse
from datetime import UTC, datetime, timedelta

import pandas as pd
from nightly import EVENTS_SQL, connect, mlflow  # same directory; run as `python jobs/estimate.py`
from psycopg.rows import dict_row

from lending import Book
from lending.contract import split_valid
from lending.decisions import params_from_row
from lending.estimate import estimate_all

GOVERNANCE = {"param_version", "status", "note", "maker", "created_at", "checker", "checked_at"}
EV_SQL = """
    SELECT customer_id, event_type, occurred_at, payload FROM events
    WHERE occurred_at >= %(start)s AND occurred_at <= %(as_of)s AND received_at <= %(as_of)s
"""


def proposal(active: dict, est: dict, year: int, as_of: datetime, sha: str) -> tuple[dict, str, int]:
    """(new values, note, number of changed values): the active values with usable estimates swapped in."""
    values = {c: v for c, v in active.items() if c not in GOVERNANCE}
    lines, changed = [], 0
    for name, e in est.items():
        old = float(active[name])
        if not e.ok:
            lines.append(f"{name} kept at {old:g}: {e.reason}")
            continue
        new = round(e.value, 4)
        lo, hi = e.value - 1.96 * e.se, e.value + 1.96 * e.se
        lines.append(f"{name} {new:g} (95% CI {lo:.4f}-{hi:.4f}, n {e.n:,}; active {old:g})")
        values[name], changed = new, changed + (new != old)
    note = (
        f"Estimated from events, planning year {year}, as of {as_of:%Y-%m-%d}, model {sha[:7]}; "
        f"other values from set {active['param_version']}. " + "; ".join(lines) + "."
    )
    return values, note, changed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-version", required=True, help="git SHA of the code being run")
    ap.add_argument("--year", type=int, default=datetime.now(UTC).year - 1, help="planning year to learn from")
    ap.add_argument("--as-of", type=datetime.fromisoformat, help="data cut-off (default: now)")
    ap.add_argument("--dry-run", action="store_true", help="insert the proposal and roll back")
    args = ap.parse_args()
    as_of = args.as_of or datetime.now(UTC)
    if as_of.tzinfo is None:
        ap.error("--as-of needs a time zone (e.g. 2026-06-01T00:00:00+00:00)")
    start = datetime(args.year, 1, 1, tzinfo=UTC)
    if as_of < start + timedelta(days=365 + 90):
        print(f"warning: as-of {as_of:%Y-%m-%d} leaves loans from late {args.year} immature; they are left out")

    # --- 1. Inputs ---------------------------------------------------------------------------------
    with connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute("SELECT * FROM parameter_sets WHERE status = 'active'").fetchall()
        if len(rows) != 1:
            raise SystemExit(f"expected exactly one active parameter set, found {len(rows)}")
        active = rows[0]
        state = pd.DataFrame(cur.execute(EVENTS_SQL, (start,)).fetchall())
        ev = pd.DataFrame(cur.execute(EV_SQL, {"start": start, "as_of": as_of}).fetchall())
    if state.empty or ev.empty:
        raise SystemExit(f"no customer state at {start:%Y-%m-%d} or no events after it: nothing to learn from")
    state, dropped = split_valid(state)
    book = Book.from_frame(state)
    ev["occurred_at"] = pd.to_datetime(ev.occurred_at, utc=True)

    # --- 2. Estimate -------------------------------------------------------------------------------
    p = params_from_row(active)
    est = estimate_all(ev, book, p, start, as_of)
    values, note, changed = proposal(active, est, args.year, as_of, args.model_version)
    print(f"{len(book):,} customers ({dropped} outside the contract), {len(ev):,} events, year {args.year}")
    for name, e in est.items():
        print(f"  {name:8s} {e.value:.4f}  se {e.se:.4f}  n {e.n:>7,}  {'ok' if e.ok else 'kept: ' + e.reason}")

    # --- 3. Propose (one INSERT; the database decides who may approve) --------------------------------
    version = None
    if changed:
        cols = ", ".join(["status", "note", *values])
        marks = ", ".join(["%s"] * (len(values) + 2))
        with connect() as conn, conn.cursor() as cur:
            row = cur.execute(
                f"INSERT INTO parameter_sets ({cols}) VALUES ({marks}) RETURNING param_version",
                ["proposed", note, *values.values()],
            ).fetchone()
            if row is None:
                raise SystemExit("INSERT INTO parameter_sets returned no version")
            version = row[0]
            if args.dry_run:
                conn.rollback()
    outcome = "no change: nothing proposed" if not changed else f"set {version} proposed"
    print(f"{outcome}{' (rolled back: dry run)' if args.dry_run and changed else ''}\n{note}")

    if mlflow:
        mlflow.log_params({"year": args.year, "as_of": as_of.isoformat(), "base_set": active["param_version"]})
        mlflow.log_metrics(
            {f"{k}_{n}": float(getattr(e, k)) for n, e in est.items() for k in ("value", "se", "n") if e.ok}
            | {"customers": len(book), "events": len(ev), "changed": changed}
        )
        mlflow.set_tags({"model_version": args.model_version, "dry_run": args.dry_run, "proposed": version})


if __name__ == "__main__":
    main()
