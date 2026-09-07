# NARMA pilot operations — 2026-09-07

This is the current deployment record. It supersedes the initial bootstrap
limitations recorded in `ops/timeweb/README.md` on September 6.

## Infrastructure and scope

- Managed Timeweb VM 9037783, project 2655641: 4 vCPU, 8 GiB RAM, 80 GiB NVMe.
- Ordinary balance-based hourly billing; no prepaid period or automatic resize.
- VPS plus public IPv4: approximately 98.67 RUB/day using monthly equivalent / 30.
- Private 10 GiB S3 bucket 556673: 79 RUB/month equivalent. Base total approximately
  101.30 RUB/day; S3 egress and any GitHub usage are separate.
- PostgreSQL 17 and the video API run in Docker. PostgreSQL has no published
  port; the API binds to 127.0.0.1:8080.
- HTTPS origin: `https://narma-72-56-98-68.sslip.io`. The free DNS service is an
  external dependency and can later be replaced by an owner-controlled domain.
- The independent browser portal now runs in the FastAPI container on the VPS.
  New portal accounts, password hashes, sessions, locked player profiles, video
  queue and monetary ledger use PostgreSQL. The old Sites deployment redirects
  browser pages and returns 410 for old APIs. It does not forward identity or
  private requests to the new server; old D1/R2 history remains archived there.

## HTTPS

Host nginx forwards `/v1/` to the private API without injecting authentication.
Anonymous `/v1/` requests return 401. The independent browser uses a distinct
Secure/HttpOnly/SameSite=Strict session cookie; the server derives its owner ID
from PostgreSQL. Browser requests cannot supply the target player or owner.
Every browser mutation validates the fixed HTTPS Origin. The private service
token is never delivered to the browser.
The certificate was issued with an isolated staging check, verified against
trusted roots and the actual served certificate, and tested for renewal.
`narma-https-renew.timer` checks hourly with randomized delay. Certificates and
renewal state survive deployments. No purchase of a domain was needed.

## Video and Gemini limits

Every decoded frame is sent in timestamp order, in batches of up to 16 images.
No transcription or frame sampling substitutes for this path. The pilot accepts
at most 3,600 frames: about 120 seconds at 30 FPS or 60 seconds at 60 FPS.
Longer videos fail before inference. A `.dem` requires the Dota game engine to
become a playable video; the engine/rendering worker is not installed here.

The PostgreSQL allowance is global and does not reset with deployment or restart:

- Total internal ceiling: $10, accounted as 2,000 RUB using a conservative fixed
  factor of 200 RUB/USD. This is an application allowance, not Google's invoice
  or an account-wide Google Cloud billing cap.
- $0.10 historical allowance covers the two recorded pre-ledger image probes.
- Each physical provider request reserves $1.20 before dispatch. Concurrent jobs
  share the same locked budget row. SDK retries and automatic function calls are off.
- Verified token usage settles at Standard input/output rates, including thoughts;
  cached input is conservatively charged at full input price.
- Unknown outcomes retain their reservation. Invalid metadata freezes dispatch.
- The price policy expires by 2027-01-01; increasing an environment variable cannot
  extend it or enlarge the global allowance.
- Maximum 250 requests per job and per owner over a rolling day. One worker
  processes one job at a time. Partial results and source frame IDs are retained.

The first Interactions pipeline probe returned undocumented internal token
counters that differed from the public totals. Its full $1.20 remains reserved
as `unknown`; migration 003 records the specific switch to GenerateContent
without refunding that reservation or resetting expenditure. GenerateContent
reads raw HTTP usage metadata, because the SDK's normal typed conversion drops
unknown fields. Unknown charges continue to fail closed.

The first GenerateContent attempt also had an uncertain outcome and retains a
separate $1.20 reservation. A single controlled retry on that same transport job
passed; neither unknown reservation was refunded. These $2.40 are conservative
holds, not a claim about Google's actual invoice.

