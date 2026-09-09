# Deep learning and all-hero builds — release receipt

Release code: `d1d9d03a9cf844df169948699ce88049f3b880d4`
Code tree: `8af537b10ddb0e9c90f5ad734f717f00a4bafebc`
Production: https://narma-72-56-98-68.sslip.io
Existing Timeweb server: 9037783.

## Product changes

- 15 original reading modules, three for each position. They cover lane/risk, map/decisions, and items/fights with worked examples, changed conditions, common mistakes, match practice and self-checks.
- 163 decision scenarios: 120 new cases and 43 enriched cases. All 60 position × difficulty × topic combinations have at least five scenarios.
- 51 advanced cases include a second decision after conditions change. Ambiguous former-answer distractors were reviewed and corrected.
- Practice offers 5/10/15-question sessions, defaults to 10, respects role/topic/depth filters, prioritizes unseen cases and preserves earlier browser history.
- Optional personal reasoning stays in the current session. It is not automatically graded or persisted as a model assessment.
- Private practice links to the corresponding public lesson and role.
- 369 attributed public Steam Workshop guides cover all 127 current Valve heroes. Each hero has a guide whose author declares patch 7.41e.
- Six inventory slots are shown; unavailable source slots remain unfilled. Actual source item groups are retained; Narma's final-slot projection excludes consumables and intermediate components.
- One purchase stage and one selected item detail are displayed at a time.
- Workshop guides sort by freshness, role specificity and author update date while preserving explicit selection.

## Source meaning and operation

The source is public Steam Workshop guide metadata and item identifiers, verified against the public Valve hero/item catalogs. It is not a statistical ranking of complete builds by winrate or popularity. Author prose and item tooltips are not republished.

At source verification, 172 guides declared7.41e and covered 127 heroes. Of those, 164 had author update dates older than 30 days and received review_due; 8 were updated within 30 days. The UI separates matching-patch counts from recently updated counts.

The running API checks the reviewed public guide IDs daily. Failed refreshes retain the last known facts with an explicit status; unpublished/private entries are removed with persisted tombstones. Unknown source item identifiers cannot produce a current_patch status. Newly published guide IDs require a reviewed catalog import.

## Verification

- Isolated full candidate CI: https://github.com/San4o9910/dota2_ai/actions/runs/34403830699
- 680 application tests passed; 1 existing test skipped; 2 dependency deprecation warnings.
- 74 operational tests passed.
- Public and private mobile/desktop browser flows passed, including keyboard use, responsive layout, WCAG checks, source freshness, role filtering, selected-item display and 5/10/15 sessions.
- Actual public Steam metadata/CDN transport verified in source CI: https://github.com/San4o9910/dota2_ai/actions/runs/34402881351
- Production deployment and published-content verification: https://github.com/San4o9910/dota2_ai/actions/runs/34404352510
- Deployment outcome: SUCCESS. Installed SHA matches the release code above; the existing server and HTTPS certificate were verified.
- Final public-site check returned 15 lessons, 163 scenarios, 127 heroes and 369 Workshop guides; latest patch 7.41e.
- Live Workshop statuses: 197 patch_changed, 164 review_due, 8 current_patch.
- No model calls were created. Hermes services remain prepared with readiness waiting_auth and runtime_verified false; authentication is still outstanding.

## Operational continuity

The local workspace disconnected during development. The candidate was recovered into separate GitHub branches, integrated against the exact existing pilot base, and verified using ordinary GitHub CI. The verified GitHub release is authoritative; do not treat the disconnected local working tree as current.

The deployment uses the existing server and allowance. Hermes preparation/auth state is preserved; this release does not activate model generation.
