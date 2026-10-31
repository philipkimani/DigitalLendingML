# Lagrangian, Backward Induction and Beta-Binomial

Three techniques the model rests on, explained from first principles, each followed by a check against what the model actually does.

- **Part A. The Lagrangian:** how one capital budget shared by 30,000 customers becomes 30,000 separate problems.
- **Part B. Vectorised backward induction:** how each customer's best sequence of decisions is found, fast.
- **Part C. Beta-Binomial:** where the acceptance estimate (n + 1)/7 comes from.

## Part A. The Lagrangian approach to the capital budget

### A1. The original problem

The model wants to maximise total expected NPV across 30,000 customers, but the extra limits it grants tie up capital, and the capital budget is limited to $250,000.

**maximise over policies:** V₁(π₁) + V₂(π₂) + … + V<sub>N</sub>(π<sub>N</sub>)

**subject to:** C₁(π₁) + C₂(π₂) + … + C<sub>N</sub>(π<sub>N</sub>) ≤ B = $250,000

| Symbol | Meaning |
|---|---|
| N | Number of customers (30,000) |
| π<sub>i</sub> | The lending policy for customer i: offer or hold in each situation |
| V<sub>i</sub> | Expected NPV that policy produces |
| C<sub>i</sub> | Capital that policy ties up |
| B | The capital budget |

**Why it is hard:** an increase that is profitable for one customer uses capital that might earn more elsewhere. The **portfolio** has to be optimised, not each customer in isolation, and with 30,000 customers the combinations are astronomical.

### A2. The Lagrangian

Introduce a non-negative multiplier λ (lambda) and fold the constraint into the objective:

**𝓛(π, λ) = Σ V<sub>i</sub>(π<sub>i</sub>) − λ · (Σ C<sub>i</sub>(π<sub>i</sub>) − B)**

- Σ V<sub>i</sub>: the portfolio's expected value
- Σ C<sub>i</sub> − B: how far capital use is above (positive) or below (negative) the budget
- λ: the penalty per dollar of capital used

Rearranged:

**𝓛 = Σ [ V<sub>i</sub>(π<sub>i</sub>) − λ · C<sub>i</sub>(π<sub>i</sub>) ] + λB**

**The key insight:** for a fixed λ, the λB term is a constant, so it does not affect which policy is best. What is left is a **sum of separate customer terms**. Maximising the sum means maximising each customer's own adjusted value:

**V<sub>i</sub>(π<sub>i</sub>) − λ · C<sub>i</sub>(π<sub>i</sub>)**

That is why one hard portfolio problem becomes 30,000 easy customer problems.

### A3. What λ means in practice

λ is the **shadow price of capital**: what the optimisation treats one more dollar of capital as being worth.

- **λ = 0:** capital is free. Each customer gets whatever is best for them alone.
- **Small λ:** capital is penalised lightly.
- **Large λ:** capital is penalised heavily, so the model favours actions that use little of it.

**Example: two customers competing for capital** (illustrative numbers):

| Customer | Expected NPV | Capital used | Adjusted value at λ = 0.30 |
|---|---|---|---|
| A | $100 | $200 | $100 − 0.30 × $200 = **$40** |
| B | $80 | $50 | $80 − 0.30 × $50 = **$65** |

A has the higher raw NPV, but B is better value **per unit of capital**. When capital is scarce, the model prefers B. A is not unprofitable; at this price, capital is simply better spent on B.

### A4. How λ works inside backward induction

Decisions happen every 60 days, so the model cannot just compare immediate profits. At each state it uses an **adjusted reward**:

**R<sup>λ</sup>(s, a) = R(s, a) − λ · C(s, a)**

and the backward-induction step becomes:

**V<sub>t</sub><sup>λ</sup>(s) = max over a of [ R(s, a) − λ · C(s, a) + δ · Σ<sub>s′</sub> P(s′ | s, a) · V<sub>t+1</sub><sup>λ</sup>(s′) ]**

