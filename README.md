# DigitalLendingML

Production deployment on Azure of a **loan limit graduation model** for digital microcredit, built for **Ruskins Digital Lending Ltd**, a fictional Kenyan lender.

At each 60-day eligibility window the model decides, per customer, whether to **offer** or **hold** a limit increase. It maximises portfolio net present value under a risk-weighted capital budget:

- customers move between **risk buckets** (prime, near-prime, subprime) as a Markov chain;
- each customer's decisions are a finite-horizon **Markov decision process**, solved by vectorised backward induction;
- the shared capital budget is priced with a **Lagrange multiplier λ**, which splits the portfolio into independent per-customer problems; bisection finds the λ that meets the budget;
- a **Monte Carlo simulator**, deliberately richer than the optimiser, validates the policy.

> **Status:** proof of concept in progress. Model ported and tested; Azure dev environment provisioned; end-to-end deployment next. All data is synthetic and every model parameter is a stated assumption, to be replaced by estimates from logged outcomes.

## Architecture

| Concern | Azure service |
|---|---|
| Training, nightly decisions, model registry, experiment tracking | Azure Machine Learning (Foundry) with a scale-to-zero compute cluster, MLflow |
| System of record | Azure Database for PostgreSQL (Entra-only authentication) |
| Decision API | FastAPI on Azure Container Apps (scale to zero) |
| Identity and secrets | Managed identity, Key Vault |
| Infrastructure | Bicep |

Details: [docs/architecture.md](docs/architecture.md). Every change and the reasoning behind it: [docs/ledger.md](docs/ledger.md).

## Quick start

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                    # create .venv with locked dependencies
uv run pytest tests/unit   # model property tests (~2 s)
```

```python
from lending import Book, Model, solve, simulate, find_lambda

book = Book.from_frame(df)  # columns: customer_id, loan_amount, days_since_last_loan, ontime_pct, n_increases
model = Model.calibrate(book)  # late rates and bucket transitions
lam = find_lambda(book, model)  # capital price that meets the budget
policy, values = solve(book, model, lam)
result = simulate(book, model, policy, S=100)
```

## Layout

```
src/lending/     model package
tests/           unit tests; opt-in parity tests against the research implementation
infra/           Bicep for the Azure environment
docs/            architecture and ledger
data/            raw, interim, processed (gitignored)
notebooks/       exploration
models/          local artifacts (gitignored; the registry is in Azure ML)
reports/figures/ charts
```

`requirements.txt` is generated from `uv.lock` (`uv export --no-dev`) for tools that need it, such as Azure ML environments. Do not edit it by hand.

## License

MIT
