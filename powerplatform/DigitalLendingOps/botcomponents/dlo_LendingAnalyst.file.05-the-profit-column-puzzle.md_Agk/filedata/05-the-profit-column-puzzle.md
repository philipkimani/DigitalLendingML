# The Profit Column Puzzle

What the profit column reveals, how it was worked out, why the data cannot fully settle it, and what it means for the model. A worked example of reconciling data against the problem statement.

## 1. The finding in one paragraph

The problem statement says each limit increase earns $40. The data's profit column does not match: it equals 40 × (n − 2) for every customer with increases. Each extra increase adds exactly $40, as stated, but every participating customer is $80 short. Separately, no customer in the file has exactly 1 or 2 increases, only 0 or 3–5. Together, these show that **one or two increases are unprofitable under whatever rule produced the data**. The missing 1s and 2s also mean **the data cannot tell which rule that is**.

## 2. The evidence

| Increases (n) | Customers | Profit in data | Stated: 40 × n | Gap |
|---|---|---|---|---|
| 0 | 13,207 | $0 | $0 | $0 |
| 1 | **0** | — | $40 | — |
| 2 | **0** | — | $80 | — |
| 3 | 5,665 | $40 | $120 | $80 |
| 4 | 5,510 | $80 | $160 | $80 |
| 5 | 5,618 | $120 | $200 | $80 |

**Checks run:**
- Each increase count maps to exactly one profit value across all 30,000 rows, so profit is a formula of the count, not a measured amount.
- `profit == 40 × (n − 2)` for every customer with increases, and `profit == 0` for every customer without. Verified in code on every row:

```python
(df.profit == np.where(df.n_inc > 0, 40 * (df.n_inc - 2), 0)).all()   # True
```

## 3. How it was worked out

1. **Spot the pattern.** Cross-tabulating increases against profit shows a perfect one-to-one mapping.
2. **Compare with the problem statement.** It says 40 × n; the data shows less.
3. **Measure the gap.** It is a constant $80, while each extra increase still adds $40.
4. **Check who pays it.** Customers with no increases show $0, not −$80, so the $80 only applies to participants.
5. **Test the formula on every row.** It holds without exception.
6. **Look for supporting evidence.** Customers with 1 or 2 increases would be unprofitable, and none exist.
7. **Test the limits of the evidence.** This is the key step, below.

## 4. The key point: two rules fit equally well

The formula is only observed at n = 0 and n = 3, 4, 5. Two different business rules produce exactly those values:

| Increases | Rule A: fixed $80 cost per participant (40n − 80) | Rule B: first two increases earn nothing (40 × max(0, n − 2)) |
|---|---|---|
| 0 | $0 | $0 |
| 1 | **−$40** | **$0** |
| 2 | **$0** | **$0** |
| 3 | $40 | $40 |
| 4 | $80 | $80 |
| 5 | $120 | $120 |

**They only disagree at 1 and 2 increases, exactly the counts missing from the data.** No analysis of this file can distinguish them.

**What each would mean for the business:**

| | Rule A: fixed cost | Rule B: first two do not pay |
|---|---|---|
| Plausible cause | A one-off cost per enrolled customer: onboarding, a credit bureau (CRB) or KYC check, setup or communications | The first two increases only cover their own expected losses and costs; margin starts from the third |
| Is a customer with 1 increase a loss? | Yes (−$40) | No ($0, just no gain) |
| Cost of enrolling someone who stops early | Real money lost | Effort with no return |
| In the MDP | Subtract $80 from the offer value at the first increase (k = 0) | Fee of $0 for the first two increases, $40 from the third |

**What both rules agree on:** one or two increases are never worth it. That is enough to explain why the data has no 1s or 2s, whichever rule is true.

## 5. A third reading tested: is the $80 the default-risk adjustment?

The problem statement says each increase generates an additional $40 of profit, *but default risk must be factored into the expected return*. That raises a fair question: is the $80 the default-risk deduction?

**It cannot be, for three reasons:**

1. **It is identical for every participant.** All 5,665 customers with 3 increases show exactly $40, across loans from $500 to $4,999 and on-time rates from 80% to 100%. A default-risk adjustment would be larger for big loans and poor payers.
2. **The shape is wrong.** A per-increase risk deduction would reduce what each increase adds (for example $40 − $8 = $32 per increase). In the data each increase still adds exactly $40; only a fixed amount per customer is removed.
3. **Realised defaults would hit some customers, not all.** Every participant carries the same $80 gap.

**What the sentence does establish:** the $40 is **gross**. Default risk must be deducted separately and customer by customer: expected loss = PD × LGD × exposure. That is what the model does, with larger deductions for riskier buckets and larger loans, growing with each increase through the leverage effect.

**One remaining possibility:** the dataset may apply a crude **flat risk haircut**, about two increases' worth of profit for everyone. If so, it ignores exactly the customer-level risk the problem asks to model, which supports modelling risk per customer.

## 6. Why are there no 1s and 2s at all?

The file cannot say. Possible explanations, roughly from most to least likely:

1. **Programme design.** Customers are only enrolled when expected to take at least three, or increases are granted in blocks.
2. **The historical policy already accounted for the cost.** A sensible lender would not start customers who would stop at one or two.
3. **How the synthetic data was generated.** The generator may simply draw counts from {0, 3, 4, 5}.
4. **Eligibility timing.** Less likely: the 60-day rule allows up to 5–6 windows a year, so 1 or 2 should be possible in principle.

## 7. What it means for the model

- **The decision becomes all-or-nothing.** Under either rule, the first increase only pays off if the customer goes on to take at least three. The value of offering the first increase therefore depends on the customer's whole expected future: their risk, acceptance propensity and how many windows remain in the year.
- **Late-year starts are less attractive.** A customer whose first window falls late in the year may not have time for three increases, so the model should be less willing to start them.
- **Acceptance propensity matters more.** A customer likely to decline later offers is a poor choice to start, even if they are low risk.
- **Backward induction handles this automatically**, provided the rule is built into the rewards. It needs no special case: the cost or zero fee at the early increases flows back through the Bellman equation.

**How it was used:** the base case uses the stated $40 per increase; the $80 reading is tested as a sensitivity case; the discrepancy is flagged in the report as a question for the product and finance teams.

**A correction to know:** in the reference analysis, the $80 sensitivity case subtracted the cost only when *evaluating* the policy, not inside the *optimiser*. The MDP chose its policy without knowing about the cost, so the −$0.67M figure overstates the impact; a policy re-optimised for the cost would lose less. The correct treatment is a one-off $80 charge on the first increase inside the Bellman equation. The ranking against the historical policy holds either way.

## 8. In 30 seconds

The profit column does not match the stated terms. It is 40 × (n − 2), not 40 × n: each increase adds $40, but every participating customer is $80 short. And nobody has one or two increases. Under either rule that fits the data, a fixed $80 cost or the first two increases earning nothing, one or two increases are never worth it, which explains the gap. Because the 1s and 2s are missing, the data cannot say which rule it is. So the base case uses the stated $40, the alternative is tested, and the question goes back to the business, because the two rules lead to different enrolment decisions.

**Which rule is more likely?** A fixed cost, because a per-customer charge for credit checks or onboarding is common. It should still be confirmed with the product and finance teams rather than assumed.

## 9. The general lesson

> Reconcile every number in the data against the problem statement. When they disagree, find the simplest formula that explains the data exactly and test it on every row. Look for independent evidence that supports it, then **check what the data cannot distinguish**. Use the stated version for the base case, test the alternatives, and ask.
