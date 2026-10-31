# Markov Decision Processes

How the MDP, the capital constraint, simulation and the weakly coupled structure fit together, and how each idea maps to the model.

**The central idea:** decide which customers should receive limit increases over time to maximise expected profit, while the whole portfolio stays within a $250,000 capital budget.

## 1. What is a Markov decision process?

A **Markov decision process (MDP)** is a framework for making decisions over time when the outcome of each decision is uncertain.

In the lending model, a decision is not just "give this customer an increase or not". It changes the customer's future risk, repayments, borrowing behaviour and profitability, so it has to be judged by its consequences over time.

### The five components

| Component | General meaning | In this model |
|---|---|---|
| **State** | What is known about the customer now | (r, k, h): risk bucket, increases granted so far this year, eligibility windows passed without an increase |
| **Actions** | The choices available | Offer an increase, or hold |
| **Reward** | Expected profit from the action | Base margin plus the $40 fee (net of early-repayment rebates), minus expected default loss (PD × LGD × limit) |
| **Transition probabilities** | Chances of moving to each next state | The bucket can stay or move (prime, near-prime, subprime); the customer can also default or churn. Separate transition matrices for hold and grant |
| **Horizon and discounting** | How far ahead, and how future value is weighted | Up to 7 sixty-day windows in 2023, plus a terminal value for six more cycles; discounted at 19% a year |

### The Markov property

**Given the current state and action, the distribution of the next state does not depend on any earlier history.** That only holds if the state contains all the history that matters.

**Example:** default risk rises with each increase granted (the leverage effect, ×(1 + 0.10k)). So the number of increases, k, has to be in the state. If it were not, two customers in the same bucket but with different numbers of increases would wrongly be treated as having the same risk.

## 2. What is a policy?

A **policy** is the rule that says which action to take in every possible state. Solving the MDP means finding the best policy.

