# Hero pool and longitudinal practice — 2026-09-07

## Scope

The standalone portal gains `/hero-pool`, using the existing PostgreSQL account
and replay-bound player identity. No OpenDota request or new model call is needed.

- One match contributes once even if uploaded several times. Only complete,
  identity-checked reports for the bound player contribute.
- Win rate uses known wins and losses; unknown outcomes stay separate. Roles
  1–5 are assigned by the player, never guessed from a hero.
- Hero/role favorites, 30/90-day or full-history filters, and per-match values
  accompany the trend chart. Unknown match dates use an explicitly labeled
  analysis chronology. Player-entered dates remain labeled as such.
- Comparisons require one hero and role, a consistent date source and at least
  three matches in each group. These are descriptive changes, not proof of
  increased game understanding or a rating benchmark.
- Repeated deaths and active-item timing supply review prompts and persistent
  practice goals. Subsequent matches record the observed measure separately
  from the player's interpretation of the decision.
- Existing per-match practice focus, self-reflection and free-text notes are
  preserved. Self-reflection is not treated as measured improvement.

## Retention

The owner can remove a ready replay's original media while retaining its report
and pool statistics. This releases the existing disk reservation. Reanalysis
requires uploading the original file again. Full replay deletion still removes
the report and excludes the match from the pool.

Migration 008 saves a complete earlier report transactionally before refresh.
Failed refreshes retain owner-scoped access. Optional coaching can be carried
forward only when identity, context and every cited event can be matched
uniquely; otherwise the earlier full report remains available with its original
event references. The text already lost before this release is not recovered.

## Hermes

The evidence exchange is prepared for NousResearch Hermes Agent. It exports a
bounded snapshot, accepts references only to its actual match/event evidence,
and retains imported recommendations separately from factual metrics. The
application explicitly reports `runtime_connected=false`; imported producer
metadata does not prove an agent executed or its interpretation is correct.

No Hermes runtime, automatic model loop, additional provider allowance, or paid
inference is activated by this release. See `HERMES_INTEGRATION.md` for the
remaining metered runtime connection. Existing Gemini reservations and call caps
remain authoritative.

## Deployment and verification

Target is the existing Timeweb server 9037783 at
`https://narma-72-56-98-68.sslip.io`; no new infrastructure is provisioned.
The earlier `007_hero_pool.sql` from the concurrent release is preserved byte
for byte. Migrations 008–010 add report preservation, Hermes exchange and the
extended pool, and import existing role notes. Readiness requires the original
notes table and all three additional migrations. The previous source remains available for
rollback; database migrations should be retained when rolling the code back.

Local verification: 209 service tests and six subtests passed, one native replay
runtime test skipped; 21 deployment regressions passed. The local database was
PGlite with a test-only prepared-statement compatibility adapter, not the
production PostgreSQL runtime. JavaScript syntax and whitespace checks passed.
Local Chromium installation timed out, so browser and accessibility verification
must pass the existing CI gate alongside real PostgreSQL and Docker builds
before deployment. Deployment outcome will be recorded after completion.
