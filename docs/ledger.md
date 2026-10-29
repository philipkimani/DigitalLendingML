# Ledger

Chronological record of every change to the project and its Azure environment: what was done, why, how, and the concept behind it. Newest at the bottom. No secrets, IDs or personal details in this file (the repo is public).

Status key: ✅ done · ⏳ in progress · ⏸ proposed, not done

---

## 2026-10-29

### 1. Local tooling ✅
- **What:** Installed Azure CLI 2.91.0 and its Azure ML extension (`ml` 2.45.2).
- **How:** `winget install -e --id Microsoft.AzureCLI` · `az extension add --name ml`
- **Concept:** `az` is the command line for all of Azure. Azure ML / Foundry ML features are an *extension* (`az ml ...`) installed on top: jobs, compute, models, endpoints, schedules.

### 2. Sign-in ✅
- **What:** Signed in to GitHub (repo owner account) and Azure.
- **How:** `gh auth switch -u <account>` · `az login`
- **Concept:** `az login` stores a token for your *Entra ID* user. Every `az` command then acts as you, limited by your role on the subscription (Owner, Contributor, ...).

### 3. Architecture designed ✅
- **What:** `docs/architecture.md`. Nightly batch model on Azure ML, Postgres as system of record, FastAPI decision API on Container Apps, Key Vault, Bicep, GitHub Actions with OIDC.
- **Why not an Azure ML online endpoint for the API:** it is an always-on VM billed 24/7; the API only reads precomputed decisions, so a scale-to-zero container is enough.

### 4. Phase 2 adopted (docs only) ✅
- **What:** Microsoft business layer added to the plan, in order: Entra app registrations → Power Automate approvals → Power Platform ALM → Copilot Studio agent → APIM → Power BI.
- **Why that order:** the custom connector and the approval flow authenticate through the Entra app registration, so it comes first. Everything needs the Phase 1 API.
- **Changed:** Power BI replaces the Next.js dashboard in the original design. One dashboard, not two.

### 5. Public-repo hygiene ✅
- **What:** Project notes for the AI assistant (`CLAUDE.md`) gitignored; commits use the GitHub no-reply email; Bicep takes identifiers as deploy-time parameters.
- **Why:** The repo is public. Nothing personal, no tenant/subscription/object IDs, no secrets.

### 6. Resource providers registered ✅
- **What:** Registered `Microsoft.MachineLearningServices`, `App`, `DBforPostgreSQL`, `ContainerRegistry`, `KeyVault`, `Storage`, `OperationalInsights`, `Insights`, `ManagedIdentity`, `Compute`.
- **How:** `az provider register -n <namespace>`
- **Concept:** Each Azure service is a *resource provider*. A subscription must register a provider once before it can create that type of resource. Free; creates nothing.

### 7. Region capacity checks ✅
- **What:** Confirmed Postgres `Standard_B1ms` exists in `southafricanorth`; regional vCPU quota is **4 cores** (DSv2/DSv3 families).
- **How:** `az postgres flexible-server list-skus -l southafricanorth` · `az vm list-usage -l southafricanorth`
- **Decision:** ML cluster uses `Standard_DS2_v2` (2 vCPU) × max 2 nodes = 4 cores, within quota. The first choice (DS3_v2, 4 vCPU × 2) would have exceeded it.
- **Concept:** *Quota* caps how many vCPUs a subscription can run per region and VM family. New subscriptions start low; raise it with a support request when needed.

### 8. Resource group created ✅
- **What:** `rg-digitallending-dev` in `southafricanorth`, tagged `project=DigitalLendingML`, `env=dev`. Empty, no cost.
- **How:** `az group create -n rg-digitallending-dev -l southafricanorth --tags ...`
- **Concept:** A *resource group* is the lifecycle container. Everything for this environment lives in it, and deleting the group deletes it all.

### 9. Infrastructure as code written and previewed ✅
- **What:** `infra/main.bicep` (16 resources: managed identity, Log Analytics, App Insights, Key Vault, Storage, Container Registry, Azure ML workspace + scale-to-zero cluster, Postgres Flexible with Entra-only auth, Container Apps environment + API app, two role assignments).
- **How:** `az bicep build -f infra/main.bicep` (lint) · `az deployment group what-if -g rg-digitallending-dev -f infra/main.bicep -p adminObjectId=<id> adminName=<upn>`
- **Concept:** *what-if* is a dry run. ARM compares the template with what exists and lists creates/changes/deletes without touching anything. Result: 16 to create.
- Reviewed section by section before deploying (see entry 11).

