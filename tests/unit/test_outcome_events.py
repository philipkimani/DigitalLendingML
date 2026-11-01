"""Outcome history: valid events, reproducible, defaults and churn are final, and the simplest parameter
(kappa = share of non-on-time loans that default) is recoverable from the events, and moves with the truth."""

import json

import pandas as pd

from api.main import Event
from lending.book import Book
from lending.outcome_events import outcome_events
from lending.params import Params
from lending.synthetic import generate

BOOK = Book.from_frame(generate(3000, seed=3))
EV = outcome_events(BOOK, seed=5)


def loan_outcomes(ev: pd.DataFrame) -> pd.Series:
    """Per loan: 'on_time', 'late' (missed, later repaid) or 'default' (missed, never repaid)."""
    loans = ev[ev.event_type.isin(["repay", "miss"])].assign(
        loan=lambda d: d.payload.map(lambda s: json.loads(s)["loan_id"])
    )
    g = loans.groupby("loan").event_type
    missed, repaid = g.apply(lambda s: "miss" in set(s)), g.apply(lambda s: "repay" in set(s))
    return pd.Series("on_time", index=missed.index).mask(missed & repaid, "late").mask(missed & ~repaid, "default")


def kappa_hat(ev: pd.DataFrame) -> float:
    o = loan_outcomes(ev).value_counts()
    return o["default"] / (o["default"] + o["late"])


def test_every_event_passes_the_ingest_contract():
    for r in EV.to_dict("records"):  # all of them: the latest events are the ones at risk (future dates)
        Event.model_validate(
            {k: r[k] for k in ("event_id", "customer_id", "event_type", "occurred_at")}
            | {"payload": json.loads(r["payload"])}
        )
    assert EV["event_id"].is_unique and (EV["received_at"] == EV["occurred_at"]).all()


def test_same_seed_same_events():
    assert outcome_events(BOOK[:200], seed=5).equals(outcome_events(BOOK[:200], seed=5))


def test_default_is_final():
    out = loan_outcomes(EV)
    defaulted = {loan.rsplit("-y", 1)[0] for loan in out[out == "default"].index}
    last = EV.groupby("customer_id").tail(1)
    assert {str(c) for c in last[last.event_type == "miss"].customer_id} == defaulted


def test_offers_get_exactly_one_response():
    offers = EV[EV.event_type == "offer"].payload.map(lambda s: json.loads(s)["offer_id"])
    replies = EV[EV.event_type.isin(["accept", "decline"])].payload.map(lambda s: json.loads(s)["offer_id"])
    assert sorted(offers) == sorted(replies)


def test_kappa_is_recovered_and_follows_the_truth():
    assert abs(kappa_hat(EV) - 0.25) < 0.03
    # Negative control: a different truth must give a different estimate.
    assert abs(kappa_hat(outcome_events(BOOK, Params(kappa=0.40), seed=5)) - 0.40) < 0.03
