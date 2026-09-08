# Narma product experience repair

The September 8, 2026 review found a concrete first-visit problem: the live root
page showed only a login form. Reading the current application also showed that
the learning panel was hidden with an empty hero pool, the generic hero plan
took precedence over a completed personal coaching plan, and section changes
did not update browser history. Passing the existing technical checks did not
establish that these player journeys were useful.

## What this release changes

- `/` gives visitors working entry points into heroes, learning, practice and
  official Dota news before they upload a replay or sign in.
- `/heroes` contains the official hero catalog, search, attribute filters and
  selected-hero information. It does not invent global win rates or matchup data.
- `/learn` publishes the original Narma lessons already present in the curriculum,
  with role selection, exercises, exceptions and source links.
- `/practice` provides a complete session of original, hypothetical decision
  scenarios, explanations and results. The score describes the exercise session,
  not the player's rank or proven skill in actual matches.
- `/updates` shows dated Valve publications and the latest patch present in the
  checked official feed. An event announcement is not a claim that an event is
  currently active.
- `/my-learning` makes personal practice independent of the hero-pool filters and
  match count. Learning is accessible even when no replay has been uploaded.
- Personal report suggestions prioritize the completed coaching response. The
  main coaching comment appears near the report metrics. A missing ChatGPT
  connection provides an actionable link to the account page.
- Private navigation has direct URLs and browser history; hero-pool rows use
  official portraits. Section changes preserve the open report and draft forms.

## Boundaries

Public read-only endpoints use fixed official feeds and a checked-in snapshot.
They neither read account tables nor call a language model. A bounded background
refresh preserves the last valid content on upstream failure and returns its
actual check time and stale status. Feed HTML is not rendered.

Personal replays, learning plans, player identities and ChatGPT authorization
remain behind the existing account checks. The single-owner pilot is not changed
into a public registration or shared subscription service. No new payment or
monetization claim is introduced.

The live pre-change browser check reached the login screen; it did not sign in
as the owner. Private regression uses synthetic fixtures and must not be
described as a live review of the owner's matches. A real ChatGPT-generated
review remains distinct from OAuth readiness and offline tests.

## Release checks

- Existing private portal regression: report, role changes, item selection,
  owner-scoped flows, OAuth UI, learning, keyboard navigation and mobile layout.
- New public regression: catalog search, lessons, scenario feedback/results,
  official news links, stale/error states and mobile/desktop layout.
- Backend tests: strict feed validation, bounded refresh, source failure,
  public access without database access and continued protection of private APIs.
- Existing PostgreSQL, pinned Hermes, network isolation and release rollback
  gates remain in the deployment workflow. Public readiness is checked through
  anonymous HTTPS GETs after installation, before analysis workers resume.

This addresses verified product defects and introduces useful public workflows.
It is not evidence of parity with STRATZ or readiness to charge customers.
