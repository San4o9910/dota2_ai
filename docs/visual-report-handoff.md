# Visual replay report: release handoff

Status checked on 2026-09-07: implemented and tested, **not deployed**. The saved owner report has not been refreshed.

## Implemented

- Shared-time net-worth/XP, income, farming and combat charts, ten-source income breakdown, death intervals and item markers.
- Key item purchase, hero inventory, active slot and first-use evidence; income between acquisitions and observed activity in the following two minutes.
- Three next-game training actions, including evidence-linked Gemini tasks and a factual fallback.
- Early/normal/late labels compare an explicit personal goal, with a one-minute tolerance. No unsupported MMR benchmark is presented.
- Selected-hero inventory telemetry uses PlayerResource selected hero handles and excludes illusions. Gold events reconcile exactly; overlapping shared-gold counters and sales are not added to earned income.

Complete replay validation: match 8984479726, 45,890 earned gold reconciled, 79 income bins, 10 sources, 10 key items, 124 unique evidence events, final tick 152653. BKB first use follows purchase by approximately 306 seconds; Shiva by 55 seconds. These are observations, not proof of causal benefit.

Validation passed: 101 Python service tests with PostgreSQL (one skip), mobile/desktop Playwright and accessibility checks, hardened native replay runtime, and 15 deployment regression tests. The latest mobile chart labels were also visually inspected. The new report was built locally from the complete real replay; no additional paid Gemini call was made.

## Actual runtime and remaining work

- Site: https://narma-72-56-98-68.sslip.io
- Existing server: 9037783; project: 2655641; IP: 72.56.98.68; approved preset: 6813. Update this existing server only.
- Last confirmed installed release: `c8a15da3eb9983466ec43817f78c0191eced302b`.
- Latest implementation commit at this checkpoint: `1218e93b604f4a8b006198b1f6502dc51ca18851`.
- Saved replay job: `354d95b9-2bb7-4700-923d-796566a7cc01`; last verified ready at attempt 2; selected Steam account: 435842051.
- Source SHA-256: `db9df23273bdac450a027ff11992428e6610403de78301c86e9adbe26320e0bc`; size: 169982117 bytes.

Initial installations failed while building dependencies on the VPS and restored the previous worker. Deployment now exports the tested CI images, streams them through SSH, verifies archive hashes and image IDs, and starts Compose with no build or registry pull. Old image IDs, API and worker rollback are retained.

The remaining blocker is Timeweb API HTTP 500. Read-only direct-server checks and the separately authorized ephemeral SSH-key diagnostic failed. The latter stopped on POST `/api/v1/ssh-keys` before any binding or host access. No uncertain POST was retried. The last main workflow, run `34113290084`, job `101714197981`, stopped before building/installing on GET `/api/v1/servers/9037783`. No application or budget change was made by these failed API checks.

The normal pinned deployment keeps a fresh API check of the exact server identity, project, marker, preset and IP. It no longer queries unrelated OS, domain or pricing catalogs for a code-only update. Provisioning and price checks remain in the explicitly unpinned creation path. No blind identity-check fallback was enabled.

After Timeweb access is restored, rerun the normal pilot workflow and verify successful installation, fresh worker heartbeat, public HTTPS and preserved budget/account identity. Use the **actual successful workflow head SHA** as the expected installed release; a later documentation commit can change that SHA.

Then update `ops/replay-support-request.json` to action `refresh`, the actual installed SHA, the job/source above, expected attempt 2 and expected insights schema `narma.replay-insights.v1`. Its dedicated workflow queues the normal worker once, retains the old report for failure recovery and verifies the owner-facing saved result. Do not reset attempts or the provider ledger. This replay already has one settled Gemini call; the refresh may use its second call within the existing allowance. Preserve unknown budget reservations.

Completion requires `replay_refresh_complete`, a ready owner-visible report with populated insights, and next-game actions (Gemini when available, factual fallback otherwise). A successful code deployment alone is not completion of the user's request.
