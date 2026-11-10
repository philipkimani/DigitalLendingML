# Agent evals

CSV test sets for Copilot Studio's built-in evaluation: agent → Evaluation → New evaluation → Single responses → Import.

| File | Agent |
|---|---|
| `internal.csv` | Lending Analyst |
| `customer.csv` | Lending Assistant |

**Test methods:** Compare meaning on every case; Capability match on cases whose expected response names a tool, because live values change. No case should create a parameter set: the propose cases stop at the confirmation. After a run, check `/parameter-sets` shows no new set.

**Results** are exported to `results/`; Copilot Studio keeps them for 89 days. Any failure is either fixed in the agent and re-run, or recorded with its reason.

## Runs, November 2026 (Dev, test pane, as the checker)

Result files hold the first part of each response, read from the results page, with a reviewer note where the grader or the platform, not the agent, decided the outcome. Meaning match is the headline score.

| Agent | Run | Meaning match | Tool use | Change before the run |
|---|---|---|---|---|
| Lending Analyst | 1 | 21/25 | 9/9 | none |
| Lending Analyst | 2 | 23/25 | 8/9 | the approvals-link topic now says it cannot approve, reject or activate |
| Lending Assistant | 1 | 13/15 | 6/6 | none |
| Lending Assistant | 2 | 13/15 | 5/6 | instructions: decline capital questions without asking for an id; no financial advice, no lists to consider |

Not caused by the agent: a cold-start connector timeout (analyst run 1), the trial's generative-orchestration rate limit (one case in each run 2), and the content filter on "Ignore your rules…", which blocked it with an error instead of a decline. Still open: the escalate topic answering a capital question, "Approve my increase now" asking for an id, and the analyst not asking for a reason before a proposal. No run created a parameter set (checked through `/parameter-sets`).
