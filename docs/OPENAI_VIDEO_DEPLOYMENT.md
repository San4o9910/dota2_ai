# Owner-funded OpenAI API and selective video release

Prepared 2026-09-12 for `San4o9910/dota2_ai`. This document describes the implemented
deployment path. It is not a receipt that a key, API allowance, model request or
production release has been activated.

## Status at preparation

- Target remains the existing Timeweb VM **9037783**, project **2655641**, IPv4
  **72.56.98.68**, public [Narma Vision](https://narma-72-56-98-68.sslip.io).
  No new hosting, resize, GPU rental, prepaid period or model purchase is made.
- Last successful pilot deployment found through read-only GitHub Actions:
  [`d1d9d03a9cf844df169948699ce88049f3b880d4`](https://github.com/San4o9910/dota2_ai/actions/runs/34404352510),
  completed 2026-09-09. This is recorded deployment evidence, not a fresh SSH health
  probe of the server on September 12.
- The September 12 [backup retry, attempt 3](https://github.com/San4o9910/dota2_ai/actions/runs/34682426796/attempts/3)
  passed SSH, downloaded the database backup and restored it in an isolated
  container. Validation then failed with `backup_provider_restore_invariants_failed`.
  That run checked out `8305600893cf7dbe9c81b8d96b31383f052428e4`; its provider
  validator rejects every legitimate Hermes call added by migration 011. This is
  a confirmed validator defect, not proof that it is the only live inconsistency.
  Run `timeweb-backup-daily.yml` after its pinned checkout is updated to the
  reviewed correction, and obtain a successful restore result before production
  deployment. Re-running the old attempt keeps its old validator.
- No `OPENAI_API_KEY` or Timeweb credential was available in the local work
  environment. Repository secret values and their presence cannot be inspected
  through the installed GitHub connector. This is not proof that a repository
  secret is absent. No private values or raw provider logs were exported.
- The owner authorized a cumulative OpenAI allowance of **$5** and reported adding
  `OPENAI_API_KEY` to Actions secrets. Prepared deployment inputs are
  `build_stats_source=authored`, `prepare_openai_api=true`,
  `openai_limit_microusd=5000000`, `openai_expires_at=2026-09-19T23:59:59Z`, with
  `prepare_chatgpt_auth=false` and `activate_hermes=false`. The allowance has not
  yet been applied on the server.
- Exact-commit CI receipts are recorded in PR #3. Successful API use, real-game
  quality and measured average cost require their own release evidence.

## Server-side configuration

| Setting | Use |
| --- | --- |
| `OPENAI_API_KEY` | Owner's paid API project key; server only |
| `OPENAI_MODEL=gpt-5.6-sol` | Pinned reviewed model; arbitrary model substitution is rejected |
| `OPENAI_MAX_DAILY_CALLS=20` | Default per-customer cap; validated range 1–250 |
| `REPLAY_COACH_PROVIDER=openai_api` | Structured `.dem` and video coaching via owner-funded API |
| `HERMES_PROVIDER=openai_api` | Hermes uses the budgeted API broker |
| `HERMES_RUNTIME_ENABLED=1` | Explicit cutover enables scheduler; ordinary releases preserve its flag |
| `VIDEO_ANALYSIS_MODE=selective_v1` | Overview plus selected detailed video episodes |
| `GEMINI_API_KEY`, `GEMINI_MODEL=gemini-3.8-flash` | Existing vision stage; its durable allowance stays separate |

The Compose default video mode is `full_frames_v1`; installing code alone does not
silently convert pending work to the new mode. The explicit API cutover selects
`selective_v1`. New job policy must remain immutable after creation.

The backend API, replay worker, video worker and Hermes broker receive the API
configuration. The browser, static assets, Hermes runner, database service and
migration service receive no OpenAI key. The runner stays on the internal
`hermes-private` Docker network and reaches the provider through the broker only.
Personal ChatGPT OAuth is not a fallback for the shared platform API.

The new migrations include `018_openai_api.sql`, `019_selective_video.sql`,
`020_hermes_openai.sql`, `021_portal_multiple_accounts.sql` and
`022_openai_cache_pricing.sql`. The portal's former singleton account database constraint is removed
for customer isolation. This does not create public registration. See
[Hermes API integration](HERMES_OPENAI_API.md).

## Add the key

The owner creates a key in the API project and saves it as the repository **Actions
secret** named exactly `OPENAI_API_KEY`:

- [OpenAI API keys](https://platform.openai.com/api-keys)
- [Narma repository Actions secrets](https://github.com/San4o9910/dota2_ai/settings/secrets/actions)

Do not paste the key into an issue, chat, workflow input, repository variable or
source file. API billing is separate from a personal ChatGPT subscription.

`openai-support.yml` provides optional `inspect` and `install-key` modes for the
existing host. It requires the **exact currently installed** 40-character release
SHA, which may differ from the workflow branch SHA. `inspect` does not receive the
OpenAI key. `install-key` installs a missing key or accepts an identical retry; it
refuses to overwrite a different existing key. Deliberate rotation is a separate
operator procedure. Other secrets and configuration remain unchanged.

This support operation never restarts a service, selects a provider, enables an
allowance or sends an inference request. It uses the established Timeweb temporary
SSH-key path and removes its binding afterward. The credential crosses encrypted
SSH stdin into `/opt/narma/secrets/video.env` using an atomic mode-0600 write. Its
output contains only presence/configuration booleans and fixed status labels.

The workflow is manual only. GitHub must have the workflow registered on the
default branch before the normal **Run workflow** UI is available. Run the reviewed
branch; publishing a feature branch alone does not prove dispatch or installation.
The existing pilot workflow can also install the first key during explicit API
cutover, so the support workflow is optional.

## Allowances and cost controls

The reviewed Sol tariff separates ordinary input ($4/M tokens), cache reads
($0.40/M), cache writes ($5/M) and output including reasoning ($20/M).
Reservations allow for the highest input rate. Actual usage is settled with
integer micro-USD accounting, rounding upward once per call; reasoning tokens
are already included in output tokens. If write telemetry is omitted, the ledger
conservatively prices non-cached input at the write rate; that is an upper bound,
not a measured invoice amount. See the official
[model pricing](https://developers.openai.com/api/docs/models/gpt-5.6-sol) and
[cache accounting](https://developers.openai.com/api/docs/guides/prompt-caching).

Explicit prompt caching marks only the reusable developer instructions. Each
match's evidence follows the breakpoint and is not requested as a cache write.
This keeps the selected model and coaching evidence intact. Cache reuse is not
guaranteed, and actual savings require real usage measurements.

Migration `022_openai_cache_pricing.sql` changes the allowance policy only when
there are no unsettled calls or reservations. It preserves previous charges,
limits, expiry and freezes. With outstanding obligations it disables new spending
and retains the old policy and holds for reconciliation. Existing request hashes
are not rewritten to match the new caching payload. Resolve outstanding requests
before this upgrade; an old saved request must not be silently sent again.

`openai_api_budget` is a separate durable monetary ledger. Its migration starts
disabled with a zero ceiling. Neither an API key nor an environment flag enables
spending. The operator may keep it disabled while code and configuration checks
run. The old Gemini ledger is never reset or appropriated for OpenAI.

For a concrete pilot, choose the total ceiling and expiry through the two optional
workflow inputs `openai_limit_microusd` and `openai_expires_at`, together with
`prepare_openai_api=true`. One USD is 1,000,000 micro-USD. Blank inputs preserve the
current allowance exactly. A supplied pair is validated before cloud operations:

- ceiling must be greater than zero and at most **10,000,000 micro-USD ($10)**;
- expiry must be a future UTC `YYYY-MM-DDTHH:MM:SSZ`, no later than
  **2026-11-21T00:00:00Z**, the reviewed model price-policy boundary;
- the ceiling is cumulative, not a new balance or a daily refill;
- lowering it below spent plus reserved funds is rejected;
- frozen accounting cannot be cleared by deployment;
- existing spend, reservations, unknown charges and customer identity are retained.

For an operator already on the VPS, the equivalent explicit command is:

```bash
cd /opt/narma/current/services/video
docker compose --project-name narma-video --env-file /opt/narma/secrets/video.env exec -T api \
  python -m narma_video.openai_budget configure \
  --limit-microusd CHOSEN_TOTAL_CEILING --expires-at CHOSEN_UTC_EXPIRY --enable
```

Replace both placeholders with the owner's chosen pilot values. This document does
not run the command or authorize a fresh monetary ceiling. Status is read-only:

```bash
docker compose --project-name narma-video --env-file /opt/narma/secrets/video.env exec -T api \
  python -m narma_video.openai_budget status
```

Never print the full env file or rendered Compose configuration. No automatic
retry after an uncertain paid attempt is added by deployment. A rejected coach
answer can still have incurred cost; usage accounting must reflect the attempt.

## Release path

1. Publish and pass `deep-learning-ci.yml` on `codex/openai-video-coach`. The push
   workflow runs operational unit tests, PostgreSQL migrations/application tests
   and browser flows including `check-video-workspace.mjs`. It has no provider key
   and performs no production deployment. Local emulation is not a replacement
   for these native PostgreSQL and container gates. Then run
   `timeweb-backup-daily.yml` with the corrected pinned checkout and require
   `backup_complete` with `restore_verified=true` before continuing. The restore validator freezes
   paid allowances only in its isolated copy and preserves live billing history.
2. Register the reviewed `timeweb-pilot.yml` on the default branch without
   changing its triggers or job conditions; GitHub requires this for manual
   dispatch. The default branch itself does not pass the deployment job guard.
   Run **Timeweb pilot deployment** on `codex/openai-video-coach`, with
   `prepare_openai_api=true`. `prepare_chatgpt_auth` and `activate_hermes` must remain
   false; the modes are mutually exclusive. Supply the API secret or keep the same
   already installed secret. A missing key fails with `missing_openai_secret`
   before copying the new release or changing host configuration.
3. The established release flow checks the pinned server, builds images off-host,
   retains exact rollback images and snapshots workers before its normal
   migration/restart cutover. Its OpenAI settings snapshot contains only previous
   non-secret provider settings. No database/password/key rotation occurs.
4. `prepare_openai_api.py` checks the schemas, selected provider, API-key presence,
   shared `resource_lock.py`, and existing ledgers in a read-only transaction.
   It checks isolated Hermes runner/broker networking with the scheduler paused
   during release preflight. It neither creates a task nor requests generation.
5. Only after those checks may the explicit allowance pair configure the OpenAI
   ledger. The original ceilings otherwise remain unchanged. The normal scheduler
   and video/replay workers then resume with their provider and budget guards.
   `.dem` parsing and video media processing use the shared PostgreSQL resource
   lock to serialize heavy work on the existing 8 GiB host.
6. Both replay and video workers must produce fresh heartbeats; Hermes broker
   health and network isolation must pass. Preserve the exact installed SHA and
   readiness receipt. User-created queued jobs may run after normal queues resume;
   the release itself submits no synthetic paid job.
7. Verify one authorized real game with actual settled usage and validated output
   before describing API access, coaching quality or per-match cost as measured.

An ordinary later release reads the existing provider selection and preserves
`openai_api`; it cannot silently switch the platform back to personal OAuth. An
explicit first API cutover enables the Hermes scheduler flag; ordinary updates
preserve its previous value. A previously selected personal provider is preserved
only as that legacy mode, never expanded to a shared all-customer subscription.

## Readiness and rollback

The deployment validates provider checkboxes and the explicit allowance before
building images or contacting the server. A ceiling requires a future
`openai_expires_at`; leaving only that field blank is an error. To correct inputs,
start a new **Run workflow**: **Re-run jobs** retains the original inputs.

`--status-only` is available on the installed release:

```bash
python3 /opt/narma/current/ops/timeweb/prepare_openai_api.py INSTALLED_RELEASE_SHA --status-only
```

It does not pause services, change configuration or invoke a provider. It is an
OpenAI-mode preflight: an old/missing configuration fails rather than inventing a
successful connection. Key presence/model selection means **configured**, not
**provider access verified**. A successful release receipt deliberately reports
`provider_access_verified=false`, `generation_smoke_performed=false`, and zero
calls created by preflight. Hermes's customer-specific `runtime_verified` requires
a settled, validated review tied to that customer's evidence.

Release failures use the existing exact-image/worker rollback and restore the
non-secret OpenAI selection snapshot. The API key survives rollback, as do all
budget ledger entries and any explicit allowance change already committed. No
rollback deletes customer data or refunds a potentially billed request. Failure
to confirm rollback must be reported honestly with the installed SHA and safe
status code.

Repeated deployments of the same SHA capture a fresh settings baseline. A unique
attempt marker prevents an early secret-write failure from restoring an older
attempt's provider settings. An existing pair of video/replay workers is accepted
only when both installed containers prove the OpenAI/selective configuration,
same release, shared media-lock bindings and identical database connection
identity. Legacy worker configurations keep the single-worker restriction.

The old `activate_video.py` full-frame synthetic paid smoke is not used by the new
selective release path. Installing an API key alone does not run that script.
