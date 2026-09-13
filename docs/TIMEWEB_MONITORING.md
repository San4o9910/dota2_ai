# Timeweb operational monitoring

This monitor checks the existing NARMA VM `9037783` in project `2655641`, IP
`72.56.98.68`. It does not restart services, delete media, renew an AI allowance,
reconcile charges or perform generation. The application snapshot runs inside a
PostgreSQL read-only transaction and emits aggregate counters only. There is no
public endpoint for budget, queue or worker information.

## Checks and interpretation

| Check | Warning | Critical |
| --- | --- | --- |
| Public HTTPS `/livez` | — | TLS/HTTP/read failure or unexpected liveness response |
| Worker heartbeat | — | Expected worker has no heartbeat or latest heartbeat is older than 15 minutes |
| Queue | Oldest queued job waiting at least 30 minutes | Waiting at least 2 hours, or processing lease expired more than 5 minutes ago |
| Media filesystem | Free space below 4 GiB or 10% | Below 2 GiB or 5%, or filesystem cannot be inspected |
| AI allowance | At most 20% unspent/unreserved capacity, or at most 48 hours to expiry | Expected provider disabled/frozen, expired or no remaining capacity |
| OpenAI accounting | Unknown billing holds or reservations expired more than 5 minutes ago | Budget counters differ from the durable call ledger |
| Daily backup restore drill | — | No successful default-branch run in 36 hours, newer failed/cancelled run, disabled workflow or unavailable evidence |

Replay worker is expected for this standalone replay platform. Video worker and
Gemini allowance are expected in `selective_v1`; Hermes worker is expected when
`HERMES_PROVIDER=openai_api`. OpenAI is expected if replay, selective video or
Hermes selects it. A missing old worker in a mode that does not use it is not an
outage. Work can keep a heartbeat occupied for several minutes, hence the
15-minute bound; this is not a five-second response-time guarantee.

The snapshot includes queued/processing/failed counts, but does not print owners,
nicknames, match/job IDs, source filenames, prompts, provider responses, session
values, connection strings, tokens or arbitrary exception text. The runner
validates the snapshot schema before forwarding it into Actions logs. The two AI
allowances remain separate. Unknown OpenAI charges stay reserved; monitoring
never clears them or treats them as refundable balance.

Backup freshness uses the existing daily restore-drill workflow's completion
result, with age measured conservatively from its start time. It does not perform
a new S3 inventory or prove retention of source media. A new in-progress attempt
cannot hide a more recent failed backup. Existing backup creation, retention and
restore code is unchanged.

## Registration and first check

1. Run the operational unit tests and the native PostgreSQL test suite against
   the candidate commit. Deploy the candidate including
   `narma_video.operations_health` into the API image. The prior `6b388397…`
   deployment does not contain this command.
2. Replace `CHECKOUT_PRODUCTION_MONITOR_SHA` in `timeweb-monitor.yml` with the
   full immutable tested source SHA. Register that workflow on the default
   branch. The default branch currently need not contain the application code;
   checkout uses the pinned commit. Never replace this with an untested moving
   branch merely to make the first run succeed.
3. Run `Timeweb operational monitor` manually with `notification_test=false`.
   Confirm `operations_monitor_complete` and inspect every non-OK check. A
   successful GitHub job alone does not prove notification delivery.
4. Confirm a subsequent `schedule` run. The intended schedule is minute 17 and
   47 of every hour UTC. It uses its own concurrency group and cannot replace a
   queued deployment or backup. A read during deployment may report a transient
   unavailable snapshot; repeat after the deployment finishes.

The runner uses the existing `TIMEWEB_CLOUD_TOKEN` to read the exact pinned VM
identity and install one short-lived SSH key, then removes both its binding and
key in `finally`. The SSH snapshot is read-only; the key lifecycle is the only
intended Timeweb mutation. Failed key cleanup is an operational failure, never
silently accepted. A terminated runner can still require manual key cleanup;
names start with `narma-monitor-`. The SSH host-key trust model is the existing
pilot's API-verified IP plus first-use key capture, not an independently pinned
host-key fingerprint. `GITHUB_TOKEN` has only `contents: read` and `actions: read`.

## Notifications and delivery evidence

Both warning and critical monitor results fail the workflow. This lets configured
GitHub Actions failure notifications warn before a budget expires. The workflow
does not contact Telegram, email APIs, Slack or any other messaging service.

Enable GitHub Actions email/web notifications in the intended operator's GitHub
notification settings and choose failures-only if desired. GitHub documents that
scheduled workflow notifications target the person who last changed the cron
syntax; verify that this is the intended active operator when registering the
workflow. [GitHub notification documentation](https://docs.github.com/en/actions/concepts/workflows-and-actions/notifications-for-workflow-runs),
[scheduled workflow actor rules](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#actor-for-scheduled-workflows).

For an explicit delivery test, manually run the same workflow with
`notification_test=true`. This intentionally fails a synthetic notification step
and skips the cloud/server checks and credentials. Record the run URL and actual
receipt time in the operator's selected channel. A notification received for a
manual run proves that manual initiator's channel; verify the scheduled actor's
delivery separately. Until a recipient confirms receipt, **delivery is unverified**.

GitHub schedules may be delayed or dropped, and public-repository schedules can
be disabled after 60 days without repository activity. This same GitHub monitor
cannot detect its own missing execution or a GitHub-wide outage. Before promising
continuous production alerting, add an independent dead-man check and verify
delivery to the designated operator. [GitHub schedule limitations](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

## First response

- `public_https` / `private_snapshot`: verify deployment status, HTTPS, VM and
  container health before changing anything. Never publish raw environment or
  container logs in an issue.
- Worker/queue failure: inspect the named worker and lease state. Do not reset
  leases or replay an uncertain paid call as a monitoring repair.
- Disk failure: pause new admissions through the application's storage guard;
  inspect retention status and cleanup results. Preserve active sources and
  reports. Do not erase the shared volume.
- Allowance warning: inspect remaining authorized capacity and deadline. A new
  amount or deadline requires an owner's concrete authorization. Monitoring
  cannot replenish or extend the current $5 allowance.
- Accounting warning: reconcile the exact private call history against provider
  usage before any release of an unknown hold. Failed generation may still have
  been billed.
- Backup failure: inspect the named backup workflow's sanitized failure stage,
  then verify a new off-server download-and-restore success. Monitor green does
  not replace a full recovery exercise.
