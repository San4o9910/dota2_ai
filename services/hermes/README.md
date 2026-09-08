# Private Hermes runtime

This service embeds the official `NousResearch/hermes-agent` checkout at
`9fd44b4dfc44138b9e5d5689acb56c438364ff7b` using its supported `uv sync` installation
and actual `run_agent.AIAgent`. The upstream source is not patched. Python 3.12,
uv 0.11.33 and the upstream dependency lock are used by the image build.

Build from the repository root:

```sh
docker build --secret id=github_token,env=GITHUB_TOKEN -f services/hermes/Dockerfile -t narma-hermes-runtime .
docker run --rm --read-only --tmpfs /tmp:rw,noexec,nosuid,size=256m \
  --memory=1g --cpus=1 --pids-limit=128 --cap-drop=ALL \
  --security-opt=no-new-privileges narma-hermes-runtime \
  /opt/hermes-venv/bin/python /app/smoke.py
```

Source builds use a read-only GitHub token supplied through a temporary BuildKit
secret. The deployment workflow uses its built-in `github.token`; no server or
model credential is involved. `fetch_source.py` authenticates only the fixed
official repository, disables redirects and tracing, and never puts the token in
Git arguments, persistent configuration, image environment or output. Its cache
is accepted only after exact commit, tree (`69a0ed6baa95d4e6af7b3c8c6147f193d29d48f7`)
and Git object integrity checks. Verified cache hits make no network request.
Git replacement objects and cache-local configuration/attribute overrides are
disabled. The exported source was checked against the trusted pinned checkout:
all 12,195 tracked files matched in bytes and executable modes, including the
upstream's declared line-ending conversion for PowerShell files.

An unsuccessful transient read may be retried once, after at least 60 seconds;
an exposed `Retry-After` is respected or the build fails if it exceeds the
240-second fetch budget. Each fetch is bounded to 90 seconds. There is no
anonymous request, alternate archive endpoint or URL rotation after throttling.
The frozen upstream dependency lock and actual-agent/network smoke tests remain
unchanged. This follows GitHub's guidance to authenticate requests and wait after
[rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api).

`GET /healthz` returns `{status: "ready", runtime_revision: "…"}` only after an
actual upstream import and the immutable build revision check. `POST /run` accepts
`{task_id, token, packet, prior_goals?}` and returns
`{final_response, runtime_revision}`. `token` is a task credential, never a model
provider key. The only configurable model endpoint is the trusted service
environment's `HERMES_BROKER_URL`, default `http://hermes-broker:8091/v1`.

Each request has a new child process, a new empty temporary profile, a 180-second
hard deadline, at most 512 KiB input and 32 KiB final output. Only one request runs
at a time. The process receives no parent credentials or proxy configuration.
Its entire process group is killed and its profile removed after success or error.
The image runs as UID 10002 and requires only writable `/tmp`.

Tools, memories, context files, checkpoints, fallback models, background reviews,
compression, telemetry and automatic dependency installs are disabled. Both
`model.streaming: false` and a single application API attempt are explicit;
`display.streaming: false` alone does not disable upstream transport streaming.
The broker separately enforces the paid-attempt cap and validates every returned
evidence reference. An internal Docker network gives the runner no direct provider
egress. These accounting and network boundaries also cover unexpected upstream
auxiliary or retry behavior.

`smoke.py` runs real isolated `AIAgent` instances against a synthetic local broker,
covering successful JSON, malformed output, a provider 500 with no retry,
deadline termination, profile removal, and success after previous failures. It
prints request key names, counts, revision and child peak RSS; it does not print
prompts, tokens or response text. The observed main request has only `model`,
`messages`, `max_tokens` and `response_format` keys. Non-inference metadata probes
may request additional GET routes, which can safely return 404.
