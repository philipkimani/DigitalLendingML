# Decision API

One FastAPI service (`api/main.py`) on Azure Container Apps. It serves decisions that the nightly job has already computed and stored; it never runs the model on request. It also takes partner events.

All customer ids and values below are **synthetic** (the 30,000-customer seed book). Interactive schema: `GET /docs` on the running service.

| Endpoint | Purpose |
|---|---|
| `GET /decisions/{customer_id}` | Today's offer/hold for one customer, with why |
| `POST /events` | Partner events, idempotent on `event_id` |
| `GET /healthz` | Liveness; never touches the database |

## Authentication

Every endpoint except `/healthz` needs an Entra ID access token for the `lending-api-dev` app, carrying the endpoint's **app role**:

| Endpoint | App role |
|---|---|
| `GET /decisions/{customer_id}` | `Decisions.Read` |
| `POST /events` | `Events.Write` |

```bash
token=$(az account get-access-token --scope <api client id>/.default --query accessToken -o tsv)
curl -H "Authorization: Bearer $token" https://<api host>/decisions/63
```

- **401** (with `WWW-Authenticate: Bearer`): no token, or not a valid token for this API (signature, issuer, tenant, audience, expiry).
- **403**: a valid token without the endpoint's role.
- **503**: the service has no authentication configured; it refuses rather than serve unauthenticated.

Roles are assigned in `infra/entra.bicep` (users for testing, apps and managed identities as callers). Only assigned principals can obtain a token at all. Services call with a managed identity; there are no client secrets.

There is no IP allow-list: identity, not network address, decides access.

---

## `GET /decisions/{customer_id}`

The decision for the customer's next eligibility window, from the **published** run. `customer_id` is 0 to 2^63−1.

| Field | Meaning |
|---|---|
| `action` | `offer` (offer a limit increase this window) or `hold` |
| `reason_code` | Why, see below. `null` for runs published before reason codes existed |
| `reason` | `reason_code` in plain words, ready to show to a person |
| `q_hold`, `q_offer` | The two values the decision compared: expected present value (USD) of holding vs offering, net of the capital charge. The action is whichever is larger |
| `run_id` | The nightly run that produced it |
| `param_version` | The approved parameter set the run used |
| `model_version` | Git SHA of the model code |
| `published_at` | When the run was published |

### Reason codes

Each code comes from a counterfactual: the run is solved twice, at today's capital price (λ\*) and with capital free (λ = 0).

| `reason_code` | `action` | Meaning |
|---|---|---|
| `npv_positive` | offer | Offering adds value at today's capital price |
| `capital_limit` | hold | Would be offered if capital were free: the capital budget went to customers where it adds more |
| `risk_return` | hold | Not worth offering even with free capital: expected loss and churn outweigh margin and fee |

The database rejects a code that disagrees with the action (migration 004).

### Examples (run 19, parameter set 22)

Customer 1, offered:

```json
{
  "customer_id": 1, "action": "offer", "reason_code": "npv_positive",
  "reason": "An increase is expected to add value: margin and fee outweigh the extra risk and capital.",
  "q_hold": 136.15, "q_offer": 136.30,
  "run_id": 19, "param_version": 22, "model_version": "9b652b6…", "published_at": "2026-10-30T15:19:30Z"
}
```

Customer 63, held by the capital budget. A close call: holding is worth 27 cents more at today's capital price; with free capital the customer would be offered. (Customer 63 was offered at a 250k budget and held after the budget fell to 200k.)

```json
{
  "customer_id": 63, "action": "hold", "reason_code": "capital_limit",
  "reason": "An increase would add value, but this cycle's capital budget went where it adds more.",
  "q_hold": 648.16, "q_offer": 647.89,
  "run_id": 19, "param_version": 22, "model_version": "9b652b6…", "published_at": "2026-10-30T15:19:30Z"
}
```

Customer 2, held on risk. Not close: offering is worth about 93 dollars less, and free capital would not change it.

```json
{
  "customer_id": 2, "action": "hold", "reason_code": "risk_return",
  "reason": "Expected losses and churn on a larger limit outweigh its margin and fee for now.",
  "q_hold": 597.15, "q_offer": 504.10,
  "run_id": 19, "param_version": 22, "model_version": "9b652b6…", "published_at": "2026-10-30T15:19:30Z"
}
```

Run 19 overall: 5,060 `npv_positive`, 3,300 `capital_limit`, 21,640 `risk_return` (30,000 customers).

**Reading `q_hold` and `q_offer`:** the gap is how strongly the model prefers its action; a gap of cents means a small change in parameters or capital could flip it. The values include the customer's whole remaining year, not just this window, so they are not "profit from this increase".

### Errors

| Status | When |
|---|---|
| 404 | No decision for this customer in the published run (unknown customer, or left out of the run) |
| 422 | `customer_id` not an integer in 0 to 2^63−1 |

---

## `POST /events`

A JSON array of 1 to 1,000 events, stored in one transaction.

```json
[
  {"event_id": "p-000123", "customer_id": 1, "event_type": "repay",
   "occurred_at": "2026-10-30T08:00:00+03:00",
   "payload": {"loan_id": "L1", "amount": 1200, "due_at": "2026-10-31T00:00:00+03:00"}}
]
```

| `event_type` | Required `payload` fields |
|---|---|
| `disburse` | `loan_id`, `amount` |
| `repay` | `loan_id`, `amount`, `due_at` (the instalment it pays) |
| `miss` | `loan_id`, `due_at` (a due date that passed unpaid) |
| `offer` | `offer_id`, `new_limit` |
| `accept`, `decline` | `offer_id` |

Rules: timestamps need a time zone; `occurred_at` may not be more than 5 minutes in the future; amounts are positive; no unknown fields at either level; an `event_id` at most once per batch. Payloads are stored in one canonical form (times in UTC).

| Response | Meaning |
|---|---|
| 200 `{"accepted": n, "duplicate": m}` | `accepted` newly stored; `duplicate` already stored with identical content (a safe retry) |
| 409 `{"detail": {"error": …, "event_ids": […]}}` | Those ids are already stored with **different** content. Nothing in the batch was stored. A correction needs a new `event_id` |
| 422 | The batch breaks a rule above. Nothing was stored |

Events feed `customer_state_asof(T)` in the database, which derives each customer's model inputs from the log as of a moment (migration 003).
