# Raising Profit and Lowering Defaults: Five Levers

What each of the five suggestions in Q5 of the [report](../report.md) actually rests on, and what was and was not tested.

**The honest split:** two of the five points (nudges, step size) come from model runs in the [sensitivity analysis](12-sensitivity-analysis.md). The other three (bandits, risk-based pricing, offline RL) are **proposals**. Nothing in the analysis tests them. Even the two that were run are what-if runs on assumed parameters, not measured effects.

| # | Lever | Status | Headline number |
|---|---|---|---|
| 1 | Behavioural nudges | Model what-if (assumed κ −15%) | +$1.79M ΔNPV |
| 2 | Smaller steps | Model what-if (step 10% / 25%) | +$0.12M / −$0.17M ΔNPV |
| 3 | Bandits on uptake and churn | Proposal | none |
| 4 | Risk-based pricing | Proposal | none |
| 5 | Offline RL on logged data | Proposal, for later | none |

## 0. How the sensitivity runs work (applies to points 1 and 2)

1. **Base:** solve the unconstrained MDP with the base assumptions, then simulate it for 40 Monte Carlo paths with seed 3.
2. **For each case:** change one parameter, **re-solve** the policy for that world, then simulate it for 40 paths with the **same seed**.
3. **ΔNPV** = case mean NPV − base mean NPV.

Points to remember:
- **The policy is re-optimised.** Each Δ is "the best policy in the changed world" vs "the best policy in the base world". It is not the old policy run in a new world.
- **These runs use the unconstrained policy**, not the capital-constrained one in the headline results, so the $250k budget does not bind here.
- **Same seed = common random numbers.** Both runs draw the same random repayments, acceptances and churn, so the difference has much less noise than either NPV on its own. Even so, **no standard error or P5–P95 range was reported for any Δ**. For reference, the base unconstrained NPV is about $14.9M with a P5–P95 spread of about ±$0.23M (100-path run). Small Δs like the step-size ones should be treated as uncertain.

## 1. Behavioural nudges (+$1.79M)

**Report claim:** an incentive for early or on-time repayment (M-Pesa cashback, an on-time streak that unlocks the next step) was the biggest controllable gain tested; a 15% fall in late payments rolling to default added about $1.79M.

### What the model did
- κ is the share of late payments that roll into default. Base κ = 0.25.
- Per-cycle default probability = κ × bucket late rate × (1 + γk) × macro multiplier M.
- The nudge case sets **κ = 0.25 × 0.85 = 0.2125**. The 0.85 is 1 − 0.15: a **15% relative cut**, not 15 percentage points (that would be κ = 0.10).
- Result: **ΔNPV = +$1,786,178**, defaults **11.66%** vs about 13.4% in the other cases, about **23,341 increases**.

### Why it pays
A lower κ cuts default probability everywhere at once. Two effects follow:
1. **Direct:** fewer losses on the existing book (LGD 65% × limit).
2. **Indirect:** each increase is now safer, so the re-solved policy grants more of them (about 23.3k vs about 20.4k in the base), which earns more $40 fees and higher limits.

### Weaknesses, stated plainly
- **The 15% is a choice, not evidence.** No source supports it. It is a round, modest-looking number, chosen the same way as the other sensitivity brackets (LGD 50/80%, γ 0/0.2, churn 0/12%).
- **The cost of the incentive is not netted off.** Only κ changes, so $1.79M is a **gross** gain. Cashback is paid out of it.
- **Rough break-even:** with about 30,000 customers, $1.79M is about **$60 per customer** in present value over the year plus terminal value. A nudge programme costing much less than that per customer (in PV) would pay off *if* it achieved the 15%. This is a back-of-envelope figure; a proper version would model the incentive's cash cost in the simulator.
- **Strictly, it models the wrong lever.** An early or on-time incentive mainly changes **how often people are late** (1 − q), or how often they repay early. It does not directly change **whether a late payer goes on to default** (κ). The κ cut is a stand-in. A streak or cashback scheme would more naturally shift q upward.
- **Early repayment costs fee income.** In the model, early repayers earn only 80% of the $40 fee. A nudge that raised the early-repayment share (30%) would *reduce* fee income. The κ-only run ignores this.
- **No uncertainty band** on the $1.79M (see section 0).
- **Roughly linear:** near the base case, ΔNPV scales about linearly with the size of the κ cut, so about **$0.12M per percentage point** of relative reduction. This is an approximation; a sweep would confirm it.

