"""Per-customer finite-horizon MDP, solved by vectorised backward induction.

State (r, k, h): risk bucket, increases granted, windows passed without one. The date follows from the
state: t = wait + cycle*(k + h) + ext*k. Capital enters only through the terminal charge lam*K(r)*(L_k - L_0),
so at a fixed lam every customer is independent and any chunk of the book can be solved on its own.
"""
import numpy as np

from .book import Book
from .params import month
from .states import Model, logit, sigmoid


def discount(p, days):
    return (1 + p.disc) ** (-days / 365)


def pd_cycle(model: Model, k, mult) -> np.ndarray:
    """Per-cycle default probability by bucket, (N, 3) or broadcastable; capped at 50%."""
    p = model.p
    return np.clip(p.kappa * model.late[None, :] * (1 + p.gamma * k) * mult, 0, 0.5)


def accept_p(book: Book, model: Model, t, k) -> np.ndarray:
    """Acceptance probability at day t after k increases: prior, macro shift and fatigue on the log-odds scale."""
    return sigmoid(logit(book.accept) + model.macro.acc_shift[month(t)] - model.p.fatigue * k)


def terminal(book: Book, model: Model, k: int, lam: float) -> np.ndarray:
    """Value after the horizon: six more cycles of margin less expected loss, minus the capital charge. (N, 3)"""
    p, L0 = model.p, book.loan
    Lk = L0 * (1 + p.step * k)
    d = discount(p, p.cycle)
    pdv = pd_cycle(model, k, model.macro.pd_mult[11])
    net = (1 - pdv) * p.m * L0[:, None] - pdv * p.lgd * Lk[:, None]
    s = (1 - pdv) * (1 - p.c0) * d
    return d * net * (1 - s ** 6) / (1 - s) - lam * p.weights[None, :] * (Lk - L0)[:, None]


def solve(book: Book, model: Model, lam: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    """Optimal offer policy and values, both (N, 3, W+1, W+1) indexed [customer, r, k, h].

    Memory is ~1.6 KB per customer, so callers solve the book in chunks.
    """
    p, L0, N, W = model.p, book.loan, len(book), model.p.windows
    V = np.zeros((N, 3, W + 1, W + 1))
    pol = np.zeros((N, 3, W + 1, W + 1), bool)
    fbar = p.fee * (1 - p.early * (1 - p.early_fee))  # expected fee net of early-repayment rebates
    dh = discount(p, p.cycle)
    dg = discount(p, p.cycle + book.ext[:, None])
    for n in range(W, -1, -1):          # windows elapsed
        for k in range(n + 1):
            h = n - k
            TV = terminal(book, model, k, lam)
            if n == W:
                V[:, :, k, h] = TV
                continue
            t = book.wait + p.cycle * n + book.ext * k
            M = model.macro.pd_mult[month(t)][:, None]
            a = accept_p(book, model, t, k)[:, None]
            Lk, Lk1 = L0 * (1 + p.step * k), L0 * (1 + p.step * (k + 1))
            p0, p1 = pd_cycle(model, k, M), pd_cycle(model, k + 1, M)
            contH = V[:, :, k, h + 1] @ model.T_hold.T
            base_h = (1 - p0) * p.m * L0[:, None] - p0 * p.lgd * Lk[:, None]
            Qh = dh * (base_h + (1 - p0) * (1 - p.c0 - p.c_deny * a) * contH)
            Qh_nodeny = dh * (base_h + (1 - p0) * (1 - p.c0) * contH)  # declined offer: no refusal churn
            if k < p.max_k:
                contG = V[:, :, k + 1, h] @ model.T_grant.T
                Qg = dg * ((1 - p1) * (p.m * L0[:, None] + fbar) - p1 * p.lgd * Lk1[:, None]
                           + (1 - p1) * (1 - p.c0) * contG)
                Qo = a * Qg + (1 - a) * Qh_nodeny
            else:
                Qo = np.full_like(Qh, -np.inf)
            live = (t <= p.horizon)[:, None]
            pol[:, :, k, h] = live & (Qo > Qh)
            V[:, :, k, h] = np.where(live, np.maximum(Qo, Qh), TV)
    return pol, V
