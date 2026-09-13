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

## Personal coach correction

The owner explicitly rejected treating the reference as a request to redraw a
chart. The primary product is a personal coach: identify a decision worth
reviewing, understand an alternative, practise it, then return to comparable
matches. The dedicated `/coach` workspace brings these actions together.

| Player question | Product behaviour | Evidence boundary |
| --- | --- | --- |
| Where should I start? | Choose a saved match and read its coaching focus and next-game task. | A parsed report without usable coaching is labelled as such. |
| What could I do differently? | New OpenAI responses contain a decision question, reasoning, conditional alternative and exception. | Every point cites current replay events; an outcome alone is not a mistake. |
| What should I keep doing? | Supported strength points can appear in a separate group. | The model is not required to invent praise or a strength for every match. |
| What repeats across my games? | Saved AI observations from the existing verified review and deterministic history observations are distinguished. | Show the supporting matches, hero, role and sample size. No invented personality, rating or progress score. |
| What do I practise next? | Show the active practice and open its existing journal. | Practice completion remains an explicit player review; match outcome does not imply mastery. |
| Can I check this claim? | Open the referenced saved report and its exact event. | Event identifiers are resolved within that report, including for archived reports. |

Opening this workspace reads existing account-scoped data. It does not generate
a new model answer. Existing reports keep their original text; new layout must
not fabricate missing decision fields in legacy commentary. The expanded format
is for new OpenAI responses, with compatible reading of earlier settled calls.

The reference's AI page was checked again directly in the browser. It still
requires Steam login and advertises mistakes, style, growth planning, matchups,
itemisation and timings. Public event cards, categories, role selection and a
link to a development tree were visible. The development tree and the full
personal coach were not inspected, so parity with those features is not claimed.

Remaining product work includes independently reviewing real coaching quality,
adding trustworthy matchup/item timing references where data permits, and
evaluating whether previous comparable match facts should enter the single-match
OpenAI prompt. Displaying existing history together is not proof that this prompt
has long-term memory. These gaps must not disappear from acceptance reporting
merely because the deployment is green.
