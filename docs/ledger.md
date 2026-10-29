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
