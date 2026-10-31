# The Optimisation Model, From First Principles

A plain-language walk through the "Optimisation model" in section 2 of the [report](../report.md): where every formula comes from, what each symbol means, and worked examples with real numbers from the model.

## 1. The problem in plain words

Every 60 days, an eligible customer reaches a **window**. At each window the lender makes one choice: **offer** the customer a limit increase, or **hold** (do not offer).

That choice has consequences that ripple forward:
- An increase earns a fee now, but the customer now owes more, and owing more makes default slightly more likely, in every future cycle.
- Holding avoids that risk, but a customer who wanted an increase may leave (churn), and every future window is lost with them.
- What happens at this window changes what is possible at the next one: how many increases they have had, which risk bucket they are in, and when the next window falls.

Because today's choice changes tomorrow's situation, this is a **sequential decision problem**. One window cannot be judged in isolation. The model's job is to find, for every customer and every situation they could be in, the choice that gives the **highest total value over time**.

**An everyday analogy:** deciding whether to lend a friend more money. The lender weighs what is gained now, how likely the friend is to pay back, how much would be lost if they do not, and whether saying no damages the friendship. Lending more now also makes it harder to say no later.

## 2. Building blocks

Everything in the model is built from a few simple ideas.

### 2.1 Expected value: weighting outcomes by their chances

When an outcome is uncertain, its **expected value** is each possible result multiplied by its probability, added up.

**Example:** a $100 loan earns $8 if repaid (probability 97.5%) and loses $65 if not (probability 2.5%).

Expected value = 0.975 × $8 + 0.025 × (−$65) = $7.80 − $1.63 = **$6.17**

The model always compares choices by expected value, which is why probabilities appear everywhere.

### 2.2 Discounting: money later is worth less than money now

At 19% a year, $1 today grows to $1.19 in a year. Turned around, $1 received in a year is only worth 1 ÷ 1.19 = **$0.84** today.

For any number of days d, the growth is 1.19 raised to d/365 (the share of a year), so:

**δ(d) = 1.19<sup>−d/365</sup>** is the value today of $1 received in d days.

| Received in | δ | $100 is worth today |
|---|---|---|
| 60 days | 0.9718 | $97.18 |
| 78 days | 0.9635 | $96.35 |
| 365 days | 0.8403 | $84.03 |

The 19% is the discount rate given in the problem statement. Every cash flow in the model is multiplied by δ for the time until it arrives. That is what makes the total a **net present value (NPV)**.

### 2.3 Expected loss: the cost of default risk

The standard credit-risk formula:

**Expected loss = PD × LGD × exposure**
- **PD:** probability of default
- **LGD:** loss given default, the share of the balance lost if they default (65% here)
- **Exposure:** how much they owe

**Example:** PD 2.5%, LGD 65%, exposure $2,000. Expected loss = 0.025 × 0.65 × $2,000 = **$32.50** per cycle.

This is how the requirement that "default risk must be factored into the expected return" enters the model.

### 2.4 Where the "60" comes from

The 60 comes straight from the eligibility rule in the problem statement: a customer is eligible for an increase 60 days after the previous loan was disbursed, assuming on-time repayments.

That rule becomes a **60-day cycle**, assuming customers are repeat borrowers who take a new loan as each one is repaid:

1. A loan is disbursed. The clock starts.
2. 60 days later the customer becomes eligible again: that is a **window**, where the model decides offer or hold.
3. If an increase is granted, it extends the borrowing term by a variable number of days, so the next disbursement, and therefore the next window, comes E days later: **60 + E**.
4. If not, the next window is simply **60** days later.

**Every place the 60 appears:**

| Where | What it does |
|---|---|
| t = w + 60(k + h) + E·k | Each window already passed adds one 60-day cycle |
| w = max(0, 60 − days since last loan) | A customer whose last loan was 45 days ago waits 15 more days for their first window; anyone past 60 days is eligible on 1 January |
| δ(60), δ(60 + E) | Cash from a cycle arrives about 60 (or 60 + E) days later, so it is discounted over that time |
| Annual PD = 1 − (1 − p)<sup>6</sup> | A year holds about six 60-day cycles (365 ÷ 60 ≈ 6.1) |
| Terminal value over six cycles | "One more year" is approximated as six more cycles |
| Up to 6 increases a year | The stated cap. With 60-day cycles, six is only reachable if a customer is eligible on 1 January and has no term extensions (6 × 60 = 360 days); any extension pushes the sixth past year-end. That is also why the data shows a maximum of five |

