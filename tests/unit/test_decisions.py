"""The step between the solver and the decisions table: right state picked, one row per customer,
and the database's parameter columns map onto Params exactly (no drift between schema and code).
"""

from dataclasses import asdict

import numpy as np

from lending import Params, bucket, solve
from lending.decisions import first_window, params_from_row


def test_params_round_trip_through_a_db_row():
    # A parameter_sets row (K split into three columns, plus governance columns) rebuilds Params exactly.
    p = Params()
    row = {k: v for k, v in asdict(p).items() if k != "K"}
    row |= {"k_prime": p.K[0], "k_near": p.K[1], "k_sub": p.K[2], "status": "active", "maker": "someone"}
    assert params_from_row(row) == p


def test_first_window_reads_state_bucket_k0_h0(book, model):
    pol, _ = solve(book, model, lam=0.0)
    i, r = np.arange(len(book)), bucket(book.ontime)
    # Only each customer's own state (own bucket, k=0, h=0) says offer: every decision must be offer.
    only_own = np.zeros_like(pol)
    only_own[i, r, 0, 0] = True
    assert (first_window(book, only_own).action == "offer").all()
    # The inverse: every other state says offer, the customer's own says hold.
    assert (first_window(book, ~only_own).action == "hold").all()
    d = first_window(book, pol)
    assert len(d) == len(book) and d.customer_id.is_unique
