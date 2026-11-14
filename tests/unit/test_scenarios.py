"""What-if scenarios: which ones run, and that measuring them behaves like the model."""

from lending import Book, Params
from lending.scenarios import evaluate, grid, sensitivity_grid, strategies
from lending.synthetic import generate

N = 500
PARAMS = Params(budget=250_000 * N / 30_000)


def test_grid_is_baseline_plus_three_levers():
    p = Params(budget=100_000, step=0.15, fee=40)
    assert grid(p) == [
        ("baseline", 100_000),
        ("budget", 80_000),
        ("budget", 120_000),
        ("budget", 150_000),
        ("step", 0.10),
        ("step", 0.20),
        ("fee", 30),
        ("fee", 50),
    ]


def test_grid_stays_inside_the_database_bounds():
    p = Params(step=0.05, fee=5)
    assert ("step", 0.0) not in grid(p)
    assert ("fee", -5) not in grid(p)


def test_a_bigger_budget_never_means_fewer_offers():
    book = Book.from_frame(generate(N, seed=42))
    small = evaluate(book, PARAMS, "baseline", PARAMS.budget, S=10, iters=6)
    big = evaluate(book, PARAMS, "budget", PARAMS.budget * 1.5, S=10, iters=6)
    assert big["offers"] >= small["offers"]
    assert small["capital_used"] <= PARAMS.budget
    assert 0 <= small["default_rate"] <= 1
    assert set(small) == {"lever", "value", "lambda", "offers", "capital_used", "npv", "default_rate"}


def test_strategy_comparison_has_the_report_shape():
    """Report summary: five strategies on the same paths; the constrained optimum keeps to budget."""
    book = Book.from_frame(generate(N, seed=42))
    rows, months = strategies(book, PARAMS, "base", S=10, iters=6)
    by = {r["strategy"]: r for r in rows}
    assert set(by) == {"historical", "grant_all", "scorecard", "optimal_free", "optimal"}
    assert by["optimal"]["capital"] <= PARAMS.budget
    assert by["optimal"]["npv_mean"] >= by["grant_all"]["npv_mean"]
    for r in rows:
        assert r["npv_p5"] <= r["npv_mean"] <= r["npv_p95"]
        assert 0 <= r["default_rate"] <= 1 and 0 <= r["churn_rate"] <= 1
    # the monthly forecast adds up to the increases of the same strategy
    for name, r in by.items():
        total = sum(m["increases"] for m in months if m["strategy"] == name)
        assert abs(total - r["increases"]) < 1e-6 * max(1.0, r["increases"])
    assert len(months) == 12 * len(rows)


def test_other_worlds_also_run_the_base_policy():
    book = Book.from_frame(generate(N, seed=42))
    rows, _ = strategies(book, PARAMS, "adverse", base_lambda=0.5, S=10, iters=6)
    assert {r["strategy"] for r in rows} >= {"optimal", "base_policy"}
    assert all(r["scenario"] == "adverse" for r in rows)


def test_sensitivity_grid_is_the_report_set():
    g = sensitivity_grid(Params())
    assert ("lgd", 0.5) in g and ("lgd", 0.8) in g and ("fixed_cost", 80.0) in g
    assert ("kappa", round(0.85 * 0.25, 4)) in g and ("c_deny", 0.12) in g
    assert len(set(g)) == len(g)