### How to make it rigorous
1. Sweep the effect size: κ cut of 5%, 10%, 15%, 20%, 30%.
2. Model the incentive explicitly: raise q (or the early share) and charge the cashback as a cash outflow per qualifying repayment.
3. Report the **break-even effect size**: how large the behavioural effect must be to cover the incentive.
4. In production, measure the real effect with a **randomised pilot** (nudge vs control within bucket) before relying on it.

**In one line:** it is a what-if, not a measured effect: if a nudge cut roll-to-default by 15%, the model says about $1.8M gross. The value of the run is showing that repayment behaviour is a high-leverage place to experiment; pilot it before relying on the number.

## 2. Smaller, more frequent steps (+$0.12M at 10%, −$0.17M at 25%)

**Report claim:** 10% increases did better than 15%, and 25% did worse.

### What the model did
- The increase size is `step`: L<sub>k</sub> = L<sub>0</sub>(1 + step × k). Base step = 0.15.
- Two cases: step = 0.10 and step = 0.25.

| Case | ΔNPV | Increases | Default rate |
|---|---|---|---|
| step 10% | **+$121,537** | 24,765 | 13.49% |
| step 15% (base) | 0 | about 20.4k | about 13.45% |
| step 25% | **−$167,787** | 12,947 | 13.35% |

### Why smaller steps win in this model
- **The fee is flat.** Every accepted increase earns $40 whatever its size. A 10% step earns the same fee for two-thirds of the extra exposure, so fee income per dollar of new risk is higher.

  **What "two-thirds" means.** It is the ratio of the step sizes: 10% ÷ 15% = 2/3. A 10% step adds two-thirds as much new lending as a 15% step, but still earns the full $40. Worked example, a customer whose initial loan is $2,000:

  | Step | Extra lending (new exposure) | Fee earned | Fee per $ of new exposure |
  |---|---|---|---|
  | 10% | $2,000 × 0.10 = **$200** | $40 | $40 ÷ $200 = **20%** |
  | 15% (base) | $2,000 × 0.15 = **$300** | $40 | $40 ÷ $300 = **13.3%** |
  | 25% | $2,000 × 0.25 = **$500** | $40 | $40 ÷ $500 = **8%** |

  $200 is two-thirds of $300, yet both earn $40. Put the other way, the 10% step earns 1.5× as much fee per dollar lent (20% vs 13.3%).

  **Why "per dollar of new risk" matters.** The money at stake if the customer defaults grows with the extra lending: the model loses LGD × limit, so a bigger increase means a bigger loss. Ignoring the leverage effect, the extra expected loss from an increase is roughly proportional to its size, while the fee is not. So the fee covers the risk of a small step more comfortably than the risk of a large one. For example, at a 2.5% per-cycle default probability and 65% LGD, the extra expected loss in the first cycle is about $200 × 2.5% × 65% ≈ **$3** for the 10% step, against about **$5** for the 15% step, and both earn $40. (Rough illustration; the full model also adds the leverage effect, later cycles and churn.)

  **The catch:** the same fee for less lending is only possible because the fee is fixed per increase. If the fee were a percentage of the increase, every step size would earn the same fee per dollar, and most of this advantage would go away.
- **Loss scales with size.** Expected loss on an increase is roughly LGD × PD × (larger limit), so smaller steps mean smaller losses when a customer defaults.
- So the re-solved policy grants **more, smaller** increases (24.8k vs 12.9k for 25% steps).

### Weaknesses
- **"More frequent" was not tested.** Only the step size changed. Eligibility windows are still every 60 days (plus E days after an increase), and the cap is still k ≤ 6. The report's wording overstates what was run.
- **The gain is mostly a flat-fee artefact.** If the fee were priced as a share of the increase, much of the advantage would go away. The finding is really "flat fees favour small steps".
- **The leverage effect is counted per increase, not per dollar.** γ raises PD by 10% *per increase k*, whatever the size. That penalises many small steps relative to a few large ones. A per-exposure leverage effect could change the answer either way.
- **Acceptance does not depend on step size.** In the model, a customer is as likely to accept a 10% bump as a 25% one. In reality small bumps may be less attractive, or customers may stop bothering.
- **The size is small.** +$0.12M is under 1% of about $14.9M NPV. Without a standard error on the Δ, it cannot be said to differ clearly from zero (see section 0).

