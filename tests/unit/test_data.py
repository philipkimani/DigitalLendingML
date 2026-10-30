"""Data contract and synthetic generator: bad inputs are rejected, generated data is reproducible and on-profile."""

import numpy as np
import pandera.errors
import pytest

from lending import bucket, validate
from lending.synthetic import generate


@pytest.fixture(scope="module")
def df():
    return generate(5_000, seed=3)


# --- Generator ----------------------------------------------------------------------------------


def test_same_seed_same_data():
    # Reproducibility: a data asset can be rebuilt exactly from its recorded (n, seed).
    assert generate(500, seed=1).equals(generate(500, seed=1))
    assert not generate(500, seed=1).equals(generate(500, seed=2))


def test_matches_reference_profile(df):
    # Bucket mix ~25% prime / 50% near-prime / 25% subprime, as in the reference book.
    shares = np.bincount(bucket(df.ontime_pct.to_numpy() / 100), minlength=3) / len(df)
    np.testing.assert_allclose(shares, [0.25, 0.50, 0.25], atol=0.02)
    # Past increases only ever 0 or 3-5.
    assert set(df.n_increases) <= {0, 3, 4, 5}


# --- Contract: each rule rejects the input it is meant to catch -------------------------------


@pytest.mark.parametrize(
    "column, bad_value",
    [
        ("loan_amount", 100),  # below the $500 minimum
        ("days_since_last_loan", 400),  # more than a year
        ("ontime_pct", 120),  # not a percentage
        ("n_increases", 7),  # above the yearly cap
        ("loan_amount", None),  # missing value
    ],
)
def test_contract_rejects_out_of_range(df, column, bad_value):
    bad = df.copy()
    bad[column] = bad[column].astype(object)
    bad.loc[0, column] = bad_value
    with pytest.raises(pandera.errors.SchemaErrors):
        validate(bad)


def test_contract_rejects_duplicate_ids(df):
    bad = df.copy()
    bad.loc[1, "customer_id"] = bad.loc[0, "customer_id"]
    with pytest.raises(pandera.errors.SchemaErrors):
        validate(bad)


def test_contract_rejects_missing_bucket(df):
    # Only prime customers: calibration could not estimate near-prime and subprime late rates.
    with pytest.raises(pandera.errors.SchemaErrors):
        validate(df[df.ontime_pct >= 95])


def test_contract_rejects_missing_column(df):
    with pytest.raises(pandera.errors.SchemaErrors):
        validate(df.drop(columns="ontime_pct"))


def test_split_valid_drops_only_the_rows_that_break_the_contract():
    from lending.contract import split_valid

    df = generate(200, seed=3)
    df.loc[[5, 9], "loan_amount"] = 6000  # outside the model's validated range
    df.loc[12, "n_increases"] = 7
    kept, dropped = split_valid(df)
    assert dropped == 3 and len(kept) == 197 and not kept.index.isin([5, 9, 12]).any()
    assert split_valid(generate(50, seed=3))[1] == 0