[Live pipeline verification](https://github.com/San4o9910/dota2_ai/actions/runs/34078240957)
passed at 03:05 UTC: authenticated upload, queue, four decoded frames, real
GenerateContent inference, persisted frame coverage, HTTP Range playback and
fixture deletion. The persistent worker was then enabled. The successful marker
prevents deployments from repeating this paid transport probe. Standalone Gemini
credential checks only fetch model metadata and perform no inference.

The Sites runtime now holds `VIDEO_SERVICE_ORIGIN` and a secret
`VIDEO_SERVICE_TOKEN`. The token was transferred through a one-time RSA-OAEP
handoff bound to this VM, release and verified workflow run. Timeweb and Gemini
keys were not exported from GitHub Actions.

Transport probes use synthetic frames and must not be described as proof of
Dota coaching accuracy. That requires a real gameplay fragment, confirmed player
identity and review against visible frame evidence.

## Backups and recovery

[First off-server restore drill](https://github.com/San4o9910/dota2_ai/actions/runs/34077846193)
succeeded: 15,998-byte PostgreSQL dump, downloaded SHA-256 matched, seven tables
and two migrations restored, no orphan batch rows. This snapshot preceded
migration 003. The restore checker also accepts its eighth audit table.

The daily workflow lives on the default GitHub branch because scheduled Actions
do not run from feature branches. It checks out the reviewed backup implementation
at `017bb830ca654b91bff28e35b69b9dc9b1109cd8`, runs at 03:41 UTC, and serializes
with deployments. Scheduling can be delayed; inspect actual completed runs rather
than assuming a strict 24-hour recovery guarantee.

Every run dumps the live database, uploads to the private bucket, downloads the
same object, checks its hash, and restores into a disposable isolated PostgreSQL
17 container on the runner. No production volume or network is attached to that
container. Its restored AI allowance is disabled before the drill ends.

Only the runner holds Timeweb/S3 administrator credentials. No S3 key is installed
on the application server or included in artifacts. Keep up to seven verified
copies; each dump is capped below 1 GiB, with an 8 GiB remote occupancy ceiling.
Failed verification removes only that run's newly created object pair. Automatic
storage expansion is required to be disabled; any Terraform correction permits
only that single in-place flag change.

These backups cover PostgreSQL video and portal account tables. The restore
checker verifies the additional five portal tables after migration 004. They
do not back up VPS media, archived Sites/D1 accounts, archived R2 replay files,
or private API keys.

For an actual recovery: stop the worker; restore into a new PostgreSQL 17 database
with `pg_restore --no-owner --no-acl --single-transaction --exit-on-error`; disable
`video_ai_budget`; verify schema and ownership; reconcile all Gemini charges made
after the snapshot before reenabling requests. An older database must never
silently restore an already-spent allowance. Preserve the original database and
media until recovery is verified. Prepare credentials separately from the dump.

## Logs and status

GitHub Actions records deployment stages, sanitized failure codes, certificate
checks and backup/restore outcomes. No tokens, prompt bodies or full API responses
are logged. API records include a generated request ID, route template, status
and duration. Docker logs rotate at 10 MiB × 3 per service.

Safe commands in the VPS console:

```bash
cd /opt/narma/current/services/video
docker compose --project-name narma-video --env-file /opt/narma/secrets/video.env --profile analysis ps --all
docker compose --project-name narma-video --env-file /opt/narma/secrets/video.env logs --tail 100 api worker
docker compose --project-name narma-video --env-file /opt/narma/secrets/video.env exec -T api python -m narma_video.budget
curl --fail http://127.0.0.1:8080/readyz
systemctl status narma-https-renew.timer
journalctl -u narma-https-renew.service --since today
```

Never display `video.env`, broad `docker inspect`, Terraform state or rendered
Compose configuration in public logs. Use `/readyz` for private config/database/
media readiness; `/livez` only proves process liveness. Worker heartbeat and
budget availability are separate signals shown by the video API.

## Remaining production gates

Real gameplay quality review; Dota-engine `.dem` rendering; explicit import of
archived history if needed; media and archived D1/R2 recovery; external alert delivery; measured full-match latency
and cost. Payments and the old OpenDota analysis flags stay off. A functioning
video pilot does not establish a production-ready full-match coaching platform.

## Independent portal and OpenDota retirement

The homepage is `https://narma-72-56-98-68.sslip.io`. It serves local HTML/CSS/JS
without ChatGPT login or remote frontend hosting. The owner creates a separate
email/password account through a 256-bit invitation in a URL fragment. Only
the SHA-256 and fixed 24-hour expiry enter deployment source/configuration.
Account creation is atomic and limited to one owner; the invitation cannot
create another account after setup. Never put the plaintext invitation in logs,
query strings, source, or screenshots. Email here is a login identifier, not a
verified email address; email recovery is not enabled.

Passwords use salted scrypt with at most two concurrent KDF operations. Session
tokens are stored only as hashes. Logout invalidates the session; password
change invalidates every session. Login/password-change locking prevents an
old-password request from creating a new session after rotation. Database rate
limits cover login, setup and password attempts.

The `.dem` profile upload is a bounded raw stream, up to 512 MiB, outside the
static directory. Its Source2 footer is read locally; the selected Steam ID is
locked transactionally. Other roster identities are not returned or persisted.
The temporary replay is removed after metadata extraction, including failures.
Uploading a replay establishes the chosen analysis subject, not proof that the
user owns the Steam account. There is no automatic whole-match rendering yet.

Both physical OpenDota network implementations were removed. Historical fixture
provenance and parsers remain for regression/archival data; retired live fetch
functions return SOURCE_RETIRED without making a request. The standalone UI
contains no match-ID search, provider selector or OpenDota flow.