### 10. Reproducibility standard decided ✅
- **What:** How every model run is made reproducible.
- **Rule:** A run is reproducible only when all five inputs are pinned and recorded:

| What must be pinned | General industry tool | This project on Azure |
|---|---|---|
| 1. Code | Git commit SHA on every run | Git; Azure ML records the SHA on each job |
| 2. Environment (Python, libraries, OS) | Docker image + locked dependencies | Azure ML **Environment**: versioned image from a pinned dependency file |
| 3. Data | DVC, Delta Lake, versioned snapshots | Azure ML **Data assets** (`name:version`), plus `run_id` / `param_version` in Postgres |
| 4. Pipeline definition | Kubeflow, Vertex Pipelines, Airflow, Dagster, Prefect | Azure ML **pipelines** as YAML specs |
| 5. Results and lineage | **MLflow** (de-facto standard) | MLflow built into Azure ML + **model registry** (model ↔ job ↔ data ↔ code) |

  Plus two surrounding layers: **infrastructure as code** (Bicep, so the platform is reproducible) and **CI/CD** (GitHub Actions launches runs, not laptops).
- **Split:**
  - `src/lending/`: Python model logic, no Azure code, unit-testable.
  - `jobs/*.py`: thin Python entry points (read inputs → call model → write outputs → log to MLflow).
  - `azureml/*.yml`: environment, pipeline and schedule specs.
  - `.github/workflows/`: tests, then `az ml job create -f azureml/<job>.yml`.
- **Why YAML (CLI v2) for pipelines:** declarative, reviewable as a diff, runs identically locally and in CI; it is the style in Microsoft's MLOps v2 reference architecture. The Python SDK v2 (`@pipeline` functions) is the alternative, better for dynamically built pipelines.
- **Acceptance test:** from any decision's `run_id`, recover commit, environment version, data version and parameter set, re-run the job, and get the same result (Monte Carlo uses fixed seeds).

### 11. Dev environment deployed ✅
- **What:** Deployed `infra/main.bicep` to `rg-digitallending-dev`: 16 resources in 7 min 53 s.
- **How:** `az deployment group create -g rg-digitallending-dev -n main -f infra/main.bicep -p adminObjectId=<id> adminName=<upn>`
- **Verified (not just "Succeeded"):**
  - `az resource list -g rg-digitallending-dev`: 10 top-level resources (the other 6 are child resources: role assignments, database, firewall rule, cluster, Postgres admin).
  - API URL returns HTTP 200 over HTTPS (placeholder image; the request woke it from 0 replicas).
  - `az ml compute show -n cpu-cluster ...`: DS2_v2, min 0 / max 2. Idle = no cost.
  - `az postgres flexible-server show ...`: Ready, v16, B1ms, Entra auth on, password auth off.
  - `az account get-access-token --resource-type oss-rdbms`: an Entra token is what you use as the Postgres "password".
- **Concept:** ARM deployments are *idempotent*. Re-running the same template changes nothing; changing the file and re-running applies only the difference. Deployment history (portal → resource group → Deployments) keeps every run's inputs and outputs.
- **Cost control:** `az postgres flexible-server stop -g rg-digitallending-dev -n <server>` when not in use (auto-restarts after 7 days).

### 12. First commit pushed ✅
- **What:** `.gitignore`, `docs/architecture.md`, `docs/ledger.md`, `infra/main.bicep` pushed to `main` (commit `1b1a9fb`).
- **How:** scan untracked files for private terms → `git add -A` → `git commit` → `git push -u origin main`
- **Concept:** commits use the GitHub no-reply email so the author address in public history is not a personal inbox.

### 13. Organisation and scale context ✅
- **What:** The project is built for **Ruskins Digital Lending Ltd** (fictional Kenyan digital microlender): up to 1M active borrowers per week, a 3–5M customer book. Targets recorded in `docs/architecture.md` → "Organisation and scale".
- **Why:** Sizing decisions (chunking, database tier, batch window, partitioning) need a concrete load to design against. Model assumptions and reference data are unchanged.

### 14. Python environment locked with uv ✅
- **What:** `pyproject.toml` (runtime: numpy, pandas; dev: pytest, openpyxl), `.python-version` = 3.12, `uv.lock`, `.venv`.
- **How:** `uv python pin 3.12` · `uv lock` · `uv sync` · run anything with `uv run ...`
- **Concept:** reproducibility input 2 (environment). `uv.lock` pins every package, including transitive ones, to an exact version and hash; `uv sync` recreates the identical environment on any machine or CI runner. The Azure ML environment will be built from the same lock.

