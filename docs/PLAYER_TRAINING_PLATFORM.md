# Narma player training platform

The product is a training loop: inspect one player's match, choose a specific
decision to improve, practise it, and check the next comparable matches. A
successful quiz or a high KDA is not evidence that the player has mastered a
skill. Revenue depends on sustained usefulness of that loop, not a large catalog
or a promise to reach a rank.

## Implemented player workflows

- Public hero catalog, original learning exercises and dated Valve news.
- Original build decision guides for all five positions. One selected guide
  shows item icons, conditions for purchases, the action after a purchase and a
  next-game check. The checked patch is displayed; a newer known patch prompts
  a review. These are editorial recommendations, not a statistical meta ranking.
- Three self-selected practice levels: foundations, application and advanced.
  Advanced situations introduce new information and ask the player to revise a
  decision. That second answer is scored separately. Repeat-missed practice is
  available; local history records the selected level.
- Replay upload accepts the match's position, optional self-reported MMR and
  independently selected depth of coaching. These values are an immutable job
  snapshot. A newer profile preference does not rewrite historical match context.
- The model input distinguishes player preferences from recorded match evidence.
  Beginner explanations have one signal and action; deeper explanations compare
  alternatives and discuss information or conditions that change the decision.
- Background motion is subtle and stops for reduced-motion preferences.

## What is still required for a paid service

1. Finish the owner's ChatGPT authorization and verify one real review with
   event links and the right hero, role and selected depth. Installed Hermes and
   OAuth readiness do not establish that a model has reviewed a match.
2. Use an appropriate service API arrangement and account-level entitlements for
   paying customers. The existing single-owner ChatGPT subscription pilot must
   not be presented as shared inference capacity for unrelated subscribers.
3. Obtain a supported, commercially usable statistical feed for global meta,
   rank cohorts, skill orders and observed item timings. OpenDota remains
   excluded. Dota2ProTracker and Dotabuff links provide external context; their
   statistics are not mirrored or invented in Narma.
4. Validate coaching usefulness with actual consecutive matches and human
   review at different skill levels. Confirm that advice identifies a real
   episode, explains an alternative and supports one measurable next action.
5. Establish account isolation, subscription lifecycle, usage limits and actual
   cost per successful analysis before choosing prices or enabling checkout.

The current video and replay paths remain distinct. A `.dem` is parsed into
game events; it is not rendered into a complete video. The legacy video worker
has a limited frame budget. Full-match video reasoning requires a separate
coverage-aware sampling and replay/video alignment design, with explicit
timestamps and observation provenance. Do not advertise that as complete.

## Competitive context

STRATZ and Dotabuff provide extensive statistics; Dota2ProTracker provides
high-ranked match examples; Dota Coach provides maintained coaching guides.
Narma's intended advantage is a personal sequence of decisions and checks across
the player's own games. Superiority has not been demonstrated. Evaluate it by
whether users can identify, practise and improve a specific recurring decision.

Basic news and discovery can remain publicly useful. A future subscription
should add recurring personal review, longitudinal practice and changes relevant
to the subscriber's hero pool, with explicit limits. No payment page, paid plan
or automatic rank-growth claim is enabled by this release.
