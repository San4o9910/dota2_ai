# Hermes with the owner-funded OpenAI API

This change adds the explicit provider `openai_api`. It is an implementation
candidate until the deployment's actual native-runtime activation check succeeds.
An installed container, a configured API key, or a successful synthetic test must
not be reported as active automatic coaching.

## Provider and isolation contract

- Set `HERMES_PROVIDER=openai_api` and pin `OPENAI_MODEL=gpt-5.6-sol` in the
  deployment configuration. The broker receives the server's `OPENAI_API_KEY`;
  the isolated Hermes runner receives only an expiring task credential.
- The scheduler still runs the actual pinned `NousResearch/hermes-agent` at
  `9fd44b4dfc44138b9e5d5689acb56c438364ff7b`, one disposable profile per task,
  with no tools, memory, background review, fallback model or unrestricted egress.
- The broker translates the single bounded text request to the shared Responses
  API adapter. The full `Review` schema and match-local evidence checks remain
  mandatory. Upstream output must match its settled call's exact output hash,
  owner, Hermes task and model before a review can be published.
- A missing key, disabled allowance, model change or provider failure never falls
  back to Gemini or a personal ChatGPT subscription.
- `chatgpt_subscription` keeps its existing exact single-owner OAuth gate.
  The paid API does not import or use personal OAuth credentials.

Migration `020_hermes_openai.sql` extends the immutable provider identity without
rewriting older tasks or billing history. The OpenAI task snapshot includes
`narma.hermes.openai-api.v1`, the model and the pinned runtime revision. Repeated
identical snapshots do not generate another call. Previously completed facts
are reused across providers. An attempted OpenAI request with uncertain billing
cannot be retried by changing the model or runtime contract; new evidence is
needed for a new automatic task.

## Billing and readiness

The shared `openai_api_budget` and `openai_api_calls` ledger reserves money before
network dispatch. Each task has at most one lifetime provider attempt. Known
usage is charged even when output is invalid or the source lease expires;
unknown usage retains the reservation. Invalid accounting freezes further
dispatch. The older Gemini ledger is never reset or used for paid OpenAI calls.

The scheduler conservatively requires enough available allowance for the maximum
accepted text input and 4,096 billed output tokens before claiming a task. This
is a dispatch ceiling, not the price of a review. The broker reserves a smaller
amount from the actual serialized request bound, then settles observed usage.
No new allowance is enabled by the Hermes migrations.

Operator status distinguishes:

| Status | Meaning |
|---|---|
| `services_unavailable` | No fresh heartbeat from the pinned runtime |
| `waiting_api_key` | The selected OpenAI configuration is unavailable |
| `paused` | Configuration exists, but the allowance cannot dispatch a bounded task |
| `ready` | Services and configuration are ready; no verified current-provider review yet |
| `running` | A task is currently leased |
| `requires_review` | A terminal attempt failed and needs inspection |
| `verified` | A settled, source-bound native-runtime review completed successfully |

`provider_configured` is distinct from `runtime_verified`. `automatic_tracking`
is true only after a verified review, a fresh heartbeat, an available allowance
and enabled scheduling. Operational status and JSON transport controls remain
outside the customer hero-pool interface. Verification proves execution and
provenance; it does not certify the truth of each coaching interpretation.

## Several client accounts

The original pilot database allowed only one row in `portal_accounts`.
Migration `021_portal_multiple_accounts.sql` removes that database limitation
while preserving existing account IDs, sessions, reports and profile bindings.
Paid coaching can therefore isolate independently provisioned clients by
`owner_id` and bound Dota account. Model history and reviews never cross owners.

This change does **not** open public registration. The current `/auth/setup`
remains a one-time bootstrap route. Customer onboarding, invitations and public
registration need their own product flow; do not advertise self-service signup
on the basis of this migration. Adding a second account also leaves the legacy
personal OAuth adapter unavailable by its existing single-owner rule.

## Validation and activation

`services/video/tests/test_hermes_openai.py` covers disabled/missing keys,
model identity, no OAuth/Gemini fallback, immutable snapshots, two independent
clients, unknown billing retention, exact settled output, forged provenance,
duplicate attempts, and leases lost before/after dispatch. These tests replace
only provider network generation with synthetic responses.

`services/hermes/smoke.py` dynamically exercises every allowed runtime model,
including the new paid model, through an unpaid local broker. It checks valid
and invalid JSON, provider failure without retry, deadline termination and
profile cleanup. Native PostgreSQL concurrency checks and the actual container
network isolation gates remain part of deployment validation.

Before calling the integration active, run the bounded native Hermes activation
with the explicitly configured allowance and preserve before/after billing,
installed revision, task identity and review validation evidence. Failed calls
must leave existing replay analysis and measured hero-pool statistics available.
