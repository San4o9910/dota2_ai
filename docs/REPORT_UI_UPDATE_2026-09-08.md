# Report header and compact item selection — 2026-09-08

The report body starts with the displayed report's Dota hero portrait and name,
followed directly by its statistics, beginning with kills/deaths/assists. The
section navigation follows those statistics. The portrait uses Valve's existing
allowed image host and a strictly checked internal hero name. Modern display
names are separate from CDN filenames (for example, `necrolyte` is Necrophos).
The live Viper and Necrophos PNGs were verified as 256×144. Missing artwork keeps
a neutral tile and the actual hero name; report/archive changes rebuild the
header from the displayed report.

The upper item strip remains. Only its selected card is visible underneath, at
full width. Buttons expose their selection with `aria-pressed` and support native
keyboard activation. Switching items updates the shared time cursor without
scrolling away from the cards. Hidden cards retain draft goal inputs and
expanded details. Timeline navigation does not change the chosen card; opening
another report, archive or explicit refreshed report starts from its first item.

The customer pool no longer requests or displays the Hermes connection status,
JSON export control or operator import metadata. The authenticated exchange API
is retained. Hermes itself is still not installed or running: the previous
release implemented only evidence transport. No runtime activation, provider
call, budget change or infrastructure change is part of this interface update.

The existing browser gate exercises two-item selection, draft retention,
keyboard activation, archive switching, image success/fallback, mobile layout
and accessibility. The normal server deployment gates remain in force.

## Confirmed deployment, 2026-09-08 06:06 UTC

- Installed release: `dddac362d404ec04bfc1a384e8ad6fbb0317b7ad`, source tree
  `df878782f2b52b11cac4a3f6a87aa36d2d94a12e`.
- [Workflow 34192844839](https://github.com/San4o9910/dota2_ai/actions/runs/34192844839),
  job `101954263265`: success. Existing server 9037783 was updated.
- Mobile/desktop browser and accessibility gates passed. An initial test used
  `textContent`, which included a decorative fallback icon; it was corrected to
  use the selected button's accessible name before any server installation.
- Real PostgreSQL suite: 240 passed, one optional test skipped. Docker runtime,
  migrations, HTTPS and replay worker heartbeat passed.
- The live check verified three saved reports' hero context without creating
  provider calls. Allowance before/after was unchanged: limit 10,000,000
  microUSD, settled spend 124,938 microUSD, reserved 6,000,000 microUSD.
- Hermes was not activated. The remaining actual runtime implementation is
  recorded in `HERMES_RUNTIME_NEXT.md`; it needs development, not another user
  authorization for already approved project work.

Live portal: <https://narma-72-56-98-68.sslip.io/>. Source is published on
`San4o9910/dota2_ai` / `codex/replay-map-hardening-8ea829a`. Documentation-only
updates do not trigger a new installation.
