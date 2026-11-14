"""What-if scenarios: re-solve the book under one changed business choice and measure the result.

Precomputed by jobs/scenarios.py so the API never solves on request. jobs/analysis.py uses the same functions for
the report's tables (strategy comparison, macro scenarios, monthly uptake, sensitivity), for Power BI.
Each scenario finds its own capital price,
then simulates on the same seed, so differences between rows come from the change and not from luck.
"""

import numpy as np

from .book import Book
from .capital import chunk_seeds, find_lambda
from .decisions import first_window
from .params import SCENARIOS, Params
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


def sensitivity_grid(p: Params) -> list[tuple[str, float]]:
    """Report section 5: one assumption at a time. kappa x 0.85 is the repayment nudge (15% fewer late payments
    rolling to default); fixed_cost 80 is the data's reading of profit."""
    return [
        ("lgd", 0.50),
        ("lgd", 0.80),
        ("c_deny", 0.0),
        ("c_deny", round(2 * p.c_deny, 4)),
        ("kappa", round(0.85 * p.kappa, 4)),
        ("step", 0.10),
        ("step", 0.25),
        ("gamma", 0.0),
        ("gamma", round(2 * p.gamma, 4)),
        ("fixed_cost", 80.0),
    ]


def strategies(
    book: Book,
    params: Params,
    scenario: str = "base",
    base_lambda: float | None = None,
    chunk: int | None = None,
    S: int = 100,
    seed: int = 11,
    iters: int = 14,
) -> tuple[list[dict], list[dict]]:
    """Report summary table and Q4: each strategy simulated on the same paths in one macro scenario.

    Returns (summary rows, monthly increases rows). Outside the base scenario, `base_lambda` adds the base
    policy (solved under the base macro path at the base capital price) run in this world.
    """
    base = Model.calibrate(book, params)
    model = base.with_(macro=SCENARIOS[scenario])
    lam = find_lambda(book, model, S=S, seed=seed, chunk=chunk, iters=iters)
    # name -> (simulate kwargs, solve model and lambda or None for a rule)
    plans: dict = {
        "historical": (dict(hist=True), None),
        "grant_all": ({}, None),
        "scorecard": (dict(policy=lambda r, k, h: r <= 1), None),
        "optimal_free": ({}, (model, 0.0)),
        "optimal": ({}, (model, lam)),
    }
    if base_lambda is not None and scenario != "base":
        plans["base_policy"] = ({}, (base, base_lambda))

    parts = list(book.chunks(chunk))
    rows, months = [], []
    for name, (kw, solved) in plans.items():
        npv, inc, cap, dflt, churn = (np.zeros(S) for _ in range(5))
        grants = np.zeros((12, S))
        for part, sd in zip(parts, chunk_seeds(seed, len(parts)), strict=True):
            run = dict(kw, policy=solve(part, solved[0], solved[1])[0]) if solved else kw
            res = simulate(part, model, S=S, seed=sd, **run)
            npv += res["npv"]
            inc += res["increases"]
            cap += res["capital"]
            dflt += res["defaults"] * len(part)  # per-customer rates: weight by chunk size
            churn += res["churn"] * len(part)
            grants += res["grants_m"]
        rows.append(
            dict(
                scenario=scenario,
                strategy=name,
                **{"lambda": solved[1] if solved else None},
                npv_mean=float(npv.mean()),
                npv_p5=float(np.percentile(npv, 5)),
                npv_p95=float(np.percentile(npv, 95)),
                increases=float(inc.mean()),
                default_rate=float(dflt.mean() / len(book)),
                churn_rate=float(churn.mean() / len(book)),
                capital=float(cap.mean()),
            )
        )
        months += [
            dict(scenario=scenario, strategy=name, month=m + 1, increases=float(g))
            for m, g in enumerate(grants.mean(1))
        ]
    return rows, months
