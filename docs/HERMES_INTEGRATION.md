# Hermes runtime integration

Narma runs the actual `run_agent.AIAgent` from the official
[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent/tree/9fd44b4dfc44138b9e5d5689acb56c438364ff7b)
checkout, pinned to `9fd44b4dfc44138b9e5d5689acb56c438364ff7b`.
Its environment is installed with `uv sync --frozen` from the upstream lockfile,
as described by the [official Python embedding guide](https://hermes-agent.nousresearch.com/docs/guides/python-library).
Installation and production activation evidence are recorded in
`HERMES_RUNTIME_RELEASE.md`; implementation alone is not a successful activation.

## Execution and accounting

- `hermes-broker` discovers eligible ready reports, creates immutable durable
  tasks and invokes `hermes-runner` privately. At least two distinct matches
  containing verified evidence are required. A repeated snapshot is idempotent.
  Automatic snapshots include the versioned provider request contract. Failed
  tasks and their ledger are immutable across contract updates; completed facts
  are deduplicated across versions. An unchanged failed contract is not retried.
- `hermes-runner` executes the pinned `AIAgent` in a fresh child process and
  temporary profile. Tools, memory, context files, compression, streaming and
  background review are disabled. The process has a hard deadline. No Gemini
  key, database credential, media mount, Docker socket or public port is present.
- The runner's Docker network is internal and contains only it and the broker.
  All model calls use the private OpenAI-compatible broker with an expiring,
  task-specific token. The broker resolves the owner and verifies the lease and
  source revisions before dispatch. Primary, retry and auxiliary requests cannot
  escape that boundary; a task permits at most one paid provider attempt.
- The broker uses the existing approved Gemini model and global allowance. Each
  attempt has `call_kind='hermes'` and exactly one `hermes_task_id` in
  `video_provider_calls`. Reservation commits before the provider call. Raw
  provider usage settles in `finally`, including invalid output and failures.
  Unknown usage retains its reservation. No budget or uncertain historical
  reservation is reset by installation, activation or rollback.
- A completed response must satisfy the strict JSON schema and every match-local
  evidence reference. Provenance is set by the server after an actual runtime
  response and a settled broker call, never by model text or an imported packet.
  Expired leases, changed sources and invalid responses cannot publish a review.
  The provider-facing schema uses Gemini's supported keywords; all stricter
  string, literal and evidence constraints are enforced locally on the response.

The scheduler runs without a customer export action. New reports and corrected
hero-pool context create new snapshots; prior valid goals are passed as explicitly
unverified interpretations. Hero and manually recorded position remain distinct.
Unknown dates, patch, abilities or role are not inferred. Existing reports,
win-rate and factual charts continue to work if optional coaching is unavailable.

## Customer presentation

The hero pool displays valid runtime observations, future actions, a checkable
criterion and buttons opening the source match at its recorded time. Filtering
by hero, position, favorites or period hides any recommendation whose cited
matches are not all in the selected set. Model prose is rendered as plain text.
Runtime versions, connection status, provider configuration and export controls
are absent from the customer page.

Recommendations are interpretations to test, not measured understanding, causal
proof, MMR or statistics. Their metrics never overwrite independently calculated
hero-pool facts. Changes or deletion of a source report, bound account, position
or recorded date invalidate access to recommendations using that source.

## Retained offline exchange API

The authenticated `/api/hermes` export/import API remains available for existing
operator integrations. Cookie ownership and same-origin CSRF rules apply; callers
cannot choose another owner. `POST /exports` creates or reuses a packet,
`GET /exports/{id}` reads it, `DELETE /exports/{id}` removes it and its manual
review, and `POST /reviews` accepts `{export_id, review}`.

Packets contain at most 30 matches and 80 events per match, the bound game account
ID, hero, recorded position, outcome, sourced dates, finite allowlisted metrics,
item facts and evidence identifiers. They exclude email, nickname, credentials,
raw replay bytes and narrative prompts. The game account ID is identifying data;
packets are not anonymous. Source binding includes the replay hash, PostgreSQL's
exact report JSON hash and a canonical position/date digest.

Manual packets remain valid for seven days, with 10 new exports per day and 50
stored exports per account. Each accepts one immutable review with idempotent
identical imports. Imported producer/version/model fields remain unverified;
manual imports cannot become runtime-verified or appear as automatic coaching.

Both transports limit reviews to 32 KiB, five patterns and three goals. Each
pattern requires evidence from at least two distinct matches; goal references
must belong to their named pattern. Empty pattern/goal arrays are valid. A valid
reference proves which episode is cited, not that its interpretation is true.

## Verification and operations

`services/hermes/smoke.py` exercises the real pinned AIAgent against a synthetic
local broker without a paid request. PostgreSQL service tests cover durable
leases, source changes, cross-owner access, idempotency, budget concurrency,
unknown usage and response validation. The browser gate checks mobile/desktop
rendering, safe text, filtering and source navigation. The Docker network gate
checks broker reachability and blocks direct external provider access.

Deployment uses the existing Timeweb server and prebuilt verified image IDs.
The activation gate checks available resources, starts the broker paused,
performs a bounded real review through the existing ledger, verifies its saved
provenance and accounting, then enables continuous scheduling. Rollback restores
prior service state without deleting billing history. No new subscription,
provider account, server or additional allowance is created.
