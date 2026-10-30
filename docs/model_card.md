# Model card: loan limit graduation (draft)

**Status:** draft, development only. Not approved for production decisions.
**Organisation:** Ruskins Digital Lending Ltd (fictional). **Version:** package `lending` 0.1.0; production versions are the git SHA recorded on each decision.

## Purpose

At each 60-day eligibility window, decide per customer whether to **offer** or **hold** a limit increase, so that portfolio NPV is as high as possible while risk-weighted capital stays within budget.

- **Users:** credit risk team (sets parameters, approves runs); lending operations (reads decisions through the API).
- **Out of scope:** first-loan approval, pricing, collections, any decision about an individual based on personal characteristics. The model only decides whether to *offer* an increase; the customer chooses whether to take it.

## How it works

1. **State** per customer: risk bucket (from on-time rate), increases granted so far, windows passed without one.
2. **Value** of offer vs hold over the year: margin and fee earned, expected default loss, churn, discounting at 19%. Solved exactly by backward induction.
3. **Capital** links customers. A single price λ per dollar of risk-weighted capital makes each customer an independent problem; bisection finds the smallest λ that keeps the portfolio within budget.
4. **Validation by simulation:** a Monte Carlo model that is deliberately richer than the optimiser (customer-specific reliability, stochastic repayment, term extensions, re-bucketing) checks that the policy still holds up.

Inputs: `docs/data_card.md`. Every assumption: `docs/assumptions.md`.

## Results on the reference book (base macro case, 100 simulated paths)

| Strategy | NPV | Increases | Default rate | Churn | Risk-weighted capital |
|---|---|---|---|---|---|
| Historical (as observed) | $11.61M | 61,874 | 14.3% | 10.3% | $2.61M |
| Grant whenever eligible | $11.63M | 66,158 | 14.0% | 10.0% | $2.80M |
| Scorecard (prime and near-prime only) | $13.07M | 52,173 | 13.6% | 13.2% | $1.99M |
| Optimal, no capital limit | $14.89M | 20,405 | 13.5% | 20.9% | $0.48M |
| **Optimal, capital limit (λ* ≈ 0.62)** | **$14.84M** | 13,401 | 13.4% | 22.6% | $0.25M |

The policy offers mainly to prime customers with small and mid-sized loans; near-prime and subprime customers get offers only on small loans. Dollar figures are indicative because the economics are assumed (see limitations).

## Evaluation

| Check | Where | Result |
|---|---|---|
| Exact parity with the reference implementation (strategy table and policy map) | `tests/parity/` (opt-in) | Pass, rtol 1e-6 / 1e-9 |
| Transition rows are probabilities | `tests/unit` | Pass |
| No risk, no capital cost, no delay ⇒ always offer | `tests/unit` | Pass |
| Higher LGD never increases offers | `tests/unit` | Pass |
| Never offer at the cap | `tests/unit` | Pass |
| λ* within budget; slightly lower λ breaks it | `tests/unit` | Pass |
| Chunked solve equals whole-book solve | `tests/unit` | Pass |
| Sensitivity: one assumption at a time | reference analysis | The ranking of strategies held in every case |

**Planned before production:** behavioural gates in `tests/model_gates` (NPV vs current champion, calibration, input drift), and a randomised champion/challenger rollout (e.g. 80/20) with NPV per customer as the main metric and default rate, churn and capital as guardrails.

## Limitations and known behaviour

- **Assumed economics.** Loss given default and churn after a refusal move NPV the most and are not estimated from data. The optimised policy accepts higher churn (22.6% vs 10.3%) in exchange for lower losses; that trade-off rests on the churn assumption and is the first thing to test.
- **Term extensions can make holding optimal even with no risk.** An increase lengthens the loan term, which can push a margin cycle past year end. Found by a failing unit test and confirmed as model behaviour, not a bug.
- **Year-end edge.** A one-year horizon produces a December spike in offers. Fix in production: a rolling twelve-month horizon.
- **Retrospective acceptance.** Acceptance is estimated from the year it is evaluated on; production must use the previous period.
- **Scale.** Solving at a fixed λ is linear and chunked. Re-finding λ by bisection over millions of customers is slow (hours on one core); the planned cadence is a nightly solve at an approved λ with periodic recalibration.
- **Fairness.** Inputs are repayment behaviour and loan size only, with no personal characteristics. Outcomes should still be checked across customer groups once real data allows.

## Governance

- Parameters change only through approved `parameter_sets` rows (maker-checker), with bounds enforced in the database.
- Every decision records `param_version`, `model_version` (git SHA), λ and the input data version, so it can be reproduced.
- Synthetic data only in this repository. Production use would also need to satisfy CBK digital credit rules and the Kenya Data Protection Act 2019.
