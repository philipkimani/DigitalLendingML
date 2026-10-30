"""Monte Carlo lifecycle simulation, deliberately richer than the solver's model.

Why a second model: the solver works with averages per risk bucket. The simulator plays the year out
customer by customer with randomness, many times over ("paths"). If a policy chosen by the simpler
solver still wins in this richer world, the solver's simplifications are not what drives the result.

Each path draws a customer-specific true reliability, stochastic repayment (early / on time / late / default),
acceptance, Poisson term extensions, churn and Bayesian re-bucketing.

Arrays are shaped (N customers, S paths): every customer on every path is simulated at once.
"""

import numpy as np

from .book import Book
from .params import month
from .solver import discount, terminal
from .states import Model, bucket, logit, sigmoid


def simulate(book: Book, model: Model, policy=None, S: int = 40, seed=1, hist: bool = False) -> dict:
    """Simulate S paths of the planning year.

    policy: None = offer whenever eligible; callable(r, k, h) -> bool array; or a solved policy array.
    hist=True replays last period's observed increase counts instead.
    seed: int or np.random.SeedSequence. Returns portfolio totals per path, each shape (S,).
    """
    # --- Starting state for every customer on every path --------------------------------------
    p, L0, N = model.p, book.loan, len(book)
    W = p.windows
    rng = np.random.default_rng(seed)
    # Beta(a, b) belief about each customer's reliability, worth n0 past loans of evidence.
    a0 = (p.n0 * book.ontime)[:, None].repeat(S, 1)
    b0 = (p.n0 * (1 - book.ontime))[:, None].repeat(S, 1)
    q = rng.beta(a0, b0)  # the customer's *true* on-time probability on this path (unknown to the lender)
    al, be = a0.copy(), b0.copy()  # the lender's belief, updated as repayments come in
    r = bucket(al / (al + be))  # risk bucket the lender sees
    k = np.zeros((N, S), int)  # increases granted so far
    h = np.zeros((N, S), int)  # windows held so far
    t = np.repeat(book.wait[:, None].astype(float), S, 1)  # day of the next window
    alive = np.ones((N, S), bool)  # not yet defaulted or churned
    npv = np.zeros((N, S))
    dflt = np.zeros((N, S), bool)
    churned = np.zeros((N, S), bool)
    grants_m = np.zeros((12, S))  # increases granted per calendar month (uptake forecast)
    ii = np.arange(N)[:, None]

    # --- One loop iteration = one eligibility window --------------------------------------------
    for _ in range(W):
        act = alive & (t <= p.horizon)  # customers with a real decision this window
        if not act.any():
            break
        mi = month(t)

        # Would the customer take an increase if offered? (same acceptance model as the solver)
        acc = sigmoid(logit(book.accept)[:, None] + model.macro.acc_shift[mi] - p.fatigue * k)
        want = rng.random((N, S)) < acc

        # Which customers get an offer, depending on the strategy being tested.
        if hist:
            offer = k < book.n_hist[:, None]  # replay what actually happened last period
            want = offer
        elif policy is None:
            offer = np.ones_like(act)  # offer to everyone eligible
        elif callable(policy):
            offer = policy(r, k, h)  # a rule, e.g. a scorecard
        else:
            offer = policy[ii, r, np.minimum(k, W), np.minimum(h, W)]  # look up the solved policy
        offer &= act & (k < p.max_k)
        grant = offer & want
        np.add.at(grants_m, (mi[grant], np.nonzero(grant)[1]), 1)
        k = k + grant
        Lk = L0[:, None] * (1 + p.step * k)

        # Repayment outcome this cycle, drawn from the customer's true reliability.
        # One uniform draw u splits into default (u < kappa*plate), late (u < plate) or on time.
        plate = np.clip((1 - q) * (1 + p.gamma * k) * model.macro.pd_mult[mi], 0, 1)
        u = rng.random((N, S))
        d = act & (u < p.kappa * plate)
        late = act & ~d & (u < plate)
        ok = act & ~d & ~late
        early = ok & (rng.random((N, S)) < p.early)

        # Cash: a default loses LGD x balance; otherwise margin, plus the fee if an increase was granted
        # (reduced by the rebate on early repayment). A grant stretches the cycle by a random extension.
        clen = p.cycle + grant * rng.poisson(book.ext[:, None], (N, S))
        cash = np.where(d, -p.lgd * Lk, p.m * L0[:, None] + grant * p.fee * np.where(early, p.early_fee, 1))
        npv += act * cash * discount(p, t + clen)

        # Bayesian update of the lender's belief: on time adds to a, late or default adds to b.
        al += ok
        be += late | d

        # Churn: baseline, plus extra if they wanted an increase and were refused.
        ch = act & ~d & (rng.random((N, S)) < p.c0 + p.c_deny * (want & ~offer))
        dflt |= d
        churned |= ch
        alive &= ~d & ~ch

        # Move the clock and counters on, and re-bucket from the updated belief.
        t = np.where(act, t + clen, t)
        h += act & ~grant
        r = bucket(al / (al + be))

    # --- Year end: value the customers still active, as the solver does ------------------------
    tv = np.zeros((N, S))
    for kk in range(W):
        m_ = alive & (k == kk)
        if m_.any():
            tv[m_] = terminal(book, model, kk, 0)[ii.repeat(S, 1), r][m_]
    npv += alive * tv * discount(p, np.maximum(t, p.horizon))
    inc = L0[:, None] * p.step * k  # extra exposure created by increases
    npv -= p.fixed_cost * (k > 0)

    # Portfolio totals per path (sum or mean over customers); the spread across paths shows uncertainty.
    return dict(
        npv=npv.sum(0),
        defaults=dflt.mean(0),
        churn=churned.mean(0),
        increases=k.sum(0),
        capital=(alive * p.weights[r] * inc).sum(0),  # risk-weighted capital still tied up at year end
        exposure_inc=(alive * inc).sum(0),
        grants_m=grants_m,
    )


def summarise(res: dict, name: str) -> dict:
    """One row of the strategy comparison table: mean and 5th-95th percentile band across paths."""
    return dict(
        strategy=name,
        NPV_mean=np.mean(res["npv"]),
        NPV_p5=np.percentile(res["npv"], 5),
        NPV_p95=np.percentile(res["npv"], 95),
        increases=np.mean(res["increases"]),
        default_rate=np.mean(res["defaults"]),
        churn_rate=np.mean(res["churn"]),
        capital=np.mean(res["capital"]),
    )
