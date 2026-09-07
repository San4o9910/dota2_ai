# Hero pool release

This document records the initial pool release. For the current extended pool,
date-based chronology, retained coaching and Hermes exchange, see
[HERO_POOL_RELEASE.md](HERO_POOL_RELEASE.md) and
[HERMES_INTEGRATION.md](HERMES_INTEGRATION.md). The initial deployment below
remains historical evidence rather than the currently installed release.

The standalone Timeweb portal now has a `/hero-pool` page and authenticated
`GET /api/hero-pool`, `PUT /api/hero-pool/matches/{match_id}` routes. A read-only
`GET /api/hero-pool/coach-context` prepares a selected hero and position for a
future external coach; it does not run Hermes or call a provider.

## Data and interpretation

- Read only the bound player's ready, complete, identity/source-matched replay
  reports. Use the newest report per account and match, so duplicate uploads do
  not increase the sample. No OpenDota requests or replay regeneration.
- Count wins only over known outcomes. Unknown outcomes and positions remain
  separate. Label the scope as uploaded replays, not all Steam games.
- Position 1–5 is supplied by the user for each match. It is never inferred from
  a hero name. Metadata is stored by owner/account/match in PostgreSQL migration
  `007_hero_pool.sql`, separately from replay facts.
- Order matches by numeric Match ID. `uploaded_at` is not presented as a verified
  gameplay date. Bound the history to the latest 1,000 distinct matches and tell
  the user when earlier matches are excluded.
- Show 10-minute last hits/net worth/deaths, average gold income, and confirmed
  downtime. A short match, stale checkpoint, missing value, or incomplete death
  intervals is unknown, never zero. Downtime requires a matching closed interval
  for every recorded death. Genuine zero deaths and zero downtime remain zero.
- Compare the latest three games to the preceding three only for one hero and
  confirmed position, with three actual values in each group. This is descriptive
  change, not a score of understanding or proof of skill improvement.
- Do not combine known different engine builds, or known and unknown builds,
  into averages/patterns. All-unknown historical builds carry an explicit caveat.
  Future reports retain the engine build from their parsed replay header.
- Recurrence requires at least three distinct games within the latest twenty
  comparable games. Repeated deaths and active-slot-to-first-use intervals link
  back to exact reports/events. An interval alone is not a demonstrated mistake.
- Focus, completion marks and notes are self-reported. Do not describe a checked
  box as verified improvement. Notes survive re-upload; removing the final copy
  of a match removes its notes. Every mutation uses session ownership and CSRF.

## Validation and deployment

The release gate checks mobile/desktop interaction, accessibility, empty and
single-match history, role filters, known-result denominators, save failure
recovery and report navigation using synthetic data. A separate PostgreSQL suite
checks real SQL, latest-report deduplication, owner/source boundaries and note
retention/deletion. Synthetic fixtures never call Gemini or the live API.

An initial CI attempt stopped before production installation on a malformed SQL
JSON path. The corrected query is covered by the PostgreSQL tests. Independent
review also identified missing life telemetry becoming zero downtime; a focused
regression now rejects this false improvement.

The production activation checks migration 007, reads each existing owner's pool,
verifies unique match counts and outcome totals, and checks anonymous `/api/hero-pool`
returns 401. It preserves the existing server, source files, saved reports,
accounts and provider ledger. A new `.dem` upload or Gemini regeneration is not
needed to populate this section from saved reports.

Hermes remains **prepared, not installed or running**. See `HERMES_HERO_POOL.md`
for the verified upstream version and the metered gateway requirement before
activation. No paid calls or new infrastructure are part of this feature.

## Confirmed deployment, 2026-09-07 20:38 UTC

- Installed release: `f323f75f9f009c7cf550975fbca3fec13ec78b3a`.
- Workflow `34159805141`, job `101859038854`: success.
- Live page: https://narma-72-56-98-68.sslip.io/hero-pool
- Existing VM 9037783, project 2655641, IP 72.56.98.68; no new server.
- PostgreSQL-backed suite: 156 passed, one optional skipped. Mobile/desktop
  interaction, synthetic report/pool screenshots and accessibility passed.
- Owner-scoped live pool verification: one owner, one distinct saved match,
  one hero. No report refresh or upload was required. This small sample does not
  support a trend; the owner must mark the position and add further matches.
- Public certificate and HTTPS verified; anonymous pool API returns 401.
  Migration 007 and current worker heartbeat verified, video worker stopped.
- Allowance before/after identical: limit 10,000,000 microUSD, settled spend
  112,713 microUSD, reserved 3,600,000 microUSD. Unknown reservations preserved.
  No synthetic or actual provider generation was part of the deployment.
- Hermes context and validation are available; Hermes remains not installed or
  running. Existing optional Gemini coaching failure was not retried or reset.

GitHub branch `codex/replay-map-hardening-8ea829a` is authoritative. Native local
branch `codex/hero-pool-progress` has the same tree with different local commit
hashes; do not push the legacy Sites origin. Documentation-only follow-ups do not
change the installed release or trigger another deployment.
