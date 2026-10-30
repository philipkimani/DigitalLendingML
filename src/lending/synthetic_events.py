"""Synthetic event history for a customer book: the events that, read back by customer_state_asof(T) in the
database (migration 003), give that book again. It lets the event path (log -> derived state -> nightly solve)
run end to end without real customer data.

Per customer, as of T (default 1 January 2026, the date the book's fields are defined against):
  * one disbursement of loan_amount, days_since_last_loan days before T;
  * 20 instalments due in the year before T: floor(ontime_pct / 5) of them repaid by the due date, the rest
    missed (half of those repaid late);
  * n_increases accepted offers in the previous calendar year, plus a few declined ones.

Read back, every field matches exactly except ontime_pct, which comes back rounded down to a multiple of 5
(20 instalments). The bucket boundaries (85, 95) are multiples of 5, so every customer keeps its risk bucket.
ponytail: 20 instalments per customer keeps the dev load small (~25 events each); more instalments give finer
ontime_pct at the cost of volume.

This is a backfill: received_at = occurred_at, i.e. history we are declaring we had at the time. Live ingest
(POST /events) always stamps received_at with the arrival time.

Command line (CSV in the events table's column order, for psql \\copy as the admin):
    uv run python -m lending.synthetic_events --book data/raw/book.csv --seed 7 --out data/raw/events.csv
"""

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

AS_OF = datetime(2026, 1, 1, tzinfo=UTC)
INSTALMENTS = 20  # per customer, due in the year before T
FIELDS = {
    "customer_id": int,
    "loan_amount": float,
    "days_since_last_loan": int,
    "ontime_pct": float,
    "n_increases": int,
}
COLUMNS = ["event_id", "customer_id", "event_type", "occurred_at", "received_at", "payload"]


def events_for_book(book: pd.DataFrame, as_of: datetime = AS_OF, seed: int = 7) -> pd.DataFrame:
    """Event history (columns COLUMNS) whose state as of `as_of` is `expected_state(book)`."""
    if as_of != as_of.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0) or as_of.tzinfo != UTC:
        raise ValueError("as_of must be 1 January 00:00 UTC (the book's fields are defined against it)")
    rng = np.random.default_rng(seed)
    day = timedelta(days=1)
    prev_year = as_of.replace(year=as_of.year - 1)
    rows: list[tuple] = []

    def add(cid: int, typ: str, at: datetime, payload: dict) -> None:
        rows.append((f"syn-{cid}-{len(rows)}", cid, typ, at, at, payload))

    cols = [book[c].astype(t).tolist() for c, t in FIELDS.items()]  # plain Python values, typed per column
    for cid, loan_amount, days, ontime, n_inc in zip(*cols, strict=True):
        add(
            cid,
            "disburse",
            as_of - days * day,
            {"loan_id": f"{cid}-last", "amount": loan_amount},
        )

        # Instalments every 18 days back from T (the oldest is 343 days before T, inside the 365-day window),
        # 4 per past loan. Which ones are late is random; how many is fixed by ontime_pct.
        late = set(rng.choice(INSTALMENTS, INSTALMENTS - int(ontime // 5), replace=False).tolist())
        for j in range(INSTALMENTS):
            due = as_of - (1 + 18 * j) * day
            loan = f"{cid}-h{j // 4}"
            amount = round(loan_amount / 4, 2)
            if j not in late:
                add(
                    cid,
                    "repay",
                    due - int(rng.integers(0, 4)) * day,
                    {"loan_id": loan, "amount": amount, "due_at": due.isoformat()},
                )
                continue
            add(cid, "miss", due + day, {"loan_id": loan, "due_at": due.isoformat()})
            if rng.random() < 0.5:  # repaid late; when that falls after T, the as-of read ignores it anyway
                add(
                    cid,
                    "repay",
                    due + int(rng.integers(2, 11)) * day,
                    {"loan_id": loan, "amount": amount, "due_at": due.isoformat()},
                )

        # Offers last calendar year: n_increases accepted, 0-2 declined.
        for k in range(n_inc + int(rng.integers(0, 3))):
            at = prev_year + int(rng.integers(0, 360)) * day
            offer = f"{cid}-o{k}"
            add(cid, "offer", at, {"offer_id": offer, "new_limit": round(loan_amount * 1.15, 2)})
            add(cid, "accept" if k < n_inc else "decline", at + day, {"offer_id": offer})

    ev = pd.DataFrame(rows, columns=COLUMNS)
    ev["payload"] = ev["payload"].map(json.dumps)
    return ev


def expected_state(book: pd.DataFrame) -> pd.DataFrame:
    """What customer_state_asof(AS_OF) returns for events_for_book(book): the book, ontime_pct rounded down to 5."""
    out = book[["customer_id", "loan_amount", "days_since_last_loan", "ontime_pct", "n_increases"]].copy()
    out["ontime_pct"] = (out["ontime_pct"] // 5) * 5
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Write a synthetic event history for a customer book to CSV.")
    ap.add_argument(
        "--book", type=Path, default=Path("data/raw/book.csv"), help="customer book CSV (lending.synthetic)"
    )
    ap.add_argument("--seed", type=int, default=7, help="random seed (record it with the load)")
    ap.add_argument("--out", type=Path, default=Path("data/raw/events.csv"), help="output CSV path")
    args = ap.parse_args()

    ev = events_for_book(pd.read_csv(args.book), seed=args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    ev.to_csv(args.out, index=False, lineterminator="\n", date_format="%Y-%m-%dT%H:%M:%S%z")
    print(f"wrote {len(ev):,} events for {ev['customer_id'].nunique():,} customers to {args.out} (seed {args.seed})")


if __name__ == "__main__":
    main()