**Example:** a customer whose last loan was 20 days before 1 January:
- first window: day 60 − 20 = **40** (about 9 February)
- if granted, with E = 18: next window at 40 + 78 = **day 118**
- if held: next window at 40 + 60 = **day 100**

**Simplifications to know:**
- The model assumes customers borrow back-to-back, with no gap between repaying and borrowing again.
- The eligibility rule assumes on-time repayments. The model lets a customer who paid late but cured stay eligible at the next window; the lateness shows up instead through a worse risk bucket. A stricter reading would skip their next window.
- The 60-day cycle also sets the per-cycle default probability, so all the risk numbers are "per 60 days".

## 3. The state: what the model needs to know

The **state** is the minimum information needed to make the decision and predict what happens next. Here it is three numbers, **(r, k, h)**:

| Symbol | Meaning | Values | Why it is needed |
|---|---|---|---|
| r | Risk bucket | prime, near-prime, subprime | Sets the default risk |
| k | Increases granted so far this year | 0–6 | Sets the current limit, the leverage effect on risk, and the cap of 6 a year |
| h | Windows passed without an increase | 0–6 | Together with k, gives the date |

**Why the date follows from the state.** Windows come every 60 days, and each increase adds the customer's term extension E. So after k increases and h holds, the next window is at

**t = w + 60(k + h) + E·k**

- **w:** days until the customer's first window (60 minus days since last loan, or 0 if already eligible)
- **60(k + h):** one 60-day cycle for every window already passed
- **E·k:** the extra days each increase added

**Example:** w = 10 days, E = 18 days, two increases granted and one hold so far.
t = 10 + 60 × 3 + 18 × 2 = 10 + 180 + 36 = **day 226**, mid-August.

Because t comes from (r, k, h), the model does not need the date as a separate state. That keeps the state small: 3 × 7 × 7 = 147 combinations per customer, small enough to solve exactly. (The code allocates an 8 × 8 grid for k and h for convenience.)

## 4. The default probability formula

**p(r, k, t) = κ · ℓ(r) · (1 + γk) · M(t)**

Built up one piece at a time:

| Piece | Meaning | Value | Running result (near-prime) |
|---|---|---|---|
| ℓ(r) | The bucket's late-payment rate per cycle (from the data: 2.6% prime, 10.0% near-prime, 17.5% subprime) | 0.100 | 10% of cycles are late |
| κ | Share of late payments that end in default | 0.25 | 0.25 × 0.100 = **2.5%** default per cycle |
| (1 + γk) | Leverage: each increase adds 10% to the risk | γ = 0.10 | After 1 increase: 2.5% × 1.1 = **2.75%** |
| M(t) | Macro multiplier for the month | about 1 on average | Rate 1 point above average: × 1.062 = **2.92%** |

**Why multiply?** Each piece scales the risk proportionally: a worse bucket, more leverage and a tougher economy each make default more likely by a factor.

**The macro multiplier:** M(t) = exp(0.06·ΔCBR + 0.10·ΔU + 0.02·Δπ), where Δ means "above the year's average". Using exp guarantees M is always positive, and turns additive shocks into multiplicative ones. One extra point on the central bank rate gives exp(0.06) ≈ 1.06, about 6% more risk.

**From per-cycle to per-year:** surviving a year means surviving six cycles, so annual PD = 1 − (1 − p)<sup>6</sup>.
- Near-prime: 1 − 0.975<sup>6</sup> = **14.1%** a year
- Prime: **3.8%**, subprime: **23.5%**

## 5. The two choices, term by term

### 5.1 Hold

**Hold = δ(60) · [ (1 − p)·m·L₀ − p·LGD·L<sub>k</sub> + (1 − p)(1 − c₀ − c<sub>d</sub>·a)·E V(r′, k, h + 1) ]**

In words: *over the next 60 days, if the customer repays the lender earns the margin; if they default the lender loses part of what they owe. If they are still a customer afterwards, the lender gets the value of their next situation. Discount all of it to today.*

| Term | Meaning |
|---|---|
| δ(60) | Everything arrives about 60 days from now, so discount it |
| (1 − p)·m·L₀ | Probability they repay × the base margin (4% of the initial loan) |
| − p·LGD·L<sub>k</sub> | Probability they default × the loss on their current limit (expected loss, section 2.3) |
| (1 − p) | They must not have defaulted to continue… |
| (1 − c₀ − c<sub>d</sub>·a) | …and must not have left. c₀ = 2% baseline churn. c<sub>d</sub> = 6% extra if they wanted an increase and were refused, weighted by a, the chance they would have wanted it |
| E V(r′, k, h + 1) | The value of where they will be next: one more hold (h + 1), same k, and a bucket r′ that may have moved. "E" means averaged over where the bucket might move |

