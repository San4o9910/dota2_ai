# Timeweb: initial access and budget check

Owner's updated target: **about 100 RUB/day for Timeweb using ordinary hourly
billing, with no prepaid monthly/yearly period purchase**, and **2,000 RUB total
for initial Gemini tests**. This supersedes the earlier 2,000/month hosting target.
This workflow only checks API access and lists public tariff fields. It cannot
create, change or delete a service and is not a deployment workflow.

1. In GitHub Settings → Secrets and variables → Actions → New repository secret,
   save the Timeweb token as `TIMEWEB_CLOUD_TOKEN`. Never use a repository variable
   or commit the token. Keep token lifetime limited to the initial setup period.
2. The workflow runs after changes to this directory or its workflow are pushed
   to `codex/replay-map-hardening-8ea829a`. If a run failed before adding the secret,
   rerun that failed job after saving it. Merely adding a secret does not start a run.
3. Read the Timeweb preflight job summary. `server_read_access: ok` confirms only
   the ability to list permitted servers, not creation, S3 or deployment access.
4. Before provisioning, verify the returned tariff's monthly-equivalent price,
   Gemini-supported location, public IPv4 price, offserver backup storage,
   traffic and any existing paid resources. Raw `price` is not a final quote.

At the earlier monthly budget, the 8 vCPU / 16 GB configuration had to be reconsidered.
A smaller pilot needs one concurrent job, restricted upload retention and actual
memory measurement. Do not deploy the existing 4 GiB worker limit on a 4 GiB host
alongside PostgreSQL and the web service without adapting and validating it.
The full Sites-to-standalone migration and live Gemini validation remain separate
work; a successful preflight does not establish production readiness.

Security: fixed HTTPS API origin and three GET endpoints, no redirects, bounded
responses/timeouts, no dependencies installed with the secret, no raw response
or provider error logging. Only the specifically named managed pilot is included
in sanitized resource status; unrelated customer resource details are omitted.
The workflow runs only on the owner's named branch, never on a pull-request
trigger. The token is exposed only to the read-only Python step.

Sources checked 2026-09-06:
- https://github.com/timeweb-cloud/sdk-javascript/blob/main/docs/ServersPreset.md
- https://github.com/timeweb-cloud/sdk-javascript/blob/main/docs/PresetsStorage.md
- https://timeweb.cloud/docs/account-management/token
- https://timeweb.cloud/prices
- https://ai.google.dev/gemini-api/docs/available-regions
- https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets

## Hourly pilot deployment

`timeweb-pilot.yml` builds the actual Docker image before any resource creation,
checks the Gemini key without inference, then runs `pilot.py` only on the owner's
named branch. Selected catalog preset: **6813, nl-1, 4 vCPU / 8 GiB / 80 GiB NVMe,
2,760 RUB monthly equivalent**, plus estimated IPv4 200/month: about 98.67/day
using a 30-day conversion. A 10 GiB S3 backup plan would add 79/month (2.63/day)
plus egress; the current bootstrap does not create a bucket or enable backups.
Creation is guarded against changed specs/prices and ambiguous existing resources.
No balance top-up, long-period purchase, automatic resize or VPS deletion occurs.
Hourly billing continues for an existing stopped server; shutdown is not deletion.

The token must be able to read the selected existing project and manage cloud
servers/SSH keys. A missing scope fails rather than requesting broader access or
creating a project. Insufficient balance may prevent creation even with hourly
billing; minimum balance and a prepaid period are different provider concepts.

The deployment uses a temporary SSH key inside the GitHub runner and removes its
Timeweb binding afterward. Initial SSH host trust is TOFU (`accept-new`); the first
host key is pinned for the rest of that run, not independently provider-verified.
Application secrets are transferred only via SSH stdin into a mode-0600 file on
the VPS; passwords are retained on repeat deployments. They are not placed in
cloud-init, source archives or GitHub logs. Remote logs are bounded by Docker's
local log driver. Deployment records include the source release SHA and stages.

Bootstrap starts PostgreSQL, migrations and the private API, validates `/readyz`,
and explicitly keeps the worker stopped. `/livez` reports process liveness;
`/readyz` checks config, PostgreSQL/schema and writable media. Neither claims
Gemini inference works. Inference budgets are still request-count limits, not a
global monetary cap. Do not enable an unattended queue before adding that cap.

Outstanding after bootstrap: a Gemini image test from the VPS, private offserver
backup/restore, domain and verified HTTPS, full website/auth/data migration from
Sites, exact `.dem` renderer integration and in-game quality validation. A green
deployment is evidence for private infrastructure readiness only.

## Verification recorded on 2026-09-06

- [Gemini vision check](https://github.com/San4o9910/dota2_ai/actions/runs/34060868435)
  completed one provider call from a GitHub runner with four synthetic JPEGs.
  It confirmed the reviewed frame IDs and did not invent a player or findings.
  Usage: 4,825 input, 91 output and 156 thought tokens (5,072 total).
  This verifies the transport and response contract, not Dota coaching quality
  or network access from the VPS. Estimated standard API cost is under $0.01;
  only the provider billing record can establish the actual charge.
- [Application CI](https://github.com/San4o9910/dota2_ai/actions/runs/34062124912)
  passed lint, type checking, tests, build, package checks and advisory lookup.
- The first managed VM was created and its public IPv4 attached. Subsequent
  attempts reuse that VM and address. SSH access was verified. These events
  do not by themselves establish a running database or application.
- The 2,000 RUB Gemini test allowance is a total allowance, separate from
  recurring Timeweb charges. No global monetary limiter is implemented yet;
  unattended analysis remains disabled. A full match's cost must be measured
  on a real video fragment before accepting full-match jobs.
