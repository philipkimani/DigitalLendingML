"""Behavioural tests of the model: properties that must hold whatever the exact numbers are.

Each test states an economic rule (e.g. "riskier losses never mean more offers") and checks the
solver obeys it. Fixtures `book` and `model` come from conftest.py (2,000 seeded customers).
"""

import dataclasses

import numpy as np
import pytest

from lending import capital, find_lambda, solve


def live_mask(book, model):
    """(N, 1, W+1, W+1) True where window (k, h) falls inside the horizon."""
    p, W = model.p, model.p.windows
    m = np.zeros((len(book), 1, W + 1, W + 1), bool)
    for n in range(W):
        for k in range(n + 1):
            m[:, 0, k, n - k] = book.wait + p.cycle * n + book.ext * k <= p.horizon
    return m


def test_transition_rows_are_probabilities(model):
    # Every row of a transition matrix is "where a customer in this bucket goes": must sum to 1.
    for T in (model.T_hold, model.T_grant):
        assert np.all((T >= 0) & (T <= 1))
        np.testing.assert_allclose(T.sum(1), 1.0)


def holds_below_cap(book, model):
    """Count real decisions (inside the horizon, below the cap) where the policy says hold."""
    pol, _ = solve(book, model, lam=0.0)
    live = np.broadcast_to(live_mask(book, model), pol.shape).copy()
    live[:, :, model.p.max_k :, :] = False
    return int((live & ~pol).sum())


def test_increase_with_no_risk_no_capital_cost_and_no_delay_is_always_offered(book, model):
    """No default risk, lam = 0 and no term extension: an increase has only upside, so every live
    window below the cap gets an offer."""
    safe = model.with_(p=model.p.with_(kappa=0.0))
    assert holds_below_cap(dataclasses.replace(book, ext=np.zeros(len(book))), safe) == 0


def test_term_extension_alone_can_justify_a_hold(book, model):
    """Even with no risk, an increase stretches the term, pushing later windows past the horizon; one lost
    cycle of margin (4% of the loan) can outweigh the $40 fee. Intended behaviour, not a bug."""
    assert holds_below_cap(book, model.with_(p=model.p.with_(kappa=0.0))) > 0


def test_higher_lgd_never_increases_offers(book, model):
    # Monotonicity: losing more on default can only make offers less attractive.
    counts = [solve(book, model.with_(p=model.p.with_(lgd=lgd)))[0].sum() for lgd in (0.5, 0.65, 0.8)]
    assert counts[0] >= counts[1] >= counts[2]


def test_never_offers_at_the_yearly_cap(book, model):
    pol, _ = solve(book, model)
    assert not pol[:, :, model.p.max_k :, :].any()


def test_chunked_solve_equals_whole_book(book, model):
    # At a fixed lam customers are independent, so solving in pieces must give the identical policy.
    whole, _ = solve(book, model, lam=0.5)
    parts = np.concatenate([solve(part, model, lam=0.5)[0] for part in book.chunks(300)])
    np.testing.assert_array_equal(whole, parts)


def test_chunked_capital_is_deterministic(book, model):
    # Same seed and chunk size -> same random streams -> same answer (reproducible runs).
    assert capital(book, model, 0.5, S=10, seed=3, chunk=700) == capital(book, model, 0.5, S=10, seed=3, chunk=700)


def test_lambda_star_is_feasible_and_tight(book, model):
    """lam* keeps capital within budget; the bisection's last infeasible point (one step lower) breaks it."""
    S, seed = 20, 11
    budget = 0.5 * capital(book, model, 0.0, S, seed)  # make the constraint bind on this book
    m = model.with_(p=model.p.with_(budget=budget))
    lam = find_lambda(book, m, S=S, seed=seed)
    assert lam > 0
    assert capital(book, m, lam, S, seed) <= budget
    assert capital(book, m, lam - 5.0 / 2**14, S, seed) > budget


def test_unreachable_budget_raises(book, model):
    # A zero budget cannot be met by any price in range: fail loudly rather than return a wrong lam.
    with pytest.raises(ValueError):
        find_lambda(book, model.with_(p=model.p.with_(budget=0.0)), S=5, hi=0.01, iters=2)
