"""From a solved policy to one decision per customer, and from a database row back to Params.

The solver returns a full policy table pol[customer, r, k, h]: offer or hold in every reachable state.
The nightly job publishes only today's action, the one at the customer's next eligibility window:
current risk bucket r, no increases yet this year (k = 0), no holds yet (h = 0).

parameter_sets stores one column per Params field (capital weights as k_prime / k_near / k_sub),
so a row rebuilds the exact Params the run used.
"""

from dataclasses import fields

import numpy as np
import pandas as pd

from .book import Book
from .params import Params
from .states import bucket

WEIGHT_COLUMNS = ("k_prime", "k_near", "k_sub")  # Params.K, by bucket


def params_from_row(row: dict) -> Params:
    """Params from a parameter_sets row (extra columns such as status or maker are ignored)."""
    values = {f.name: row[f.name] for f in fields(Params) if f.name != "K"}
    kp, kn, ks = (float(row[c]) for c in WEIGHT_COLUMNS)
    return Params(**values, K=(kp, kn, ks))


def first_window(book: Book, pol: np.ndarray) -> pd.DataFrame:
    """Today's action per customer: the policy at state (current bucket, k = 0, h = 0)."""
    r = bucket(book.ontime)
    offer = pol[np.arange(len(book)), r, 0, 0]  # one state per customer: fancy indexing on axes 0 and 1
    return pd.DataFrame(
        {
            "customer_id": book.ids,
            "bucket": r,
            "action": np.where(offer, "offer", "hold"),
        }
    )