| Symbol | Meaning |
|---|---|
| s, a | Current state; action (offer or hold) |
| R(s, a) | Expected immediate reward |
| C(s, a) | Capital attributed to the action |
| δ | Discount factor |
| P(s′ \| s, a) | Probability of moving to state s′ |
| V<sub>t+1</sub><sup>λ</sup>(s′) | Future value under the same capital price |

**An important detail: count capital correctly.** Capital held against a higher limit is a **stock** that persists. It is not a new cost each period. Charging the full amount every period would count it several times.

### A5. Finding the right λ: bisection

The right price is not known in advance, so search for it:

1. **Choose a trial λ.**
2. **Optimise the policy** with backward induction using the adjusted rewards.
3. **Measure total capital use** and compare it with $250,000.
4. **Adjust:** too much capital means raise λ; too little means lower λ.
5. **Repeat** until the policy fits closely enough.

Bisection keeps a lower and an upper bound, tests the midpoint, and keeps whichever half still contains the target. Each step halves the range.

**When it works:** when a higher price never increases capital use, which is true here, since raising λ only ever removes increases. **A catch:** with offer/hold choices, capital use jumps in steps rather than changing smoothly, so no single λ may hit the budget exactly.

### A6. Limits: the Lagrangian is not a guarantee

For a fixed λ, the problem becomes easy, but with discrete choices the resulting policy may not use exactly the budget. If it overshoots, the options are:
- adjust λ and re-solve;
- apply a final portfolio-level feasibility check (for example, trim the lowest-value increases until the budget fits);
- use a method that enforces the budget directly, such as a mixed-integer programme over a set of pre-built plans.

**The principle:** the capital constraint must be **verified** in the final policy, not assumed to hold because a shadow price was found.

### A7. Checked against the model

| Point in the explanation | What the model actually does |
|---|---|
| Capital must be counted consistently, not as a new cost every period | **Done correctly.** The charge λ·K(r)·(L<sub>k</sub> − L₀) is applied **once**, in the terminal value, to the extra limit still held at year-end. |
| Units of λ | Both NPV and capital are in **dollars**, so λ is "dollars of NPV per dollar of year-end risk-weighted capital". **λ* ≈ 0.62 means about 62 cents of NPV per extra dollar of capital budget**, at the margin and under the model's assumptions. |
| Verify the policy meets the constraint | **Verified on the reporting paths.** λ is searched with capital measured on the same 100 simulated paths used to report results, which gives $249,999 of $250,000. An earlier version measured capital on only 16 paths during the search and came out **$250,976** (0.4% over) on a separate 100-path evaluation: a useful hint of the out-of-sample gap. |
| The constraint itself | It is on **expected** capital (the average over simulated paths), not every path. Individual paths can exceed the budget. |

**In production:** measure capital exactly rather than by simulation where possible, or add a final trimming step that removes the lowest-value increases until the budget holds. Decide with the funding partner whether the budget must hold on average or with high confidence, for example in 95% of scenarios.

**In 30 seconds:** the portfolio capital constraint is handled with a Lagrangian. The shadow price λ penalises capital use in the reward. For a fixed λ, the problem splits into independent customer-level dynamic programmes, solved by backward induction. λ is then adjusted by bisection until aggregate capital matches the $250,000 budget, and the resulting policy is checked against the constraint. The model balances expected NPV against scarce capital instead of optimising each customer in isolation.

## Part B. Vectorised backward induction

### B1. Backward induction

Suppose decisions happen over three 60-day periods:
- **Period 3 (last):** what is the value of offering an increase when nothing comes after?
- **Period 2:** knowing the best decisions and outcomes in period 3, what should be done now?
- **Period 1:** knowing the best decisions in periods 2 and 3, what should be done now?

The work goes **backwards** because today's decision changes tomorrow's situation, and tomorrow's situation can only be valued once it is known how to act from there.

### B2. The formula

The value of taking action a in state s at time t:

**Q<sub>t</sub>(s, a) = R<sub>t</sub>(s, a) + δ · Σ<sub>s′</sub> P(s′ | s, a) · V<sub>t+1</sub>(s′)**

