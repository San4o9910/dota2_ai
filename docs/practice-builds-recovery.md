# Trainer and community build UI recovery — 2026-09-09

Base commit: 525cd5e593c27cbdf1b10cc2597cdcdf033ce389.
Base tree: ab622377f6d71a4c0105daa365d2ad0e973d9b52.

The development executor disconnected during work (409 environment_offline).
These files were reconstructed from the base GitHub files and successful patch
inputs recorded during this task. This is not a byte-for-byte verified copy of
the disconnected working directory. Comments, markup whitespace and test
organization may differ. No production deployment is represented by this branch.

## Implemented trainer behavior
- Default series length 10, selectable 5/10/15; no role, topic or level widening
  when a narrow pool contains fewer scenarios.
- Completed history retains question identifiers; unseen matching situations
  lead, then the oldest recently practised situations. Legacy five-question
  histories remain readable.
- Three or four alternatives supported.
- Rich scenario fields: briefing, decision_steps, worked_example, common_trap,
  counterfactual {change, decision}, takeaway, replay_task {setup, action, success}.
- One deeper explanation accordion at a time, optional private rationale,
  per-topic recap and a concrete task for the next replay.
- Rationale text is not automatically assessed, sent remotely or persisted.
- Catalog bounds: 500 situations, 4 MiB text response.

## Implemented community build behavior
- Authored guides render independently of the Workshop response.
- All/Narma/Workshop source selection; hero and role filtering.
- Broad core/support classifications are explicitly distinguished from exact
  positions. No support/core crossover or inferred exact position.
- Workshop original item phase groups plus a separately labelled Narma
  inventory projection; up to six factual items and visible empty placeholders.
- Only one phase bar and one chosen item detail shown.
- Author, original Steam URL, patch, source update date and coverage displayed.
  No invented winrate, purchase minute or statistical popularity.
- Workshop selections dispose the authored statistics adapter; Steam ids
  cannot be passed to the STRATZ endpoint.
- Source errors preserve the authored library and any cached community feed.

## Review corrections included after reconstruction
- A late Workshop response updates the picker and coverage without replacing an
  unchanged authored detail, preserving its focus and open explanation.
- Fresh official patch updates override the last Workshop patch response.
  Workshop-only confirmation expires after 30 minutes if fresh confirmation
  cannot be obtained. Individual fetched guides expire after 24 hours.
- Repeated identical coverage does not rewrite its live region.
- An empty loaded source exits the loading state correctly.

## Verification
Before disconnection, local Node syntax checks passed for builds.js and
workshop-builds.js. The original trainer pure check passed against 43 scenarios.

For this reconstruction, V8 executed 1,236 assertions: the complete trainer
pure checks against the base 43-scenario catalog, plus Workshop role/freshness
checks. The reconstructed builds.js passed V8 syntax compilation after stripping
module import/export declarations. Full Workshop URL validation tests require
native Node URL and are saved in scripts/check-workshop-builds.mjs.

Required integration checks before release:
1. node scripts/check-practice-roles.mjs against the expanded authored catalog.
2. node scripts/check-workshop-builds.mjs.
3. Browser checks of default10, selected15, role pools, rich feedback, phase
   selection, six slots/partial sources, deep links and asynchronous failures.
4. Serve the new /assets/workshop-builds.js in the UI fixture.
5. Integrate the independent Workshop backend/API and real source snapshot.

## Follow-up: unknown items in future patches
The Workshop refresh adapter currently uses its bundled item-name catalog.
New or unavailable ids in an author's updated guide must be retained as
unknown_item_ids. The backend owner is adding this field and assigning
review_due when nonempty; known purchases remain available.

The frontend independently refuses a current_patch badge for such a guide,
excludes it from the current-patch coverage count, and tells the player that
the item list is incomplete. Stronger stale, patch_changed and unknown states
are retained with an additional completeness message. IDs are validated and
not shown as guessed item names. Native regression checks cover this behavior.
