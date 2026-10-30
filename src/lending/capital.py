"""Portfolio capital constraint: chunked capital measurement and the bisection for the capital price lam*.

The idea in plain words
-----------------------
The budget caps total risk-weighted capital across *all* customers, which would tie every customer's
decision to every other's. Instead we put a price lam on each dollar of capital (a Lagrange multiplier,
or "shadow price"). At a given price each customer is solved alone; a higher price means fewer offers
and less capital used. Bisection then finds the lowest price at which the book fits the budget.

Capital is the only link between customers. At a fixed lam each chunk is solved and simulated on its own
and the risk-weighted capital summed, so memory is bounded by the chunk size, not the book size.
"""

import numpy as np

from .book import Book
from .simulate import simulate
from .solver import solve
from .states import Model


def chunk_seeds(seed: int, n_chunks: int):
    """One seed for an unchunked run (matches the reference); independent child streams otherwise.

    SeedSequence.spawn gives each chunk its own random stream that does not overlap the others.
    Results are deterministic for a given (seed, chunk size); record both with the run.
    """
    return [seed] if n_chunks == 1 else np.random.SeedSequence(seed).spawn(n_chunks)


def capital(book: Book, model: Model, lam: float, S: int = 100, seed: int = 11, chunk: int | None = None) -> float:
    """Mean (over S paths) risk-weighted capital used by the lam-optimal policy across the whole book."""
    parts = list(book.chunks(chunk))
    total = np.zeros(S)
    # Solve and simulate each chunk independently, adding up its capital path by path.
    # strict=True: a mismatch between chunks and seeds raises instead of silently dropping customers.
    for part, sd in zip(parts, chunk_seeds(seed, len(parts)), strict=True):
        pol, *_ = solve(part, model, lam)
        total += simulate(part, model, pol, S, sd)["capital"]
    return float(total.mean())


def find_lambda(
    book: Book, model: Model, S: int = 100, seed: int = 11, chunk: int | None = None, hi: float = 5.0, iters: int = 14
) -> float:
    """Smallest capital price whose policy keeps mean capital within budget, measured on the same paths
    used for reporting. The upper bound only moves to feasible values, so the result is feasible by
    construction; hi - (5 / 2**iters) is infeasible.
    """
    budget = model.p.budget
    cap = lambda lam: capital(book, model, lam, S, seed, chunk)  # noqa: E731

    # If the free policy already fits, capital costs nothing: lam* = 0.
    if cap(0.0) <= budget:
        return 0.0
    # The search needs an upper bound that does fit; otherwise no price in range works.
    if cap(hi) > budget:
        raise ValueError(f"lam={hi} still exceeds the capital budget; raise the upper bound")

    # Bisection: halve the interval [lo, hi] each step. lo is always over budget, hi always within it.
    # 14 halvings of [0, 5] pin lam* to within 5 / 2**14 ~ 0.0003.
    lo = 0.0
    for _ in range(iters):
        mid = (lo + hi) / 2
        if cap(mid) > budget:
            lo = mid
        else:
            hi = mid
    return hi
