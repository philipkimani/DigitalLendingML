"""Parity with the original research implementation.

Opt-in: set LENDING_REFERENCE_DIR to a folder holding the reference book (loan_limit_increases.xlsx) and the
reference results (results_strategies.csv, results_policy_map.csv). Neither is committed. Takes a few minutes.
"""

import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from lending import Book, Model, find_lambda, simulate, solve, summarise
from lending.states import bucket

REF = os.environ.get("LENDING_REFERENCE_DIR")
pytestmark = pytest.mark.skipif(not REF, reason="LENDING_REFERENCE_DIR not set")


@pytest.fixture(scope="module")
def ref():
    assert REF, "LENDING_REFERENCE_DIR not set"
    d = Path(REF)
    df = pd.read_excel(d / "loan_limit_increases.xlsx", header=1)
    df.columns = ["customer_id", "loan_amount", "days_since_last_loan", "ontime_pct", "n_increases", "profit"]
    book = Book.from_frame(df.apply(pd.to_numeric))
    return book, Model.calibrate(book), d


def test_strategies_match_reference(ref):
    book, model, d = ref
    lam = find_lambda(book, model, S=100, seed=11)
    strategies: dict[str, dict[str, Any]] = {
        "Historical 2023 (as observed)": dict(hist=True),
        "Grant all eligible": dict(),
        "Scorecard rule (prime + near-prime only)": dict(policy=lambda r, k, h: r <= 1),
        "MDP optimal (no capital limit)": dict(policy=solve(book, model, 0.0)[0]),
        "MDP optimal + capital constraint": dict(policy=solve(book, model, lam)[0]),
    }
    got = pd.DataFrame(
        [summarise(simulate(book, model, S=100, seed=11, **kw), name) for name, kw in strategies.items()]
    ).set_index("strategy")
    want = pd.read_csv(d / "results_strategies.csv", index_col="strategy")
    pd.testing.assert_frame_equal(got[want.columns], want, rtol=1e-6)
    assert got.loc["MDP optimal + capital constraint", "capital"] <= model.p.budget


def test_policy_map_matches_reference(ref):
    book, model, d = ref
    lam = find_lambda(book, model, S=100, seed=11)
    pol = solve(book, model, lam)[0]
    r0 = bucket(book.ontime)
    names = ["prime", "near-prime", "subprime"]
    first = pd.DataFrame(
        {
            "bucket": [names[b] for b in r0],
            "loan_band": pd.cut(book.loan, [0, 1500, 2500, 3500, 5000]),
            "offer": pol[np.arange(len(book)), r0, 0, 0],
        }
    )
    got = first.pivot_table(index="bucket", columns="loan_band", values="offer", aggfunc="mean", observed=True)
    got = got.loc[names]
    want = pd.read_csv(d / "results_policy_map.csv", index_col="bucket")
    np.testing.assert_allclose(got.to_numpy(float), want.to_numpy(float), rtol=1e-9)
