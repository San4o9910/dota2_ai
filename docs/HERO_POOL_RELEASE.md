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
Local Chromium installation timed out; CI subsequently passed mobile/desktop
interaction and accessibility checks. The actual 390 px and 1440 px pool
screenshots were also inspected without a blocking visual finding. Docker
builds, the isolated replay runtime check and the real PostgreSQL suite passed
(209 tests passed, one optional test skipped).

### Confirmed deployment, 2026-09-07 20:57 UTC

- Installed release: `35095e7ee00acd5b16fdd5a0b3d371358d644357`.
- [Workflow 34160970073](https://github.com/San4o9910/dota2_ai/actions/runs/34160970073),
  job `101862571813`: success. Source tree:
  `b8ef71804641a0b61277826b8f5419ae9743ddf3`.
- Live page: <https://narma-72-56-98-68.sslip.io/hero-pool>.
  Existing VM 9037783 and project 2655641 were retained; no infrastructure or
  budget change was requested.
- Migrations and readiness passed. Replay worker has a fresh heartbeat; video
  worker remains stopped. HTTPS certificate verified; anonymous pool and Hermes
  APIs return 401, and the pool page and liveness endpoint return 200.
- Owner-scoped live verification found one owner, one distinct saved match,
  one hero and one known outcome. Outcome totals and deduplication passed.
  The existing match was included without refresh or upload; this sample does
  not support a longitudinal comparison yet.
- Provider call count did not increase during the pool check. Allowance before
  and after activation was identical: limit 10,000,000 microUSD, settled spend
  112,713 microUSD and reserved 3,600,000 microUSD. Existing reservations remain
  intact. No synthetic inference or coaching retry was performed.
- Hermes remains an offline evidence exchange; automatic runtime integration
  is not activated. Previously lost coaching text is not recovered.

The authoritative branch is `San4o9910/dota2_ai` /
`codex/replay-map-hardening-8ea829a`. The working checkout's local merge commits
have different hashes but the same release tree; do not publish a legacy Sites
origin or overwrite concurrent work. Documentation-only updates do not trigger
deployment. This record supersedes the earlier release details in
`HERO_POOL_OPERATIONS.md` and points to `HERMES_INTEGRATION.md` for current
exchange contracts and remaining runtime work.