### 15. Model ported to `src/lending/` ✅
- **What:** The research script split into a package:

| Module | Contents |
|---|---|
| `params.py` | Frozen `Params` (all assumptions), Kenya 2023 macro scenarios |
| `book.py` | `Book`: customer arrays, built from a table, sliceable into chunks |
| `states.py` | Buckets, late rates, transition matrices; `Model` = population-level calibration shared by all chunks |
| `solver.py` | Vectorised backward induction for every customer at a given capital price λ |
| `simulate.py` | Monte Carlo lifecycle simulator, strategy summary |
| `capital.py` | Chunked capital measurement and the λ* bisection |

- **Changes from the reference:** no module-level globals (everything passed explicitly, so it is testable and two scenarios can run side by side); solve and simulation run **in chunks** so memory is bounded by chunk size, not book size. At 5M customers the reference layout would need ~8 GB for the value table and ~80 GB for simulation arrays.
- **Concept:** at a fixed λ every customer is an independent MDP (Lagrangian decomposition), so chunking the solve is *exact*, not an approximation. Capital is a sum over customers, so it can be accumulated chunk by chunk. Chunked simulation uses child seeds (`SeedSequence.spawn`), deterministic for a given (seed, chunk size).

### 16. Unit tests: 9 passing, one wrong assumption found ✅
- **How:** `uv run pytest tests/unit` (2,000-customer seeded test book, ~2 s)
- **Tests:** transition rows are probabilities · no-risk/free-capital/no-delay ⇒ always offer · higher LGD never increases offers · never offer at the yearly cap · chunked solve = whole-book solve · chunked capital deterministic · λ* within budget and one bisection step lower breaks it · unreachable budget raises.
- **Finding:** the planned check "λ = 0 and zero risk ⇒ offer everywhere" **failed** (10,116 holds out of 109,893 live states). Diagnosis: holds clustered in later windows (day 160–300) for customers with long term extensions. Hypothesis tested by setting the term extension to 0: holds dropped to 0. Cause: an accepted increase stretches the loan term, pushing later eligibility windows past year end; one lost cycle of margin (4% of the loan, ~$110 on $2,750) outweighs the $40 fee. **The model was right; the test statement was incomplete.** The test now states the full condition, and a second test pins the term-extension trade-off as intended behaviour.
- **Concept:** a failing test is evidence about either the code or the claim. Investigate before "fixing" either.

### 17. Parity with the research implementation ✅
- **What:** On the original 30,000-customer book, the port reproduces all five strategy results (NPV mean and P5–P95, increases, default rate, churn, capital) to 1e-6 and the offer-rate policy map to 1e-9, including λ* and budget use.
- **How:** `LENDING_REFERENCE_DIR=<folder> uv run pytest tests/parity` (opt-in; reference files are not in the repo; skipped otherwise). 6 min 15 s.
- **Concept:** a refactor of a model is only safe with a parity check against the trusted version on real inputs. Unit tests prove properties; parity proves sameness.

### 18. Scale finding (deferred): λ bisection at full Ruskins scale ⏸
- **Measured (1 core):** 30k customers: solve 0.4 s, 100-path simulation 5.6 s. Extrapolated to 5M: solve ~1 min, one simulation ~15 min, full bisection (16 × both) **~4.4 h**.
- **Status:** recorded for later. Ruskins scale is the target direction; the current priority is a proof of concept of model deployment to production. Likely future design: nightly solve at an approved λ, monthly λ calibration as a parallel job with maker-checker approval.

### 19. Project foundations ✅
- **What:** the setup a data-science repo needs before modelling, which was skipped at first.

| File / folder | Purpose |
|---|---|
| `README.md` | Front door: what the project is, quick start, layout, status |
| `LICENSE` | MIT: others may reuse with attribution (no license = all rights reserved) |
| `.gitattributes` | Text stored and checked out with LF; binary types marked; ends CRLF warnings on Windows |
| `.editorconfig` | Same encoding, line endings and indentation in every editor |
| `.gitignore` | Adds `.claude/` (private), data and model artifacts, notebook checkpoints |
| `.env.example` | Every setting the code reads, without values; no passwords exist because auth is Entra |
| `requirements.txt` | **Generated** from `uv.lock` (`uv export --no-dev`), runtime only, with hashes, for Azure ML and other pip-based tools |
| `data/{raw,interim,processed}`, `models/`, `notebooks/`, `reports/figures/` | Cookiecutter-data-science layout: immutable raw data, derived data, exploration and production code kept apart |

