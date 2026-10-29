"""Monte Carlo lifecycle simulation, deliberately richer than the solver's model.

Each path draws a customer-specific true reliability, stochastic repayment (early / on time / late / default),
acceptance, Poisson term extensions, churn and Bayesian re-bucketing.
"""
import numpy as np

from .book import Book
from .solver import discount, terminal
from .states import Model, bucket, logit, sigmoid
from .params import month


def simulate(book: Book, model: Model, policy=None, S: int = 40, seed=1, hist: bool = False) -> dict:
    """Simulate S paths of the planning year.

    policy: None = offer whenever eligible; callable(r, k, h) -> bool array; or a solved policy array.
    hist=True replays last period's observed increase counts instead.
    seed: int or np.random.SeedSequence. Returns portfolio totals per path, each shape (S,).
    """
    p, L0, N = model.p, book.loan, len(book)
    W = p.windows
    rng = np.random.default_rng(seed)
    a0 = (p.n0 * book.ontime)[:, None].repeat(S, 1)
    b0 = (p.n0 * (1 - book.ontime))[:, None].repeat(S, 1)
    q = rng.beta(a0, b0)
    al, be = a0.copy(), b0.copy()
    r = bucket(al / (al + be))
    k = np.zeros((N, S), int)
    h = np.zeros((N, S), int)
    t = np.repeat(book.wait[:, None].astype(float), S, 1)
    alive = np.ones((N, S), bool)
    npv = np.zeros((N, S))
    dflt = np.zeros((N, S), bool)
    churned = np.zeros((N, S), bool)
    grants_m = np.zeros((12, S))
    ii = np.arange(N)[:, None]
    for _ in range(W):
        act = alive & (t <= p.horizon)
        if not act.any():
            break
        mi = month(t)
        acc = sigmoid(logit(book.accept)[:, None] + model.macro.acc_shift[mi] - p.fatigue * k)
        want = rng.random((N, S)) < acc
        if hist:
            offer = k < book.n_hist[:, None]
            want = offer
        elif policy is None:
            offer = np.ones_like(act)
        elif callable(policy):
            offer = policy(r, k, h)
        else:
            offer = policy[ii, r, np.minimum(k, W), np.minimum(h, W)]
        offer &= act & (k < p.max_k)
        grant = offer & want
        np.add.at(grants_m, (mi[grant], np.nonzero(grant)[1]), 1)
        k = k + grant
        Lk = L0[:, None] * (1 + p.step * k)
        plate = np.clip((1 - q) * (1 + p.gamma * k) * model.macro.pd_mult[mi], 0, 1)
        u = rng.random((N, S))
        d = act & (u < p.kappa * plate)
        late = act & ~d & (u < plate)
        ok = act & ~d & ~late
        early = ok & (rng.random((N, S)) < p.early)
        clen = p.cycle + grant * rng.poisson(book.ext[:, None], (N, S))
        cash = np.where(d, -p.lgd * Lk, p.m * L0[:, None] + grant * p.fee * np.where(early, p.early_fee, 1))
        npv += act * cash * discount(p, t + clen)
        al += ok
        be += late | d
        ch = act & ~d & (rng.random((N, S)) < p.c0 + p.c_deny * (want & ~offer))
        dflt |= d
        churned |= ch
        alive &= ~d & ~ch
        t = np.where(act, t + clen, t)
        h += act & ~grant
        r = bucket(al / (al + be))
    tv = np.zeros((N, S))
    for kk in range(W):
        m_ = alive & (k == kk)
        if m_.any():
            tv[m_] = terminal(book, model, kk, 0)[ii.repeat(S, 1), r][m_]
    npv += alive * tv * discount(p, np.maximum(t, p.horizon))
    inc = L0[:, None] * p.step * k
    npv -= p.fixed_cost * (k > 0)
    return dict(npv=npv.sum(0), defaults=dflt.mean(0), churn=churned.mean(0), increases=k.sum(0),
                capital=(alive * p.weights[r] * inc).sum(0), exposure_inc=(alive * inc).sum(0), grants_m=grants_m)


def summarise(res: dict, name: str) -> dict:
    return dict(strategy=name, NPV_mean=np.mean(res["npv"]), NPV_p5=np.percentile(res["npv"], 5),
                NPV_p95=np.percentile(res["npv"], 95), increases=np.mean(res["increases"]),
                default_rate=np.mean(res["defaults"]), churn_rate=np.mean(res["churn"]),
                capital=np.mean(res["capital"]))
