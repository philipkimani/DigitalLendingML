"""The step between the solver and the decisions table: right state picked, one row per customer,
and the database's parameter columns map onto Params exactly (no drift between schema and code).
"""

from dataclasses import asdict

import numpy as np

from lending import Params, bucket, solve
from lending.decisions import explain, first_window, params_from_row


def test_params_round_trip_through_a_db_row():
    # A parameter_sets row (K split into three columns, plus governance columns) rebuilds Params exactly.
    p = Params()
    row = {k: v for k, v in asdict(p).items() if k != "K"}
    row |= {"k_prime": p.K[0], "k_near": p.K[1], "k_sub": p.K[2], "status": "active", "maker": "someone"}
    assert params_from_row(row) == p


def test_first_window_reads_state_bucket_k0_h0(book, model):
    pol, *_ = solve(book, model, lam=0.0)
    i, r = np.arange(len(book)), bucket(book.ontime)
    # Only each customer's own state (own bucket, k=0, h=0) says offer: every decision must be offer.
    only_own = np.zeros_like(pol)
    only_own[i, r, 0, 0] = True
    assert (first_window(book, only_own).action == "offer").all()
    # The inverse: every other state says offer, the customer's own says hold.
    assert (first_window(book, ~only_own).action == "hold").all()
    d = first_window(book, pol)
    assert len(d) == len(book) and d.customer_id.is_unique


def test_q_values_are_the_numbers_the_decision_compares(book, model):
    pol, V, q = solve(book, model, lam=0.3)
    i, r = np.arange(len(book)), bucket(book.ontime)
    assert (pol[i, r, 0, 0] == (q[i, r, 1] > q[i, r, 0])).all()
    np.testing.assert_allclose(V[i, r, 0, 0], q[i, r].max(axis=1))


def test_reason_codes_follow_the_free_capital_counterfactual(book, model):
    free = solve(book, model, lam=0.0)[0]
    # At lam = 0 nothing is held for capital: every hold is risk/return.
    d0 = explain(book, free, solve(book, model, 0.0)[2], free)
    assert set(d0.reason_code) == {"npv_positive", "risk_return"}
    assert ((d0.action == "offer") == (d0.reason_code == "npv_positive")).all()
    # At a high capital price some offers turn into holds, and exactly those are capital_limit.
    pol, _, q = solve(book, model, lam=5.0)
    d = explain(book, pol, q, free)
    lost = (d0.action == "offer") & (d.action == "hold")
    assert lost.any() and (d.reason_code[lost] == "capital_limit").all()
    assert (d.reason_code[d0.action == "hold"] == "risk_return").all()
