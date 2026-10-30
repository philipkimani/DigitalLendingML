"""The customer book: one array per attribute, sliceable into chunks for million-customer runs.

Storing columns as numpy arrays (not a DataFrame) is what lets the solver and simulator compute for
every customer at once. from_frame is the single door data comes in through, so the contract is checked
there, and derived per-customer inputs (first window, term extension, acceptance prior) are made there.
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .contract import validate


@dataclass(frozen=True, eq=False)
class Book:
    ids: np.ndarray = field(repr=False)
    loan: np.ndarray = field(repr=False)  # initial loan L0
    ontime: np.ndarray = field(repr=False)  # on-time repayment rate q0 in (0, 1)
    wait: np.ndarray = field(repr=False)  # days until the first eligibility window
    ext: np.ndarray = field(repr=False)  # expected term extension (days) when an increase is taken
    accept: np.ndarray = field(repr=False)  # acceptance propensity prior
    n_hist: np.ndarray = field(repr=False)  # increases taken last period (for replaying history)

    @classmethod
    def from_frame(cls, df: pd.DataFrame, cycle: int = 60) -> "Book":
        # Trust boundary: every book passes the data contract (types, ranges, unique ids,
        # all buckets present) before any maths runs. Raises with every failed rule listed.
        df = validate(df)
        loan = df.loan_amount.to_numpy(float)
        n = df.n_increases.to_numpy(int)
        return cls(
            ids=df.customer_id.to_numpy(),
            loan=loan,
            ontime=np.clip(df.ontime_pct.to_numpy(float) / 100, 0.01, 0.995),  # 100% gives a degenerate Beta
            wait=np.maximum(0, cycle - df.days_since_last_loan.to_numpy(float)),
            ext=10 + 20 * loan / 5000,
            accept=(n + 1) / 7,  # Beta-Binomial posterior mean, ~5 offers seen
            n_hist=n,
        )

    def __len__(self) -> int:
        return len(self.loan)

    def __getitem__(self, sl: slice) -> "Book":
        # Slicing a Book slices every array the same way, giving a smaller Book (used for chunks).
        return Book(**{k: v[sl] for k, v in self.__dict__.items()})

    def chunks(self, size: int | None):
        """Yield consecutive sub-books of at most `size` customers (whole book if size is None)."""
        size = size or len(self)
        for i in range(0, len(self), size):
            yield self[i : i + size]