**In one line:** smaller steps win because the $40 fee is flat and losses scale with exposure. It is a modest effect, partly an artefact of the fee structure, and only size was varied, not frequency.

## 3. Learning uptake and churn directly (bandits)

**Report claim:** a contextual bandit or Thompson sampling on offer timing and size would replace the assumed effects with measured ones.

### What is currently assumed

| Effect | How it is set now | Evidence |
|---|---|---|
| Acceptance propensity | Beta-Binomial on each customer's 2023 count: â<sub>i</sub> = (n<sub>i</sub> + 1)/7 | Revealed behaviour, but assumes about 5 offers each |
| Offer fatigue | −0.10 on the logit per increase k | Assumption |
| Macro effect on acceptance | +0.05Δπ − 0.04ΔCBR + 0.03ΔU | Directions from literature, sizes assumed |
| Base churn | 2% per cycle | Assumption |
| Refusal churn | +6% if the customer wanted an increase and was refused | Assumption, and it moves NPV by **+$1.45M / −$0.80M** at 0% / 12% |

Refusal churn is the second most important assumption after LGD, and the data says nothing about it. That is the main reason to experiment.

### What a bandit is
- A **multi-armed bandit** chooses between actions ("arms") and learns which pays best while it is still choosing, balancing *exploring* (trying uncertain arms) against *exploiting* (using the best so far).
- **Contextual:** the best arm depends on the customer's context (bucket, k, loan size, macro month).
- **Thompson sampling:** keep a posterior for each arm's reward, draw one sample from each posterior, and play the arm with the highest draw. Uncertain arms sometimes draw high and get tried, so exploration happens naturally. It fits this project well, because acceptance is already modelled as Beta-Binomial: each arm's acceptance can have a Beta posterior updated with every offer.

### A concrete design
- **Arms:** {hold, offer +10%, offer +15%, offer +25%}, optionally × {offer now, wait one window}.
- **Context:** bucket, k, h, loan band, uptake band, macro month.
- **Reward:** the true reward (NPV) only arrives after several cycles. Use a short-horizon proxy: accepted, then repaid the next cycle on time, minus expected loss. Then calibrate the proxy against NPV as outcomes come in.
- **Guardrails:** randomise only inside a safe set (e.g. no large steps for subprime). Keep the capital budget as a hard constraint. Cap the share of traffic that explores.
- **Log the action probabilities** for every decision. This is essential for point 5.

### The hard part: measuring refusal churn
Measuring refusal churn means refusing some customers who would have been offered, and seeing who leaves. That is commercially costly and touches fair treatment of borrowers. Options: small randomised holdouts, or using the policy's natural near-ties (customers where Q<sub>offer</sub> ≈ Q<sub>hold</sub>) as the place to randomise, since refusing them costs least. Any design should be checked against the Central Bank of Kenya's digital credit provider rules on fair treatment.

**In one line:** uptake and refusal churn are assumed, and churn is the second biggest driver, so learn them with Thompson sampling inside a safe set, using a short-horizon reward and logging propensities so the data can later support offline RL.

## 4. Risk-based pricing

**Report claim:** price the increase fee by bucket, rather than simply refusing most near-prime customers.

### What the current policy does
The constrained policy's offer rate at the first window, by bucket and initial loan:

| Bucket | ≤$1,500 | $1,500–2,500 | $2,500–3,500 | $3,500–5,000 |
|---|---|---|---|---|
| Prime | 100% | 90% | 45% | 8% |
| Near-prime | 36% | 0% | 0% | 0% |
| Subprime | 10% | 0% | 0% | 0% |

Near-prime is about half the book, and above $1,500 it gets **no offers at all**. At $40, the fee does not cover the extra expected loss and capital cost for them.

### The idea
The policy has only two options: offer at $40 or refuse. A **third option** is to offer at a price that covers the risk. For each bucket there is a break-even fee where Q<sub>offer</sub> = Q<sub>hold</sub>. Above it, offering is worth more than refusing, so the customer who currently gets nothing (and has a refusal-churn risk) can be served profitably.

