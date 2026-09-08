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

Deployment result will be recorded after verification.
