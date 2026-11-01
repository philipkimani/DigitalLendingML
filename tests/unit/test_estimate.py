"""Estimator plumbing: loan outcomes follow the definitions, immature loans are left out, and thin data is
refused (ok=False, active value carried over) rather than estimated. Recovery itself: tests/model_gates."""

from datetime import UTC, datetime, timedelta

from lending import Book, Params
from lending.estimate import estimate_all, loans
from lending.outcome_events import START, outcome_events
from lending.synthetic import generate

BOOK = Book.from_frame(generate(400, seed=2))
EV = outcome_events(BOOK, seed=3)
AS_OF = datetime(2026, 6, 1, tzinfo=UTC)


def test_each_matured_loan_has_exactly_one_outcome():
    ln = loans(EV, START, AS_OF)
    assert len(ln) and (ln[["default", "late", "on_time"]].sum(axis=1) == 1).all()
    assert (ln.early <= ln.on_time).all()


def test_loans_not_yet_90_days_past_due_are_left_out():
    as_of = START + timedelta(days=200)
    ln = loans(EV, START, as_of)
    assert (ln.due <= as_of - timedelta(days=90)).all()
    assert len(ln) < len(loans(EV, START, AS_OF))


def test_thin_data_is_refused_and_carried_over():
    small = BOOK[:40]
    est = estimate_all(outcome_events(small, seed=3), small, Params(), START, AS_OF)
    assert not est["gamma"].ok and est["gamma"].value == Params().gamma
    assert not est["fatigue"].ok and est["fatigue"].value == Params().fatigue
    assert not est["c0"].ok and "needed" in est["c0"].reason