and the best value of the state:

**V<sub>t</sub>(s) = max over a of Q<sub>t</sub>(s, a)**

| Symbol | Meaning in this model |
|---|---|
| s | Customer state: risk bucket and lending history |
| a | Offer an increase, or hold |
| R<sub>t</sub>(s, a) | Expected immediate reward: margin, fee, expected loss |
| P(s′ \| s, a) | Probability of moving to state s′ |
| V<sub>t+1</sub>(s′) | Best expected value from that next state |
| δ | Discount factor |

In words: *the value of an action is what it earns now, plus the discounted, probability-weighted value of where it leads.*

### B3. A small worked example

A prime customer at the final decision. Holding is worth $100. If offered:
- immediate expected profit: $40
- 80% chance of staying prime (future value $100), 20% of slipping to near-prime (future value $50)
- discount factor 0.95

Q(offer) = 40 + 0.95 × [0.8 × 100 + 0.2 × 50]
= 40 + 0.95 × 90
= **$125.50**

$125.50 is more than $100, so **offer**.

The real model also accounts for defaults, losses, acceptance, churn and the capital price. The worked examples in [note 08](08-the-optimisation-model.md) do this with real parameters.

### B4. What "vectorised" means

**Without vectorisation**, the code loops:

```python
for customer in customers:
    for state in states:
        for action in actions:
            calculate_value(customer, state, action)
```

**With vectorisation**, every customer's numbers sit in one array and each calculation runs on the whole array at once. NumPy performs these whole-array operations in fast compiled code, which is typically tens to hundreds of times faster than a Python loop.

**The flow:**
1. **Final period:** calculate terminal values for all states of all customers.
2. **Each earlier period:** compute expected future values with array operations, then compare offer and hold for every state at once.
3. **First period:** the optimal decision for every state is now known: the **policy**.

### B5. Why it matters

- Backward induction finds the best **sequence** of decisions, not just the best single step.
- Vectorisation makes it fast enough to solve every customer exactly.
- The result is a **policy**: a lookup table from each state to the best action.
- **It does not enforce the capital budget by itself.** That is the Lagrangian's job (Part A): λ adjusts the rewards, and backward induction then optimises under that price.

### B6. Checked against the model

| Point | The model |
|---|---|
| Number of periods | Up to **7** eligibility windows per customer in 2023, not dozens |
| State | (r, k, h): bucket, increases so far, windows without one. The date follows from these (see [note 08](08-the-optimisation-model.md)) |
| Array size | 30,000 customers × 3 buckets × 8 × 8 values of (k, h) |
| Order of solving | Backward over n = k + h, from 7 down to 0, all customers at once |
| Transitions | P(s′ \| s, a) is the bucket transition matrix, one for hold and one for grant |

## Part C. Beta-Binomial: where (n + 1)/7 comes from

### C1. The question

A customer received about five increase offers and accepted three. What is the probability they accept the next one? Call it p.

The obvious answer is 3 ÷ 5 = 60%. But five observations is very little evidence. Someone who accepted 5 of 5 is not certain to accept the next one, and someone who accepted 0 of 5 is not certain to refuse. Bayesian estimation combines the evidence with a starting assumption to give more sensible numbers.

### C2. The Beta distribution

The **Beta distribution** describes uncertainty about a probability, because its values lie between 0 and 1:

**p ~ Beta(α, β)**

Think of α as "prior acceptances" and β as "prior rejections", pseudo-counts that encode the starting belief.

**Beta(1, 1)** is the **uniform prior**: every acceptance probability from 0 to 1 is equally plausible before seeing any data. It does not mean the customer actually accepted once and refused once.

### C3. Deriving the update

Bayes' rule: **posterior ∝ likelihood × prior**

- **Likelihood** of n acceptances and m rejections, for a given p: proportional to p<sup>n</sup> · (1 − p)<sup>m</sup>
- **Beta prior:** proportional to p<sup>α−1</sup> · (1 − p)<sup>β−1</sup>

