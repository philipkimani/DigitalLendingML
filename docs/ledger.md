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

### 23. Microsoft agent tooling for Claude Code ✅
- **What:** two official Microsoft plugins installed at user level (not part of the repo):
  - `azure@claude-plugins-official` (Microsoft's Azure Skills plugin): Azure skills (prepare, validate, deploy, quotas, cost, diagnostics, Foundry), plus the **Azure MCP Server** (`npx @azure/mcp`), which runs as the signed-in `az` user.
  - `microsoft-docs@microsoft-docs-marketplace` (Microsoft Learn MCP): searches and fetches current learn.microsoft.com pages and code samples.
- **Why:** check SKUs, quota, API versions and YAML schemas against live Azure and current docs before writing infra or job specs, instead of relying on memory (the DS3_v2 quota slip in entry 8 is the kind of error this catches).
- **First start:** the Azure MCP server timed out (30 s), because its first start downloads the package. Once downloaded, it starts in ~4 s. Reconnect with `/mcp` or a restart.
- **Safety:** the Azure MCP server can create and delete resources as the user. Tool approval prompts stay on; any Azure change is still proposed first.
- **Check:** a Learn search for the Azure ML CLI v2 environment/command-job YAML schema returned the official reference pages.

### 24. Agent guardrails (private `.claude/settings.json`) ✅
- **What:** project-level Claude Code settings, gitignored (local working preferences, not part of the deliverable).
  - **Ask first:** any mutating `az` command (`create`, `delete`, `update`, `set`, `assign`, `start`, `stop`, `purge`, `build`), including `az deployment group create` and `az ml job create`.
  - **Blocked outright:** `az group delete`, `git push --force` / `-f`.
  - **Allowed without asking:** `uv run pytest`, `uv run ruff check`, `uv run mypy`, and read-only `az ... show` / `list` / `what-if`.
  - **Hook:** after any file edit, `.py` files are formatted with `uv run ruff format`, so changes match the pre-commit checks before a commit.
- **Gotcha found while testing the hook:** `jq` on Windows writes CRLF line endings. The trailing `\r` broke both the `*.py` match and the file path (`os error 123`). Fixed by piping through `tr -d '\r'`.
- **Concept:** guardrails belong in configuration that the tool enforces, not in memory or good intentions. Rules are evaluated deny → ask → allow, so a deny can't be overridden by a broader allow.

### 25. Data card, assumptions log, model card (draft) ✅
- **What:** `docs/data_card.md`, `docs/assumptions.md`, `docs/model_card.md`.
- **Why:** write down the data contract and every assumption *before* generating synthetic data, so the generator is built to a spec and every number in the model has a stated source and a plan for replacing it.
- **Data card:** the five input columns with types, allowed ranges and meaning; the reference book's profile, which the generator should reproduce by default. Each numeric column is close to uniform; buckets are 25/50/25 prime/near-prime/subprime; increase counts are only 0 or 3–5. It also lists the planned Postgres tables.
- **Assumptions log:** every parameter with code name, value, source, sensitivity and how to replace it with an estimate. Loss given default and churn after a refusal matter most.
- **Model card:** purpose and out-of-scope uses, method, results, the evaluation evidence (parity and unit tests), limitations (term-extension behaviour, year-end edge, retrospective acceptance, scale) and governance.
- **Concept:** a data card is the contract between whoever produces the data and the model that reads it. A model card states what the model is for, what it was tested on, and where it should not be trusted.

### 26. Data contract, synthetic generator, exploration notebook ✅
- **Dependencies:** `pandera` (runtime: the contract runs whenever data enters the model); `matplotlib`, `ipykernel`, `nbclient` (dev only, for notebooks). Lock updated by `uv add`.
- **Data contract** `src/lending/contract.py`: a pandera schema for the five book columns (types, ranges, no nulls, unique ids) plus a whole-table rule that every risk bucket has customers. `Book.from_frame` now validates every input, so bad data fails at the door with every broken rule listed (`lazy=True`).
- **Generator** `src/lending/synthetic.py`: `generate(n, seed)` draws each field independently (the reference fields are uncorrelated), reproduces the data-card profile (25/50/25 buckets; increases 0 or 3–5) and validates its own output. CLI: `uv run python -m lending.synthetic --n 30000 --seed 42 --out data/raw/book.csv` (output is gitignored).
- **Tests** `tests/unit/test_data.py` (10 new, 19 total, all pass): same seed gives same data; profile matches; each contract rule rejects the input it targets.
- **Notebook** `notebooks/01_eda.ipynb`: generate → distributions → buckets, late rates, transition matrices → one unconstrained solve and the offer map by bucket and loan size. A markdown note explains every cell. It was executed end to end to verify it, and saved without outputs so diffs stay readable.
- **Not added:** local MLflow. Azure ML provides MLflow tracking, which the job step will use, so a local server would be a duplicate.
- **Concept:** validate at trust boundaries, not everywhere. One contract, enforced at the single entry point every dataset passes through.

### 27. Explanatory notes across the model code ✅
- **What:** a concept-level docstring at the top of each module, plus notes on each block of code. Covers `params`, `book`, `states`, `solver` (backward induction, hold/grant/offer values, terminal value), `simulate` (paths, Bayesian re-bucketing, cash flows), `capital` (shadow price, bisection) and the model tests (the economic rule each test checks).
- **Why:** the code doubles as study material; each block should say what it does and why.
- **Check that behaviour is unchanged:** the code of all 7 files was compared before and after with comments and docstrings ignored (Python AST): identical. Lint, types and all 19 tests pass.
- **Concept:** comments explain *why* and the concept behind the code; the code itself shows *how*. Comparing ASTs proves an edit was documentation-only.

### 28. PoC step 1: synthetic book registered as an Azure ML data asset ✅
- **What:** `customer-book:1`, type `uri_file`, defined in `azureml/data/customer-book.yml` and registered with
  `az ml data create -f azureml/data/customer-book.yml -g rg-digitallending-dev -w mlw-digitallending-dev`.
- **Where it lives:** the workspace's default datastore `workspaceblobstore` (a container in the workspace storage account), under `LocalUpload/<hash>/book.csv`. The asset is a named, versioned pointer to that blob; jobs will reference `azureml:customer-book:1`.
- **Reproducibility evidence:** tags record `generator`, `n`, `seed` and `md5`. Local file, the blob's stored `Content-MD5`, and a fresh rebuild from the tags all hash to the same MD5.
- **Cost:** ~750 KB of blob storage (fractions of a cent a month). No compute.
- **Gotchas:**
  - The CLI wasn't on this session's PATH. The system PATH had it, but the running process had started with a stale copy. Stopgap: reload PATH from the registry per command. Fix: restart the tool.
  - `az ml data` has no `download` command in this extension version. Verified through the storage layer instead (`az storage blob show` → `contentMd5`).
  - That check used `--auth-mode key` (storage account keys). **Production fix:** Entra auth (`--auth-mode login` with *Storage Blob Data Reader*) and shared-key access disabled on the account.
- **Concept:** datastore = connection to storage; data asset = versioned, immutable reference to data in it. New data means a new version, never an overwrite.

### 29. Session restart checks ✅
- **What:** after restarting the tool, checked that the Azure CLI works without the PATH stopgap, and whether the Azure MCP server connects.
- **How:** `az account show -o table` in a plain shell.
- **Result:** the CLI works; the stale PATH was fixed by the restart, so the stopgap is retired. The Azure MCP server timed out again on start (30 s connect timeout). Two other plugin servers timed out too, so this looks like slow startup rather than an Azure problem. Decision: use the `az` CLI and `psql` for all Azure work; the MCP server is optional.
- **Concept:** fix the cause (a process started before the install inherits an old environment), then remove the workaround so it doesn't linger.

### 30. PoC step 2: Postgres schema and least-privilege role ✅
- **What:** `db/migrations/001_init.sql` and `db/bootstrap_identity.sql`.
- **Tables:** `events` (partner `event_id` primary key: idempotent ingest), `customer_state` (same ranges as the data contract), `parameter_sets` (one column per model parameter with bounds as CHECK constraints; a maker-checker constraint requires a checker who is not the maker; at most one `active` row), `runs` (one nightly solve; at most one `published`), `decisions` (offer/hold per customer per run; every row carries `param_version` and `model_version`, and a composite foreign key makes them match the run), `audit` (written by trigger on `parameter_sets` and `runs`), `schema_migrations`.
- **Role:** `lending_app` group role holds the grants: read `customer_state` and `parameter_sets`; insert `events`; insert and update `runs`; insert `decisions`. No update or delete on events, no write on parameters, nothing on audit. The managed identity becomes a member through `pgaadauth_create_principal` + `GRANT lending_app`.
- **Why:** the rules that keep decisions trustworthy (parameter bounds, maker-checker, reproducibility, append-only events) are enforced by the database, so a bug in any client can't break them.
- **Known limit:** `events` is unpartitioned. At production volume, partition by month; that moves idempotency into a separate key table, because a partitioned table's primary key must include the partition column.
- **Concept:** a partial unique index (`ON t ((true)) WHERE status = 'active'`) enforces "at most one row in this state". Publishing a run is then a status flip in one transaction, so readers never see a half-written run.
- **Applied:**
  1. Firewall rule `dev-client` for one IP (the developer machine), so `psql` can reach the server: `az postgres flexible-server firewall-rule create -g rg-digitallending-dev --server-name <server> --name dev-client --start-ip-address <ip> --end-ip-address <ip>`. **Dev stopgap**; production uses private networking and this rule is deleted.
  2. `001_init.sql` to `lending`, then `bootstrap_identity.sql` to `postgres`, as the Entra admin. The password is a short-lived Entra token (`az account get-access-token --resource-type oss-rdbms`), set only in the shell process.
- **Verified** with `tests/db/check_001.sql` (runs in a transaction and rolls back; stops on the first failure). The database rejected: `lgd = 65`, `kappa = 0`, a negative budget, an approval with no checker, a maker approving their own set, a second active set, a second published run, a `model_version` that is not a git SHA, a decision whose versions differ from its run, an action other than offer/hold, a loan above 5,000. A repeated `event_id` was ignored. Audit rows were written by the triggers. The managed identity is in `lending_app`, has no admin attributes, and has exactly the intended table privileges (18 checked).
- **Gotcha:** on `firewall-rule` commands the az CLI takes the server as `--server-name`; `--name` there is the rule name.
- **Concept:** test the database's behaviour, not its DDL: try what must be refused and assert it is refused, inside a transaction that rolls back.

### 31. Maker-checker enforced by the database (migration 002) ✅
- **Gap found in 001:** `maker` and `checker` were client-supplied text, so any caller with write access could type another person's name as checker and approve their own parameter set. The constraint compared two strings the client controlled.
- **What:** `db/migrations/002_maker_checker.sql`. A `BEFORE INSERT OR UPDATE` trigger on `parameter_sets`:
  - sets `maker` from `session_user` (the authenticated login; `SET ROLE` can't change it) and drops any client-supplied checker;
  - new sets start as `draft` or `proposed` only;
  - parameter values are immutable after insert (a change is a new version);
  - allowed transitions: draft → proposed (maker); proposed → approved/rejected (member of `lending_checker`, not the maker; the trigger records `checker` and `checked_at`); approved → active and active → retired (`lending_checker`).
  - New group role `lending_checker`: read parameters and audit, update `status` only.
- **How:** applied with `psql ... -v ON_ERROR_STOP=1 -f db/migrations/002_maker_checker.sql` as the Entra admin.
- **Verified:** `tests/db/check_001.sql` was renamed to `tests/db/check_schema.sql` and extended. It was run before 002 and **failed** at the maker check (the gap was real), then run after 002 and passed. New rejections: a set inserted as approved or as active, the maker approving their own set, editing a value after insert. The 001 constraints are also tested with the trigger disabled inside the rolled-back transaction, to show they still back it up.
- **Concept:** never trust identity a client asserts; take it from the authenticated session. Run the test before the fix: a test that never failed hasn't proven anything.

### 32. First active parameter set, through real maker-checker ✅
- **What:** the base-case parameters (the `lending.params.Params` defaults) are now the active set in `parameter_sets`, approved by a second person.
- **Checker account:** a dev-only Entra user, created with a generated password that is stored only in the gitignored `.env` and was never printed. It was mapped into Postgres with `db/bootstrap_identity.sql`, which now takes `-v role=` so the same script serves `lending_app` (workloads) and `lending_checker` (approvers).
- **Flow:**
  1. The maker (Entra admin) inserted the set as `proposed`. The trigger recorded the maker from the login.
  2. The checker, signed in with its own token, moved it proposed → approved → active in one transaction. The trigger recorded checker and time.
  3. The audit table shows the insert by the maker and both status changes by the checker. One active set exists.
  - Honest note: the checker's commands were run by the assistant at the developer's request, using the checker's own sign-in.
- **Its version number is 21, not 1:** the rolled-back test runs used identity values, and sequences don't roll back. That's expected; version numbers are unique, not gap-free.
- **Gotchas:**
  - Device-code sign-in was blocked by Entra **security defaults** (error 530035), which treat that flow as risky. Kept security defaults on and used the browser flow instead.
  - Signing in a second account on the same machine kept silently reusing the existing Windows/browser session (even in an InPrivate window), so the checker profile kept getting the admin account. Fix: a separate `AZURE_CONFIG_DIR` for the checker, the Windows broker turned off for that profile only (`core.enable_broker_on_windows=false`), and the sign-in URL opened with `prompt=login` so Entra must ask for credentials. Always check `az account show` after a login; the exit code was 0 every time.
  - Postgres truncates role names to 63 characters, so a long guest UPN appears shortened in `maker`/`actor`. It's consistent, so comparisons hold; prefer short UPNs for human approvers.
- **Concept:** separation of duties is only real when the system can tell the two people apart. Here identity comes from Entra tokens and is recorded by the database, not typed by a client.

### 33. PoC step 3 (part 1): nightly job built and dry-run against the real database ✅
- **Dependencies:** `psycopg[binary]` (Postgres client) and `azure-identity` (Entra tokens) in a new `jobs` dependency group, so the model package itself stays dependency-light. `uv add --group jobs "psycopg[binary]" azure-identity`.
- **Input loaded:** the synthetic book, rebuilt from seed 42 and checked against the data asset's MD5, copied into `customer_state` as the Entra admin (`psql \copy ... FROM 'data/raw/book.csv' WITH (FORMAT csv, HEADER true)`): 30,000 rows. In production this table is maintained from partner events; this is a documented dev seed load.
- **Code:**
  - `src/lending/decisions.py`: `params_from_row` (a `parameter_sets` row → `Params`) and `first_window` (the policy at each customer's next window: current bucket, k = 0, h = 0).
  - `tests/unit/test_decisions.py`: the DB row round-trips to `Params` exactly (catches schema/code drift); `first_window` reads exactly the customer's own state (hand-built policies that say offer only there, and the inverse). 21 tests pass; ruff and mypy clean.
  - `jobs/nightly.py`:
    1. reads the active set and `customer_state` in a short read transaction;
    2. solves outside any transaction (calibrate → bisect λ\* → solve in chunks);
    3. writes the run, streams decisions with `COPY` and publishes in ONE transaction.

    Sign-in is an Entra token from `DefaultAzureCredential` (managed identity on Azure ML, the az CLI locally). `--dry-run` rolls step 3 back.
- **Dry run** (local, as the admin, against the real database), `uv run --group jobs python jobs/nightly.py --model-version <sha> --dry-run`, took 113 s:
  - λ\* = 0.646; capital used 249,840 of the 250,000 budget (within budget, as bisection guarantees);
  - 5,569 offers of 30,000;
  - offer rate by bucket: prime 55.5%, near-prime 8.3%, subprime 2.2%;
  - the data fingerprint MD5 equals the registered data asset's MD5, so the table holds exactly the asset's rows;
  - afterwards: 0 runs, 0 decisions, 0 run audit rows (the rollback left nothing).
- **Not covered by the dry run:** the managed identity's grants (it ran as the admin), the Azure ML environment and compute, network access from Azure, and MLflow logging. The first cloud run covers those.
- **Deferred:** Q-values and reason codes in `decisions` (they need the solver to return Q, which touches parity-checked code; needed for the API's explanations); a schedule (billable, needs approval).
- **Concept:** keep long computation outside the write transaction, and make the write transaction all-or-nothing. Readers see the old run until the commit and the full new run after it.

### 34. PoC step 3 (part 2): first nightly run on Azure ML, published ✅
- **Commits (local only, not pushed):** model, schema, job and docs; then the Azure ML config, so the recorded SHA describes everything that ran. Pre-commit checks passed (gitleaks, ruff, mypy). A scan for personal and environment identifiers in the committed files was clean.
- **Environment:** `azureml/environments/nightly.yml` (`lending-nightly:1`): Microsoft's Ubuntu 22.04 base image plus `conda.yml`, whose pip pins are generated from `uv.lock` (`jobs` + new `azureml` group: mlflow, azureml-mlflow). Local and cloud runs use the same library versions. The `azureml` group isn't installed locally. `az ml environment create -f azureml/environments/nightly.yml -g rg-digitallending-dev -w mlw-digitallending-dev`.
- **Job:** `azureml/jobs/nightly.yml`, a command job on `cpu-cluster`. `.amlignore` allows only `src/` and `jobs/` to be uploaded. The managed identity's client id and the server name are passed at submit (`--set environment_variables.AZURE_CLIENT_ID=... environment_variables.PGHOST=... inputs.model_version=$(git rev-parse HEAD)`), never committed.
- **Result:** completed about 13 minutes after submission, including the one-off image build.
  - Run published with parameter version 21, the commit SHA, λ\* 0.646057 and 5,569 offers of 30,000, identical to the local dry run.
  - The audit shows the **managed identity** inserting and publishing the run, so the `lending_app` grants are sufficient.
  - Metrics logged to MLflow (Azure ML studio → job → Metrics).
  - Cost: cents (one DS2_v2 node for minutes; the cluster scales back to 0).
- **Bug found and fixed: the data fingerprint depended on the operating system.** The same rows hashed differently locally and in the cloud. Cause: `DataFrame.to_csv` uses the OS line ending (`\r\n` on Windows, `\n` on Linux). Fixed by forcing `lineterminator="\n"`. The published run's fingerprint was computed with `\n`, so it is already the canonical value.
  - **Correction to entry 33:** the dry run's fingerprint matched the data asset's MD5 only because both were written with Windows line endings. The asset MD5 is a checksum of a file; the run fingerprint is a hash of the rows as read. They are related but different checks.
- **Gotcha:** running `az logout` in a second az profile while the Windows account broker (WAM) is on also signed the shared Windows account out of the first profile ("Account has previously been signed out of this application"). Fix: `az login` again. Rule: turn the broker off in a secondary profile before using it, and don't run `az logout` there while the broker is on.
- **Note:** Azure ML drops git details from a job when the remote URL contains anything credential-shaped (here only a username). The SHA is recorded anyway through `--model-version`.
- **Concept:** a reproducibility fingerprint must be canonical: identical inputs give an identical hash on any machine. Comparing a local run with a cloud run on the same data is what exposed this.

### 35. PoC step 4: decision API live on Container Apps, deployed by GitHub Actions ✅
- **Git:** the remote URL no longer contains a username (Azure ML had been dropping git details because of it). The local commits from steps 2 to 4 pushed to `main`.
- **API** (`api/main.py`): `GET /decisions/{customer_id}` returns today's action from the **published** run with its run id, parameter version and model git SHA; 404 when the customer has no decision; 422 for ids outside 0..2^63−1. `GET /healthz` for liveness. Connections come from a small pool; each new connection signs in with a fresh Entra token from the managed identity (tokens expire after about an hour, so connections are recycled every 30 minutes). Unit tests swap the database for a fake (`tests/unit/test_api.py`); `httpx` added to dev for FastAPI's test client. A suggested switch to `httpx2` was not made: unverified package name, possible typosquat.
- **Image** (`api/Dockerfile`): Python 3.12 slim, only the `api` dependency group installed from `uv.lock` (`--frozen`), non-root user, port 8000. `.dockerignore` is an allow-list, so `.env`, data and the venv never reach a build.
- **Build: why GitHub Actions.** `az acr build` (ACR Tasks) is blocked on this subscription (`TasksOperationsNotAllowed`), and building locally needs Docker Desktop. Standard GitHub-hosted runners are free for public repositories, so the image is built on the runner.
- **Pipeline** (`.github/workflows/api.yml`): on pushes to `main` that touch the API or its dependencies: unit tests → build → push to ACR tagged with the commit SHA → `az containerapp update --image`. A failing test stops the rollout. Infrastructure is not changed by the pipeline.
- **Infra** (`infra/main.bicep`, reviewed with what-if, then `az deployment group create`):
  - a separate **deploy identity** with a federated credential trusted only for this repository's `main` branch; AcrPush on the registry and Contributor on the API's Container App only. No client secret exists anywhere. Client, tenant and subscription ids are repository secrets; the registry name is a repository variable.
  - Container App: ingress on port 8000; **IP allow-list with one client IP (dev stopgap**; production is Entra auth in front of the API, then APIM); `PGUSER` set to the runtime identity.
  - `apiImage`, `allowedIp` and `githubRepo` are required parameters passed at deploy time, so an infra deploy can't silently roll back the image CI rolled out.
- **Bug found and fixed: OIDC subject format.** The first run failed at Azure sign-in (`AADSTS700213: No matching federated identity record`). GitHub sent the subject with immutable ids, `repo:<owner>@<owner id>/<repo>@<repo id>:ref:refs/heads/main`, while the credential expected `repo:<owner>/<repo>:...`. Kept the id form (a renamed, deleted or re-created repository of the same name gets no access), passed in at deploy time; the job re-ran green.
- **Smoke test** (from the allowed client, against the live URL): `/decisions/1` → offer, `/decisions/2` and `/decisions/30000` → hold, all from run 8 with parameter version 21 and the model SHA, matching the database; `/decisions/30001` → 404; `/decisions/-5` → 422; `/healthz` → 200. The deployed image tag equals the pushed commit SHA. Not tested: a request from a non-allowed IP (expect 403).
- **Observed:** the very first request after scale-to-zero got a plain-text 404 from the platform proxy before the replica was ready; every request after that reached the app. Acceptable in dev; production either keeps one replica warm (always billed) or has callers retry.
- **Concept:** separate identities for running and for deploying. The pipeline can ship images but can't read decisions; the API can read decisions but can't deploy. Federation replaces stored secrets with short-lived tokens bound to one repository and branch.

### 36. PoC step 5: end-to-end check, a governed parameter change reaches the live API ✅
- **Change:** capital budget 250,000 → 200,000; every other value copied from parameter set 21. Chosen because the expected effect is unambiguous: less capital ⇒ higher shadow price λ\* ⇒ fewer offers.
- **Maker:** the admin inserted set 22 as `proposed` (`INSERT ... SELECT` from set 21 with the new budget). The trigger recorded the admin as maker.
- **Checker:** the dev checker account (its own az profile, Entra token) approved set 22, then in **one transaction** retired set 21 and activated set 22, so there is never a moment with zero or two active sets. The script stops unless `session_user` is the checker.
- **Run:** nightly job on Azure ML at the pushed commit, submitted as in entry 34. It completed and published run 9 as the managed identity. `az ml job stream` failed client-side with a base64 decoding error while the job kept running; waited on `az ml job show --query status` instead.
- **Results (run 8 → run 9):**
  - λ\* 0.646057 → 0.802002;
  - offers 5,569 → 5,060 of 30,000;
  - 509 customers moved offer → hold; **none** moved hold → offer (tighter capital only removes offers, as expected);
  - run 8 `superseded`, run 9 `published`, in the same transaction.
- **Audit trail:** admin INSERT (proposed) → checker approved → checker retired 21 / activated 22 → managed identity inserted and published run 9 and superseded run 8.
- **Live API:** `/decisions/63` and `/decisions/193` (offer in run 8) now return hold; `/decisions/1` still offer, `/decisions/2` still hold; every response carries run 9, parameter version 22 and the new model SHA. No API change or redeploy was needed: it always reads the published run.
- **Rollback path:** a retired set can't be re-activated (history isn't rewritten). Going back to 250,000 means proposing a new set with set 21's values and approving it the same way.
- **Concept:** the governed path is the only path. A parameter change reaches customers only through maker → independent checker → reproducible run → atomic publish, and each step is recorded by the database under the identity that did it.

### 37. Event ingest: `POST /events`, idempotent on the partner's event id (code + database check; not yet deployed)
- **What:** the decision API now also accepts partner events (`disburse`, `repay`, `miss`, `offer`, `accept`, `decline`) in batches of 1 to 1,000. No migration: the `events` table, its primary key on `event_id` and the `lending_app` grants (SELECT, INSERT only) were already in `001_init`.
- **Why:** customer state should come from what customers actually do, not from the static synthetic book. Ingest is the first half; building `customer_state` from events is the next step.
- **How it behaves** (`api/main.py`):
  - one statement per batch, `INSERT ... SELECT FROM unnest(...) ON CONFLICT (event_id) DO NOTHING RETURNING event_id`, inside one transaction;
  - ids that already existed are re-read and compared field by field: identical → counted as `duplicate` (a safe retry); different content → **409** listing those ids, and the whole batch is rolled back, so a partner correction is never silently dropped (a correction needs a new event id);
  - rejected with 422 before the database: unknown type or field, empty or oversized batch, a timestamp without a time zone, a timestamp more than 5 minutes in the future, the same id twice in one batch;
  - `payload` stays free-form until state derivation defines what each event type must carry.
- **Tests:** `tests/unit/test_events.py` (5 tests, in-memory fake store using the same conflict rule): retry stores nothing twice, the same instant in another time zone is a duplicate, a changed body is 409 and stores nothing, malformed batches are 422. 30 unit tests pass; ruff and mypy clean.
- **Database check:** the insert, retry and conflict SQL run against the dev database as the Entra admin inside a transaction that was rolled back: 3 inserted, a retry inserted 0 and found 3, identical retry → no conflicts, changed payload → exactly that id flagged, 0 rows left afterwards. This confirmed the array types (`jsonb[]`, `timestamptz[]`) and that a jsonb round trip compares equal.
- **Firewall:** the client's public IP had changed, so the Postgres `dev-client` rule was updated to the new address (`az postgres flexible-server firewall-rule update -g <rg> -s <server> -n dev-client --start-ip-address <ip> --end-ip-address <ip>`). Still a dev stopgap; it is removed when private networking lands. The API's IP allow-list still has the old address and is updated at deploy time through Bicep.
- **Deployed:** pushed to `main`; the pipeline tested, built and rolled out the image tagged with the commit. Then a Bicep deploy updated the API's IP allow-list to the new client address, passing the image that CI had just rolled out (deploying before the rollout finished would have set the old image back). What-if showed one real change, the allow-list address; the rest was known what-if noise. Read-only check: `/healthz` 200, `/decisions/1` 200 (run 9, set 22), and `/events` is in the live OpenAPI schema.
- **Live write check** (from the allowed client): 2 new `smoke-` events → `accepted 2`; the same batch again → `duplicate 2`; one with a changed payload → 409 naming that id; no time zone, unknown type and an empty batch → 422. In the database (as the admin): exactly 2 rows, the original payload kept after the 409. Both rows were then deleted as the admin so test data can't feed state derivation; 0 events remain.
- **Not yet done:** caller authentication beyond the IP allow-list (next step, Entra auth).
- **Concept:** idempotency is a promise about retries, not about duplicates. Same id + same content = no-op; same id + different content is an error to surface, never a write to drop.

### 38. Customer state derived from events (code and checks; migration not yet applied)
- **What:** the model's four inputs per customer can now come from the event log instead of the seeded `customer_state` table.
- **Why:** in production, state must follow what customers actually do; the seed table was a stand-in.
- **Design: no stored state, a function of the log "as of T"** (`db/migrations/003_state_from_events.sql`):
  - `customer_state_asof(T)` uses only events with `occurred_at <= T` **and** `received_at <= T`. The log is append-only, so the same T always returns the same rows: a run that records T (new column `runs.state_as_of`) can be rebuilt exactly, even after late events arrive. No snapshot tables, and the app role still has no write access to state (EXECUTE on the function is granted to `lending_app` only).
  - `ontime_pct`: instalments (one per `loan_id`, `due_at`) due in the 365 days to T, share repaid by the due date; a late repay after a miss counts once, as late. `loan_amount`: first disbursement this calendar year (UTC), else the latest. `days_since_last_loan`: latest disbursement to T, capped at 364. `n_increases`: distinct offers accepted in the previous calendar year (UTC), capped at 6. Customers with no disbursement or nothing due are left out.
  - Scale note in the file: a year of events is scanned per call; at production volume this becomes a daily per-customer rollup maintained incrementally.
- **Ingest contract tightened** (`api/main.py`): each event type now requires its payload fields (`disburse`: loan_id, amount; `repay`: loan_id, amount, due_at; `miss`: loan_id, due_at; `offer`: offer_id, new_limit; `accept`/`decline`: offer_id), no unknown fields, time zones required. Payloads are stored in one canonical form (times in UTC), so a retry that writes the same instant in another time zone is still a duplicate.
- **Synthetic history** (`src/lending/synthetic_events.py`): for each customer in a book, an event history that reads back as that book as of 1 January 2026: one disbursement, 20 instalments (`floor(ontime_pct / 5)` on time, so `ontime_pct` comes back rounded down to a multiple of 5 and every customer keeps its bucket), accepted and declined offers last year. Loaded as a **backfill** (`received_at = occurred_at`, declared history); live ingest always stamps arrival time. 30,000 customers → 862,712 events.
- **Nightly job** (`jobs/nightly.py`): `--state-source table|events` (default `table`), `--as-of` (default now). Customers outside the data contract are dropped and counted (`customers_dropped`); the run fails if more than 1% are dropped (systemic data problem). The seed table must still be fully clean. The run records `state_as_of` and the data version names the as-of moment.
- **Checks:**
  - unit: payload contract per type and canonical form (`test_events.py`), generator invariants and every generated event passing the ingest contract (`test_synthetic_events.py`), `split_valid` drops only bad rows (`test_data.py`). 37 tests pass; ruff and mypy (src, api) clean.
  - database: `tests/db/check_state_asof.sql`, hand-built events with known answers (first-this-year L0, days, on-time share with late/partial/not-yet-due/too-old/late-arriving events, distinct accepts with a UTC year boundary checked under a UTC+3 session, exclusions, the cap at 6, a late arrival not changing a past as-of, EXECUTE privileges). Run on the dev database together with migration 003 inside **one transaction that was rolled back**: all checks pass; afterwards only 001 and 002 are recorded and the function does not exist.
- **Not yet done (each needs approval):** apply 003; load the synthetic history; compare `customer_state_asof('2026-01-01')` with the seed table; dry run of the nightly job from events; commit and push (the push redeploys the API with the stricter payload contract).
- **Concept:** bitemporal reads. "What happened by T" (`occurred_at`) and "what we knew by T" (`received_at`) are different questions; reproducible decisions need both cut-offs.

### 39. State from events applied on dev: migration 003, synthetic history loaded, read-back exact, nightly dry run
- **Migration 003 applied** as the Entra admin (`psql -v ON_ERROR_STOP=1 -f db/migrations/003_state_from_events.sql`); `tests/db/check_state_asof.sql` passes on the applied schema.
- **`tests/db/check_schema.sql` made safe for a live database.** It had been written against an empty one and stopped at "second active set" (set 22 is active). Worse, its "loan above 5000" case used customer 1, who now exists, so the insert failed on the duplicate key and the check **passed for the wrong reason**. Fixed: the first active set is inserted only if none exists; the current published run is superseded inside the rolled-back transaction and every run/decision insert targets only the check's own run; the range case uses an unused id; check events use a `check-` prefix. All 18 checks pass; afterwards run 9 is still published and set 22 still active.
- **Synthetic history loaded** as a backfill (`\copy events (...) FROM 'data/raw/events.csv' WITH (FORMAT csv, HEADER true)`, generator seed 7, from the seed-42 book): 862,712 events, 30,000 customers, 55 s, 236 MB, `received_at = occurred_at` on every row.
- **Read-back:** `customer_state_asof('2026-01-01T00:00:00Z')` against the seed table: 30,000 of 30,000 customers, 0 differences in loan amount, days, increases and (floored) on-time share, 0 bucket changes. 8.6 s over the full log.
- **Nightly dry run from events** (`jobs/nightly.py --state-source events --as-of 2026-01-01T00:00:00+00:00 --dry-run`, local, as the admin, rolled back): 30,000 customers, 0 dropped, 45 s. λ\* 0.0, 3,101 offers, capital used 128k of the 200k budget, against run 9's λ\* 0.802 and 5,060 offers.
- **Why the difference:** solving the seed book locally with parameter set 22 gives λ\* 0.802 / 5,060 offers as-is and λ\* 0.0 / 3,101 offers with on-time share floored to multiples of 5, exactly the two results. The event path reproduces its input exactly; the gap is the synthetic history's 5-point resolution (on average 2.5 points lower reliability → higher PD → fewer offers, and capital stops binding).
- **Finding for the model:** decisions are very sensitive to the on-time share (a 2.5-point average shift removed 39% of offers). With real events a customer has a limited number of instalments a year, so the share is a noisy estimate. Using the counts themselves (on time, due) as Beta-Binomial evidence would carry that uncertainty instead of a point percentage; added to the backlog, not changed.
- **Concept:** a reconciliation that matches field by field still needs a downstream check; the end-to-end result exposed a sensitivity the field check could not.
