# Remediation status — 2026-09-06

## Profile and map repair

- The profile endpoint accepts an owned uploaded raw `.dem` as an alternative
  to OpenDota. It reads a bounded Source 2 footer, decodes raw Snappy/protobuf,
  checks the embedded match ID and binds the selected immutable account ID.
  The roster stays private. Metadata order is never used as a player slot.
- A successful metadata-only binding returns `target: null`; it does not mark
  the replay ready, create an analysis target, or reserve a credit. Full parsing
  or a valid OpenDota roster is still required to identify the canonical slot.
- The upload page links to profile binding. The profile panel lets the user
  choose OpenDota or their uploaded raw `.dem`. Uploading a file in chat does
  not transfer it into the website's private replay bucket.
- Tower labels retain T1/T2/T3/T4 after destruction. Unknown state uses a `?`
  badge with a clickable label. Paired T4 labels are separated with leader lines.
- The demo has placement-only ward records and incomplete building events;
  it cannot truthfully display active ward lifetimes or all tower states.
  The missing external replay worker and exact fog-of-war data remain blockers.
- Production OpenDota transport failure was observed. A workerd experiment
  ruled out the detached global-fetch hypothesis. Fixed-category transport logs
  aid diagnosis without exposing player data or exception text. Live OpenDota
  recovery is not claimed, and runtime flags remain disabled.
- `youtube-full` supplies transcripts, not visual game understanding. A future
  video pipeline can combine FFmpeg clips with Gemini video understanding and
  verify observations against replay events; no such pipeline is deployed yet.

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

## One player per account — 2026-09-06

- Nickname lookup binds a single immutable Dota account ID to the authenticated
  platform account. Nicknames are compared without case, with exact Unicode NFC
  spelling. Ambiguous or hidden identities fail before any analysis reservation.
  This is a chosen coaching profile, not verified Steam account ownership.
- Profile, Scan and analysis creation share an account lookup budget. Client
  slot/hero/account overrides are rejected. A private match target controls
  reservation, replay substitution, model execution and reading saved reports.
- Only the target player's personal summary enters the model evidence. Shared
  team, fight and economy facts remain context. Grounding also rejects disguised
  references to another player's personal summary.
- Replay player identities are stored separately from shared normalized data.
  Steam64 values retain exact digits; names may be protobuf byte strings; hero
  and team mapping never assumes metadata order equals game player slot.
- The submitted replay has valid Source 2 framing and a readable end
  metadata record identifying the requested nickname. This is not a completed
  entity/combat parse or AI report. Four other provided match IDs remain
  unverified because development-environment OpenDota requests were unavailable.
- Migration 0012 adds profile/target storage and private replay identity data;
  database guards prevent target switching. Runtime analysis/payment gates
  remain unchanged.
- Local verification: lint and generated types passed; 155 unit/SQLite cases
  passed across the full run and targeted rerun after two stale test assertions
  were corrected. The production build and all 5 package tests passed.

## Nickname lookup correction — 2026-09-06

- Production logs confirmed 503 responses on the profile lookup endpoint; the
  profile/target tables are present in the live database. The old error boundary
  discarded dependency error codes, so those traces cannot identify the exact
  OpenDota failure behind the reported request.
- Profile lookup now validates only the requested match's complete player roster.
  It does not require parsed combat statistics or populate the analysis cache.
  Full analysis still requires its existing validated, parsed match data.
- Account and analysis endpoints preserve safe provider error codes, messages
  and retry headers. Server diagnostics include a code and request identifier;
  provider response bodies, player identities and database details stay private.
- Regression cases cover unparsed rosters, shuffled and invalid slots, wrong
  matches, provider failures and timeouts, with no binding or credit reservation
  on failure. Live OpenDota availability is separate from these local checks.
- Verification passed: lint (two existing warnings), generated types, all 160
  unit/SQLite cases, production build and all 5 package tests.

## Ward and neutral-camp markers — 2026-09-06

- Replaced text-dot wards with scalable vector eye glyphs. Radiant wards are
  green, Dire red; Observer and Sentry have different iris shapes.
- Removed ward history. Only confirmed active intervals are drawn, including
  exact removal boundaries and rewind. Selected details disappear with their
  markers. Unknown lifetimes are hidden, including the placement-only demo.
- Added all 28 pinned 7.41 camp locations and their difficulty/geographical side.
  Triangle/bar/outlined glyphs distinguish small, medium, large and ancient
  camps. They identify locations, not currently living creeps. A map-frame
  gutter prevents edge glyphs from being clipped on small screens.
- Exact in-game fog remains unimplemented. Read-only replay/schema research did
  not establish a terrain-mask exporter; the environment lacks the game-level
  geometry and running Dota engine needed to verify reconstruction. The map
  explicitly labels that limitation. `FOG_OF_WAR.md` records the evidence and
  required next work; this release does not claim a functional fog integration.
- Validation: lint/types passed; 164 unit/SQLite cases verified across the full
  run and a targeted rerun after updating one obsolete fog-status text assertion.
  The production build and all 5 package tests passed. No Dota-engine or browser
  visual parity check is implied by these results.
