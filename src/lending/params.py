"""Model assumptions and macro scenarios.

Every value is a stated assumption, to be replaced by estimates once offers and repayment outcomes are logged.
Params is frozen: a changed parameter set is a new object, mirroring a new row in parameter_sets.
"""
from dataclasses import dataclass, field, replace

import numpy as np

CUTS = (0.85, 0.95)  # on-time rate thresholds: bucket 0 prime >= 0.95, 1 near-prime >= 0.85, 2 subprime


@dataclass(frozen=True)
class Params:
    n0: float = 20             # past loans of evidence behind each on-time rate (Beta prior strength)
    kappa: float = 0.25        # share of late payments that roll to default
    early: float = 0.30        # share of on-time payers who repay early
    early_fee: float = 0.8     # share of the fee earned on early repayment (rebate)
    gamma: float = 0.10        # leverage effect: PD x (1 + gamma k) after k increases
    step: float = 0.15         # each increase adds 15% of the initial loan
    lgd: float = 0.65          # loss given default
    m: float = 0.04            # base margin per repaid cycle, share of initial loan
    fee: float = 40.0          # fee per accepted increase, earned at repayment
    c0: float = 0.02           # baseline churn per cycle
    c_deny: float = 0.06       # extra churn when a wanted increase is refused
    K: tuple[float, float, float] = (0.08, 0.12, 0.20)  # capital weight by bucket
    budget: float = 250_000.0  # risk-weighted capital budget
    disc: float = 0.19         # annual discount rate
    fixed_cost: float = 0.0    # per participating customer (sensitivity only)
    fatigue: float = 0.10      # acceptance log-odds drop per increase already taken
    horizon: int = 365         # days in the planning year
    cycle: int = 60            # days between eligibility windows
    max_k: int = 6             # yearly cap on increases

    @property
    def weights(self) -> np.ndarray:
        return np.asarray(self.K)

    @property
    def windows(self) -> int:
        """Decision epochs that fit in the horizon (7 for 365/60)."""
        return self.horizon // self.cycle + 1

    def with_(self, **changes) -> "Params":
        return replace(self, **changes)


@dataclass(frozen=True, eq=False)
class Macro:
    pd_mult: np.ndarray = field(repr=False)   # (12,) monthly multiplier on default probability
    acc_shift: np.ndarray = field(repr=False)  # (12,) monthly shift in acceptance log-odds


def macro_path(dpi: float = 0.0, dcbr: float = 0.0, du: float = 0.0) -> Macro:
    """Kenya 2023 monthly path (CPI inflation, CBK rate, unemployment), optionally shifted in pp.

    CPI: KNBS 2023. CBK rate: MPC decisions 2023. Unemployment: assumed flat baseline.
    Elasticities are illustrative, set for scenario tests.
    """
    pi = np.array([9.0, 9.2, 9.2, 7.9, 8.0, 7.9, 7.3, 6.7, 6.8, 6.9, 6.8, 6.6]) + dpi
    cbr = np.array([8.75, 8.75, 9.5, 9.5, 9.5, 10.5, 10.5, 10.5, 10.5, 10.5, 10.5, 12.5]) + dcbr
    u = np.full(12, 5.7) + du
    return Macro(pd_mult=np.exp(0.06 * (cbr - 10.0) + 0.10 * (u - 5.7) + 0.02 * (pi - 7.7)),
                 acc_shift=0.05 * (pi - 7.7) - 0.04 * (cbr - 10.0) + 0.03 * (u - 5.7))


SCENARIOS = {"base": macro_path(), "adverse": macro_path(4, 3, 2), "benign": macro_path(-2, -2, -1)}


def month(t: np.ndarray) -> np.ndarray:
    """Day of year -> month index 0..11."""
    return np.clip((t / 30.42).astype(int), 0, 11)
