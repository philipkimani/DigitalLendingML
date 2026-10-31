# DigitalLendingML

Production deployment on Azure of a **loan limit graduation model** for digital microcredit, built for **Ruskins Digital Lending Ltd**, a fictional Kenyan lender.

At each 60-day eligibility window the model decides, per customer, whether to **offer** or **hold** a limit increase, given the customer's risk, current loan size, likelihood of accepting, and how much capital the portfolio has left. It maximises portfolio net present value (NPV) under a risk-weighted capital budget.

> **Status:** working proof of concept on Azure. A nightly job solves the policy for the whole book and publishes one decision per customer, with a reason code; an authenticated API serves them and ingests partner events. All data in this repository is synthetic, and every model parameter is a stated assumption to be replaced by estimates from logged outcomes ([docs/assumptions.md](docs/assumptions.md)).

> **Full research report:** this README summarises the model and results. The complete write-up (problem statement, data findings, method, assumptions, answers to the five questions, sensitivity, production notes and figures) is in **[docs/report.md](docs/report.md)**, and each technique is explained step by step in the **[study notes](docs/study/README.md)**.

## The model

The problem is sequential: whether to offer an increase now depends on what the best decisions will be later in the year. It is modelled as a **Markov decision process** over risk states, solved exactly for every customer, with a single **shadow price on capital** keeping the portfolio within budget, and checked in a **Monte Carlo simulation** of the year.

**Risk states.** Customers sit in three buckets by on-time repayment rate: prime (95% and above), near-prime (85–95%) and subprime (below 85%); default and churn are absorbing. Each customer's repayment reliability is a Beta distribution centred on their on-time rate (worth about 20 loans of evidence), updated after every loan, with the customer re-bucketed. Granting an increase shifts the transition matrix slightly towards the worse buckets: a larger limit means more repayment strain.

**Uptake.** Each customer's propensity to accept is the Beta-Binomial posterior mean (n + 1) / 7 from their past increases, shifted on the log-odds scale for the macro environment and for fatigue (each increase taken makes the next a little less likely).

