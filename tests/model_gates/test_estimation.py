"""Parameter-recovery gate for the estimators (lending.estimate), blocking in CI.

Simulate a year of outcomes from known parameters (lending.outcome_events), estimate them back, and require
every estimate within 3 standard errors of the truth. A negative control repeats it with every parameter
moved: the estimates must follow the new truth and leave the old one. A test that passes whatever the truth is
proves nothing.

10,000 customers keep it to ~15 s; seeds are fixed, so a failure is reproducible. Five seeds on the full
30,000 book gave mean z within ±0.4 for every parameter (no bias; ledger 68).
"""

from datetime import UTC, datetime

import pytest

from lending import Book, Params
from lending.estimate import estimate_all
from lending.outcome_events import START, outcome_events
from lending.synthetic import generate

AS_OF = datetime(2026, 6, 1, tzinfo=UTC)  # every outcome of the pilot year has matured by then
BASE = Params()
SHIFTED = Params(kappa=0.40, gamma=0.30, fatigue=0.30, early=0.50, c0=0.05)
ESTIMATED = ("kappa", "gamma", "fatigue", "early", "c0")


@pytest.fixture(scope="module")
def book() -> Book:
    return Book.from_frame(generate(10_000, seed=42))


def recover(book: Book, truth: Params) -> dict:
    return estimate_all(outcome_events(book, truth, seed=11), book, truth, START, AS_OF)


@pytest.mark.parametrize("truth", [BASE, SHIFTED], ids=["base", "negative-control"])
def test_every_parameter_is_recovered(book, truth):
    est = recover(book, truth)
    for name in ESTIMATED:
        e, want = est[name], getattr(truth, name)
        assert e.ok, f"{name}: {e.reason}"
        assert abs(e.value - want) < 3 * e.se, f"{name}: estimate {e.value:.4f} vs truth {want} (se {e.se:.4f})"
        if truth is SHIFTED:  # the estimate followed the truth, away from the base value
            assert abs(e.value - getattr(BASE, name)) > 3 * e.se, f"{name} did not move with the truth"
