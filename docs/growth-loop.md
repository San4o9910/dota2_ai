# NARMA Vision: next-game learning loop

The owner approved practice follow-up, cross-match conversation, personal replay
exercises, a short report, feedback, owner operations and share cards. The visual
choice for the signature motion remains open; no candidate is activated in the
production interface until the owner selects it.

## Player experience

- Practice follow-up reads canonical owned history. It shows a baseline and up
  to five post-plan measurements on the same hero and manually selected role.
  Duplicate, pre-plan, undated and known different-build games are excluded.
  Unsupported exercises request manual review. Measurement changes never certify
  correct choices, mastery or MMR gains. Existing self-reports stay separate.
- Chat offers this-match and cross-match scopes. The latter adds up to two
  same-hero/role matches, bounded evidence and the current valid exercise. History
  can be read from later matches. Referenced reports and roles are checked again
  before dispatch and before publication. Old answers are interpretations, not
  factual input for new match claims. Opening history does not call a provider.
- Personal exercises use real event anchors and authored decision questions. The
  player writes an answer before seeing conditions, alternatives and exceptions.
  This is self-review, not an unperformed AI assessment. Discussing the answer
  populates the chat composer; it still requires an explicit send.
- A short report highlights one strength, a decision to review and a next action
  from the existing saved commentary. Missing conclusions are not fabricated.
- Feedback stores a reason, optional note and exact report/advice reference. The
  player sees that feedback goes to the platform owner. It does not silently
  regenerate a paid report. An optional button prepares a clarification in chat.
- A PNG card is previewed on the player's device. Nickname and match ID are
  hidden by default. A separate download/share action is required. No public
  report endpoint is created and no Telegram message is sent automatically.

## Owner and operations

`/owner` and `/api/owner/dashboard` are platform-owner-only. They summarize jobs
from seven days, cumulative provider costs by task and user, held/unknown costs
and submitted feedback. Completion time includes upload and queue time. Server
costs and invoices are not inferred from provider ledgers.

An optional cumulative per-user money ceiling applies to the OpenAI and Gemini
reservation paths under their shared per-owner lock. NULL preserves the existing
global and daily limits. Zero blocks new reservations. Editing requires a fresh
password/session check; existing spend, holds and global allowances never reset.
Already dispatched requests still settle their observed usage.

Migration 025 adds feedback, exercise attempts, optional user ceilings and chat
source manifests. Replay deletion erases the associated user text and chat
conversations referring to that source while retaining provider accounting.

The monitor logger now accepts an event name independently of a check's `name`
field. Its regression test invokes the actual JSON writer for all severity levels.
The scheduled default-branch monitor must pin a tested revision with this fix;
its schedule and permissions do not need changing.

## Motion candidates for owner selection

1. **N cut**: a short orange diagonal separates and recombines the N mark; 800 ms.
2. **Focus**: four brackets converge on the mark or selected episode; 950 ms.
3. **Trajectory**: a short path links a match, observation and next step; 1100 ms.

The chosen motif should have a shorter UI variation, appear only on meaningful
transitions, never block interaction, never loop, and honor reduced motion. No
audio or persistent background motion is proposed.

## Verification and limits

Native PostgreSQL tests cover ownership, idempotency, scopes, role changes during
an answer, source deletion and spending limits with fake provider responses.
Browser scenarios cover explicit sending, exercises, feedback, private preview,
download, responsive layout, accessibility and existing login/report behavior.
No test here calls paid AI or raises the existing five-dollar allowance.

Real-match teaching quality and throughput still require evidence on the deployed
service. Map reconstruction remains conditional: the current probe exposes raw
cell/offset positions, but a validated patch-specific transform and perspective
are not established. This change does not draw invented hero movement.
