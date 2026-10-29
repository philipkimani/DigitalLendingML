import numpy as np
import pandas as pd
import pytest

from lending import Book, Model


@pytest.fixture(scope="session")
def book() -> Book:
    """2,000 seeded customers shaped like the reference book (uniform features, 0 or 3-5 past increases)."""
    rng = np.random.default_rng(0)
    n = 2000
    return Book.from_frame(pd.DataFrame({
        "customer_id": np.arange(n),
        "loan_amount": rng.uniform(500, 5000, n).round(2),
        "days_since_last_loan": rng.integers(0, 120, n),
        "ontime_pct": rng.uniform(70, 100, n).round(1),
        "n_increases": rng.choice([0, 3, 4, 5], n),
    }))


@pytest.fixture(scope="session")
def model(book) -> Model:
    return Model.calibrate(book)