### 5.2 Offer

**Offer = a · δ(60 + E) · [ (1 − p′)(m·L₀ + f) − p′·LGD·L<sub>k+1</sub> + (1 − p′)(1 − c₀)·E V(r′, k + 1, h) ] + (1 − a) · (Hold without the refusal penalty)**

In words: *if the lender offers, the customer accepts with probability a. If they accept, the cycle runs E days longer and the lender earns margin plus the fee, but the risk is higher and so is the balance at stake. If they decline, it is as if the lender held, except the customer does not feel refused.*

| Term | Meaning |
|---|---|
| a | Probability they accept the offer |
| δ(60 + E) | An accepted increase extends the cycle by E days, so cash arrives a little later |
| p′ | Default probability with one more increase: p × (1 + γ(k+1)) ÷ (1 + γk) |
| (m·L₀ + f) | Base margin plus the increase fee f |
| f | $40 net of early-repayment rebates: 30% repay early and keep only 80% of the fee, so f = 40 × (1 − 0.3 × 0.2) = **$37.60** |
| − p′·LGD·L<sub>k+1</sub> | Expected loss on the new, higher limit (15% of the initial loan higher) |
| (1 − c₀) | Only baseline churn: they got what they wanted |
| E V(r′, k + 1, h) | The value of the next situation, with one more increase |
| (1 − a) · Hold without penalty | If they decline, it is back to holding, but with no refusal churn because an offer was made |

### 5.3 Choosing: the Bellman principle

**V = max(Offer, Hold)**

The value of being in a state is the value of the **better** choice. This is **Bellman's principle of optimality** (Richard Bellman, 1950s): *the best plan from here is the best first step, followed by the best plan from wherever that step leads.*

**Why solve backwards (backward induction):**
- At the **last** window of the year, everything after is known: it is the terminal value (section 6). So the best choice there can be computed directly.
- Knowing the best value at the last windows gives the best choice at the second-to-last windows, and so on back to the first window.
- **Analogy:** planning a road trip backwards from the destination. With the best route from every town to the end known, choosing the best first leg is easy.

## 6. Valuing the customer after 31 December: the terminal value

Without this, the model would treat the end of 2023 as the end of the relationship. It would happily grant late-year increases, collect the fee, and ignore all the extra risk carried into 2024.

**The idea:** after year-end, assume the customer continues for six more cycles at their current limit, with no more increases.

Each future cycle earns, on average, **net = (1 − p)·m·L₀ − p·LGD·L<sub>k</sub>** (margin minus expected loss).

The chance the customer is still there for each cycle, discounted, multiplies by **s = (1 − p)(1 − c₀)·δ(60)** per cycle. So the six cycles are worth:

TV = δ(60) · net · (1 + s + s² + s³ + s⁴ + s⁵)

That bracket is a **geometric series**, which sums to (1 − s⁶) ÷ (1 − s). So:

**TV = δ(60) · net · (1 − s⁶) / (1 − s)**

**Example** (near-prime, $2,000 loan, no increases):
- net = 0.975 × $80 − 0.025 × 0.65 × $2,000 = $78.00 − $32.50 = **$45.50** per cycle
- s = 0.975 × 0.98 × 0.9718 = **0.9286**
- (1 − 0.9286⁶) ÷ (1 − 0.9286) = **5.025** (worth about five cycles, not six, after survival and discounting)
- TV = 0.9718 × $45.50 × 5.025 = **$222.20**

With one increase, the limit is $2,300 and the risk 2.75%, so net falls to $36.69 and TV to **$178.12**. **That $44 drop is the long-run cost of the extra limit**, and it is what a late-year fee has to beat.

**An assumption to know:** the base margin is earned on the **initial** loan only, and each increase earns a one-off fee. So a higher limit adds risk in every future cycle but no ongoing margin. That makes the model deliberately conservative about increases. If increased limits earn ongoing margin in reality, the model would grant more.

## 7. Worked example: one decision, start to finish

**Customer:** near-prime, initial loan $2,000, acceptance probability a = 0.57 (took 3 increases in 2023, so (3 + 1) ÷ 7). Their **last** window of the year, no increases yet. To keep it hand-checkable: the macro multiplier is 1, and their bucket does not move.

