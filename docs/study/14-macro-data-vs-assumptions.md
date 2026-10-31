# Macro Data vs Assumptions

A comparison of official Kenyan data (KNBS and Central Bank of Kenya publications) with the assumptions used in the [report](../report.md), plus how to describe the $250,000 capital limit correctly.

## 1. Summary

- **Confirmed exactly:** the two macro series the model actually uses, monthly CPI inflation and the central bank rate for 2023.
- **Unverified:** unemployment (5.7%). It does not affect the base case, only the scenarios.
- **Different in an instructive way:** capital. Kenyan bank regulation applies a flat charge (about 14.5% per $1 of loans), while the model uses risk-tiered charges (8% / 12% / 20%) that average about 13%.
- **Mis-labelled:** the $250,000 limit is not derived from regulation, so it should be called a capital allocation or risk-exposure constraint set by the funding partner (section 4).
- **Loose cross-check:** the assumed default rates (about 13.9% average) sit near the banking-sector gross NPL ratio (15.6% at December 2023), though the two measure different things.

## 2. What the data confirms

### CPI inflation, monthly 2023

Source: KNBS, *Consumer Price Indices and Inflation Rates for December 2023*, Table 1.

| Month | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| KNBS (%) | 9.0 | 9.2 | 9.2 | 7.9 | 8.0 | 7.9 | 7.3 | 6.7 | 6.8 | 6.9 | 6.8 | 6.6 |
| Model (%) | 9.0 | 9.2 | 9.2 | 7.9 | 8.0 | 7.9 | 7.3 | 6.7 | 6.8 | 6.9 | 6.8 | 6.6 |

**Exact match.** The year's average is 7.69%; the model centres its macro effects on 7.7%.

### Central bank rate, monthly 2023

Source: CBK Monetary Policy Committee press releases and CBR history.

| Month | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CBK (%) | 8.75 | 8.75 | 9.50 | 9.50 | 9.50 | 10.50 | 10.50 | 10.50 | 10.50 | 10.50 | 10.50 | 12.50 |
| Model (%) | 8.75 | 8.75 | 9.50 | 9.50 | 9.50 | 10.50 | 10.50 | 10.50 | 10.50 | 10.50 | 10.50 | 12.50 |

**Exact match.** The year's average is 10.125%; the model centres on 10.0%, a negligible difference.

**MPC decisions in 2023:** retained 30 Jan; raised to 9.50% on 29 Mar; retained 29 May; raised to 10.50% in late June; retained 9 Aug and 3 Oct; raised to 12.50% on 5 Dec.

**Convention to know:** the March and June hikes came at the end of the month, so most of each month was at the old rate. The model assigns the new rate to the whole month. That is a common monthly convention and makes no material difference.

**What this means:** the macro path driving the results is confirmed by primary sources, so the base-case numbers stand.

## 3. Where the assumptions differ from the data

### 3.1 Unemployment: not verified

| | Official source | Assumption |
|---|---|---|
| KNBS quarterly 2023 | not found | — |
| ILO modelled annual 2023 | not found | — |
| Value used | — | 5.7%, flat all year |

**Impact:** none on the base case. The model uses unemployment only as a deviation from 5.7%, and in the base case it stays at 5.7%, so it never moves default risk or uptake. It only matters in the adverse (+2pp) and benign (−1pp) scenarios, which are chosen shifts anyway.

**How to describe it:** "an assumed baseline of 5.7%", not a KNBS figure.

### 3.2 Capital: flat regulation vs a risk-tiered model

Source: CBK *Prudential Guidelines* (January 2013), CBK/PG/03 Capital Adequacy.

| Requirement (commercial banks) | Value |
|---|---|
| Core capital / risk-weighted assets | 8.0% (10.5% with buffer) |
| Total capital / risk-weighted assets | 12.0% (14.5% with buffer) |
| Core capital / total deposits | 8.0% |
| Capital conservation buffer | 2.5 percentage points |
| Risk weight on ordinary loans and advances | **100%** |

**Turning that into capital per $1 of lending:** 100% risk weight × 14.5% total capital ratio = **14.5 cents of capital per $1 of loans, the same for every borrower.**

| | CBK rule (bank) | Model |
|---|---|---|
| Capital per $1 of extra exposure | 14.5%, flat | 8% prime, 12% near-prime, 20% subprime |
| Book-weighted average (25 / 50 / 25 mix) | 14.5% | **13.0%** |
| Varies with borrower risk? | **No** | **Yes** |

**What this means:**
- **On average, the model's charge is close to the regulatory one** (13% vs 14.5%).
- **The structure differs.** Under the standardised rule, capital does not depend on whether a borrower is prime or subprime; default losses do that work. The model's risk-tiered charges behave like **internal economic capital**, or like the risk-sensitive approaches larger banks use, not the standardised regulatory rule.
- **Consequence for the policy:** under a flat 14.5% charge, the capital constraint would push the policy less strongly away from subprime customers. Their exclusion would rest mainly on expected losses, which in the results are already large enough to exclude most of them.

**Caveats:**
- These ratios come from the **2013** guidelines; amendments in force in 2023 were not checked.
- No separate risk weight for unsecured retail or consumer loans was found; 100% is the general treatment of loans and advances.

### 3.3 Digital credit providers: no capital rule found

Source: *Central Bank of Kenya (Digital Credit Providers) Regulations, 2022*, Legal Notice No. 46 of 2022.

