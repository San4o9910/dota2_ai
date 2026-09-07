# Hero-aware report and item cards — 2026-09-07

## User-visible changes

- The last-hit histogram sits immediately below the yellow income histogram
  in the same right column. Both still use the shared report time cursor. On
  narrow screens, sources precede the stacked histograms and selected interval.
- Each key item is a card with Valve's Dota inventory artwork, acquisition and
  first-use milestones, observed arrival and active-slot times, and the existing
  realization evidence. An inventory sighting is not relabeled as a purchase.
  Missing use remains unknown; passive items do not require a button press.
- Personal timing goals, reset, evidence links and timeline navigation remain.
  Icons use a fixed Valve CDN path, strict canonical item identifiers and no
  referrer. A unavailable image leaves a neutral tile and the item name.
- A hero context appears before the next-game plan, including the selected
  report's hero, manually recorded position, and observed ability counters.
  A contextual plan takes precedence over the previous generic plan. The
  existing saved Gemini commentary remains separate and unchanged.

## Why the old analysis appeared generic

The parser selected the correct player and hero, but deterministic training
suggestions did not receive the hero. Gemini received its internal hero name
while the stored ability/item usage aggregates were omitted. The old UI also
preferred an existing generic coaching plan and did not display ability usage.

The provider input now includes a bounded projection of selected-player
ability/item usage and explicit instructions to use the actual hero. This
changes future metered analyses without launching any regeneration.

Existing reports receive `hero_context` next to the immutable `report` in the
authenticated replay-detail response. Archives receive their own sibling
context. Saved facts, provider text, report hashes and historical evidence IDs
are unchanged. Position is joined by owner/account/match only after validating
the report's identity and source digest. No provider is called on a read.

## Interpretation boundaries

Observed ability totals may include pregame events. They do not prove that an
ability was ready, unused or effective in a specific episode. Hero-specific
questions link to actual recorded episodes, without inventing cast events or
cooldown telemetry. Generic heroes use their observed abilities/items; the
Necrophos guide additionally uses qualitative mechanics verified in Valve's
own [hero data](https://www.dota2.com/datafeed/herodata?language=english&hero_id=36)
and [hero page](https://www.dota2.com/hero/necrophos). This reference is not a
version-specific simulation of the saved replay. No role, MMR benchmark, item
build or damage threshold is inferred.

Artwork source example:
[Valve Radiance icon](https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/items/radiance.png).
Seven canonical item icons were checked as successful PNG responses. CSP adds
only that image host; it does not permit external scripts or API destinations.

## Verification

Focused tests cover provider projection, owner-scoped context, immutable current
and archived reports, unknown/ambiguous telemetry and hero-specific guidance.
The existing UI gate covers graph geometry and shared cursors, item milestones,
loaded/missing/invalid icons, hero-plan precedence, archive context, mobile
layout and accessibility. Test image responses and report data are synthetic;
they do not call model providers or the live application.

Deployment checks additionally read up to three saved reports per bound owner
and verify their context matches each report's hero and recorded position,
alongside the existing unchanged provider-ledger check. The existing Timeweb
server and allowance are retained. Deployment outcome is recorded after CI.