| Item | Value |
|---|---|
| p (no increase) | 2.5% |
| p′ (one increase) | 2.75% |
| L₀ → L₁ | $2,000 → $2,300 |
| E (term extension) | 10 + 20 × 2,000 ÷ 5,000 = 18 days |
| f | $37.60 |
| TV with 0 / 1 increases | $222.20 / $178.12 |

**Hold:**
- Cash this cycle: 0.975 × $80 − 0.025 × 0.65 × $2,000 = **$45.50**
- Survive and stay: 0.975 × (1 − 0.02 − 0.06 × 0.57) = 0.975 × 0.9458
- Hold = 0.9718 × [$45.50 + 0.975 × 0.9458 × $222.20] = 0.9718 × $250.41 = **$243.35**

**Offer:**
- If accepted, cash this cycle: 0.9725 × ($80 + $37.60) − 0.0275 × 0.65 × $2,300 = $114.37 − $41.11 = **$73.25**
- Accepted branch = 0.9635 × [$73.25 + 0.9725 × 0.98 × $178.12] = **$234.14**
- If declined: hold without the refusal penalty = **$250.55**
- Offer = 0.57 × $234.14 + 0.43 × $250.55 = **$241.20**

**Decision:** Hold ($243.35) beats Offer ($241.20) by **$2.15**, so **hold**.

**Why:** the fee lifts this cycle's cash from $45.50 to $73.25, but the extra limit cuts the customer's future value from $222 to $178. For a near-prime customer with a $2,000 loan, those almost cancel, and the small refusal-churn penalty is not enough to tip it.

### Contrast: a prime customer, same loan

Prime risk is much lower (p = 0.65%), so the extra limit costs little in future value ($362 → $350). Offer = **$422.40** vs Hold = **$399.85**: **offer**, by $22.54.

### How the decision changes with risk and loan size

Offer minus hold at the last window (positive = offer), same simplifications, no capital charge:

| Bucket | $1,000 | $2,000 | $3,000 | $4,500 |
|---|---|---|---|---|
| Prime | +$21.8 | +$22.5 | +$22.9 | +$22.6 |
| Near-prime | +$9.1 | −$2.1 | −$13.6 | −$31.2 |
| Subprime | −$1.9 | −$23.6 | −$45.4 | −$78.0 |

This reproduces the report's policy pattern: prime customers are offered, near-prime only on small loans, and subprime hardly ever. **Loan size matters because the fee is a flat $40, while the extra loss grows with the balance.**

## 8. The portfolio problem: sharing a limited capital budget

### The constraint

**maximise Σᵢ E[NPVᵢ] subject to Σᵢ E[K(r)·(L<sub>i,k</sub> − L<sub>i,0</sub>)] ≤ C**

In words: *maximise the total value across all customers, but the capital tied up by all the extra limits cannot exceed the budget.*

| Symbol | Meaning |
|---|---|
| Σᵢ | Add up over all 30,000 customers |
| L<sub>i,k</sub> − L<sub>i,0</sub> | Customer i's extra limit at year end |
| K(r) | Capital held per $1 of extra limit: 8% prime, 12% near-prime, 20% subprime |
| C | The capital budget, $250,000 (an allocation, not a regulatory figure; see [note 14](14-macro-data-vs-assumptions.md)) |

**Example:** a near-prime customer with one increase on a $2,000 loan has $300 of extra limit, which ties up 0.12 × $300 = **$36** of capital.

### Why this is hard, and the trick that solves it

Without the budget, each customer could be solved separately. With it, every customer's decision competes for the same pot of capital, so in principle all 30,000 decisions are tangled together.

**The trick: put a price on capital.** Instead of a hard limit, charge every customer **λ dollars of value for each dollar of capital** their extra limit ties up at year end. In the terminal value this is −λ·K(r)·(L<sub>k</sub> − L₀).

- If λ = 0, capital is free and each customer does whatever is best for them alone.
- As λ rises, capital-hungry increases (big loans, risky buckets) stop being worth it first.
- Find the λ at which total capital use just fits the budget. Each customer's choice at that price is then also the best choice under the budget.

This is called **Lagrangian relaxation**, after Joseph-Louis Lagrange's method for constrained optimisation. **Analogy:** instead of rationing office space by decree, charge each team rent per square metre and raise the rent until demand fits the building. Each team decides for itself, and the space goes to whoever values it most.