**Decision model.** The state is (r, k, h): risk bucket, increases granted so far, windows passed without one. The date follows from the state, t = w + 60(k + h) + E·k (w the wait to the first window, E the customer's term extension). The per-cycle default probability is

  p(r, k, t) = κ · ℓ(r) · (1 + γk) · M(t)

with ℓ(r) the bucket's late-payment rate, γ the leverage effect of each increase and M(t) a macro multiplier; cash flows are discounted by δ(d) = 1.19<sup>−d/365</sup>. At each window:

- **Hold:** δ(60) · [ (1 − p)·m·L₀ − p·LGD·L<sub>k</sub> + (1 − p)(1 − c₀ − c<sub>d</sub>·a)·E V(r′, k, h + 1) ]
- **Offer:** a · δ(60 + E) · [ (1 − p′)(m·L₀ + f) − p′·LGD·L<sub>k+1</sub> + (1 − p′)(1 − c₀)·E V(r′, k + 1, h) ] + (1 − a) · Hold without the refusal penalty

where a is the acceptance probability, f the fee net of early-repayment rebates, m the base margin, c₀ baseline churn and c<sub>d</sub> the extra churn when a customer who wanted an increase is refused. After the horizon a customer is valued by six more cycles of expected margin less expected loss, so year end is not treated as the end of the relationship.

**Portfolio constraint.** maximise Σᵢ E[NPV<sub>i</sub>] subject to Σᵢ E[K(r)·(L<sub>i,k</sub> − L<sub>i,0</sub>)] ≤ C, with capital weights K of 8% / 12% / 20% by bucket. Capital is the only link between customers, so the constraint is relaxed with a **Lagrange multiplier λ**: each customer becomes an independent MDP in which extra exposure still held at year end is charged λ·K(r) per dollar. All customers are solved at once by **vectorised backward induction**, and **bisection** finds the smallest λ\* whose policy stays within budget. This is the weakly coupled MDP decomposition (Hawkins 2003; Adelman and Mersereau 2008); its cost grows linearly with the number of customers.

**Simulation.** The policy is evaluated in a simulator deliberately richer than the optimiser: customer-specific true reliability, stochastic repayment (early, on time, late, default), random acceptance, Poisson term extensions, churn and Bayesian re-bucketing. If the optimised policy still wins there, the optimiser's bucket-level simplifications are not what drives the result.

## Research results

From the research phase, on a 30,000-customer reference book replaying a year (2023, Kenya macro path), 100 simulated paths. Charts and the full discussion: [docs/report.md](docs/report.md).

| Strategy | NPV mean | NPV P5–P95 | Increases | Default rate | Churn | Risk-weighted capital |
|---|---|---|---|---|---|---|
| Historical (as observed) | $11.61M | 11.37–11.87M | 61,874 | 14.3% | 10.3% | $2.61M |
| Grant whenever eligible | $11.63M | 11.37–11.88M | 66,158 | 14.0% | 10.0% | $2.80M |
| Scorecard rule (prime and near-prime only) | $13.07M | 12.82–13.32M | 52,173 | 13.6% | 13.2% | $1.99M |
| Optimal policy, no capital limit | $14.89M | 14.66–15.10M | 20,405 | 13.5% | 20.9% | $0.48M |
| **Optimal policy with capital limit** | **$14.84M** | 14.59–15.06M | 13,401 | 13.4% | 22.6% | $0.25M |

The constrained policy raises NPV by about **$3.2M (28%)** over the historical policy, with 78% fewer increases, a tenth of the risk-weighted capital and a slightly lower default rate. The price is higher churn, the most important assumption to test before relying on the result.

**What the optimal policy looks like** (share of customers offered at their first window):

| Bucket | Loan up to $1.5k | $1.5k–2.5k | $2.5k–3.5k | Above $3.5k |
|---|---|---|---|---|
| Prime | 100% | 90% | 45% | 8% |
| Near-prime | 36% | 0% | 0% | 0% |
| Subprime | 10% | 0% | 0% | 0% |

Loan size matters as much as risk: a $40 fee cannot cover the loss from even a small rise in default probability on a large balance. Offers also become rarer as increases accumulate, since each adds leverage and lowers acceptance.

**Borrower behaviour.** Churn after a refusal matters most: with no refusal churn NPV rises by $1.45M; doubling it to 12% lowers NPV by $0.80M and the policy grants more. Acceptance propensity focuses offers on customers likely to take them. Repayment behaviour works through bucket migration: customers can earn their way into eligibility, or out of it, during the year.

**Economic conditions.**

| Scenario | NPV mean | Increases | Default rate | Capital price λ |
|---|---|---|---|---|
| Base (2023 path) | $14.79M | 13,402 | 13.4% | 0.62 |
| Adverse (CPI +4pp, policy rate +3pp, unemployment +2pp) | $8.26M | 11,325 | 19.8% | 0 |
| Benign (CPI −2pp, policy rate −2pp, unemployment −1pp) | $17.67M | 14,120 | 10.7% | 0.91 |
| Base policy run in the adverse world | $8.25M | 13,303 | 19.9% | — |

In a downturn the policy tightens by itself and the capital limit stops binding; in good conditions capital becomes the bottleneck (higher λ). The base-case policy loses only about 0.1% in the adverse world against a re-optimised one: the policy rules can stay stable while the capital budget follows the macro outlook.

**Sensitivity.** Loss given default dominates (50% adds $2.36M, 80% removes $2.33M), followed by a repayment nudge (a 15% fall in late payments rolling to default adds $1.79M) and refusal churn. In every case tested the optimised policy beat the historical one. Other levers: smaller, more frequent steps (10% beat 15%), risk-based fee pricing, and learning uptake and churn directly (contextual bandits, then reinforcement learning once offers and outcomes are logged).

**Limitations.** Default, loss, leverage, churn and macro parameters are assumed, so dollar figures are indicative; the ranking of strategies held across every sensitivity case. The replay uses the same year's uptake to estimate and evaluate. The optimiser works at bucket level (within-bucket risk lives only in the simulator). A one-year horizon creates a year-end edge effect, which a rolling horizon removes.

## Production design

The repository turns that research into a governed service:

1. **Log everything.** Partner events (disbursements, repayments, misses, offers, responses) are ingested idempotently. Each customer's model inputs are derived from the event log **as of a moment**, so any run can be rebuilt exactly.
2. **Nightly batch, not on-request solving.** A job reads the approved parameter set, solves the book, and publishes one decision per customer in a single transaction. Every decision records the parameter version and the model's git SHA.
3. **Explain every decision.** Each decision stores the two values it compared and a reason code from a counterfactual (would the customer be offered if capital were free?): `npv_positive`, `capital_limit` or `risk_return`.
4. **Governed parameters.** Parameter changes are maker-checker: proposed by one person, approved by another, enforced by the database. The capital budget (and so λ) is a business decision, not a code change.
5. **Next:** champion/challenger rollout against the current rule, monitoring (population stability, predicted versus actual default and uptake), and estimation of the assumed parameters from logged data.

## Architecture

| Concern | Azure service |
|---|---|
| Nightly decisions, experiment tracking | Azure Machine Learning with a scale-to-zero compute cluster, MLflow |
| System of record (events, state, parameters, decisions, audit) | Azure Database for PostgreSQL, Entra-only authentication |
| Decision API and event ingest | FastAPI on Azure Container Apps (scale to zero), Entra ID tokens with app roles |
| Identity | Managed identities and OIDC federation; no stored secrets |
| Infrastructure | Bicep, including Entra objects (Microsoft Graph Bicep) |
| CI/CD | GitHub Actions: unit tests, image build and rollout; migrations and database checks on a fresh PostgreSQL |

Full research report (method, results, sensitivity, figures): [docs/report.md](docs/report.md). Study notes explaining each technique from first principles: [docs/study/](docs/study/README.md). Details: [docs/architecture.md](docs/architecture.md). API reference: [docs/api.md](docs/api.md).

## Quick start

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                    # create .venv with locked dependencies
uv run pytest tests/unit   # model, data and API tests (seconds)
uv run python -m lending.synthetic --n 30000 --seed 42 --out data/raw/book.csv   # a synthetic book
```

```python
import pandas as pd
from lending import Book, Model, solve, simulate, find_lambda

book = Book.from_frame(pd.read_csv("data/raw/book.csv"))  # data contract enforced here
model = Model.calibrate(book)  # late rates and bucket transitions
lam = find_lambda(book, model)  # capital price that meets the budget
policy, values, q = solve(book, model, lam)  # q: first-window (hold, offer) values per customer and bucket
result = simulate(book, model, policy, S=100)
```

## Layout

```
src/lending/     model package: parameters, risk states, solver, simulator, decisions, data contract
api/             FastAPI decision API and event ingest, Dockerfile
jobs/            nightly job (Azure ML)
azureml/         job and environment definitions
db/              SQL migrations
infra/           Bicep: Azure environment and Entra app registration
scripts/         developer helpers
tests/           unit tests, database checks, opt-in parity tests against the research implementation
docs/            research report, study notes, architecture, API, data card, assumptions, model card, roadmap
notebooks/       exploration
```

`requirements.txt` is generated from `uv.lock` (`uv export --no-dev`) for tools that need it, such as Azure ML environments. Do not edit it by hand.

## References

- Hawkins, J. (2003). *A Lagrangian decomposition approach to weakly coupled dynamic optimization problems and its applications.* PhD thesis, MIT.
- Adelman, D. and Mersereau, A. J. (2008). Relaxations of weakly coupled stochastic dynamic programs. *Operations Research*, 56(3), 712–727.
- Central Bank of Kenya (2023). Monetary Policy Committee decisions; *Bank Supervision Annual Report 2023*.
- Kenya National Bureau of Statistics (2023). *Consumer Price Indices and Inflation Rates*, December 2023.

## License

MIT
