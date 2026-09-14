# NARMA VISION: controlled rollout

This document describes the standalone Timeweb application. Older Sites/D1,
all-frame video and subscription-auth notes are historical and do not describe
this release. A passing deployment is not a measured capacity or coaching-quality
claim.

## Access and source files

The existing platform owner remains unchanged. Public registration is available at
`/register` after the owner has initialized the platform. Visitors supply email,
a password of 12–256 characters and matching confirmation. Registration creates
an isolated ordinary account and signs it in; it never grants platform authority,
reuses an existing account or calls an AI provider. `/login` opens the login form.
Email is a login identifier, **not verified email ownership**. No confirmation or
password-recovery emails are sent. Save the offline recovery codes after signup.

The shared admission ceiling remains 25 accounts including the owner. Existing
unexpired invitations reserve seats; public signup cannot claim an invited email
without its token. All account admission paths serialize under the same database
lock. Registration is rate limited independently of login and does not increase,
reset or extend any AI allowance. The ceiling is a pilot guardrail, not a claim
that the VM can process 25 simultaneous games.

The owner can still issue email-bound one-use invitations after re-entering their
password. Invitations expire after 24 hours and must be shared privately.
This registration release does not delete or replace existing accounts. Removing
an old account requires identifying its exact owner and preserving provider cost
records; public signup never takes over its matches or administrator rights.

Every account can generate five offline recovery codes after password
reauthentication. Store them privately outside the application. A code resets the
password once and revokes existing sessions. Changing the password invalidates
the old recovery codes; generate a new set afterwards. There is no email-based
password recovery and no passwordless administrator override.

Keep original `.dem` and video files locally. Server sources are working copies;
they are not included in the PostgreSQL backup. Saved reports, account data and
cost ledgers are in PostgreSQL. Loss of the VM can require uploading sources
again. This release adds disk admission safeguards, not automatic deletion or
paid object storage. Explicit user deletion remains the way to release source
space while preserving an available report.

## Release order

1. Pass the native PostgreSQL suite, browser checks, operational tests and the
   provider-free concurrency rehearsal on the exact candidate commit.
2. Deploy the candidate with the current provider settings and monetary limits
   preserved. Do not refill a budget to make a deployment pass. If the idle-worker
   preflight reports active work, allow it to finish before the next deployment.
3. Verify the new version's readiness, sign in with the existing account, generate
   recovery codes, then exercise registration with a separate test account and verify isolation.
4. Register the operational monitor on the default branch with a tested immutable
   checkout reference. Confirm GitHub Actions notification preferences and an
   actual notification receipt. Workflow code alone does not prove delivery.
5. Update the daily backup workflow's immutable checkout to a tested revision
   including migration-023 restore checks, and confirm its next successful drill.
6. Collect real-game validation and server timings before opening paid access.

The already authorized OpenAI ceiling is **5,000,000 micro-USD total**, expiring
at **2026-09-19T23:59:59Z**. This is not an available-balance assertion. Settled
spend and unresolved reservations consume the same ceiling. This release neither
raises it nor extends its expiry. Exhaustion or expiry makes new AI commentary
unavailable while existing reports and deterministic replay analysis remain
accessible. A public paid service needs a separately agreed ongoing funding and
customer-allocation policy.

## Restoring after loss of the VM

The scheduled backup uploads a bounded PostgreSQL dump to the existing private
off-server bucket, downloads it, verifies its hash and restores it into an
isolated PostgreSQL 17 container. Up to seven verified copies are retained. A
daily schedule implies a potentially day-long data-loss window; it does not
provide continuous recovery. The full replacement-VM recovery time is not yet
measured.

For a real recovery, keep the replacement service inaccessible and its workers
stopped. Preserve the old database/media if still available. Restore a verified
dump into a separate database with `pg_restore --no-owner --no-acl
--single-transaction --exit-on-error`. Use the matching application source and
apply any later migrations before accepting traffic.

Before enabling access, run the same invariants and containment actions as
`ops/timeweb/backup.py:verify_restored_database` against the disconnected restored
database: ownership and ledger consistency, provider allowances disabled without
changing money/reservations/expiry, all sessions removed, and all invitation and
recovery tokens revoked. The downloaded dump itself is unchanged by the rehearsal;
these actions must also be applied to the actual restored database. Old passwords
may also have changed after the snapshot: verify account ownership before
reopening a restored installation, then rotate credentials and issue fresh
recovery codes. Never publish the dump or log its contents.

Reconcile provider charges since the snapshot before any paid dispatch. A stale
snapshot must not grant previously spent money again. Do not clear unknown holds
without billing evidence. Source files are not recovered by this procedure;
preserve ready reports and request a fresh upload for work whose source is missing.
Finally verify HTTPS, sessions, report ownership, workers, a fresh backup and
monitor delivery before reopening access.

## Evidence still required on the deployed service

- A complete invitation/recovery journey using separate real browser sessions.
- A monitor execution plus confirmed external notification delivery.
- A restored replacement service, with measured recovery time and documented
  treatment of missing source files and post-snapshot charges.
- Real matches across roles, including coaching evidence review, settled unit
  costs, queue delay, failures and more than one simultaneous user.

Provider-free CI rehearsals establish application concurrency behavior in CI.
They neither call OpenAI/Gemini nor measure native parser/model throughput on the
Timeweb VM. See `PILOT_VALIDATION.md` for the measurement protocol.
