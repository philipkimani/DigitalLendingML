"""What-if scenarios: which ones run, and that measuring them behaves like the model."""

from lending import Book, Params
from lending.scenarios import evaluate, grid
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
