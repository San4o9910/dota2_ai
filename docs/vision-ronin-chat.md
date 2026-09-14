# NARMA Vision: Ronin, teaching modes and coach conversation

The active application is the FastAPI/Clarity portal on Timeweb, released from
`codex/openai-video-coach`. This change does not deploy the older Sites app.

The public pages and personal portal share `vision-theme.css`: Noturno #001621,
Vulcanico #FF4103 and Milky #FFFDF1. Forms, focus states, navigation, responsive
layouts and reduced motion share the same treatment. Match team colors and
economy chart encodings keep their meaning.

An explicit training depth now requests `narma.replay-coaching.v3`. The response
must identify the selected depth and include a three-part lesson: a concept,
steps and check for foundations; options, selection condition and exception for
application; opportunity cost, uncertainty and cancellation condition for
advanced. These lesson fields receive the same reference, text and numeric-claim
validation as the rest of the replay commentary. The ordinary mode retains v2.
Exact previously paid legacy/v2 requests remain readable and are never rebilled
because a response contract changed. Match telemetry is independent of depth.

The coach and full replay pages expose a shared conversation. GET reads history;
only an explicit POST asks the model. A question is bound to the authenticated
owner, pinned player, ready replay, report hash and current position/MMR/depth.
Up to six successful earlier turns provide bounded conversational context.
Answers link only to evidence from the current report. A changed report or role
opens a separate context; old text is not silently applied to new facts.

Migration 024 adds chat turns and permits a chat task in the existing OpenAI call
ledger. It does not alter the allowance, expiry, spend or outstanding reservations.
Each turn has one attempt, a lease, an idempotency key, the existing daily call
limit, at most one active turn per owner and at most forty turns per report/context.
Deletion removes question/answer/input text while retaining paid accounting.
Provider failures do not fabricate an answer or automatically retry. Missing
usage retains the reservation. No live paid smoke test is part of verification.

Verification: the existing Python/native PostgreSQL and browser suites, plus
`test_coach_chat.py`, `test_replay_mode_contract.py` and the conversation scenario
in `check-portal-ui.mjs`. Use only the isolated CI database and fake providers.
Release through the existing Timeweb workflow with preserved AI configuration.
