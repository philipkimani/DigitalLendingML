# Macro Scenarios: Base, Adverse and Benign

What the base case and the three scenarios in the [report](../report.md) mean, in plain language, and how the economy reaches the model.

## 1. The base case

The **base case** is the central story: the model run with all its assumptions as they stand, including the economy as it actually was in Kenya in 2023, month by month.

| Input | 2023 path | Source |
|---|---|---|
| Inflation (CPI) | about 9% in January, falling to 6.6% in December | KNBS, verified |
| Central bank rate | 8.75% → 9.50% (March) → 10.50% (June) → 12.50% (December) | CBK, verified |
| Unemployment | 5.7%, flat | Assumption, not verified |

Every headline number in the report (portfolio NPV, the policy table, λ*) is a base-case result. It answers: *given what actually happened to the economy in 2023, what was the best increase policy?*

## 2. Why have scenarios?

A lending policy should not only work in the one economy it happened to be tested in. Scenarios are **"what if?" versions of 2023**: the economy is shifted up or down, and everything else stays the same. They show:
- how sensitive the results are to the economy;
- whether the policy still makes sense if conditions turn out differently.

## 3. The three scenarios

Each scenario shifts **all twelve months** of the 2023 path by a fixed amount, so the shape of the year stays the same, just higher or lower.

| Scenario | The story | Shift to every month |
|---|---|---|
| **Base** | 2023 as it happened | none |
| **Adverse** | A tougher economy: prices rising faster, money more expensive, more people out of work | inflation +4 points, central bank rate +3 points, unemployment +2 points |
| **Benign** | A kinder economy: calmer prices, cheaper money, more jobs | inflation −2, central bank rate −2, unemployment −1 |

## 4. How the economy reaches the model

The economy affects the model through two channels.

### Channel 1: default risk (the macro multiplier M)

Every customer's default probability is multiplied by

**M = exp(0.06 × Δ central bank rate + 0.10 × Δ unemployment + 0.02 × Δ inflation)**

where Δ means "points above the base level".

| Scenario | Calculation | M | Effect on default risk |
|---|---|---|---|
| Adverse | exp(0.06 × 3 + 0.10 × 2 + 0.02 × 4) = exp(0.46) | **1.58** | about **58% more likely** |
| Benign | exp(0.06 × (−2) + 0.10 × (−1) + 0.02 × (−2)) = exp(−0.26) | **0.77** | about **23% less likely** |

**Example:** a near-prime customer defaults with 2.5% probability per 60-day cycle in the base case. In the adverse scenario that becomes 2.5% × 1.58 ≈ **4.0%**, so annual default risk rises from about 14% to about 22%.

**Why exp?** It keeps the multiplier positive, and turns "points above normal" into a percentage change in risk. Each extra point on the central bank rate adds about 6% to default risk.

### Channel 2: demand for increases (acceptance)

Each customer's chance of accepting an offer shifts on the log-odds scale by

**0.05 × Δ inflation − 0.04 × Δ central bank rate + 0.03 × Δ unemployment**

| Scenario | Calculation | Shift | Effect on demand |
|---|---|---|---|
| Adverse | 0.05 × 4 − 0.04 × 3 + 0.03 × 2 | **+0.14** | slightly **more** demand |
| Benign | 0.05 × (−2) − 0.04 × (−2) + 0.03 × (−1) | **−0.05** | slightly **less** demand |

**The intuition:** higher prices and job losses push people to want more credit; higher interest rates make credit less attractive. In the adverse scenario the first effect wins. So **a tougher economy brings more demand from the very customers who have become riskier**, which is exactly when a good policy matters most.

## 5. What happens in each scenario

The policy is **re-optimised** for each scenario. The model asks: *if this were the economy, what would the best policy be?* Then it runs the Monte Carlo simulation in that world.

| Scenario | NPV mean | Increases | Default rate | Capital price λ |
|---|---|---|---|---|
| Base (2023 path) | $14.79M | 13,402 | 13.4% | 0.62 |
| Adverse | $8.26M | 11,325 | 19.8% | 0 |
| Benign | $17.67M | 14,120 | 10.7% | 0.91 |
| Base policy run in the adverse world | $8.25M | 13,303 | 19.9% | — |

| Scenario | How the policy responds | Capital (λ) | NPV |
|---|---|---|---|
| **Adverse** | Becomes much more cautious by itself and grants fewer increases | Does not use the full budget, so λ falls to **zero**: capital stops being the bottleneck and risk takes over | Falls a lot, because defaults are much higher whatever the policy |
| **Benign** | Wants to grant more | Capital becomes the bottleneck, so λ **rises** to 0.91: each extra dollar of capital is worth more | Rises |

**The lesson:** in bad times the constraint is risk; in good times the constraint is capital. That is useful for treasury and the funding partner: extra capital allocation is worth most when conditions are good.

## 6. The fourth row: the robustness test

The table's fourth row, **"Base policy run in the adverse world"**, is probably the most useful one for a lender.

**The real-world problem:** nobody knows which economy is coming. The policy is set for the economy expected (the base case), and then the economy turns out worse.

**What the row does:** it takes the **base-case policy, without re-optimising it**, and runs it in the adverse world.

**The question it answers:** *after planning for a normal year and getting a bad one, how much worse off is the lender than if it had planned for the bad year?*

**The answer is "almost nothing":** $8.25M against $8.26M, about 0.1% less NPV than the policy built for the adverse world.

**In plain words:** the policy's rules (favour prime customers and small loans, avoid subprime) are sensible in any economy. What should change with the economy is **how much capital to allocate**, not the rules themselves.

## 7. In 30 seconds

The base case uses Kenya's actual 2023 inflation and central bank rate. It is then stressed: an adverse scenario with inflation 4 points higher, rates 3 points higher and unemployment 2 points higher, and a benign one going the other way. In the adverse case default risk rises by about 58%, the policy tightens on its own, and capital stops being the constraint. The key test runs the base policy in the adverse world without re-optimising: it loses almost nothing, so the rules are robust and the economy mainly changes how much capital to allocate.

## 8. Caveats to know

- **The size of the macro effects is an assumption.** The 0.06, 0.10 and 0.02 (and the acceptance coefficients) have directions from the literature but chosen magnitudes. The scenarios show the *pattern* of response, not a forecast. Estimating them properly needs several years of data on defaults, uptake and the economy.
- **The shifts are constant through the year.** A real downturn builds gradually and hits some groups (for example, sectors or regions) harder than others.
- **Defaults are independent within a scenario.** Even the adverse case understates how badly a correlated shock could hit a portfolio. The fix is a shared economic shock per simulated path (see [note 10](10-monte-carlo-simulation.md)).
- **Unemployment is an assumed baseline (5.7%).** It does not affect the base case, because it stays flat there, but it does feed the adverse and benign shifts.

## 9. Self-test

1. **What makes the base case "base"?** It uses the actual 2023 economic path and all the central assumptions.
2. **Why shift every month by the same amount?** To keep the shape of the year, so the only difference from the base case is the level of the economy.
3. **By how much does adverse raise default risk?** About 58% (multiplier 1.58).
4. **Why does demand rise slightly in the adverse case?** Inflation and unemployment push people towards credit more than higher rates push them away.
5. **Why does λ fall to zero in the adverse case?** The policy becomes so cautious that it does not use the full capital budget, so capital is no longer scarce.
6. **What does the fourth row show?** That a policy built for a normal year still performs almost as well in a bad year: the rules are robust.
