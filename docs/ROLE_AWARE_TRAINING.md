# Position-specific training

## Problem

The selected position was carried through requests, but much of the public
curriculum and the hero-specific replay guidance used the same prose for all
five roles. Support farm trends were labelled as improving when increasing.
The build catalog had one role per hero, so Viper on position 3 returned no guide.

## Changes

- One authored role context defines lane, map, fight, item and farm priorities
  for each position. It is guidance, never evidence of actions in a replay.
- Public and personal lessons retain their stable IDs and saved plans while
  adapting actions, questions, drills and evaluation to the selected role.
- The practice bank contains 43 situations. Each role has an exclusive scenario
  at every difficulty; filtered practice prioritizes it without mixing roles.
- The build catalog contains 17 six-slot guides, adding Viper 3, Necrophos 3,
  Spirit Breaker 3, Rubick 5 and Crystal Maiden 4. Unsupported combinations show
  the selected role's tasks and explicit supported alternatives.
- Replay reads project current-role practice over saved evidence. Changing a
  match's position refreshes the report, pool and personal learning. Old model
  commentary without the current role-aware coaching method is not displayed
  as current advice; this does not trigger a model request.
- Support farm trends are descriptive context, not a higher-is-better score.
  Personal journal choices include lane support and rotation windows. Migration
  017 extends allowed focus values without rewriting existing assessments.
- Hermes receives the same role priorities and instructions to distinguish
  role tasks from observed facts. This release does not authenticate Hermes or
  invoke a language model.

## Verification and limits

Automated browser checks exercise all five learning positions, Viper 2→3 and
Rubick 4→5 build changes, unsupported-role handling, saved-match role changes,
and support journal choices on mobile and desktop. Python regressions cover
role context, old-commentary invalidation, evidence preservation and support
focus persistence. Deployment checks require five distinct role actions.

Positions remain declared by the player. Ward coverage, allied safety, rune
control and the quality of rotations require relevant replay review; a farm
counter cannot establish them. Builds are authored instructional plans with
review dates, not a live popularity or win-rate ranking. The build catalog does
not claim to cover every hero on every position.

## Installed release — 2026-09-09

- Code: `53fdf7de317ddad80f6cdc66e4a5ec520fca5ad1`.
- Deployment: https://github.com/San4o9910/dota2_ai/actions/runs/34396476567 — successful.
- PostgreSQL/API suite: 663 passed, 1 skipped; 74 operations tests passed.
- Public and private browser gates passed on mobile and desktop; practice role
  coverage checks passed for all five positions and all three difficulties.
- Existing server 9037783 updated. Live checks found 17 six-slot guides,
  43 practice situations and all five distinct role-specific learning plans.
- Read-only checks preserved the existing owner and four saved matches;
  three evidence reports passed the learning check. Replay worker heartbeat is
  fresh. These checks created zero model requests.
- Live browser verification confirmed different Viper 2/3 inventories, different
  support/carry lesson actions and an exclusive position-5 lane question.
- Hermes services remain prepared with `waiting_auth`, not authenticated. No
  runtime activation or model generation was performed by this release.

Live examples:
- https://narma-72-56-98-68.sslip.io/builds?q=Viper&position=3
- https://narma-72-56-98-68.sslip.io/learn?position=5
- https://narma-72-56-98-68.sslip.io/practice?position=5