### How to test it in the existing model
1. Make the fee a per-bucket array (e.g. $40 / $60 / $90) instead of a scalar, in both the solver and the simulator.
2. Re-solve and compare ΔNPV, offer rates and defaults with the flat $40 case.
3. Search for the per-bucket fee that maximises NPV.

### Why the model would currently overstate the gain
- **No price elasticity.** Acceptance in the model does not depend on the fee. In reality a higher fee lowers take-up. That has to be added (e.g. a logit term in the fee) and then measured, which ties back to point 3.
- **Adverse selection.** Customers willing to pay more may be the riskier ones within a bucket.
- **Effective APR and regulation.** Higher fees on short loans mean high effective annual rates. Pricing changes would need checking against the Central Bank of Kenya's digital credit provider regulations and consumer-protection rules.

**In one line:** the policy can only offer at $40 or refuse, so near-prime above $1,500 gets nothing. A bucket-level fee adds a middle option, but it needs a price-elasticity estimate and a regulatory check before the gain is real.

## 5. Reinforcement learning on logged data (offline RL)

**Report claim:** worthwhile once a few cycles of offers and outcomes have been recorded; the MDP gives it a sensible starting policy and a benchmark.

### Why not now
- The 2023 data has **no outcomes**: no defaults, no losses, no churn. Those are all assumed. RL learns from rewards, so it has nothing to learn from yet.
- The MDP already works with a small state (bucket, k, h) and known (assumed) dynamics. RL earns its keep when the state is richer and the dynamics are unknown.

### What offline RL is
- **Offline (batch) RL** learns a policy from a fixed log of (state, action, reward, next state) records, without experimenting live.
- The main risk is **distribution shift**: the learned policy may favour actions the log rarely contains, where its value estimates are guesses. **Conservative** methods (CQL, BCQ, IQL) penalise or restrict such actions.

### Off-policy evaluation (OPE): the gate before deployment
Before a learned policy goes live, estimate its value from the log:
- **Inverse propensity scoring (IPS):** reweight logged rewards by π<sub>new</sub>(a|s) / π<sub>log</sub>(a|s). It needs the logged action probabilities, which is why point 3 insists on logging them.
- **Doubly robust:** combines a reward model with IPS, so the estimate is unbiased if either one is right, with lower variance.
- **Fitted Q evaluation (FQE):** fits a value function for the new policy on the log.

**Deployment rule:** deploy the new policy only if its OPE **lower confidence bound** beats the MDP policy's value. Then roll it out gradually (e.g. 10% of traffic) with a holdout.

### How the MDP helps
1. **Starting policy:** the MDP is the behaviour policy that generates the first logs, which are sensible and stay within capital.
2. **Benchmark:** any RL policy has to beat it, on OPE and then in a live A/B test.
3. **Warm start / structure:** the MDP's value function can initialise the learned Q-function, and its capital shadow price λ carries over as a cost on capital use.

### Timeline
Each cycle is about 60 days and rewards arrive late, so "a few cycles" means roughly 6–12 months of logs, ideally with bandit-style exploration (point 3) so that the log covers more than one action per state.

**In one line:** not yet, since there are no outcomes to learn from. Once the MDP and a bandit have logged a few cycles with propensities, offline RL with off-policy evaluation can try to beat the MDP, which stays as the benchmark and safe fallback.

## 6. How the five fit together

1. **Now:** deploy the MDP policy (with the capital constraint) as the safe baseline.
2. **Alongside it:** run small randomised experiments: a nudge pilot (point 1), step sizes (point 2), and fee tiers (point 4), all through the bandit framework (point 3), logging propensities.
3. **After 6–12 months:** the measured effects replace the assumptions in the MDP, and offline RL (point 5) tries to beat the updated MDP using the logs.

The common thread: **each point turns an assumption into a measurement.** The sensitivity analysis says which assumptions matter most (LGD, the repayment behaviour behind κ, refusal churn), so that is where experiments should go first.

## 7. Tighter wording for the report's claims

- **Nudges:** "If an incentive cut the share of late payments rolling to default by 15%, the model puts the gain at about $1.79M before the incentive's cost. This is an assumption to test with a pilot, not a measured effect."
- **Steps:** "Smaller 10% steps did slightly better than 15% (+$0.12M), and 25% did worse (−$0.17M), largely because the $40 fee is flat. Only step size was varied, not frequency."
- Points 3–5 are already worded as proposals, which is accurate.