Multiply them by adding the exponents:

**posterior ∝ p<sup>n+α−1</sup> · (1 − p)<sup>m+β−1</sup>**

That is exactly the shape of another Beta distribution:

**p | data ~ Beta(α + n, β + m)**

**The rule:** add the acceptances to α and the rejections to β. Because the prior and posterior are the same family, the Beta is called the **conjugate prior** for binomial data.

### C4. The posterior mean

The mean of Beta(α, β) is α ÷ (α + β). After the update:

**p̂ = (α + n) ÷ (α + β + n + m)**

**Example:** prior Beta(1, 1), five offers, three accepted, two refused:

p̂ = (1 + 3) ÷ (1 + 1 + 3 + 2) = 4 ÷ 7 = **57.1%**

It is slightly below the raw 60%, pulled towards 50% by the prior. The fewer the observations, the stronger that pull.

### C5. The whole table

Five offers, Beta(1, 1) prior. Since n + m = 5, the formula simplifies to **p̂ = (n + 1) ÷ 7**: five offers plus the two prior pseudo-counts give the 7.

| Accepted (n) | Refused | Calculation | Estimate | In the data? |
|---|---|---|---|---|
| 0 | 5 | 1 ÷ 7 | 14.3% | Yes: 13,207 customers |
| 1 | 4 | 2 ÷ 7 | 28.6% | No one |
| 2 | 3 | 3 ÷ 7 | 42.9% | No one |
| 3 | 2 | 4 ÷ 7 | 57.1% | Yes: 5,665 |
| 4 | 1 | 5 ÷ 7 | 71.4% | Yes: 5,510 |
| 5 | 0 | 6 ÷ 7 | 85.7% | Yes: 5,618 |

**Worked practice:** a customer who accepted 2 of 5 would get (1 + 2) ÷ (1 + 1 + 5) = 3 ÷ 7 = 42.9%, posterior Beta(3, 4). With a stronger Beta(2, 2) prior, it would be (2 + 2) ÷ (2 + 2 + 5) = 4 ÷ 9 = 44.4%: pulled further towards 50%.

### C6. What to remember

1. The **prior** expresses the starting uncertainty about acceptance.
2. The **likelihood** is the evidence from observed acceptances and refusals.
3. The **posterior** combines them, and the update is just adding counts.
4. The **posterior mean** is the single number used as the acceptance probability.
5. **The five-offer assumption is separate from the maths.** The Bayesian update is valid, but "about five offers each" is an assumption: the data has no offer log. Five is used because it is the maximum observed count.

### C7. Checked against the model

| Point | The model |
|---|---|
| Formula | â = (n + 1) ÷ 7 per customer, exactly as derived |
| Where it is used | As the base acceptance probability, then shifted on the log-odds scale for the month's macro conditions and for fatigue (−0.10 per increase already taken) |
| Same idea elsewhere | Repayment reliability uses Beta(20q, 20(1 − q)): a much stronger prior worth about 20 loans, centred on the customer's on-time rate. It is updated after every simulated loan, which is what moves customers between buckets ([note 06](06-risk-buckets-and-bayesian-updating.md)) |
| Weakness | The 2023 count is used both to estimate acceptance and to evaluate the 2023 policy, so it is a retrospective replay |

**In production:** log every offer, acceptance, refusal and eligibility window. Then each customer's actual number of offers replaces the assumed five, and acceptance can be modelled with real features rather than a single count.

## How the three fit together

| Technique | Role in the model |
|---|---|
| Beta-Binomial | Estimates each customer's acceptance probability (and, with a stronger prior, repayment reliability) |
| Vectorised backward induction | Finds the best offer/hold decision for every state of every customer, accounting for the future |
| Lagrangian relaxation | Prices capital so 30,000 independent decisions add up to a portfolio within budget |
| Monte Carlo simulation | Tests the resulting policy in a richer, random world (see [note 10](10-monte-carlo-simulation.md)) |
