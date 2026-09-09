# Independent authored builds: source and review record

Review date: 2026-09-09. Scope: one original situational six-slot variant for each
of the 12 existing guides, plus six concise notes about relevant changes in
Valve's 7.41e patch. This is a source-backed mechanics check and an authored
coaching judgment. It is not a statistical claim that these are the most popular
or highest-win-rate six-item combinations.

## What players can do

Select an existing hero/position guide, keep its base six-slot plan, or apply one
specific match condition. Each alternative replaces one discretionary item and
explains the trade-off. The six-slot inventory and its selected-item explanation
remain the primary interface. This feature requires neither STRATZ nor model
credentials. The alternatives are not automatically personalized from a replay.

| Guide | Condition | Replace | With |
| --- | --- | --- | --- |
| Juggernaut, 1 | Attacks miss an accessible evasive target | Butterfly | Monkey King Bar |
| Drow Ranger, 1 | One blockable targeted catch; block cannot easily be broken first | Butterfly | Linken's Sphere |
| Phantom Lancer, 1 | Real hero can safely attack and needs a cheaper slow | Butterfly | Diffusal Blade |
| Viper, 2 | Group suffers magic damage; no existing Pipe purchaser | Butterfly | Pipe of Insight |
| Puck, 2 | Several controls prevent casting and exit | Octarine Core | Black King Bar |
| Necrophos, 2 | Waiting for Radiance loses necessary fights to magic damage | Radiance | Pipe of Insight |
| Axe, 3 | Nearby allies die to magic after successful initiation | Shiva's Guard | Pipe of Insight |
| Centaur, 3 | Control prevents completing Stomp despite sufficient health | Heart | Black King Bar |
| Rubick, 4 | First burst kills before useful second action | Scythe of Vyse | Aeon Disk |
| Spirit Breaker, 4 | An ally needs a basic dispel more than extra cooldown reduction | Octarine Core | Lotus Orb |
| Lich, 5 | Existing saves do not remove the critical dispellable effect | Aether Lens | Lotus Orb |
| Crystal Maiden, 5 | Physical attacks kill before expensive Hex is affordable | Scythe of Vyse | Ghost Scepter |

These are conditional decisions, not universal recommendations. The support
examples explicitly allow buying a less expensive defensive item before waiting
for a luxury item. A final inventory illustrates slot allocation, not a mandatory
purchase order or a claim that every support should reach six completed items.

## Primary evidence checked

The official [Valve patch list](https://www.dota2.com/datafeed/patchnoteslist?language=english)
identified 7.41e as latest during this review. The
[official 7.41e change log](https://www.dota2.com/patches/7.41e), read through its
[public JSON feed](https://www.dota2.com/datafeed/patchnotes?version=7.41e&language=english),
provided the six scoped notes bundled with the relevant guides. These are
editorial summaries; patch refresh does not regenerate them.

The current [Valve item list](https://www.dota2.com/datafeed/itemlist?language=english)
was used to resolve canonical item IDs. Individual item descriptions were read
from Valve's own public item-data feed:

| Item | Official data | Mechanic that supports the condition |
| --- | --- | --- |
| Monkey King Bar | [135](https://www.dota2.com/datafeed/itemdata?language=english&item_id=135) | Pierce provides a chance to hit through evasion; not guaranteed accuracy on every attack. |
| Linken's Sphere | [123](https://www.dota2.com/datafeed/itemdata?language=english&item_id=123) | Blocks most targeted spells once per cooldown; not all forms of catch. |
| Diffusal Blade | [174](https://www.dota2.com/datafeed/itemdata?language=english&item_id=174) | Targeted slow and mana burn from the real hero's attacks. Current text explicitly excludes illusion mana burn. |
| Pipe of Insight | [90](https://www.dota2.com/datafeed/itemdata?language=english&item_id=90) | Nearby group receives a magic barrier; repeated barrier applications have a restriction. |
| Black King Bar | [116](https://www.dota2.com/datafeed/itemdata?language=english&item_id=116) | Active basic dispel and defensive window. The guide requires checking the threatening spell's immunity behavior. |
| Aeon Disk | [256](https://www.dota2.com/datafeed/itemdata?language=english&item_id=256) | Threshold-triggered strong dispel and temporary zero dealt/received damage; cooldown grows on procs. |
| Lotus Orb | [226](https://www.dota2.com/datafeed/itemdata?language=english&item_id=226) | Basic dispel and targeted spell reflection; original damage is not cancelled. |
| Ghost Scepter | [37](https://www.dota2.com/datafeed/itemdata?language=english&item_id=37) | Physical protection, increased magic vulnerability, and incompatibility with debuff immunity. |

No competitor guide text was copied. No Dota2ProTracker/Dotabuff automated data
collection, paid data purchase, or OpenDota integration was introduced.

## Freshness contract

`narma_video.build_reviews.review_payload(updates)` accepts the existing bounded
Valve updates payload. It reads checked-in guides and returns
`narma.build-reviews.v1`, with a `guides` map keyed by guide ID. It performs no
network requests, accesses no user data, and never reads provider credentials.

Each guide contains `state`, `reason`, `verified_patch`, `checked_at`,
`final_checked_at`, `review_due_at`, compatible `adaptations`, scoped
`adaptations_checked_at` / `adaptations_verified_patch`, and `patch_notes`.

- `reviewed`: healthy Valve feed younger than 30 minutes, matching patch,
  authored mechanics review younger than seven days.
- `review_due`: same confirmed patch but the authored review is seven days old.
- `patch_changed`: healthy official feed identifies a different patch; authored
  patch/date remain unchanged.
- `unknown`: current patch cannot be confirmed, or review/date data are invalid.

The feed's own `checked_at` is not an editorial check. A healthy feed cannot
refresh a guide's authored date or make its popularity/efficiency claims valid.
The original full-guide `checked_at` dates remain 2026-09-08. This change records
only the specific new alternatives at 2026-09-09; a new full review must examine
the full guide before updating its original date. A final-inventory edit also
does not extend the full-guide review window.

Unknown/stale status does not erase useful authored explanations. Players see
their status and sources. Operators must review the guide after a new patch;
this release does not pretend that source polling performs coaching research.

## Verification

`PYTHONPATH=services/video python3 -m unittest discover -s services/video/tests -p test_build_reviews.py -q`

Nine deterministic tests cover feed failures and age, new patches, future and
invalid editorial dates, the exact seven-day expiry, unchanged dates after feed
refresh, fixed official source links, and six-slot compatibility for every guide.
Invalid alternatives that duplicate a final item, remove boots, use an
unreviewed item, or combine a known component and upgrade are excluded.

Runtime integration, frontend interaction and deployment are separate release
checks. Passing these tests alone does not establish a successful live rollout.
