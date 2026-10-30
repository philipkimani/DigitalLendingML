"""Per-customer finite-horizon MDP, solved by vectorised backward induction.

The idea in plain words
-----------------------
A Markov decision process (MDP) describes a customer as being in a *state* and us choosing an *action*
(offer or hold) at each 60-day eligibility window. The best action now depends on what is best later,
so we solve the year **backwards**: first the value at year end, then the last window, then the one
before, and so on to the first. That is backward induction (the Bellman recursion).

State (r, k, h): risk bucket, increases granted, windows passed without one. The date follows from the
state: t = wait + cycle*(k + h) + ext*k. Capital enters only through the terminal charge lam*K(r)*(L_k - L_0),
so at a fixed lam every customer is independent and any chunk of the book can be solved on its own.

"Vectorised" means every customer and every risk bucket is computed at once with numpy arrays
(shape (N, 3)), instead of a Python loop per customer. The only loops are over windows and increases.
"""

import numpy as np

from .book import Book
from .params import month
from .states import Model, logit, sigmoid


def discount(p, days):
    """Present-value factor for cash received `days` from now at the annual rate p.disc (19%)."""
    return (1 + p.disc) ** (-days / 365)


def pd_cycle(model: Model, k, mult) -> np.ndarray:
    """Per-cycle default probability by bucket, (N, 3) or broadcastable; capped at 50%.

    PD = kappa (share of late payments that default) x late rate of the bucket
         x (1 + gamma k) (each increase adds leverage) x macro multiplier for the month.
    """
    p = model.p
    return np.clip(p.kappa * model.late[None, :] * (1 + p.gamma * k) * mult, 0, 0.5)


def accept_p(book: Book, model: Model, t, k) -> np.ndarray:
    """Acceptance probability at day t after k increases: prior, macro shift and fatigue on the log-odds scale.

    Working on the log-odds scale (logit) lets us add effects and still get a probability back (sigmoid).
    """
    return sigmoid(logit(book.accept) + model.macro.acc_shift[month(t)] - model.p.fatigue * k)


def terminal(book: Book, model: Model, k: int, lam: float) -> np.ndarray:
    """Value after the horizon: six more cycles of margin less expected loss, minus the capital charge. (N, 3)

    Without this, the model would treat 31 December as the end of the relationship and undervalue
    keeping a customer. The capital charge lam*K(r)*(extra exposure) is where the budget bites.
    """
    p, L0 = model.p, book.loan
    Lk = L0 * (1 + p.step * k)  # loan size after k increases
    d = discount(p, p.cycle)
    pdv = pd_cycle(model, k, model.macro.pd_mult[11])  # December's macro conditions carried forward
    net = (1 - pdv) * p.m * L0[:, None] - pdv * p.lgd * Lk[:, None]  # expected profit of one cycle
    s = (1 - pdv) * (1 - p.c0) * d  # chance the customer is still here next cycle, discounted
    # Six cycles of `net`, each surviving and discounted by s: a geometric series, summed in closed form.
    return d * net * (1 - s**6) / (1 - s) - lam * p.weights[None, :] * (Lk - L0)[:, None]


def solve(book: Book, model: Model, lam: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    """Optimal offer policy and values, both (N, 3, W+1, W+1) indexed [customer, r, k, h].

    pol[i, r, k, h] is True where offering beats holding; V is the expected value of being in that state.
    Memory is ~1.6 KB per customer, so callers solve the book in chunks.
    """
    # --- Set-up -------------------------------------------------------------------------------
    p, L0, N, W = model.p, book.loan, len(book), model.p.windows
    V = np.zeros((N, 3, W + 1, W + 1))
    pol = np.zeros((N, 3, W + 1, W + 1), bool)
    fbar = p.fee * (1 - p.early * (1 - p.early_fee))  # expected fee net of early-repayment rebates
    dh = discount(p, p.cycle)  # discount over a normal 60-day cycle (hold)
    dg = discount(p, p.cycle + book.ext[:, None])  # a granted increase also stretches the term (grant)

    # --- Backward induction ------------------------------------------------------------------
    # n = windows elapsed, from the last (W) back to the first (0). At window n the customer has had
    # k increases and h holds, with k + h = n, so we visit every reachable (k, h) pair.
    for n in range(W, -1, -1):
        for k in range(n + 1):
            h = n - k
            TV = terminal(book, model, k, lam)
            if n == W:
                # Past the last window: only the terminal value remains.
                V[:, :, k, h] = TV
                continue

            # Inputs for this window: calendar day, macro multiplier, acceptance, loan sizes, PDs.
            t = book.wait + p.cycle * n + book.ext * k
            M = model.macro.pd_mult[month(t)][:, None]
            a = accept_p(book, model, t, k)[:, None]
            Lk, Lk1 = L0 * (1 + p.step * k), L0 * (1 + p.step * (k + 1))
            p0, p1 = pd_cycle(model, k, M), pd_cycle(model, k + 1, M)  # PD if we hold / if we grant

            # HOLD: earn this cycle's margin or lose LGD x balance, then move to (k, h+1).
            # contH = expected next value, averaging over where the bucket goes (T_hold rows).
            contH = V[:, :, k, h + 1] @ model.T_hold.T
            base_h = (1 - p0) * p.m * L0[:, None] - p0 * p.lgd * Lk[:, None]
            # Refusing someone who wanted an increase (prob. a) adds churn c_deny.
            Qh = dh * (base_h + (1 - p0) * (1 - p.c0 - p.c_deny * a) * contH)
            Qh_nodeny = dh * (base_h + (1 - p0) * (1 - p.c0) * contH)  # declined offer: no refusal churn

            if k < p.max_k:
                # GRANT (if accepted): bigger loan, fee earned, higher PD, move to (k+1, h).
                contG = V[:, :, k + 1, h] @ model.T_grant.T
                Qg = dg * (
                    (1 - p1) * (p.m * L0[:, None] + fbar) - p1 * p.lgd * Lk1[:, None] + (1 - p1) * (1 - p.c0) * contG
                )
                # OFFER = accepted with prob. a (grant), otherwise it is a hold without the refusal penalty.
                Qo = a * Qg + (1 - a) * Qh_nodeny
            else:
                # At the yearly cap an offer is impossible.
                Qo = np.full_like(Qh, -np.inf)

            # Windows that fall after the horizon are not real decisions: keep the terminal value there.
            live = (t <= p.horizon)[:, None]
            pol[:, :, k, h] = live & (Qo > Qh)
            V[:, :, k, h] = np.where(live, np.maximum(Qo, Qh), TV)
    return pol, V
