# Timeweb: initial access and budget check

Owner's initial target: **2,000 RUB/month for Timeweb**, separate from Gemini.
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
4. Before provisioning, verify the returned tariff's monthly payment period,
   Gemini-supported location, public IPv4 price, offserver backup storage,
   traffic and any existing paid resources. Raw `price` is not a final quote.

At this budget, the earlier 8 vCPU / 16 GB configuration must be reconsidered.
A smaller pilot needs one concurrent job, restricted upload retention and actual
memory measurement. Do not deploy the existing 4 GiB worker limit on a 4 GiB host
alongside PostgreSQL and the web service without adapting and validating it.
The full Sites-to-standalone migration and live Gemini validation remain separate
work; a successful preflight does not establish production readiness.

Security: fixed HTTPS API origin and three GET endpoints, no redirects, bounded
responses/timeouts, no dependencies installed with the secret, no raw response
or provider error logging, and no customer resource names/IPs/IDs in public logs.
The workflow runs only on the owner's named branch, never on a pull-request
trigger. The token is exposed only to the read-only Python step.

Sources checked 2026-09-06:
- https://github.com/timeweb-cloud/sdk-javascript/blob/main/docs/ServersPreset.md
- https://github.com/timeweb-cloud/sdk-javascript/blob/main/docs/PresetsStorage.md
- https://timeweb.cloud/docs/account-management/token
- https://timeweb.cloud/prices
- https://ai.google.dev/gemini-api/docs/available-regions
- https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets
