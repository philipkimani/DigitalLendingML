# Data card

What data the model reads, what each field means, and what values are allowed. The synthetic generator (`src/lending/synthetic.py`) and the data contract (`src/lending/contract.py`, pandera) are built to this card; if they disagree, this card is updated first.

**All data in this repository is synthetic.** No real customer data or personal information is used or committed. Customer ids are pseudonymous integers with no link to any person.

## 1. Customer book (model input)

One row per customer, as of the start of the planning year. Read by `lending.book.Book.from_frame`.

| Column | Type | Allowed values | Meaning | Used as |
|---|---|---|---|---|
| `customer_id` | int64 | unique, ≥ 0 | Pseudonymous customer key | Join key; never a feature |
| `loan_amount` | number (USD) | 500 – 5,000 | Initial loan size L₀ | Margin, exposure, increase size; term extension `10 + 20·L₀/5000` days |
| `days_since_last_loan` | int64 | 0 – 364 | Days between last loan and 1 January | First eligibility: `max(0, 60 − days)` |
| `ontime_pct` | float64 (%) | 0 – 100, two decimals | Share of past repayments made on time | Risk bucket and Beta prior on reliability (clipped to 1%–99.5%) |
| `n_increases` | int64 | 0 – 6 | Limit increases taken last year | Acceptance prior `(n + 1) / 7` |

Risk buckets come from `ontime_pct`: **prime** ≥ 95%, **near-prime** 85–95%, **subprime** < 85%. Every bucket must contain at least one customer, or calibration stops with an error.

### Reference profile (the 30,000-customer book the model was developed on)

The generator should reproduce this shape by default:

| Field | Observed |
|---|---|
| `loan_amount` | 500 – 4,999, close to uniform (mean 2,753, sd 1,293) |
| `days_since_last_loan` | 0 – 364, close to uniform (mean 181, sd 105) |
| `ontime_pct` | 80 – 100, close to uniform (mean 90.0, sd 5.75) |
| Buckets | prime 25.1%, near-prime 50.3%, subprime 24.6% |
| `n_increases` | 0 (44%), 3 (19%), 4 (18%), 5 (19%); never 1, 2 or 6 |
| Quality | no nulls, no duplicate ids |

Known quirks: no customer below 80% on time, so "subprime" here means 80–85%; increase counts are bunched at 0 and 3–5, which looks like a past business rule rather than customer behaviour. The generator should offer these as defaults and allow wider ranges for stress tests.

## 2. Operational tables (planned, Postgres)

Defined by migrations in `db/migrations/` once the database step is built. Listed here so the generator and the API agree on shapes from the start.

| Table | Grain | Key | Purpose |
|---|---|---|---|
| `events` | one partner event (loan, repayment, offer response) | partner `event_id` | Raw, append-only, idempotent ingest |
| `customer_state` | one row per customer | `customer_id` | Current book row (section 1), rebuilt from events |
| `parameter_sets` | one versioned parameter set | `param_version` | Maker-checker: only `approved`/`active` rows drive decisions |
| `decisions` | customer × run | (`customer_id`, `run_id`) | Offer/hold, with `param_version`, `model_version` (git SHA), λ, data version |
| `audit` | one change | id | Who changed what and when |

## 3. Lineage and versioning

- Synthetic books are registered as **Azure ML data assets** with an explicit version; the generator seed and arguments are stored with the asset.
- Every nightly run records the data asset version it read, so any decision can be traced back to its input.

## 4. What the data cannot tell us

There are no repayment outcomes, no history of risk states and no record of offers made or declined. Default, migration, acceptance and churn therefore come from stated assumptions (`docs/assumptions.md`) until the decision log in section 2 has collected real outcomes.
