"""Blocking model gates, run on a seeded synthetic book in CI: `uv run pytest tests/model_gates`.

The gate book is 5,000 customers with the budget scaled to match (250k x 5,000 / 30,000), 40 paths,
seed 11 for every policy (common random numbers, so policies are compared on identical luck).

The champion is the approved model's metrics on exactly this setup, stored in champion.json. A change
that is *meant* to move the policy updates it on purpose, reviewed in the same pull request:
    UPDATE_CHAMPION=1 uv run pytest tests/model_gates
"""

import json
import os
from pathlib import Path

import numpy as np
import pytest

from lending import Book, Model, Params, find_lambda, gates, simulate, solve
from lending.synthetic import generate

N, S, SEED = 5_000, 40, 11
CHAMPION = Path(__file__).with_name("champion.json")


@pytest.fixture(scope="module")
def book() -> Book:
    return Book.from_frame(generate(N, seed=42))


@pytest.fixture(scope="module")
def model(book) -> Model:
    return Model.calibrate(book, Params(budget=250_000 * N / 30_000))


@pytest.fixture(scope="module")
def candidate(book, model) -> dict:
    lam = find_lambda(book, model, S=S, seed=SEED, iters=10)
    pol, *_ = solve(book, model, lam)
    res = simulate(book, model, pol, S=S, seed=SEED)
    return dict(
        npv=float(res["npv"].mean()),
        capital=float(res["capital"].mean()),
        increases=float(res["increases"].mean()),
        lam=lam,
    )


@pytest.fixture(scope="module")
def rules(book, model) -> dict[str, float]:
    """Mean NPV of the simple strategies the optimised policy has to beat, on the same paths."""
    runs = {
        "historical replay": simulate(book, model, None, S=S, seed=SEED, hist=True),
        "grant whenever eligible": simulate(book, model, None, S=S, seed=SEED),
        "scorecard (prime and near-prime)": simulate(book, model, lambda r, k, h: r <= 1, S=S, seed=SEED),
    }
    return {name: float(res["npv"].mean()) for name, res in runs.items()}


def test_npv_vs_champion(candidate, rules, model):
    if os.environ.get("UPDATE_CHAMPION") == "1":
        CHAMPION.write_text(json.dumps({k: round(v, 4) for k, v in candidate.items()}, indent=2) + "\n")
    champion = json.loads(CHAMPION.read_text())
    assert gates.npv_vs_champion(candidate, rules, champion, model.p.budget) == []


def test_npv_gate_blocks_a_worse_policy(rules, model):
    """The gate must be able to fail: 'grant whenever eligible' is far below the champion and over budget."""
    champion = json.loads(CHAMPION.read_text())
    worse = dict(npv=rules["grant whenever eligible"], capital=10 * model.p.budget, increases=0.0)
    fails = gates.npv_vs_champion(worse, rules, champion, model.p.budget)
    assert any("champion" in f for f in fails) and any("budget" in f for f in fails)


def test_default_calibration(book, model):
    hold = simulate(book, model, lambda r, k, h: np.zeros_like(r, bool), S=S, seed=SEED)
    assert gates.calibration(gates.implied_default_rate(book, model), float(hold["defaults"].mean())) == []


def test_calibration_gate_blocks_drift(book, model):
    """If the world defaulted twice as often as the optimiser assumes, the gate fails."""
    implied = gates.implied_default_rate(book, model)
    assert gates.calibration(implied, 2 * implied)


def test_population_stable(book):
    fails, warns = gates.stability(book, Book.from_frame(generate(N, seed=99)))
    assert fails == [] and warns == []


def test_stability_gate_blocks_a_shifted_population(book):
    """A book where everyone pays 3 points less on time is a different population: PSI must fail."""
    df = generate(N, seed=99)
    df["ontime_pct"] = df.ontime_pct - 3
    fails, _ = gates.stability(book, Book.from_frame(df))
    assert fails
