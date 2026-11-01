"""Synthetic outcome history: a year of customer behaviour simulated from a known parameter set, as events.

Why a second generator: lending.synthetic_events replays the book's *state* (so customer_state_asof gives the
book back); it contains no defaults or churn and its acceptances are copied, not modelled, so nothing can be
estimated from it. This one draws behaviour from the same mechanics as the Monte Carlo simulator
(simulate.py), with the parameters known. Estimators can then be tested by parameter recovery: estimate from
these events and check the estimate lands near the truth.

Per customer, one loan per cycle starting at the first eligibility window (book.wait days after `start`):
  * a randomised historical policy offers an increase to `offer_rate` of eligible customers; the customer
    accepts if they want one (acceptance model: prior, macro shift, fatigue per increase taken);
  * the loan is disbursed (with the increase if granted) and due one cycle later (plus a Poisson term
    extension after an increase);
  * one uniform draw u decides the outcome, as in simulate.py: default if u < kappa * p_late, late if
    u < p_late, else on time, with p_late = (1 - q)(1 + gamma k) * macro, q the customer's true on-time rate;
  * on time: repaid on the due date, or 1-5 days early with probability `early`; late: missed, repaid 2-60
    days after the due date; default: missed and never repaid (90 days past due is derived by the reader);
  * churn: c0 per cycle, plus c_deny if they wanted an increase and did not get one; churned and defaulted
    customers produce no further events.
The next cycle starts when the loan is repaid. Offers stop at the end of the planning year (`horizon` days);
loans keep running for `tail_days` more so that outcomes near the year end have time to mature.

Events use the existing types and payloads only. Backfill: received_at = occurred_at.

Command line (CSV in the events table's column order, plus the true parameters as JSON next to it):
    uv run python -m lending.outcome_events --book data/raw/book.csv --seed 11 --out data/raw/outcomes.csv
"""

import argparse
import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .book import Book
from .params import SCENARIOS, Macro, Params, month
from .states import logit, sigmoid
from .synthetic_events import COLUMNS

# A past pilot year starting 1 January, so "increases this year" means the calendar year, as in the model and
# in customer_state_asof. The last outcomes land ~1 cycle + extension + 60 days late after the tail (~700 days
# from start), and ingest refuses future events, so outcome_events raises if any event is in the future.
START = datetime(2024, 1, 1, tzinfo=UTC)


def outcome_events(
    book: Book,
    p: Params = Params(),
    macro: Macro = SCENARIOS["base"],
    start: datetime = START,
    seed: int = 11,
    offer_rate: float = 0.5,
    tail_days: int = 180,
) -> pd.DataFrame:
    """Event history (columns COLUMNS) of one simulated year for `book` under the true parameters `p`."""
    rng = np.random.default_rng(seed)
    N = len(book)
    q = rng.beta(p.n0 * book.ontime, p.n0 * (1 - book.ontime))  # true on-time rate, unknown to the lender
    t = book.wait.astype(float)  # day (from start) of the customer's next window
    k = np.zeros(N, int)  # increases taken this year
    alive = np.ones(N, bool)
    ids = book.ids.tolist()
    rows: list[tuple] = []
    day = timedelta(days=1)

    def emit(mask: np.ndarray, typ: str, at_days: np.ndarray, **fields: list) -> None:
        """One event per customer in `mask`, at day `at_days`, payload {field: value for that customer}."""
        for i in np.nonzero(mask)[0].tolist():
            at = start + float(at_days[i]) * day
            rows.append((f"sim-{ids[i]}-{len(rows)}", ids[i], typ, at, at, {f: v[i] for f, v in fields.items()}))

    w = 0
    while True:
        act = alive & (t <= p.horizon + tail_days)
        if not act.any():
            break
        mi = month(t)
        in_year = act & (t <= p.horizon)

        # Offer and response (the same draw order as simulate.py: want first, then the policy).
        want = rng.random(N) < sigmoid(logit(book.accept) + macro.acc_shift[mi] - p.fatigue * k)
        offer = in_year & (k < p.max_k) & (rng.random(N) < offer_rate)
        grant = offer & want
        k = k + grant
        loan = book.loan * (1 + p.step * k)

        # Outcome: one uniform draw splits default / late / on time; early is a second draw among on time.
        p_late = np.clip((1 - q) * (1 + p.gamma * k) * macro.pd_mult[mi], 0, 1)
        u = rng.random(N)
        d = act & (u < p.kappa * p_late)
        late = act & ~d & (u < p_late)
        ok = act & ~d & ~late
        early = ok & (rng.random(N) < p.early)
        due = t + p.cycle + grant * rng.poisson(book.ext)
        churn = act & ~d & (rng.random(N) < p.c0 + p.c_deny * (in_year & want & ~offer))

        # Payload fields per customer for this window; timestamps within the window day keep the order
        # offer -> response -> disbursement.
        oid = [f"{c}-o{w}" for c in ids]
        lid = [f"{c}-y{w}" for c in ids]
        amount = np.round(loan, 2).tolist()
        due_at = [(start + x * day).isoformat() for x in due.tolist()]
        emit(offer, "offer", t + 9 / 24, offer_id=oid, new_limit=amount)
        emit(offer & want, "accept", t + 10 / 24, offer_id=oid)
        emit(offer & ~want, "decline", t + 10 / 24, offer_id=oid)
        emit(act, "disburse", t + 11 / 24, loan_id=lid, amount=amount)
        paid_at = np.where(early, due - rng.integers(1, 6, N), due)
        late_at = due + rng.integers(2, 61, N)
        emit(ok, "repay", paid_at, loan_id=lid, amount=amount, due_at=due_at)
        emit(late | d, "miss", due + 1, loan_id=lid, due_at=due_at)
        emit(late, "repay", late_at, loan_id=lid, amount=amount, due_at=due_at)

        alive &= ~d & ~churn
        t = np.where(late, late_at, np.where(act, due, t))  # next window once the loan is repaid
        w += 1

    ev = pd.DataFrame(rows, columns=COLUMNS).sort_values(["customer_id", "occurred_at"], kind="stable")
    if (last := ev["occurred_at"].max()) > datetime.now(UTC):
        raise ValueError(f"simulated history reaches {last:%Y-%m-%d}, in the future; choose an earlier start")
    ev["payload"] = ev["payload"].map(json.dumps)
    return ev.reset_index(drop=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Simulate a year of outcomes from known parameters, as events (CSV).")
    ap.add_argument("--book", type=Path, default=Path("data/raw/book.csv"), help="customer book CSV")
    ap.add_argument("--seed", type=int, default=11, help="random seed (recorded in the truth file)")
    ap.add_argument("--out", type=Path, default=Path("data/raw/outcomes.csv"), help="output CSV path")
    args = ap.parse_args()

    p = Params()
    ev = outcome_events(Book.from_frame(pd.read_csv(args.book), cycle=p.cycle), p, seed=args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    ev.to_csv(args.out, index=False, lineterminator="\n", date_format="%Y-%m-%dT%H:%M:%S%z")
    truth = {"seed": args.seed, "start": START.isoformat(), "params": asdict(p)}
    args.out.with_suffix(".truth.json").write_text(json.dumps(truth, indent=2) + "\n")
    print(f"wrote {len(ev):,} events for {ev['customer_id'].nunique():,} customers to {args.out} (seed {args.seed})")


if __name__ == "__main__":
    main()
