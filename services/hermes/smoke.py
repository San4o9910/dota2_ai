"""Exercise the real installed AIAgent through a synthetic, unpaid local broker.

Run inside the runner image: /opt/hermes-venv/bin/python /app/smoke.py
No monkeypatch of Hermes, provider SDK, network transport or child isolation.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import resource
import tempfile
import threading
import time
from uuid import uuid4

from agent_task import ALLOWED_MODELS, MODEL, REVISION
from server import RunError, run_isolated, validate_request

TOKEN = "synthetic-unpaid-task-credential-123456"
FINAL = {"schema_version": 1, "snapshot_sha256": "a" * 64,
         "producer": {"name": "NousResearch/hermes-agent", "version": REVISION, "model": MODEL},
         "patterns": [], "goals": []}
REQUEST = {"task_id": str(uuid4()), "token": TOKEN,
           "packet": {"snapshot_sha256": "a" * 64, "snapshot": {"observations": []},
                      "response_schema": {"type": "object"}, "instructions": "Return JSON."}}
CALLS = []
MODE = "valid"
ACTIVE_MODEL = MODEL


class Broker(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def send_json(self, status, value):
        raw = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        if self.path == "/v1/models":
            self.send_json(200, {"object": "list", "data": [{"id": ACTIVE_MODEL, "object": "model",
                "context_length": 131072, "max_output_tokens": 4096}]})
        else:
            self.send_json(404, {"error": {"message": "No such metadata route"}})

    def do_POST(self):
        assert self.path == "/v1/chat/completions", self.path
        assert self.headers.get("Authorization") == "Bearer " + TOKEN
        value = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        CALLS.append(value)
        assert value["model"] == ACTIVE_MODEL
        assert not value.get("tools") and not value.get("stream")
        if MODE == "provider_error":
            self.send_json(500, {"error": {"message": "Synthetic broker failure", "type": "server_error"}})
            return
        if MODE == "deadline":
            time.sleep(25)
        final = {**FINAL, "producer": {**FINAL["producer"], "model": ACTIVE_MODEL}}
        content = "not valid JSON" if MODE == "malformed" else json.dumps(final)
        self.send_json(200, {"id": "chatcmpl-synthetic", "object": "chat.completion", "created": 1,
            "model": ACTIVE_MODEL, "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}})


def main():
    global MODE, ACTIVE_MODEL
    broker = ThreadingHTTPServer(("127.0.0.1", 0), Broker)
    threading.Thread(target=broker.serve_forever, daemon=True).start()
    os.environ["HERMES_BROKER_URL"] = f"http://127.0.0.1:{broker.server_port}/v1"
    profiles_before = set(os.listdir(tempfile.gettempdir()))
    try:
        assert run_isolated(None, deadline=30) == {"status": "ready", "runtime_revision": REVISION}
        cases = [(model, mode) for model in sorted(ALLOWED_MODELS)
            for mode in ("valid", "malformed", "provider_error", "deadline", "valid")]
        for model, mode in cases:
            ACTIVE_MODEL = model
            MODE = mode
            CALLS.clear()
            began = time.monotonic()
            try:
                result = run_isolated(validate_request({**REQUEST, "model": model}), deadline=15 if mode == "deadline" else 30)
                assert mode == "valid", f"{mode} unexpectedly succeeded"
                assert json.loads(result["final_response"]) == {**FINAL, "producer": {**FINAL["producer"], "model": model}}
                assert result["runtime_revision"] == REVISION
            except RunError as exc:
                if mode == "valid":
                    raise
                assert exc.code == {"deadline": "HERMES_DEADLINE_EXCEEDED",
                                    "malformed": "HERMES_OUTPUT_JSON_INVALID",
                                    "provider_error": "HERMES_UPSTREAM_CALL_FAILED"}[mode]
            assert len(CALLS) == 1, f"{mode}: unexpected auxiliary/retry provider calls: {len(CALLS)}"
            # No task profile persists, including after kill and provider error.
            assert not {p for p in set(os.listdir(tempfile.gettempdir())) - profiles_before
                        if p.startswith("narma-hermes-")}
            print(json.dumps({"event": "hermes_actual_runtime_smoke", "case": mode, "model": model,
                              "provider_requests": len(CALLS), "request_keys": sorted(CALLS[0]),
                              "seconds": round(time.monotonic() - began, 2), "runtime_revision": REVISION}), flush=True)
        print(json.dumps({"event": "hermes_actual_runtime_verified", "runtime_revision": REVISION,
                          "child_peak_rss_kib": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss}), flush=True)
    finally:
        broker.shutdown()
        broker.server_close()


if __name__ == "__main__":
    main()
