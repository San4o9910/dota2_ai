# Remediation status — 2026-09-05

The project remains a private pilot. It is not a certified paid production
release. Version 4 was privately published with user authorization; the map
and economy correction below is prepared for the same authorized audience.

## Implemented

- Bundled, calibrated 7.41 game raster; no external map-image dependency.
  Tower standing/destroyed/unknown state follows the selected time; ambiguous
  T4 events and incomplete logs are explicit. Ward placement/removal uses entity
  handles. Missing ward removal never becomes a fabricated active ward.
- The selected match owns its map/economy/events. Another match never receives
  the demo's scene. Gold andXP use a shared chart and cursor. Replay Gold uses
  sampled net worth; OpenDota Gold retains its earned-gold meaning.
- Authenticated resumable multipart `.dem`/`.dem.bz2` upload, owner access,
  bounded memory/storage, idempotency and cleanup. Separate pinned-parser adapter
  with private normalized results; authenticated external worker entrypoints.
- Model output selects numeric evidence; arbitrary model prose is replaced by
  application-owned review questions. Correct numbers can no longer carry an
  invented cause of death or unobserved ability/vision claim into the report.
- Persistent training checkboxes and owner-scoped factual follow-up questions.
  These free data lookups are not sold as a professional coach conversation.
- Match roster uses hero names; account and replay routes are linked explicitly.
- Durable analysis attempt caps, lease recovery, original-bucket refunds,
  browser-independent scheduling source and bounded request lifetime.
- Payment return page reads the owner's order even when checkout is closed.
  Manual refresh reuses authoritative provider verification. A canceled event
  cannot overwrite a credited success. Missing provider ID never implies no
  charge and no longer triggers an automatic time-based cancellation.

## Still required before paid production

1. Provision the private external worker, secure machine access, R2 lifecycle
   cleanup and the appropriate runtime model/settings. Follow ops/README.md.
2. Parse real replays end to end and compare event/position timestamps against
   the game. Add other patch maps only with matching source/calibration.
3. Exact team vision needs additional parser data and validation. The current
   release deliberately reports fog unavailable. Sampled heroes/wards are not
   a terrain visibility mask; trees and structures in the raster are static.
4. Test checkout/webhook/cancel/duplicate/lost response in the provider sandbox.
   Automated refunds remain unimplemented; do not launch recurring paid plans
   or claim the existing catalog's coach-question promise is fulfilled.
5. Build a patch-tagged, coach-reviewed evaluation set. Validate usefulness and
   unsupported-claim rate on matches across roles/MMR. Watching a channel alone
   does not train the deployed model or prove coaching quality.
6. Stage migrations, verify backup/restore and monitoring before enabling paid
   production. Private publishing does not enable payments or provision workers.

## Verification scope

`npm run check` covers lint, types, unit/SQLite endpoint regression tests,
build and package tests. New cases include failed-parser storage quotas,
concurrent parts, foreign-owner reads, abort failure/retry, expired leases,
idempotent worker claims/results, negative-time objectives, map rewind and
unsupported causal prose. Real provider/DEM execution, browser visual QA and
load/restore drills are separate outstanding evidence, not implied by tests.

Candidate verification completed locally: lint and generated types passed;
144 unit/SQLite regression tests and5 package tests passed. The final fixture
chronology correction passed all5 fixture tests and a fresh build/package
verification. Dependencies are unchanged from the earlier same-day advisory
check (0high/critical,5moderate,1low); that is not a zero-advisory claim.

## Map and economy correction

- Replaced the schematic terrain with the original 7.41 game-map image from
  Buny154 / Liquipedia, with Valve attribution. Natural image proportions and
  tower/base calibration are preserved; two independent gate anchors are
  within 6 image pixels. This does not certify exact replay visibility.
- Gold, XP and fight intervals now share a seconds-based axis and cursor.
  A fight can be selected and zoomed; its start and end are directly seekable.
  The final partial minute is retained instead of rounding match duration.
- Each team has its own signed Gold/XP result. Relative advantage is explicitly
  a difference of changes, not kill bounty or team income. Per-player deltas
  are normalized when available; missing detail stays unknown.
- `npm run check` passed: lint, generated types, 149 unit/SQLite regression
  tests, production build and 5 package tests. New cases cover real timeline
  geometry, honest fight totals, player attribution, raster integrity and
  independent coordinate anchors. No browser or live gameplay validation
  was performed for this correction.
