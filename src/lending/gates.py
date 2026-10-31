"""Model gates: the checks a model or parameter change must pass before it ships.

Unit tests prove the maths does what it says. Gates prove the *policy* is still good:
  1. NPV vs champion   - the optimised policy beats the simple rules and stays close to the approved model.
  2. Calibration       - the default rate the optimiser assumes matches what the richer simulator produces.
  3. Stability (PSI)   - the customers being scored still look like the ones the model was built on.

Each check returns a list of failure messages (empty = pass), so the same functions serve the CI gate
tests and, later, the nightly job's pre-flight checks.
"""

import numpy as np

from .book import Book
from .params import month
from .solver import pd_cycle
from .states import Model, bucket

# Report section 6: fall back to the scorecard rule if default calibration drifts by more than ~20%.
CALIBRATION_TOL = 0.20
# Common PSI reading: < 0.10 stable, 0.10-0.25 moderate shift (warn), > 0.25 major shift (fail).
PSI_WARN, PSI_FAIL = 0.10, 0.25


def psi(reference: np.ndarray, current: np.ndarray, bins: int = 10, categorical: bool = False) -> float:
    """Population stability index: sum over bins of (cur% - ref%) * ln(cur% / ref%).

    Continuous values are cut at the reference's deciles, so each bin holds ~10% of the reference.
    Empty bins get a tiny share instead of zero, which would make the log blow up.
    """
    if categorical:
        cats = np.union1d(reference, current)
        ref = np.array([(reference == c).mean() for c in cats])
        cur = np.array([(current == c).mean() for c in cats])
    else:
        edges = np.quantile(reference, np.linspace(0, 1, bins + 1))[1:-1]
        ref = np.bincount(np.searchsorted(edges, reference, side="right"), minlength=bins) / len(reference)
        cur = np.bincount(np.searchsorted(edges, current, side="right"), minlength=bins) / len(current)
    ref, cur = np.clip(ref, 1e-6, None), np.clip(cur, 1e-6, None)
    return float(np.sum((cur - ref) * np.log(cur / ref)))


def stability(reference: Book, current: Book) -> tuple[list[str], list[str]]:
    """PSI on the risk-bucket mix and the on-time rate. Returns (failures, warnings)."""
    scores = {
        "bucket mix": psi(bucket(reference.ontime), bucket(current.ontime), categorical=True),
        "on-time rate": psi(reference.ontime, current.ontime),
    }
    fails = [f"PSI {name} = {v:.3f} > {PSI_FAIL}" for name, v in scores.items() if v > PSI_FAIL]
    warns = [f"PSI {name} = {v:.3f} > {PSI_WARN}" for name, v in scores.items() if PSI_WARN < v <= PSI_FAIL]
    return fails, warns


def implied_default_rate(book: Book, model: Model) -> float:
    """Share of customers the optimiser expects to default within the year if nobody gets an increase.

    Walks each customer's eligibility windows with the optimiser's per-bucket PD for that month,
    surviving both default and baseline churn. Bucket moves are ignored (they roughly cancel in the mix).
    """
    p = model.p
    r = bucket(book.ontime)
    alive = np.ones(len(book))
    defaulted = np.zeros(len(book))
    t = book.wait.astype(float)
    for _ in range(p.windows):
        act = t <= p.horizon
        pd_ = pd_cycle(model, 0, model.macro.pd_mult[month(t)][:, None])[np.arange(len(book)), r]
        defaulted += act * alive * pd_
        alive *= np.where(act, (1 - pd_) * (1 - p.c0), 1)
        t = t + p.cycle
    return float(defaulted.mean())


def calibration(implied: float, simulated: float, tol: float = CALIBRATION_TOL) -> list[str]:
    """Fail when the simulator's default rate is more than `tol` (relative) away from the optimiser's."""
    gap = abs(simulated - implied) / implied
    return (
        []
        if gap <= tol
        else [f"default calibration off by {gap:.0%} (optimiser {implied:.2%}, simulated {simulated:.2%})"]
    )


def npv_vs_champion(
    candidate: dict, rules: dict[str, float], champion: dict | None, budget: float, npv_tol: float = 0.02
) -> list[str]:
    """candidate: mean NPV / capital / increases of the optimised policy on the gate paths.
    rules: mean NPV of each simple rule on the same paths. champion: the approved model's stored metrics.
    """
    fails = [
        f"optimised NPV {candidate['npv']:,.0f} does not beat {name} ({npv:,.0f})"
        for name, npv in rules.items()
        if candidate["npv"] <= npv
    ]
    if candidate["capital"] > budget:
        fails.append(f"capital {candidate['capital']:,.0f} exceeds the budget {budget:,.0f}")
    if champion is not None:
        drift = (candidate["npv"] - champion["npv"]) / abs(champion["npv"])
        if drift < -npv_tol:
            fails.append(f"NPV {drift:+.1%} vs champion (tolerance -{npv_tol:.0%})")
    return fails
