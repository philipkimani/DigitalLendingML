"""What-if scenarios: re-solve the book under one changed business choice and measure the result.

Precomputed by jobs/scenarios.py so the API never solves on request. Each scenario finds its own capital price,
then simulates on the same seed, so differences between rows come from the change and not from luck.
"""

import numpy as np

from .book import Book
from .capital import chunk_seeds, find_lambda
from .decisions import first_window
from .params import Params
from .simulate import simulate
from .solver import solve
from .states import Model


def grid(p: Params) -> list[tuple[str, float]]:
    """(lever, value) rows: the current values, then one change at a time. Values the database refuses are left out."""
    rows = [
        ("baseline", p.budget),
        *(("budget", round(p.budget * x, 2)) for x in (0.8, 1.2, 1.5)),
        *(("step", round(p.step + d, 4)) for d in (-0.05, 0.05)),
        *(("fee", p.fee + d) for d in (-10, 10)),
    ]
    limits = {"step": lambda v: 0 < v <= 1, "fee": lambda v: 0 <= v <= 1000}
    return [(lever, v) for lever, v in rows if limits.get(lever, lambda _: True)(v)]


def evaluate(
    book: Book,
    params: Params,
    lever: str,
    value: float,
    chunk: int | None = None,
    S: int = 100,
    seed: int = 11,
    iters: int = 14,
) -> dict:
    """One scenario's results. `baseline` changes nothing; any other lever replaces that parameter."""
    model = Model.calibrate(book, params if lever == "baseline" else params.with_(**{lever: value}))
    lam = find_lambda(book, model, S=S, seed=seed, chunk=chunk, iters=iters)
    parts = list(book.chunks(chunk))
    npv, capital, defaults, offers = np.zeros(S), np.zeros(S), np.zeros(S), 0
    for part, sd in zip(parts, chunk_seeds(seed, len(parts)), strict=True):
        pol, *_ = solve(part, model, lam)
        res = simulate(part, model, pol, S, sd)
        npv += res["npv"]
        capital += res["capital"]
        defaults += res["defaults"] * len(part)  # a per-customer rate: weight by chunk size
        offers += int((first_window(part, pol).action == "offer").sum())
    return {
        "lever": lever,
        "value": float(value),
        "lambda": lam,
        "offers": offers,
        "capital_used": float(capital.mean()),
        "npv": float(npv.mean()),
        "default_rate": float(defaults.mean() / len(book)),
    }
