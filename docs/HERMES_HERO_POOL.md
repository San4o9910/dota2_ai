# Hermes and the hero pool

Status: **integration context prepared; Hermes is not installed or running**.
The preparation adds no provider calls, API keys, SDK dependencies, scheduled
jobs or new infrastructure expense. The hero pool and its factual trends work
without Hermes or OpenDota.

## What has been verified

Checked on 2026-09-07 against the official Nous Research documentation:

- [Hermes Agent v0.21.0](https://github.com/NousResearch/hermes-agent/releases/tag/v2026.8.31),
  release tag `v2026.8.31`, commit prefix `29112be`, is an MIT agent framework.
  It is a different product from the Hermes language-model family.
- The [tagged project requirements](https://github.com/NousResearch/hermes-agent/blob/v2026.8.31/pyproject.toml)
  specify Python `>=3.11,<3.14`. The [Linux installer](https://hermes-agent.nousresearch.com/docs/getting-started/installation)
  supports an unprivileged service account and skipping browser/computer use.
- [Native Gemini integration](https://hermes-agent.nousresearch.com/docs/guides/google-gemini)
  accepts `GOOGLE_API_KEY` or `GEMINI_API_KEY` and uses Gemini API project quota.
  This does not establish that a consumer Gemini subscription covers platform
  requests. NARMA must account for every API call in its existing spending ledger.
- [Memory](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory)
  belongs to a Hermes home/profile. [Profiles are not sandboxes](https://hermes-agent.nousresearch.com/docs/user-guide/profiles).
  A shared profile must not contain unrelated customers' reports or observations.
- [MCP](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp)
  supports exact tool allowlists and disabling resource/prompt utilities and
  model sampling. This can expose a small owner-scoped factual API in the future.

## Current contract

`build_hero_coach_context` accepts the already authenticated result of
`hero_pool.get_pool`. It selects one canonical hero and one explicitly selected position
from 1 to 5, then exposes at most the latest 20 matching games. It is a pure
projection: it does not query a database or establish ownership itself. The
caller must obtain the pool using the authenticated account, never accept a
client-supplied pool as trusted input, and never accept an account ID from the
agent as an authorization decision.

The context contains only explicitly allowed metrics, existing deterministic
patterns and references to selected reports. Nicknames, Steam/account/owner
identifiers, free-form notes and arbitrary report fields are excluded. Match ID
and report job ID remain as evidence references; they are not authorization
credentials. Positions are self-reported, not verified game-role detections.
Unknown positions are excluded. Missing or different engine builds
and an unknown patch remain explicit limitations.

`validate_hero_coach_annotations` validates hypothetical agent output without
calling a model. An agent may prioritize and annotate at most three existing
patterns. It cannot create a pattern ID, invent a report/timestamp reference,
change deterministic observations or attach numeric claims to narrative text.
Exact measurements remain server-produced fields referenced by metric ID.
Validation of prose is a structural/numeric guard, not proof of semantic truth:
qualitative proposed actions still need evaluation before enabling publication.

## Activation design

1. Build an image from the verified upstream release and pin its complete commit
   and image digest. Review its actual dependency lock before enabling it.
2. Start one isolated non-root one-shot process per dataset revision. No public
   dashboard, shell, browser, arbitrary SQL, cloud administration, delegation,
   auto-installed skills or network tools are needed for this task.
3. Keep longitudinal evidence and plans in owner-scoped PostgreSQL. Supply an
   ephemeral Hermes home and only the selected context. Do not share mutable
   Hermes memory across customer accounts.
4. Route inference through a metered gateway using NARMA's existing provider-call
   ledger and global/request limits. Do not hand the agent a direct Gemini key
   that bypasses these limits. Unknown-billing calls retain their reservation;
   never retry them automatically or reset the ledger to make another call.
5. Deduplicate jobs by owner, hero, self-reported position, context dataset version,
   model and instruction version. Unchanged data does not need another AI call.
6. Initially allow one job at a time. A 1 CPU / 1 GB container limit and 120-second
   external deadline are proposed starting limits, not measured upstream
   requirements. Measure RSS under load alongside the replay worker before
   activation on the existing 4 CPU / 8 GB server. A second server is not yet
   justified by this preparation.
7. Persist only validated annotations as a separate version. Preserve factual
   charts, win rates and prior successful coaching on a provider failure. Show
   the actual status and last success time; do not label preparation as an
   active Hermes agent.

[Hermes configuration](https://hermes-agent.nousresearch.com/docs/user-guide/configuration)
currently defaults to unlimited agent turns and multiple provider retries. Turn
limits permit a final grace call. Compression and auxiliary tasks can add calls;
MCP sampling can also generate inference. Consequently, `max_turns` is not a
monetary cap. Explicitly disable these extra routes and enforce the independent
gateway ledger and process deadline before activation.

The long-term feature measures observable changes: hero/position results,
early farm and deaths, repeated item-delivery/use patterns and training progress.
It does not claim to directly measure a person's understanding of Dota or infer
intent from a single statistic. Conclusions require enough comparable games.