Because the price is the only link between customers, the problem **splits into 30,000 independent small MDPs**, which is why it scales linearly.

### The effect of the price, with numbers

At λ = 0.61 (close to the report's λ* ≈ 0.62):

| Customer ($2,000 loan, one increase) | Capital tied up | Charge (0.61 × capital) | Offer − hold before | After |
|---|---|---|---|---|
| Prime | 0.08 × $300 = $24 | $14.64 | +$22.5 | +$14.7 (still offer) |
| Near-prime | 0.12 × $300 = $36 | $21.96 | +$9.1 at $1,000; −$2.1 at $2,000 | +$3.4 at $1,000; −$13.6 at $2,000 |

The charge squeezes out the marginal cases first and leaves the clearly profitable ones.

### Finding λ*: bisection

1. Start with a range, λ between 0 and 5.
2. Try the middle (2.5). Solve all customers, simulate, and measure the capital used.
3. Too much capital? The price is too low, so search the upper half. Too little? Search the lower half.
4. Repeat. Each step halves the range; about 15 steps pin λ* down to roughly 0.0002.

**Result:** λ* ≈ 0.62.

**What λ* means:** the **shadow price** of capital. One more dollar of budget would add about **$0.62** of NPV. Treasury, or the funding partner, can use it directly: if extra capital costs less than 62 cents per dollar of value, expanding the allocation pays.

## 9. "Vectorised backward induction" in plain words

Instead of solving 30,000 customers one at a time in a loop, the code stores every customer's numbers in one large table (an array) and does each calculation for all of them at once. NumPy runs these whole-table operations in fast compiled code. Backward induction then takes about 50 steps (one per state combination), each step updating all 30,000 customers together.

## 10. Simplifications in the worked examples

The examples in sections 6–8 are simplified so they can be checked by hand:
- They use the **last** window, so the next state is the terminal value. At earlier windows the model uses the full continuation value from the next window.
- The **bucket does not move**. The real model averages over the transition matrix (r → r′).
- The **macro multiplier is 1**. The real model uses each month's value.

The qualitative pattern (prime offered, near-prime on small loans, subprime rarely) matches the full model's results in the report.

## 11. Self-test

1. **What does δ(60) = 0.9718 mean?** $1 received in 60 days is worth about 97 cents today at 19% a year.
2. **Why does p multiply by (1 + γk)?** Each increase adds 10% to default risk through extra debt (the leverage effect).
3. **Why is there a (1 − a) term in the offer equation?** The customer might decline. Then it is like holding, but without the refusal churn.
4. **Why does the terminal value matter?** Without it, the model would grant late-year increases for the fee and ignore the risk carried into next year.
5. **Why do larger loans get fewer offers?** The fee is a flat $40, but the extra loss on default grows with the balance.
6. **What does λ* ≈ 0.62 tell treasury?** One more dollar of capital allocation is worth about 62 cents of NPV.
7. **Why can 30,000 customers be solved independently?** The capital price is the only link between them. Once it is fixed, each customer's problem stands alone.
8. **Where does (1 − s⁶)/(1 − s) come from?** The sum of a geometric series of six survival-and-discount factors.

## 12. Symbol glossary

| Symbol | Meaning | Value |
|---|---|---|
| r, k, h | Bucket, increases so far, windows without one | state |
| t, w, E | Window date, wait to first window, term extension | days |
| p, p′ | Default probability per cycle, without and with one more increase | e.g. 2.5%, 2.75% |
| ℓ(r) | Bucket late-payment rate | 2.6% / 10.0% / 17.5% |
| κ | Late payments that default | 25% |
| γ | Leverage effect per increase | 10% |
| M(t) | Macro multiplier | around 1 |
| δ(d) | Discount factor over d days | 1.19<sup>−d/365</sup> |
| m | Base margin per cycle | 4% of L₀ |
| L₀, L<sub>k</sub> | Initial loan, limit after k increases | L<sub>k</sub> = L₀(1 + 0.15k) |
| f | Fee net of early-repayment rebate | $37.60 |
| LGD | Loss given default | 65% |
| a | Acceptance probability | (n + 1) ÷ 7 |
| c₀, c<sub>d</sub> | Baseline churn, extra churn after refusal | 2%, 6% |
| V | Value of a state (the better of offer and hold) | — |
| K(r) | Capital per $1 of extra limit | 8% / 12% / 20% |
| C | Capital budget | $250,000 |
| λ, λ* | Price of capital; the price that fits the budget | λ* ≈ 0.62 |
