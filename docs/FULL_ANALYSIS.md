# Authenticated full analysis

Status: implemented behind fail-closed runtime flags for closed-beta staging.

## User flow

1. A signed-in user submits a Match ID and one Dota player slot on `/analyses`.
2. `POST /api/analyses` validates same-origin JSON, account state and a bounded
   idempotency key.
3. One D1 transaction creates the job and reserves exactly one active analysis
   entitlement. A repeated request reuses the existing job.
4. `POST /api/analyses/:id/run` acquires a ninety-second lease, fetches and
   normalizes OpenDota evidence, requests a strict OpenAI report, validates it,
   stores the immutable report and consumes the reservation.
5. Retryable failures return the job to `queued` with a durable
   `retry_not_before` cooldown. The API preserves the bounded provider delay in
   `Retry-After`; early retries do not consume another attempt.
6. A terminal failure or the last allowed attempt releases the exact
   reservation bucket. A fresh idempotency key may then create a new job for the
   same match identity; active `queued`, `running`, or `ready` work stays unique.
7. A queued job can be canceled explicitly. A running job can be canceled only
   after its lease expires, preventing a stale worker from publishing a report
   after the reservation was returned.
8. History and details always filter by the current account on the server.

The runner is deliberately pull-driven because the current Sites package has no
durable Queue binding. Do not enable `ANALYSIS_FULFILLMENT_ENABLED` until request
duration, disconnect, expired-lease recovery and repeated-run behavior pass in
the real staging Worker. Cloudflare documents a thirty-second post-response
limit for `waitUntil`, so it is not used as a substitute for a durable queue.

## API

| Route | Method | Result |
|---|---|---|
| `/api/analyses` | `POST` | Creates or replays one reserved job. Requires `Idempotency-Key`. |
| `/api/analyses` | `GET` | Returns owner-scoped cursor history, at most fifty jobs. |
| `/api/analyses/:id` | `GET` | Returns an owner-scoped job and its validated report, if ready. |
| `/api/analyses/:id` | `DELETE` | Cancels an owned queued job, or an expired running lease, and releases its reservation. |
| `/api/analyses/:id/run` | `POST` | Runs or retries one owned, leased job when fulfillment is enabled; retry delays use `Retry-After`. |

Every response is `Cache-Control: no-store`. Errors use
`{ error: { code, message, retryable, requestId } }`; storage/provider details
and account identifiers never cross the public boundary.

## Runtime gates

`ANALYSIS_RUNTIME_ENABLED=true` allows reservation and job creation.
Fulfillment additionally requires all of the following:

- `ANALYSIS_FULFILLMENT_ENABLED=true`;
- a server-only `OPENAI_API_KEY`;
- a syntactically valid `OPENAI_MODEL`;
- the same model present in the operator-maintained, comma-separated
  `OPENAI_ALLOWED_MODELS` value;
- the exact D1 `DB` binding.

Absent or malformed values fail closed. None of these flags are enabled by the
source tree.

## Workspace component

`AnalysisWorkspace` contains three parts: a labeled creation form, an
owner-history list and a detail/report panel. Its explicit states are loading,
empty, queued, running, retryable failure, terminal failure and ready. Native
form controls and buttons provide keyboard behavior; status text is announced
through polite live regions; primary targets are at least forty-four pixels.
Queued cooldowns show a local countdown based on the server header. Running work
never polls silently: the user explicitly chooses “Проверить и восстановить”,
or requests cancellation after the lease timeout.

The UI must render quantitative model output only from mechanically validated
structured claims. Free-form prose is never parsed to manufacture charts or
numbers.

## Remaining release gates

- Workerd/D1 concurrency tests, not only SQLite contract tests;
- real staging identity-header forgery and IDOR tests;
- OpenDota/OpenAI timeout and disconnect recovery on the deployed Worker;
- keyboard, automated accessibility and 375/768/1440 visual checks in a browser;
- a durable queue or a measured decision to keep the pull runner;
- deployed verification that provider `Retry-After`, lease expiry, stale-worker
  rejection and reservation release behave identically on D1;
- retention, account-erasure, observability and operational replay procedures.
