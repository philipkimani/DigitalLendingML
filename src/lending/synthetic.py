"""Synthetic customer book, shaped like the reference book described in docs/data_card.md.

Why synthetic: the repository is public and must never hold real customer data. The generator
reproduces the *shape* of the reference book (ranges, distributions, bucket mix) so the model
behaves the same way, without any real person behind a row.

Reproducible by design: the same (n, seed) always gives the same file, so a data asset version
can be rebuilt exactly from its recorded arguments.

Command line:
    uv run python -m lending.synthetic --n 30000 --seed 42 --out data/raw/book.csv
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from .contract import validate

# Past-increase counts seen in the reference book: only 0 or 3-5 (never 1, 2 or 6),
# which looks like an old business rule. Probabilities are the observed shares.
N_INCREASES = {0: 0.44, 3: 0.19, 4: 0.18, 5: 0.19}


def generate(n: int = 30_000, seed: int = 42) -> pd.DataFrame:
    """Return a validated synthetic book of n customers.

    In the reference book the four fields are independent of each other (rank correlations
    all ~0), so each one is drawn on its own.
    """
    # One seeded generator drives every draw, so the whole table depends only on (n, seed).
    rng = np.random.default_rng(seed)

    df = pd.DataFrame(
        {
            # Pseudonymous ids: a plain counter, no meaning, no link to a person.
            "customer_id": np.arange(1, n + 1),
            # Uniform $500-$4,999 whole dollars, as in the reference book.
            "loan_amount": rng.integers(500, 5000, n),
            # Uniform 0-364 days since the last loan.
            "days_since_last_loan": rng.integers(0, 365, n),
            # Uniform 80-100% on time, two decimals. Gives roughly 25% prime (>=95),
            # 50% near-prime (85-95) and 25% subprime (<85).
            "ontime_pct": rng.uniform(80, 100, n).round(2),
            # Past increases drawn from the observed mix above.
            "n_increases": rng.choice(list(N_INCREASES), n, p=list(N_INCREASES.values())),
        }
    )

    # Check our own output against the data contract before anyone uses it.
    return validate(df)


def main() -> None:
    # Command-line wrapper: parse arguments, generate, write CSV, report what was written.
    ap = argparse.ArgumentParser(description="Write a synthetic customer book to CSV.")
    ap.add_argument("--n", type=int, default=30_000, help="number of customers")
    ap.add_argument("--seed", type=int, default=42, help="random seed (record it with the data asset)")
    ap.add_argument("--out", type=Path, default=Path("data/raw/book.csv"), help="output CSV path")
    args = ap.parse_args()

    df = generate(args.n, args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)
    print(f"wrote {len(df):,} customers to {args.out} (seed {args.seed})")


if __name__ == "__main__":
    main()
