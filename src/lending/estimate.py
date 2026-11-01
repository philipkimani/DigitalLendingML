"""Estimate model parameters from the event log: kappa, gamma, fatigue, early, c0.

Each estimator matches the data-generating mechanics of simulate.py / outcome_events.py, so the estimates can
be validated by parameter recovery (tests/model_gates/test_estimation.py) before they meet real data.

Inputs: the events (columns of the events table), the customer book as of the start of the planning year
(each customer's on-time rate and acceptance prior), the active parameters (n0, cycle and the macro path are
taken as known), the planning year, and as_of (the run date). Definitions (docs/assumptions.md):
  * a loan is *on time* if repaid by its due date, *early* if repaid at least a day before it;
  * *late* if missed and repaid within 90 days; *default* if missed and not repaid within 90 days;
  * a customer *churns* after a loan if they take no new loan within one cycle of repaying it;
  * k = increases accepted earlier in the same calendar year.
Only matured loans count: due at least 90 days before as_of (default needs 90 days to be observed), and for
churn, repaid at least one cycle before as_of (right-censoring).

Each estimate carries a standard error, the number of observations behind it, and ok=False with a reason when
there is too little data; the job then carries the active value over.
"""

import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from .book import Book
from .params import SCENARIOS, Macro, Params, month
from .states import logit, sigmoid

DPD = timedelta(days=90)  # default definition: 90 days past due (Basel / IFRS 9 backstop)
MINIMUM = {"kappa": 30, "gamma": 200, "fatigue": 200, "early": 500, "c0": 30}  # what n counts: see each estimator


@dataclass(frozen=True)
class Estimate:
    value: float
    se: float
    n: int  # observations behind it (meaning per parameter: see MINIMUM)
    ok: bool
    reason: str = ""


def loans(ev: pd.DataFrame, year: datetime, as_of: datetime) -> pd.DataFrame:
    """One row per loan disbursed in the planning year that has matured by as_of, with its outcome and k."""
    pl = ev.payload.map(lambda s: json.loads(s) if isinstance(s, str) else s)
    e = ev.assign(loan_id=pl.map(lambda d: d.get("loan_id")), due_at=pl.map(lambda d: d.get("due_at")))
    disb = e[e.event_type == "disburse"][["customer_id", "loan_id", "occurred_at"]].rename(
        columns={"occurred_at": "when"}
    )
    rep = e[e.event_type == "repay"].groupby("loan_id").agg(repaid_at=("occurred_at", "max"), due=("due_at", "first"))
    miss = e[e.event_type == "miss"].groupby("loan_id").agg(due_m=("due_at", "first"))
    out = disb.join(rep, on="loan_id").join(miss, on="loan_id")
    out["due"] = pd.to_datetime(out.due.fillna(out.due_m), utc=True)
    out = out[out.due.notna() & (out.when >= year) & (out.when < year + timedelta(days=365)) & (out.due <= as_of - DPD)]
    missed = out.due_m.notna()
    cured = out.repaid_at.notna() & (out.repaid_at <= out.due + DPD)
    out = out.assign(
        default=missed & ~cured,
        late=missed & cured,
        on_time=~missed,
        early=~missed & (out.repaid_at <= out.due - timedelta(days=1)),
        t=(out.when - year).dt.days,
    )
    return out.assign(k=_accepted_before(ev, out, year)).drop(columns="due_m")


def _accepted_before(ev: pd.DataFrame, rows: pd.DataFrame, year: datetime) -> np.ndarray:
    """For each row (customer_id, at): accepts by that customer in the same calendar year at or before `at`."""
    acc = ev[(ev.event_type == "accept") & (ev.occurred_at >= year)][["customer_id", "occurred_at"]]
    acc = acc.sort_values("occurred_at").rename(columns={"occurred_at": "when"}).assign(n=1)
    acc["n"] = acc.groupby("customer_id").n.cumsum()
    left = rows[["customer_id", "when"]].reset_index().sort_values("when")
    merged = pd.merge_asof(left, acc, on="when", by="customer_id", direction="backward")
    return merged.set_index("index").n.reindex(rows.index).fillna(0).to_numpy(int)


