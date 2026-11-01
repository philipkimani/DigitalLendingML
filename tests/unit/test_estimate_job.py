"""The dev test cohort and the estimation job's proposal: ids kept apart, the state year rebuilds the book's
fields, and a proposal swaps in only usable estimates and says why the others were kept."""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from api.main import Event
from lending import Params
from lending.estimate import Estimate
from lending.outcome_events import START, cohort
from lending.synthetic import generate

sys.path.insert(0, str(Path(__file__).parents[2] / "jobs"))
from estimate import proposal

BOOK_DF, EV = cohort(generate(200, seed=4), Params(), id_offset=1_000_000, seed=6)


def test_cohort_ids_are_apart_and_rates_rounded():
    assert BOOK_DF.customer_id.min() > 1_000_000 and set(EV.customer_id) == set(BOOK_DF.customer_id)
    assert (BOOK_DF.ontime_pct % 5 == 0).all()
    assert EV.event_id.is_unique


def test_the_state_year_only_leaks_late_repayments_into_the_pilot_year():
    # synthetic_events puts some events exactly at its as-of date (part of the state: the read uses <=) and lets
    # some late repayments land after it (the state read ignores them). Those repay the state year's own loans,
    # so no estimator can mistake them for pilot-year activity.
    syn = EV[EV.event_id.str.startswith("syn-")]
    after = syn[syn.occurred_at > START]
    assert set(after.event_type) <= {"repay"}
    assert after.payload.map(lambda s: "-h" in json.loads(s)["loan_id"]).all()
    assert EV[EV.event_id.str.startswith("sim-")].occurred_at.min() >= START


def test_every_cohort_event_passes_the_ingest_contract():
    for r in EV.to_dict("records"):
        Event.model_validate(
            {k: r[k] for k in ("event_id", "customer_id", "event_type", "occurred_at")}
            | {"payload": json.loads(r["payload"])}
        )


ACTIVE = {"param_version": 54, "status": "active", "note": "", "kappa": 0.25, "gamma": 0.1, "lgd": 0.65}
AS_OF = datetime(2026, 6, 1, tzinfo=UTC)


def test_proposal_swaps_in_usable_estimates_and_keeps_the_rest():
    est = {"kappa": Estimate(0.31234, 0.004, 900, True), "gamma": Estimate(0.1, float("inf"), 12, False, "12 < 200")}
    values, note, changed = proposal(ACTIVE, est, 2024, AS_OF, "abcdef1234")
    assert values == {"kappa": 0.3123, "gamma": 0.1, "lgd": 0.65} and changed == 1
    assert "gamma kept at 0.1: 12 < 200" in note and "set 54" in note and "abcdef1" in note


def test_no_change_means_nothing_to_propose():
    est = {"kappa": Estimate(0.25, 0.004, 900, True)}
    assert proposal(ACTIVE, est, 2024, AS_OF, "abcdef1")[2] == 0