- **Concept: one source of truth for dependencies.** `pyproject.toml` declares, `uv.lock` pins, `requirements.txt` is an export. Editing the export by hand creates drift between local and cloud environments.
- **Concept: raw data is immutable.** Code reads `raw/` and writes `interim/`/`processed/`; a run can always be recreated from raw plus code.
- **Next:** code quality tooling (ruff, type checker, pre-commit with a secret scanner).

### 20. Push rejected: wrong GitHub account ✅
- **Symptom:** `git push` → `403 Permission ... denied to <other account>`. The commit was fine locally.
- **Diagnosis:** git gets its GitHub password from the GitHub CLI (`gh auth git-credential`), which hands out the token of whichever account is *active*. Several accounts are signed in on this machine and the active one had been switched elsewhere. Putting the username in the remote URL did not help: this `gh` version ignores the username and answers only for the active account.
- **Fix (repo-local, durable):** a custom git credential helper in `.git/config` that asks `gh` for this repo owner's token by name, whatever account is active:
  `git config --local credential.https://github.com.helper '!f() { test "$1" = get && echo username=<owner> && echo "password=$(gh auth token -u <owner>)"; }; f'` (preceded by an empty helper entry to reset inherited ones).
- **Concept:** git credential helpers are a chain configured per scope (system → global → repo). An empty entry clears the inherited chain; the token stays in the OS keyring, never in the repo.

### 21. Code quality tooling ✅
- **What:** dev dependencies `ruff` (lint + format), `mypy` + `pandas-stubs` (types), `pre-commit` (runs checks on every commit); config in `pyproject.toml` and `.pre-commit-config.yaml`; git hook installed with `uv run pre-commit install`.
- **Hooks on every commit:** large-file guard (500 KB), private-key detector, YAML/TOML validity, end-of-file and whitespace fixers, **gitleaks** secret scanner, ruff, ruff-format, mypy.
- **What the first run caught (before any fix):**

| Finding | Meaning | Action |
|---|---|---|
| B905 `zip()` without `strict=` in `capital.py` | If chunk and seed counts ever differed, `zip` would silently drop customers from the capital total | `strict=True`: mismatch now raises |
| B008 call in default argument (`Params()`) | Shared default object; dangerous only if mutable | Not a bug (`Params` is frozen); recorded via `extend-immutable-calls` instead of silencing the rule |
| 2 × mypy in the parity test | `Optional[str]` passed to `Path`; mixed-type dict passed as `**kwargs` | Explicit check narrows the type; dict annotated |
| Import order, `__all__` order, long line, formatting of 11 files | Style only | Auto-fixed; unit tests confirm behaviour unchanged |

- **Concept:** a linter's value is the occasional real bug (B905 here), not the style. Each suppression is recorded with its reason, never blanket-disabled.

### 22. Hook setup: slow first run, and a secret-scan false positive ✅
- **Slow install (~20 min):** PyPI downloads ran at ~35 KB/s while general internet ran at 5.6 MB/s (measured with `curl`). A second install attempt then queued behind the first one's cache lock. **Lesson:** when an install stalls, check running processes and the cache before starting another attempt.
- **Duplicate tool environments:** the upstream ruff hook installs its own copy of ruff, so pre-commit was downloading ruff a second time. **Fix:** ruff and mypy hooks run from the project environment (`repo: local`, `uv run ...`). `uv.lock` is the single source of truth for tool versions; the full hook run now takes ~9 s.
- **Secret scan:** full-history scan (`gitleaks git .`) flagged `infra/main.bicep` line 202, `kvSecretsUserRole = '4633458b-…'`. Reviewed: this is the **built-in Azure role definition id** for "Key Vault Secrets User", public and identical in every tenant; it grants nothing by itself. Recorded as a documented exception: inline `gitleaks:allow` comment (current and future commits) plus the exact finding fingerprint in `.gitleaksignore` (history). Re-scan: no leaks in history or tracked files (the only other hits were inside the gitignored `.venv`).
- **Concept:** treat a scanner finding as evidence to review, not noise to mute. Exceptions are narrow (one fingerprint) and justified in the file.
