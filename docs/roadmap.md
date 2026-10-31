# Roadmap

What is left to finish the build, in order. Detail for Phase 2 steps: `docs/architecture.md`. History of completed work: `docs/ledger.md`.

## Done

- [x] Phase 1: Azure dev environment (Bicep), model port with parity tests, data contract, synthetic data
- [x] Postgres schema with maker-checker enforced by a trigger
- [x] Nightly solve on Azure ML, decisions published to Postgres
- [x] Decision API on Container Apps, deployed by GitHub Actions (OIDC)
- [x] Event ingest (idempotent) and customer state rebuilt from events
- [x] Reason codes on every decision
- [x] Database CI (fresh Postgres, all migrations and checks)
- [x] 2.1 Entra: API app roles, token-only access (IP allow-list removed)
- [x] 2.2 approvals, steps 1–3c: approval endpoints acting as the approver's own database login; custom connector with no secret

## Now: 2.2 maker-checker approvals

- [ ] Commit and push the connector work (Entra connector app, `api/connector.swagger.json`, test)
- [ ] 3d Power App: proposed sets, comparison with the active set, Approve / Reject / Activate, database refusal text shown
- [ ] 3e Power Automate notification when a set is proposed
- [ ] 4 End-to-end in the browser as maker and as checker
- [ ] Optional: propose a parameter set through the API (today the maker uses psql)

## Next: model and ML

- [ ] Model gates in `tests/model_gates/`: NPV vs champion, calibration, PSI drift; blocking
- [ ] Monthly estimation (`jobs/estimate.py`): estimate parameters from logged events, write them as *proposed* sets into the approval flow
- [ ] Train / validate jobs and model registration in Azure ML
- [ ] On-time evidence as instalment counts (Beta-Binomial) instead of a point percentage
- [ ] Decide at the customer's actual increases-this-year and windows-held

## Hardening

- [ ] Private networking; then remove the dev client firewall rule on Postgres
- [ ] `docs/identities.md`: owner of every identity and credential
- [ ] Azure Monitor alerts: failed nightly job, failed flows, API 5xx

## Phase 2, remaining

- [ ] 2.3 ALM: `DigitalLendingOps` solution in `powerplatform/`, managed import via GitHub Actions
- [ ] 2.4 Copilot Studio "Lending Analyst" agent (read-only), eval set in `copilot/evals/`
- [ ] 2.5 API Management in front of the API
- [ ] 2.6 Power BI portfolio report with row-level security

Open decisions: M365 tenant for Teams / SharePoint / Power Platform; Copilot Studio licensing; Power BI connectivity to Postgres.

## Separate track

- [ ] Mock customer app on top of the API (simulated customers check whether they qualify for an increase)

Not planned: a nightly schedule. The nightly job is run by hand.
