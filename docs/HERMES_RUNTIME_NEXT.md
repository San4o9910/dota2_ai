# Hermes runtime: implementation checkpoint, 2026-09-08

**Status:** real Hermes is not installed or invoked by Narma Vision. The existing
`hermes_bridge.py` implements bounded evidence export and review import. Neither
those routes nor computed hero-pool patterns are a running agent. The technical
connection/export panel has been removed from the customer interface. This
document does not activate a runtime or authorize an additional allowance.

The missing work is implementation, not another user approval. Existing project
development/deployment authorization and the existing Gemini allowance remain
applicable. No new account, provider credential, server or subscription has been
identified as necessary. Actual remaining budget and server memory headroom must
be measured during activation; this investigation did not read their live values.

## Verified upstream contract

Inspected source: official [NousResearch/hermes-agent at
9fd44b4dfc44138b9e5d5689acb56c438364ff7b](https://github.com/NousResearch/hermes-agent/tree/9fd44b4dfc44138b9e5d5689acb56c438364ff7b).
This pins the inspected revision, not a claim that this revision has passed a
Narma runtime smoke test. The checkout was read without installing dependencies
or making inference calls.

The [official embedding guide](https://hermes-agent.nousresearch.com/docs/guides/python-library)
supports an upstream checkout with `uv sync`, followed by importing
`run_agent.AIAgent`. It supports a custom `base_url` and `api_key`, and returns
`final_response` from `run_conversation()`. Use a new instance for each task.

At the inspected revision, `run_agent.AIAgent` additionally accepts explicit
`provider`, `api_mode`, `max_tokens`, `skip_background_review` and
`run_budget_seconds`. Its default iteration count is unlimited; the docs' default
must not be relied upon. Empty `enabled_toolsets=[]` means no tools. The
initialization code discovers plugins regardless, so an empty isolated profile
is still needed. `skip_memory=True` alone does not disable compression or the
background review. Configure `compression.enabled=false` and pass
`skip_background_review=True`. Auxiliary and main paths have separate
retry/fallback machinery. An iteration limit or final aggregate usage callback
is therefore not an enforceable spend boundary. See the pinned
[initialization](https://github.com/NousResearch/hermes-agent/blob/9fd44b4dfc44138b9e5d5689acb56c438364ff7b/agent/agent_init.py)
and [auxiliary client](https://github.com/NousResearch/hermes-agent/blob/9fd44b4dfc44138b9e5d5689acb56c438364ff7b/agent/auxiliary_client.py).

## Minimal implementation on the existing server

1. Add durable `hermes_tasks` keyed by owner, bound game account and immutable
   snapshot hash. Use a fenced lease, bounded attempts and idempotent completion.
   Enqueue eligible snapshots after a report becomes ready; skip inference when
   there are fewer than two distinct eligible matches. Position/date/source
   changes and deletion must invalidate tasks and recommendations using the
   existing bridge's checks. Do not spend again on an identical completed
   snapshot. Store longitudinal context in Narma's database.

2. Extend `video_provider_calls` with an explicit Hermes task reference and
   `call_kind='hermes'`; preserve the constraint that each call has exactly one
   owning task. Reuse the same `video_ai_budget` row, `reserve`/`settle` accounting,
   model, price policy, daily owner limit and uncertain reservations. Do not
   classify Hermes calls as replay calls: that would misattribute the workload
   and collide with the existing replay lifetime-attempt rule.

3. Implement a private OpenAI-compatible `/v1/chat/completions` broker. Hermes
   receives only an expiring task credential; the broker resolves owner/task from
   that credential. It validates the lease and snapshot, reserves before **each**
   provider attempt, then calls the existing Gemini GenerateContent API with
   SDK retries disabled, fixed model and bounded input/output. Read raw Gemini
   usage and settle in `finally`, including invalid output, cancellation and
   timeout. Unknown usage retains the reservation. Reject unsupported models,
   tools, media and unbounded requests before inference. Every retry is another
   reservation or is denied by the task/global limit. Non-inference `/v1/models`
   can expose the one approved model. Do not trust Hermes' reported aggregate
   token total for billing.

4. Build a separate, pinned upstream runtime environment and invoke the actual
   `AIAgent`, using `provider='custom'`, `api_mode='chat_completions'`, the broker's
   URL, no tools, no context files, no memory, no background review, no fallback
   model, explicit iteration/output bounds and a hard process deadline. Disable
   compression in its generated empty profile. Use a fresh temporary profile per
   task; inject only the validated snapshot and relevant prior goals. The runtime
   gets no Gemini key, database connection, host mounts, Docker socket or client
   credentials. Give it only an internal network with the broker; the broker is
   the sole component with provider egress. This ensures auxiliary or retry paths
   cannot bypass accounting even if upstream behavior changes. No public Hermes
   gateway/dashboard is needed for this use case.

5. Validate strict JSON with the existing bridge's schema and match-local
   evidence checks. Record verified runtime revision and source snapshot in
   server-controlled provenance, separate from model text. Show useful pattern
   observations, a next-game goal and subsequent evidence in the pool. Keep
   operational connection/export controls outside the customer page. A runtime
   attestation proves which software ran, not the truth of every interpretation;
   generated prose must not become measured win-rate, MMR or a fabricated
   understanding score.

## Activation evidence still required

- Real pinned `AIAgent` against a synthetic local broker: valid output,
  malformed output, provider retry, auxiliary attempt and deadline termination.
- Native PostgreSQL checks: concurrency, exhausted/disabled allowance,
  unknown-usage retention, lease loss, duplicate snapshots and cross-owner access.
- Container check that the runner can reach its broker and cannot reach Gemini
  or any alternate model provider directly; no shared writable player profile.
- Existing-server memory/resource check, then one bounded real review with the
  shared ledger's before/after values and saved evidence references. Failure must
  leave existing replay analysis and hero-pool facts usable.

None of these runtime activation gates were performed by the UI correction.
Installing a package alone, exposing an export button, or renaming the existing
Gemini replay coach would not complete this integration.
