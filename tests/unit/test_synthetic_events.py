"""Synthetic event history: every event passes the ingest contract, and per customer the history encodes the
book (one disbursement days_since_last_loan before T, floor(ontime_pct / 5) of 20 instalments on time,
n_increases accepted offers last year). The SQL read-back itself is checked in the database."""

import json
from datetime import datetime, timedelta

import pandas as pd

from api.main import Event
from lending.synthetic import generate
from lending.synthetic_events import AS_OF, INSTALMENTS, events_for_book, expected_state

BOOK = generate(300, seed=1)
EV = events_for_book(BOOK)


def test_every_event_passes_the_ingest_contract():
    for r in EV.to_dict("records"):
        e = Event.model_validate(
            {k: r[k] for k in ("event_id", "customer_id", "event_type", "occurred_at")}
            | {"payload": json.loads(r["payload"])}
        )
        assert e.payload == json.loads(r["payload"])  # already in the canonical form ingest stores
    assert EV["event_id"].is_unique and (EV["received_at"] == EV["occurred_at"]).all()


def test_history_encodes_the_book():
    want = expected_state(BOOK).set_index("customer_id").to_dict("index")
    by_customer: dict[int, list[dict]] = {}
    for r in EV.to_dict("records"):
        by_customer.setdefault(r["customer_id"], []).append(r | {"p": json.loads(r["payload"])})
    assert by_customer.keys() == want.keys()
    for cid, evs in by_customer.items():
        w = want[cid]
        (disb,) = [e for e in evs if e["event_type"] == "disburse"]
        assert disb["occurred_at"] == AS_OF - timedelta(days=int(w["days_since_last_loan"]))
        assert disb["p"]["amount"] == w["loan_amount"]
        due = [e for e in evs if e["event_type"] in ("repay", "miss")]
        assert len({e["p"]["due_at"] for e in due}) == INSTALMENTS
        on_time = {
            e["p"]["due_at"]
            for e in due
            if e["event_type"] == "repay" and e["occurred_at"] <= datetime.fromisoformat(e["p"]["due_at"])
        }
        assert len(on_time) / INSTALMENTS * 100 == w["ontime_pct"]
        assert sum(e["event_type"] == "accept" for e in evs) == w["n_increases"]
        assert all(e["occurred_at"] < AS_OF for e in evs if e["event_type"] in ("offer", "accept", "decline"))


def test_same_seed_same_events():
    pd.testing.assert_frame_equal(events_for_book(BOOK, seed=3), events_for_book(BOOK, seed=3))


def test_buckets_survive_the_rounding():
    edges = [0, 85, 95, 101]
    assert (
        pd.cut(BOOK.ontime_pct, edges, right=False) == pd.cut(expected_state(BOOK).ontime_pct, edges, right=False)
    ).all()
