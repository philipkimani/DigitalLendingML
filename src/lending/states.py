"""Risk buckets, bucket transitions and the calibrated Model every chunk solves against."""
from dataclasses import dataclass, field

import numpy as np

from .book import Book
from .params import CUTS, SCENARIOS, Macro, Params


def bucket(q: np.ndarray) -> np.ndarray:
    """On-time rate -> 0 prime, 1 near-prime, 2 subprime."""
    return np.where(q >= CUTS[1], 0, np.where(q >= CUTS[0], 1, 2))


def sigmoid(x):
    return 1 / (1 + np.exp(-x))


def logit(p):
    return np.log(p / (1 - p))


def late_rates(book: Book) -> np.ndarray:
    """Mean late-payment rate per bucket, shape (3,)."""
    r = bucket(book.ontime)
    if len(np.unique(r)) < 3:
        raise ValueError("every risk bucket needs at least one customer to estimate its late rate")
    return np.array([(1 - book.ontime[r == b]).mean() for b in range(3)])


def transitions(book: Book, p: Params, seed: int = 7, sims: int = 20) -> tuple[np.ndarray, np.ndarray]:
    """Per-cycle bucket transition matrices (hold, grant), by simulating one Beta-Bernoulli update of the book.

    Granting lowers reliability slightly through the leverage effect.
    """
    rng = np.random.default_rng(seed)
    q0, r0 = book.ontime, bucket(book.ontime)
    out = []
    for grant in (0, 1):
        T = np.zeros((3, 3))
        for _ in range(sims):
            a, b = p.n0 * q0, p.n0 * (1 - q0)
            q = rng.beta(a, b) * (1 - p.gamma * (1 - q0) * grant)
            ok = rng.random(len(q0)) < q
            np.add.at(T, (r0, bucket((a + ok) / (a + b + 1))), 1)
        out.append(T / T.sum(1, keepdims=True))
    return out[0], out[1]


@dataclass(frozen=True, eq=False)
class Model:
    """Population-level inputs shared by every customer: parameters, macro path, late rates, transitions."""
    p: Params
    macro: Macro
    late: np.ndarray = field(repr=False)     # (3,)
    T_hold: np.ndarray = field(repr=False)   # (3, 3)
    T_grant: np.ndarray = field(repr=False)  # (3, 3)

    @classmethod
    def calibrate(cls, book: Book, p: Params = Params(), macro: Macro = SCENARIOS["base"], seed: int = 7) -> "Model":
        return cls(p, macro, late_rates(book), *transitions(book, p, seed))

    def with_(self, p: Params | None = None, macro: Macro | None = None) -> "Model":
        """Same calibration under different parameters or macro scenario (transitions are not re-estimated)."""
        return Model(p or self.p, macro or self.macro, self.late, self.T_hold, self.T_grant)
