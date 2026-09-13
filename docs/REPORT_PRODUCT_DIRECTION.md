# Report direction from owner feedback, 2026-09-13

The owner wants a Dota coach whose report explains what happened, which decisions
matter and what to practise next. A working deployment and a collection of charts
do not establish that this product goal has been met.

## Reference actually inspected

- Owner reference: https://aidota2.ru/player/435842051/ai
- Public match preview inspected in the browser:
  https://aidota2.ru/player/1044002267/match/8960991322/event/0

Observed: role context, named event cards on a time-labelled chart, event-category
filters, readable explanations and a match-summary entry point. The separate AI
coach advertises mistakes, play style, growth plan, matchups, itemisation and
timings. That coach and most match explanations required Steam sign-in; their
contents, quality and history/memory behaviour were not verified.

## This correction

- Put the existing grounded coaching and next-game plan before numeric drilldown.
- Replace tiny death/kill/purchase markers with readable time buttons, event
  details and a comparison before/at the selected event.
- Keep charts and event references useful for checking a coaching claim.
- Distinguish a parsed factual report from a usable AI commentary. Show the
  bounded failure reason and recorded usage of the exact owned call when known.
- A saved or archived report must not imply another paid request, successful new
  coaching, or usage belonging to another source/context.

This correction does not establish why the owner's third analysis stopped using
OpenAI. That requires the actual call/failure/allowance evidence. It does not
increase funding, clear unknown charges or force repeat generation.

## Product acceptance still needed

Review actual owner matches: can the player identify a useful next-game action,
open its evidence, understand the coaching's limits and distinguish a factual
fallback from an AI response? Confirm repeated-game coaching and improvements
with real history before claiming a personal long-term coach or parity with the
reference. Do not invent grades, causes of death, matchup benchmarks or progress
scores to make the interface resemble a competitor.
