# NARMA background workers

These workers are prepared source. They have not been run against a real `.dem`
or the production Site. Do not enable paid fulfillment on the strength of unit
tests. Keep checkout off until the separate release runbook is complete.

## Runtime and credentials

The Site requires D1 `DB`, R2 `REPLAYS`, and migrations through `0012`.
Set a server-side `REPLAY_WORKER_TOKEN` of at least 32 random characters. Put the
same value in the external process environment as `NARMA_REPLAY_WORKER_TOKEN`.
Set `NARMA_SITE_ORIGIN` to the HTTPS origin. Never put these credentials in the
browser bundle, repository, URL, or screenshots.

For a private Site, the hosting access gate is separate from the application
worker token. If the provider supplies a machine access credential, set it as
`NARMA_SITES_ACCESS_TOKEN`; the script sends it through OAI-Sites-Authorization.
Verify this access path through the hosting control plane before starting the
worker. Do not open the Site or parser to the public to bypass an access gate.

No host or machine-access credential is provisioned by these scripts.

## Pinned parser

Reviewed protocol: [odota/parser at de9d6b260b15427fcaec16c061884f18ea3a6b14](https://github.com/odota/parser/tree/de9d6b260b15427fcaec16c061884f18ea3a6b14).
Requires Java21/Maven in its upstream Dockerfile, Node22 and `bzip2` for our worker.

```sh
git clone https://github.com/odota/parser.git /srv/narma-parser
git -C /srv/narma-parser checkout --detach de9d6b260b15427fcaec16c061884f18ea3a6b14
docker build --tag narma-parser:de9d6b2 /srv/narma-parser
docker run --detach --name narma-parser --restart unless-stopped \
  --publish 127.0.0.1:5600:5600 --memory 6g \
  --env 'JAVA_TOOL_OPTIONS=-Xms256m -Xmx4g -XX:+ExitOnOutOfMemoryError' \
  narma-parser:de9d6b2
node ops/replay-worker.mjs --once
```

Run the Node process with a service supervisor, a dedicated unprivileged user,
and a private temporary directory. Remove `--once` for polling. Run **one**
replay worker per parser instance; upstream buffers events in memory. The 6GiB
container limit and 4GiB heap are initial benchmark settings, not proven sizing.
Pin the upstream base-image digest after the first validated build. Parser and
application worker must share the loopback network namespace; do not expose
port5600 or upstream `replay_url` endpoints.

The worker downloads only its assigned R2 object. It accepts up to512MiB stored
and2GiB decompressed data, parses two bounded streams, checks the end-of-match
epilogue, maps player ordinals, and submits a normalized private snapshot.
HTTP200 alone is not evidence that upstream parsed a complete replay.

A claim lives20minutes. Up to3 attempts recover process/transport failures.
Claim IDs and accepted result payloads are idempotent. Parser failures retain
the source file and continue to count toward the owner's1GiB storage cap.
An interrupted multipart operation must be canceled and restarted if retry
remains locked; we deliberately do not overlap potentially stale part writes.
Configure provider lifecycle cleanup for orphaned incomplete multipart uploads
(e.g.1day) before enabling uploads broadly: an R2 create-response loss can leave
an upload without a locally known multipart ID. Do not expire completed source
objects without an application retention policy.

## Analysis scheduler

Run separately from the slower replay parser:

```sh
node ops/analysis-worker.mjs --once
```

Without `--once` it polls every10seconds, using the same machine credential.
It uses the existing durable job lease and ledger; closing the browser does not
remove the job. Per-attempt deadline25seconds, max9attempts/owner/day,
100attempts/site/day,2livejobs/owner. These are conservative pilot caps,
not a guaranteed currency budget. Set a provider-side spend limit as well.
History reads and scheduler polls recover exhausted reservations; jobs left
idle for a day are canceled with their original credit bucket restored.

Set `OPENAI_MODEL` and `OPENAI_ALLOWED_MODELS` to the same verified supported
model. Keep `ANALYSIS_RUNTIME_ENABLED` and `ANALYSIS_FULFILLMENT_ENABLED` off
until the provider call, timeout/retry and entitlement checks pass in staging.
A token/model and a running process are runtime setup, not source-code defaults.

## Required real-replay check

Upload a known7.41 `.dem`, verify its match ID/winner/duration/10heroes against
the game, then compare a pregame ward, ward removal, tower destruction and rewind
at three timestamps. Confirm the map's patch and inspect Gold/XP at minute
boundaries. Remove a file and confirm R2 cleanup. Interrupt the worker and
confirm retry without duplicated credits. Repeat with malformed and truncated
files and a long replay before changing bounds.

The current parser emits sampled hero positions, wards, buildings and economy.
It does **not** supply exact team fog-of-war, dynamic tree state or player
camera. Enemy positions are hidden in team-specific ward mode because their
visibility is unknown. Do not describe this as a complete in-game observer.

## Player identity binding

The app stores one coaching identity per authenticated account. Nickname lookup
chooses a stable Dota account ID; it does not authenticate Steam ownership.
The application never accepts a client-selected player slot for new analyses.

The replay adapter reads identity from the epilogue, preserving Steam64 using
Node22 JSON reviver source text and BigInt. It matches unique hero plus team,
never metadata roster order. It accepts both strings and validated Gson
ByteString byte arrays. The worker callback stores this roster in private
identity_payload, separate from the normalized match and model evidence.
Unknown identity remains null; reprocess legacy replay results before using
them for profile binding. Production replay execution is still unverified.
