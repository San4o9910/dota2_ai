# Deep learning and Workshop builds — integration checkpoint

Status: INTEGRATED CANDIDATE. Not deployed. Full release verification is running on codex/deep-learning-workshop-builds.

The local execution environment disconnected with environment_offline / HTTP409 during development on 2026-09-09. This branch preserves integration code reconstructed against exact base525cd5e593c27cbdf1b10cc2597cdcdf033ce389 from the implementation contracts and recorded edits. It is not a byte-for-byte verified copy of the inaccessible workspace.

User request: deepen learning beyond short three-question sessions and add builds for all current Dota2 heroes with honest patch freshness.

Integration:
- Role-specific reading modules API and escaped chapter UI with worked examples, changed conditions, mistakes, match practice, self-checks.
- Private practice links back to the relevant public role/stage.
- Workshop builds API and cache lifecycle.
- Beginning of expanded Python/browser regression coverage.

Dependencies to integrate before testing/deployment:
- codex/learning-content-recovery-20260909:15reading modules and expanded practice bank.
- codex/practice-builds-recovery-20260909:trainer and Workshop frontend.
- codex/workshop-recovery-20260909:Steam adapter, tests, collection/seed tooling.

Remaining gates:
- Complete deterministic browser fixture for Workshop; verify 5/10/15 sessions and role/depth coverage.
- Build an actual public-only Steam seed; verify hero coverage against current Valve hero list. Preserve source author, patch, author update date; do not present author guides as statistically highest-winrate builds.
- Test adapter with real public Steam metadata/CDN (no key/model call); stale/withdrawn entries must stay honest.
- Full native PostgreSQL, ops, public/private UI gates; only then update existing pilot branch.
- Same existing Timeweb server only. Preserve Hermes preparation state; no paid model generations, no OpenDota.

Last production code SHA:53fdf7de317ddad80f6cdc66e4a5ec520fca5ad1; pilot head525cd5e593c27cbdf1b10cc2597cdcdf033ce389.