def _mle(loglik, lo: float, hi: float, grid: int = 11) -> tuple[float, float]:
    """Maximise a smooth 1-D log-likelihood: a coarse grid, a fine grid around its best point, then a parabola
    through the best fine point and its neighbours. Returns (estimate, standard error from the curvature).
    ponytail: 1-D only; use scipy.optimize if a model ever needs more than one free parameter."""
    xs = np.linspace(lo, hi, grid)
    best = xs[int(np.argmax([loglik(x) for x in xs]))]
    step = xs[1] - xs[0]
    xs = np.linspace(max(lo, best - 2 * step), min(hi, best + 2 * step), grid)
    ll = np.array([loglik(x) for x in xs])
    i = int(np.clip(ll.argmax(), 1, grid - 2))
    h = xs[1] - xs[0]
    a, b, c = ll[i - 1], ll[i], ll[i + 1]
    curv = (a - 2 * b + c) / h**2
    x = xs[i] + h * (a - c) / (2 * (a - 2 * b + c)) if curv < 0 else xs[i]
    return float(x), float(1 / np.sqrt(-curv)) if curv < 0 else float("inf")


def _proportion(hits: pd.Series, name: str, n_for_guard: int) -> Estimate:
    n = len(hits)
    v = float(hits.mean()) if n else float("nan")
    se = float(np.sqrt(v * (1 - v) / n)) if n else float("inf")
    ok = n_for_guard >= MINIMUM[name]
    return Estimate(v, se, n, ok, "" if ok else f"{n_for_guard} < {MINIMUM[name]} needed")


def kappa(ln: pd.DataFrame) -> Estimate:
    """Share of loans not repaid on time that default (in the simulator, P(default | not on time) = kappa)."""
    bad = ln[~ln.on_time]
    return _proportion(bad.default, "kappa", int(bad.default.sum()))


def early(ln: pd.DataFrame) -> Estimate:
    """Share of on-time loans repaid at least a day early."""
    good = ln[ln.on_time]
    return _proportion(good.early, "early", len(good))


def gamma(ln: pd.DataFrame, book: Book, p: Params, macro: Macro) -> Estimate:
    """Leverage effect: P(not on time) = (1 - q)(1 + gamma k) M(t), each customer's q unknown.

    q is integrated out per customer over its Beta(n0 * ontime, n0 * (1 - ontime)) prior (Gauss-Legendre
    nodes), which gives the exact likelihood of the generating process; customers are independent given gamma.
    """
    pos = pd.Series(np.arange(len(book)), index=book.ids)
    cust = pos.reindex(ln.customer_id).to_numpy()
    keep = ~np.isnan(cust)
    order = np.argsort(cust[keep], kind="stable")  # loans grouped by customer, for reduceat
    cust, y = cust[keep].astype(int)[order], (~ln.on_time.to_numpy())[keep][order]
    k, m = ln.k.to_numpy()[keep][order], macro.pd_mult[month(ln.t.to_numpy()[keep])][order]
    nodes, w = np.polynomial.legendre.leggauss(32)
    x = (nodes + 1) / 2  # q on (0, 1)
    a, b = p.n0 * book.ontime, p.n0 * (1 - book.ontime)
    lbeta = np.array([math.lgamma(ai) + math.lgamma(bi) - math.lgamma(ai + bi) for ai, bi in zip(a, b, strict=True)])
    log_prior = (a[:, None] - 1) * np.log(x) + (b[:, None] - 1) * np.log1p(-x) - lbeta[:, None] + np.log(w / 2)
    used, starts = np.unique(cust, return_index=True)

    def loglik(g: float) -> float:
        pl = np.clip((1 - x[None, :]) * (1 + g * k[:, None]) * m[:, None], 1e-12, 1 - 1e-12)
        per_loan = np.where(y[:, None], np.log(pl), np.log1p(-pl))
        z = np.add.reduceat(per_loan, starts, axis=0) + log_prior[used]  # sum over each customer's loans
        zmax = z.max(1, keepdims=True)
        return float((zmax[:, 0] + np.log(np.exp(z - zmax).sum(1))).sum())

    n = int((y & (k > 0)).sum())
    ok = n >= MINIMUM["gamma"]
    if not ok:
        return Estimate(p.gamma, float("inf"), n, False, f"{n} < {MINIMUM['gamma']} late loans after an increase")
    v, se = _mle(loglik, 0.0, 1.0)
    return Estimate(v, se, n, True)