- **Found:** licensing requirements (Reg. 4), a CBK licence decision within 60 days (Reg. 5(1)), publication of licensees, an annual fee and an annual compliance return, and fit-and-proper tests for owners and officers.
- **Not found:** any numerical minimum capital requirement or exposure limit.
- **Do not** apply commercial-bank capital ratios to digital credit providers automatically.

**What this means for a lending platform:** a digital lending platform often relies on **capital partners** (banks and credit investors) that supply the balance sheet and licences. Where loans sit on a bank's balance sheet, that bank's capital ratio applies to the bank, which turns it into an allocation it gives the programme. There may be no direct regulatory capital constraint on the platform itself.

### 3.4 Default levels: a loose cross-check

Source: CBK *Bank Supervision Annual Report 2023*.

| Measure | Value |
|---|---|
| Banking-sector gross NPL ratio, Dec 2022 | 13.9% |
| Banking-sector gross NPL ratio, Dec 2023 | **15.6%** |
| Quarterly 2023 values | not found |
| Assumed annual default rate by bucket | 3.8% / 14.1% / 23.6% |
| Book-weighted average (25 / 50 / 25) | **≈ 13.9%** |
| Customers defaulting in the simulation | 13.4%–14.3% |

**Why it is only a loose check:**
- The **NPL ratio** is the share of loan *value* that is non-performing, a stock measure across all bank lending.
- **The model's rate** is the share of *customers* defaulting in a year in a digital microloan book.
- Digital lending usually defaults more than bank lending, so being close to the banking NPL ratio is plausible but not a calibration.

**Supporting point:** NPLs rose through 2023 while the central bank rate rose, which matches the direction of the macro effect (higher rates, higher default risk).

## 4. Describing the $250,000 capital limit correctly

**The issue:** the model imposes a $250,000 capital limit on the loan-increase policy. That amount is not derived from any regulatory rule. It was set so the constraint would bind and the method would be visible.

**The more accurate description:** unless the amount is explicitly derived from the applicable regulatory capital rules, it is better described as a **capital allocation or risk-exposure constraint set by the funding partner**.

**Why that framing fits a platform lender:**
- The capital partner (a bank or credit investor) funds the loans and sets how much risk-weighted exposure it will allocate to the programme, based on its own capital ratio, risk appetite and return targets.
- The problem's requirement to observe regulatory capital constraints and predefined risk thresholds is met indirectly: the partner's own regulatory capital requirement is one input into the allocation it grants.
- The same optimisation method applies unchanged. Only the label and the source of the number change.

**What would make it a genuine regulatory constraint:** deriving the budget from the rules, for example: capital the partner is willing to hold against this programme ÷ (risk weight × required capital ratio). With a 100% risk weight and a 14.5% ratio, a partner willing to commit $X of capital supports about $X ÷ 0.145 of extra exposure, and the charge would be flat across buckets rather than tiered.

**What λ means under this framing:** λ* (≈ 0.62) becomes the **shadow price of partner capital**: the NPV gained from one more dollar of capital the partner allocates. That is a useful negotiating number: each extra dollar of capital allocation is worth about 62 cents of NPV to the programme.

**In 30 seconds:** the problem asks for regulatory capital constraints but gives no thresholds. Kenyan bank rules apply a flat 100% risk weight and a 14.5% total capital ratio, and the digital credit regulations set no numerical capital limit. So the $250,000 is better described as a capital allocation set by the funding partner, not a regulatory figure. The method is the same either way, and λ tells you what each extra dollar of allocation is worth.

## 5. Still missing from the data

| Missing | Why it matters | Priority |
|---|---|---|
| **Multi-year history** (e.g. 2015–2024) of CPI, central bank rate and NPLs | One year of 12 points cannot estimate how strongly macro conditions move defaults and uptake; the effect sizes stay assumptions | High |
| Digital-lending default rates, recoveries (LGD) and pricing | κ, LGD and margin are about digital credit, which bank-wide data does not capture | High |
| Digital credit provider capital or exposure rules | Settles whether any regulatory capital constraint applies to the platform | Medium |
| Current risk-weight rules (post-2013 amendments) | The 100% weight may be outdated | Medium |
| Unemployment (KNBS quarterly, ILO annual) | Only affects the scenarios | Low |
| Monthly commercial bank lending rates | Would support the 4% base margin through funding cost | Low |
| Quarterly 2023 NPL ratios | Within-year trend | Low |

## 6. Questions to check understanding

- **Where does the macro data come from?** KNBS monthly CPI and CBK MPC decisions for 2023. Both series were verified against primary sources and match exactly.
- **Is 5.7% unemployment official?** No, it is an assumed baseline. The model uses unemployment only as a deviation from that baseline, and it is flat in the base case, so the base results do not depend on it.
- **Are the capital charges regulatory?** No. Kenyan standardised rules give a flat 14.5% per dollar of loans. The tiered 8/12/20% averages 13%, so the level is similar, but it is risk-sensitive, more like internal economic capital. Production should use the partner's actual rule.
- **Is the $250,000 a regulatory limit?** No. It is best described as a capital allocation set by the funding partner, chosen so the constraint binds and the method shows.
- **Do the default rates make sense?** They average about 14% a year, close to the 15.6% banking NPL ratio at end-2023. The measures differ (value vs customers, bank vs digital), so it is a sense check, not a calibration.
