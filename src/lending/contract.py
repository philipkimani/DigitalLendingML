"""Data contract for the customer book: the rules every input must pass before the model sees it.

A data contract is the agreement between whoever produces the data (the synthetic generator today,
partner events in production) and the model that reads it. It is written down in docs/data_card.md
and enforced here with pandera, so a bad file fails loudly at the door instead of producing quietly
wrong decisions later.
"""

import pandera.pandas as pa

from .params import CUTS

# --- Column rules -----------------------------------------------------------------------------
# One pa.Column per input field: its type, whether nulls are allowed, and the allowed range.
# The ranges match docs/data_card.md section 1. `coerce=True` converts compatible types
# (e.g. a loan read from CSV as int) instead of rejecting them.
COLUMNS = {
    # Pseudonymous key: must be unique, because the API looks decisions up by it.
    "customer_id": pa.Column(int, pa.Check.ge(0), unique=True, nullable=False),
    # Initial loan in USD.
    "loan_amount": pa.Column(float, pa.Check.in_range(500, 5000), coerce=True, nullable=False),
    # Days since the last loan; sets when the customer is first eligible (60-day rule).
    "days_since_last_loan": pa.Column(int, pa.Check.in_range(0, 364), coerce=True, nullable=False),
    # Share of past repayments made on time, in percent; sets the risk bucket.
    "ontime_pct": pa.Column(float, pa.Check.in_range(0, 100), coerce=True, nullable=False),
    # Limit increases taken last year; feeds the acceptance prior (n + 1) / 7. Cap is 6 a year.
    "n_increases": pa.Column(int, pa.Check.in_range(0, 6), coerce=True, nullable=False),
}


# --- Whole-table rule ---------------------------------------------------------------------------
# Calibration estimates a late-payment rate per risk bucket, so every bucket needs customers.
# This checks the table as a whole, which a single-column rule cannot do.
def _all_buckets_present(df) -> bool:
    q = df["ontime_pct"] / 100
    return bool((q >= CUTS[1]).any() and ((q >= CUTS[0]) & (q < CUTS[1])).any() and (q < CUTS[0]).any())


# --- The schema ---------------------------------------------------------------------------------
# strict=False lets extra columns through (e.g. a profit column in a source file); they are ignored.
BOOK = pa.DataFrameSchema(
    COLUMNS,
    checks=pa.Check(_all_buckets_present, error="every risk bucket (prime, near-prime, subprime) needs a customer"),
    strict=False,
    name="customer_book",
)


def validate(df):
    """Return the validated (type-coerced) book, or raise listing every rule that failed.

    lazy=True collects all failures in one error instead of stopping at the first,
    which is what you want when fixing a bad file.
    """
    return BOOK.validate(df, lazy=True)


def split_valid(df):
    """(validated rows that pass every per-row rule, number of rows dropped).

    For state derived from events: a customer outside the model's validated range (say a $6,000 loan) gets
    no decision rather than stopping the whole run. Table-level rules (every bucket present) still raise.
    """
    try:
        return validate(df), 0
    except pa.errors.SchemaErrors as err:
        bad = err.failure_cases["index"].dropna().unique()
        kept = df.drop(index=bad)
        return validate(kept), len(df) - len(kept)