**Illustrative** (not the model's exact output):

| Customer state | Decision |
|---|---|
| Prime, no previous increase | Offer |
| Prime, several previous increases | Consider, allowing for fatigue and capital |
| Near-prime, low exposure | Offer only if the adjusted value is positive |
| Subprime | Hold |
| Defaulted or churned | No further offers |

**The model's actual pattern** (share offered at the first window, from the [report](../report.md)):

| Bucket | Up to $1.5k | $1.5k–2.5k | $2.5k–3.5k | Above $3.5k |
|---|---|---|---|---|
| Prime | 100% | 90% | 45% | 8% |
| Near-prime | 36% | 0% | 0% | 0% |
| Subprime | 10% | 0% | 0% | 0% |

**The key point:** the policy is not simply "offer to prime customers". It depends on the state, the timing, expected future outcomes and the capital price, which is why loan size matters as much as bucket.

## 3. Why "weakly coupled"?

The portfolio has 30,000 customers, and each has their own decision process:
- repayment outcomes depend on their own risk state;
- acceptance depends on their own propensity;
- their future state depends on their own actions and outcomes;
- their expected NPV can be computed from their own model.

If customers were completely independent, each could be optimised separately and the results added up.

**But there is one shared restriction:** total capital across the portfolio cannot exceed $250,000. That single constraint links otherwise separate problems.

A **weakly coupled MDP** is exactly this: many individual decision processes that interact only through a small number of shared resource constraints. It avoids building one enormous joint MDP whose state would have to describe every customer at once.

```
              Shared capital budget: $250,000
             /            |                 \
     Customer 1 MDP   Customer 2 MDP  ...  Customer N MDP
             \            |                 /
          Portfolio check: add up capital used, compare with budget
```

**Why the joint MDP is impossible:** with 147 states per customer, a joint state for 30,000 customers would have 147<sup>30,000</sup> combinations. The weakly coupled structure is what makes the problem solvable at all.

## 4. How the Lagrangian makes it tractable

The shared capital constraint is the hard part. The model puts a **price** on capital, the shadow price λ:

**Adjusted value = Expected NPV − λ × Capital used**

For a **fixed** λ, each customer's adjusted problem stands alone and is solved by backward induction. Then:
- add up capital across the portfolio;
- too much? raise λ, making capital more expensive;
- too little? lower λ, letting more profitable increases through;
- repeat until capital fits the budget (bisection).

## 5. What λ* ≈ 0.62 means

The star marks the **selected** value of λ.

| Report figure | Interpretation |
|---|---|
| Capital budget: $250,000 | The maximum intended allocation |
| λ* ≈ 0.62 | The selected price on capital; one extra dollar of budget would add about $0.62 of NPV at the margin |
| Capital used: $249,999.54 | Average capital used by the selected policy, on the simulated paths used to report results |
| Unused: under $1 | The gap between the budget and the reported use |

**The under-$1 gap does not mean the model is accurate to the dollar.** It reflects the bisection's precision (14 halvings of the range from 0 to 5) and how capital is measured.

**Average vs every path.** The constraint is on **average** capital across simulated paths. It does not guarantee every individual path stays under $250,000; some may exceed it while the average stays within. A real lender would have to specify which applies:
- **expected capital** (the average), which is what the model constrains;
- **capital on every path**, a much stricter requirement;
- a **risk measure**, for example capital at the 95th percentile of paths.

These are different constraints, and they give different policies.

## 6. Tuning and reporting on the same paths

The simulation is random (acceptance, repayment, default, churn), so the capital a policy uses varies across paths.

Here λ is chosen by checking capital on a set of 100 simulated paths, and results are reported on **the same** paths. That is **in-sample**: the policy is evaluated on the data used to tune it, so the reported capital fits the budget more precisely than it would on fresh paths.

**A stronger evaluation would use:**
1. **Calibration paths:** to find λ and the policy.
2. **Validation paths:** independently generated, to test the chosen policy.
3. **Stress scenarios:** adverse economics, and changes to default, uptake and churn assumptions.
4. **Capital checks:** the average, the spread across paths, and the share of paths over budget.

**Evidence on the size of the gap:** an earlier version of the model chose λ on 16 paths and reported on 100 different paths. That version came out about 0.4% over budget ($250,976). It was effectively an out-of-sample test, and it suggests the out-of-sample gap is small, around half a percent either way. A proper validation on fresh paths would confirm it.

**In short:** λ was tuned on the same simulated paths the results are reported on, so the near-exact fit to the budget is in-sample; expect a gap of about 0.4% on fresh paths. In production, tune on calibration paths, validate on independent ones, report the share of paths over budget, and agree with the funding partner whether the limit applies on average or at a high percentile.

## 7. Why the cost grows linearly with customers

Doubling the portfolio from 30,000 to 60,000 customers, with states, actions and periods per customer fixed, doubles the number of independent customer problems. The work is roughly

**O(N × T × S × A)**

| Symbol | Meaning | In this model |
|---|---|---|
| N | Number of customers | 30,000 |
| T | Decision periods | up to 7 windows |
| S | States per customer | 3 buckets × 8 × 8 values of (k, h) |
| A | Actions | 2 |

With T, S and A fixed, that is **O(N)**: linear in the number of customers. That is why the approach can scale to millions without building a joint MDP.

**The qualification:** total runtime also depends on the number of λ-search iterations, Monte Carlo paths and transition calculations. "Linear" is accurate for the per-customer optimisation step with fixed model dimensions. It does not mean the whole production system's runtime grows exactly linearly. In the reference analysis, the λ search with 100 paths per step is the slowest part.

## 8. In 30 seconds

Each customer is an MDP: their risk bucket and lending history define the state, and each 60-day window is a choice between offering and holding. Customers are optimised individually, but their decisions are weakly coupled by the shared $250,000 capital budget. Lagrangian relaxation puts a shadow price on capital, each customer's problem is solved by backward induction, and λ is adjusted by bisection until average capital fits the budget. Because the customer problems separate once λ is fixed, the method scales linearly with the size of the book.

**The key takeaway:** the MDP decides what is best for each customer over time; the Lagrangian coordinates those decisions around a shared capital budget; simulation evaluates the uncertain portfolio outcomes. The capital result is strongest when it is also confirmed on independent paths.

## 9. Self-test

1. **Name the five components of an MDP.** State, actions, reward, transition probabilities, horizon and discounting.
2. **Why must k be in the state?** Default risk depends on the number of increases, so without k the Markov property would fail.
3. **What is a policy?** A rule giving the best action in every possible state.
4. **What makes the MDP "weakly coupled"?** Independent customer problems linked only by the shared capital budget.
5. **Why not build one joint MDP?** Its state space would have 147<sup>30,000</sup> combinations.
6. **What does λ* = 0.62 mean?** One more dollar of capital budget adds about 62 cents of NPV at the margin.
7. **Is the budget guaranteed on every simulated path?** No, only on average across paths.
8. **What is the in-sample concern?** λ was tuned and reported on the same paths, so the fit to the budget is optimistic; validate on fresh paths.
9. **Why is the cost linear in N?** Once λ is fixed, each customer is solved independently with a fixed-size state space.

## Related notes

- [08 The optimisation model](08-the-optimisation-model.md): the Bellman equations term by term, with worked numbers
- [09 Lagrangian, backward induction and Beta-Binomial](09-lagrangian-backward-induction-beta-binomial.md): the derivations
- [10 Monte Carlo simulation](10-monte-carlo-simulation.md): how the simulated paths are generated
