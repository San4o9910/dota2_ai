# Visual replay report: release handoff

Status checked on 2026-09-07: **deployed and the saved owner report refreshed successfully**. Optional new Gemini coaching failed; the previous detailed coaching text could not be recovered. The factual report includes three next-game training actions.

## Implemented and live

- Shared-time net-worth/XP, income, farming and combat charts, ten-source income breakdown, death intervals and item markers.
- Key item purchase, hero inventory, active slot and first-use evidence; income between acquisitions and observed activity in the following two minutes.
- Three next-game training actions based on replay evidence; supported Gemini tasks are used when a valid model response is available.
- Early/normal/late labels compare an explicit personal goal, with a one-minute tolerance. No unsupported MMR benchmark is presented.
- Selected-hero inventory telemetry uses PlayerResource selected hero handles and excludes illusions. Gold events reconcile exactly; overlapping shared-gold counters and sales are not added to earned income.

Complete replay validation: match 8984479726, 45,890 earned gold reconciled, 79 income bins, 10 sources, 10 key items, 124 unique evidence events, final tick 152653. BKB first use follows purchase by approximately 306 seconds; Shiva by 55 seconds. These are observations, not proof of causal benefit.

Validation passed: 101 Python service tests with PostgreSQL (one skip), mobile/desktop Playwright and accessibility checks, hardened native replay runtime, and 21 deployment regression tests. The production saved report was rebuilt from the complete real replay and verified through the owner-scoped report accessor. Browser CI checks use synthetic fixtures; they are not evidence of a signed-in production browser session.

## Actual runtime

- Site: https://narma-72-56-98-68.sslip.io
- Existing server: 9037783; project: 2655641; IP: 72.56.98.68; approved preset: 6813. Update this existing server only.
- Confirmed installed release: `2601a5fca0e42abb970047ae4970b540c4ee14c6`.
- Successful deployment workflow: `34120203071`, job `101736277246`.
- Successful saved-report refresh: `34120869804`, job `101738337376`.
- Saved replay job: `354d95b9-2bb7-4700-923d-796566a7cc01`; ready at attempt 3; selected Steam account: 435842051.
- Source SHA-256: `db9df23273bdac450a027ff11992428e6610403de78301c86e9adbe26320e0bc`; size: 169982117 bytes.

Deployment verified public HTTPS/certificate, unauthenticated API rejection, ready PostgreSQL/schema/media/API, fresh replay-worker heartbeat, and stopped unused video-worker. Deployment itself made no paid provider calls and preserved the allowance and reservations.

The earlier Timeweb API HTTP 500 resolved on retry. A subsequent installation exposed Docker image identity differences between classic CI storage and the VPS containerd store. The portable verification fix checks exact exported image config digests and ordered rootfs layers after authenticated transfer, then pins the verified local IDs. It does not weaken content verification. The existing API and worker were restored on the failed attempt; the corrected deployment completed normally. The normal controller still verifies the exact pinned server identity before SSH.

## Saved report and optional coaching

Authoritative completion event `replay_refresh_complete` confirms:

- ready owner-visible report, exact source/player identity, complete replay, final tick 152653;
- `narma.replay-insights.v1`, 79 gold bins, 10 sources, 10 key items, 79 pace points, 16 death intervals;
- three deterministic training actions available through the UI fallback;
- optional coaching `unavailable`, failure `REPLAY_COACH_UNAVAILABLE`, no new Gemini next-game tasks;
- two provider calls: original settled charge 8,740 microUSD; refresh call billing status unknown, charged amount unknown.

Do not claim the Gemini refresh succeeded or that its unknown call was free. Do not reset attempts, reservations or provider-call counters, and do not bypass the existing per-replay call cap to generate again. The $10 global allowance was unchanged; earlier unknown reservations of 2,400,000 microUSD were preserved before refresh. The new unknown call also requires normal provider-spend reconciliation.

The old detailed coaching was replaced when the factual refresh finished successfully but optional coaching failed. The provider ledger stores usage/accounting, not response text. The latest successful S3 backup (workflow `34101482742`, job `101676695375`, 08:37 UTC) contains zero replay jobs and predates this upload; it cannot restore that text. No recovery mutation or additional generation was performed after this finding.

Known follow-up: preserve an existing valid coaching report durably before refresh, and carry it forward only after uniquely remapping and verifying every referenced evidence event when optional generation fails. Parser event IDs change as telemetry expands; copying old IDs unchanged is unsafe. Log a bounded provider error category to distinguish transport failures without exposing prompts or credentials. These are follow-ups, not changes claimed in this release.

Reopen the existing match after reloading the site; uploading the replay again is unnecessary for the new factual visualizations and training plan.
