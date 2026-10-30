# Assumptions log

Every economic input the model uses. Most are **judgement, not estimates**: the input data has no repayment outcomes, offers or declines. Each row says where the value came from and how it gets replaced. Code: `src/lending/params.py` (`Params`, `macro_path`).

Changing a value in production is a new row in `parameter_sets`, approved by a second person (maker-checker), never an edit to code.

## Parameters

| Parameter | Code | Value | Source | Sensitivity | Replace with |
|---|---|---|---|---|---|
| Late payments that roll to default | `kappa` | 25% | Judgement; gives annual default ≈ 4% / 14% / 24% by bucket | Medium | Default rate by bucket from the repayment log |
| Loss given default | `lgd` | 65% | Judgement: unsecured mobile credit, weak recoveries | **Highest** (50% → +$2.4M NPV; 80% → −$2.3M) | Recoveries on defaulted loans |
| Leverage effect | `gamma` | +10% default risk per increase | Judgement: over-indebtedness | Low | Default rate by number of increases |
| Increase size | `step` | 15% of initial loan | Common step size | Low | Business decision |
| Base margin | `m` | 4% of initial loan per repaid cycle | Fees less funding and operating cost | Medium | Finance (unit economics) |
| Fee per increase | `fee` | $40, earned at repayment | Business rule (given) | — | Business rule |
| Early repayment | `early`, `early_fee` | 30% of on-time payers; they earn 80% of the fee | Judgement: interest rebate | Low | Repayment log |
| Term extension | `Book.ext` | 10–30 days, longer for bigger loans | Judgement | Matters for timing (see model card) | Loan terms after an increase |
| Baseline churn | `c0` | 2% per cycle | Judgement | Medium | Retention data |
| Churn after a refused increase | `c_deny` | +6% | Judgement: saying no costs retention | **High** (0% → +$1.5M; 12% → −$0.8M) | Randomised test of refusals; **first to measure** |
| Acceptance prior | `Book.accept` | `(n + 1) / 7` (≈5 offers seen) | Beta-Binomial posterior mean | Medium | Offer and response log |
| Acceptance fatigue | `fatigue` | −0.10 log-odds per increase taken | Judgement | Low | Offer and response log |
| Reliability prior strength | `n0` | 20 past loans of evidence | Judgement | Low | Fit to repayment histories |
| Capital weights | `K` | 8% / 12% / 20% by bucket | Riskier exposure uses more capital | Medium | Risk / finance policy |
| Capital budget | `budget` | $250,000 | Chosen so the limit binds | Sets λ* | Risk appetite statement |
| Discount rate | `disc` | 19% a year | Business rule (given) | Low | Finance (cost of capital) |
| Planning horizon, cycle, cap | `horizon`, `cycle`, `max_k` | 365 days, 60 days, 6 increases | Eligibility rule | — | Business rule |

## Macro path (Kenya, 2023)

| Input | Value | Source |
|---|---|---|
| CPI inflation | monthly, 9.0% (Jan) to 6.6% (Dec) | KNBS (2023) |
| Central bank rate | 8.75%, raised to 9.50% (Mar), 10.50% (Jun), 12.50% (Dec) | CBK Monetary Policy Committee decisions (2023) |
| Unemployment | 5.7%, flat | Assumed baseline; affects scenarios only |
| Macro effect sizes | default multiplier and acceptance shift per pp | **Illustrative**, set for scenario tests; direction consistent with the 2023 rise in banking-sector NPLs as rates rose |

Scenarios: `base`; `adverse` (+4pp inflation, +3pp rate, +2pp unemployment); `benign` (−2, −2, −1).

## Modelling assumptions

- Customers interact only through the capital budget, which is what makes them independent at a fixed λ and lets the book be solved in chunks.
- Default and churn are absorbing within the year; after 31 December a customer is valued at six more cycles of margin less expected loss.
- Acceptance is estimated from the same year's increase counts it is evaluated on (a retrospective replay). In production it must be estimated from the **previous** period.

Sensitivities above are NPV changes on the reference book; see the model card for how they were produced.
