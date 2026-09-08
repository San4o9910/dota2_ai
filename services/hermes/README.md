# Private Hermes runtime

This service embeds the official `NousResearch/hermes-agent` checkout at
`9fd44b4dfc44138b9e5d5689acb56c438364ff7b` using its supported `uv sync` installation
and actual `run_agent.AIAgent`. The upstream source is not patched. Python 3.12,
uv 0.11.33 and the upstream dependency lock are used by the image build.

Build from the repository root:

```sh
docker build -f services/hermes/Dockerfile -t narma-hermes-runtime .
docker run --rm --read-only --tmpfs /tmp:rw,noexec,nosuid,size=256m \
  --memory=1g --cpus=1 --pids-limit=128 --cap-drop=ALL \
  --security-opt=no-new-privileges narma-hermes-runtime \
  /opt/hermes-venv/bin/python /app/smoke.py
```

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