def offers(ev: pd.DataFrame, year: datetime) -> pd.DataFrame:
    """Offers made in the planning year with their response and k (accepts earlier that year)."""
    pl = ev.payload.map(lambda s: json.loads(s) if isinstance(s, str) else s)
    e = ev.assign(offer_id=pl.map(lambda d: d.get("offer_id")))
    off = e[(e.event_type == "offer") & (e.occurred_at >= year) & (e.occurred_at < year + timedelta(days=365))]
    off = off[["customer_id", "offer_id", "occurred_at"]].rename(columns={"occurred_at": "when"})
    resp = e[e.event_type.isin(["accept", "decline"])].set_index("offer_id").event_type
    off = off.assign(accepted=off.offer_id.map(resp).eq("accept"), answered=off.offer_id.isin(resp.index))
    off = off[off.answered]
    k = _accepted_before(ev, off.assign(when=off.when - timedelta(seconds=1)), year)  # earlier accepts only
    return off.assign(k=k, t=(off.when - year).dt.days)


def fatigue(off: pd.DataFrame, book: Book, macro: Macro, p: Params) -> Estimate:
    """Acceptance log-odds drop per increase already taken. Each customer's own prior propensity enters as an
    offset, so customers who like increases (and therefore have more of them) do not bias the slope."""
    prior = pd.Series(book.accept, index=book.ids).reindex(off.customer_id).to_numpy()
    keep = ~np.isnan(prior)
    o = logit(prior[keep]) + macro.acc_shift[month(off.t.to_numpy()[keep])]
    k, y = off.k.to_numpy()[keep], off.accepted.to_numpy()[keep]

    def loglik(f: float) -> float:
        s = np.clip(sigmoid(o - f * k), 1e-12, 1 - 1e-12)
        return float(np.where(y, np.log(s), np.log1p(-s)).sum())

    n = int(keep.sum())
    if n < MINIMUM["fatigue"]:
        return Estimate(p.fatigue, float("inf"), n, False, f"{n} < {MINIMUM['fatigue']} answered offers")
    v, se = _mle(loglik, 0.0, 2.0)
    return Estimate(v, se, n, True)


def c0(ln: pd.DataFrame, ev: pd.DataFrame, as_of: datetime, p: Params) -> Estimate:
    """Baseline churn per cycle, from loans where the customer was offered an increase that window (nobody
    was refused, so the refusal effect c_deny cannot be mixed in). Churn = no new loan within one cycle."""
    cyc = timedelta(days=p.cycle)
    offered_at = ev[ev.event_type == "offer"][["customer_id", "occurred_at"]].rename(columns={"occurred_at": "o"})
    base = ln[~ln.default & ln.repaid_at.notna() & (ln.repaid_at <= as_of - cyc)].reset_index()
    pairs = base.merge(offered_at, on="customer_id")
    hit = pairs[(pairs.o <= pairs.when) & (pairs.o >= pairs.when - timedelta(days=1))]["index"].unique()
    base = base[base["index"].isin(hit)]
    nxt = ev[ev.event_type == "disburse"][["customer_id", "occurred_at"]].rename(columns={"occurred_at": "n"})
    pairs = base.merge(nxt, on="customer_id")
    stayed = pairs[(pairs.n > pairs.when) & (pairs.n <= pairs.repaid_at + cyc)]["index"].unique()
    churned = ~base["index"].isin(stayed)
    return _proportion(churned, "c0", int(churned.sum()))


def estimate_all(
    ev: pd.DataFrame, book: Book, p: Params, year: datetime, as_of: datetime, macro: Macro = SCENARIOS["base"]
) -> dict[str, Estimate]:
    """Every estimable parameter. Events need columns customer_id, event_type, occurred_at (UTC), payload."""
    ev = ev.assign(payload=ev.payload.map(lambda s: json.loads(s) if isinstance(s, str) else s))  # parse once
    ln = loans(ev, year, as_of)
    return {
        "kappa": kappa(ln),
        "gamma": gamma(ln, book, p, macro),
        "fatigue": fatigue(offers(ev, year), book, macro, p),
        "early": early(ln),
        "c0": c0(ln, ev, as_of, p),
    }
