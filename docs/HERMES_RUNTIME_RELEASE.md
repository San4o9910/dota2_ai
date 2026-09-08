# Hermes runtime release — 2026-09-08

## Verified before publication

- Official unmodified AIAgent source pinned to
  `9fd44b4dfc44138b9e5d5689acb56c438364ff7b`; 63 dependencies installed from its
  upstream lockfile. Actual runtime smoke: valid JSON, malformed JSON, provider
  error without retry, hard process deadline and recovery after failure all pass.
  Exactly one provider request per case, no auxiliary request, disposable
  profiles removed. Measured peak child RSS: about 127 MiB.
- Local isolated PostgreSQL-compatible service suite: 309 passed, one optional
  native replay test skipped. Native PostgreSQL is an additional CI gate.
- Follow-up lease checks: all 14 task tests pass; the additional actual budget-row
  contention test requires native PostgreSQL and runs in CI. The full captured
  AIAgent request passes the real broker request validator unchanged.
- Deployment regression suite: 25 passed. Browser regressions are prepared for
  390 and 1440 pixels, including recommendation filtering and event navigation;
  actual Chromium runs in CI.
- Existing applied migrations are unchanged. Migration 011 adds durable runtime
  tasks and explicit Hermes provider-call attribution. No budget reset, new
  provider credential, server or additional allowance is included.

## Production activation

The first activation of `ca680f41a1da57ac1028cd71cd5bfbba3b95f7c6`
(workflow `34195780521`) passed the actual Docker runtime/network checks,
Chromium mobile/desktop checks, 25 deployment tests and 312 native PostgreSQL
tests (one optional replay test skipped). Its live provider attempt failed;
activation rolled back to `dddac362d404ec04bfc1a384e8ad6fbb0317b7ad`.
The existing site and replay worker remained available after rollback.

Task `83576cfc-0942-44df-ba14-8da6d90bad54` is terminally failed. Provider call 9
has unknown usage and retains its 1,200,000 micro-USD reservation. Read-only
diagnostics confirmed the existing $10 limit, spent 124,938 and reserved
7,200,000 micro-USD, leaving 2,675,062 available. No reservation was released.
Server memory was sufficient, neither container was OOM-killed, and a free
model metadata request from the existing server succeeded. The original
generic error did not preserve a provider HTTP status, so its exact cause
cannot be established from the retained logs.

The corrective request contract `narma.hermes.review.v2` projects the JSON
schema onto Gemini's documented subset, while keeping strict local response
validation. Fixed-vocabulary diagnostics now distinguish provider HTTP status,
transport errors, empty output and invalid JSON without exposing request or
response text. A real Google SDK request with synthetic four-match input passes
an intercepted HTTP test without a paid call.

The corrected contract is part of immutable task input and receives a new
digest. It never resets the failed task, its one-attempt limit or its ledger.
Identical completed facts are reused across contract versions, and a repeated
v2 snapshot cannot generate another attempt. This is one corrective release,
not an automatic retry policy. Its live activation result is recorded below.

### Corrective release result

`d39c50178c17cc7f66e91014ada1169cf8551413` (workflow `34198341110`)
passed all Docker/network/browser gates, 25 deployment tests and 331 native
PostgreSQL tests (one optional replay test skipped). Its v2 activation failed
with a provider HTTP 400 `INVALID_ARGUMENT`; no valid response was produced.
Read-only workflow `34199193025` verified this category and the successful
rollback to the same working `dddac36` release. API health is healthy and the
replay worker is running. Both Hermes services are stopped; automatic tracking
is not active and must not be reported as connected.

V2 task `8f413400-f040-4dee-a261-6cce7c2138f0` and call 10 remain in failed/
unknown states respectively. The limit is still 10,000,000 micro-USD, spent
124,938 and reserved 8,400,000, leaving 1,475,062 available. The first task/call
and all earlier unknown reservations are unchanged. Further investigation uses
non-generative synthetic requests only until a concrete correction is known.

### Native JSON-object bridge contract

Read-only workflow `34199833911` performed exactly two free `countTokens`
requests with synthetic text: the exact v2 generation configuration and a
baseline without that configuration. Both returned HTTP 200 and 11 tokens.
This does not prove that the generation engine accepts the output schema and
does not establish the cause of the previous HTTP 400. No generation or ledger
mutation occurred.

The final bounded correction maps Hermes's actual `json_object` request to
Gemini's independent JSON MIME mode. The broker no longer adds the optional
provider-side schema compiler. The immutable input contract is
`narma.hermes.json-object.v1`; full local Review and evidence validation remain
mandatory. This is a transport simplification, not a claim that the discarded
provider error message has been recovered. A real SDK interception gate checks
that no provider schema fields are sent. Fixed error reason and field labels
are retained without exposing provider text, credentials or match data.

At most one new activation attempt was permitted within the remaining existing
allowance. All old failed tasks, provider calls and unknown reservations remain
unchanged, and successfully reviewed facts are reused across contracts.

### Final verified state — 2026-09-08 07:50 UTC

- Source `60ce729abcb58bdac41315e8a62ea36e8cf3b6c4`, workflow
  `34200482332`, passed the browser, actual Hermes Docker/runtime/isolation,
  25 deployment tests and 348 native PostgreSQL tests (one optional replay
  test skipped). Local final broker suite: 65 passed; task suite: 20 passed.
- The bounded live attempt reached Gemini and received HTTP **503 UNAVAILABLE**,
  category `provider_unavailable`, field label `model`. This is the confirmed
  reason for this final attempt's failure. It does not retrospectively establish
  the reason for v1 or the exact invalid parameter in v2.
- Final task `2af60635-a7b7-4d61-a044-cca4163e86ec` is terminally failed with
  one attempt; call 11 has unknown usage and retains its reservation. No real
  runtime review has succeeded or been published. Automatic tracking is off.
- Independent read-only workflow `34200576476`, diagnostic source
  `12ed8d1bf9ff43421d1498d6b677002aea3bb164`, confirmed rollback to live
  `dddac362d404ec04bfc1a384e8ad6fbb0317b7ad`: API healthy, replay worker running,
  both Hermes containers stopped, neither OOM-killed, zero provider requests
  made by the diagnostic. Existing reports and prior customer UI fixes remain.
- Existing allowance remains 10,000,000 micro-USD ($10); settled spend 124,938,
  reserved 9,600,000, available **275,062**. Reservations are not confirmed
  charges. Calls 9, 10 and 11 and all previous uncertain history remain intact.
  Available allowance is below the existing 1,200,000 per-attempt reservation;
  another activation must not proceed under the present ledger state.

Do not report Hermes as connected. Further activation requires provider
availability and an explicit, audited accounting/retry decision; never reset
unknown reservations, increase the allowance or bump a contract merely to
repeat a failed request. Google documents that failed HTTP 400/500 requests are
not charged for tokens, but this release does not silently reconcile any prior
ledger record from that general statement. Preserve the observed error evidence
for a separate accounting review.

References: [final deployment](https://github.com/San4o9910/dota2_ai/actions/runs/34200482332),
[independent diagnostic](https://github.com/San4o9910/dota2_ai/actions/runs/34200576476),
[Gemini billing](https://ai.google.dev/gemini-api/docs/billing#am-i-charged-for-failed-requests).
