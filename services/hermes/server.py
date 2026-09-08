"""Private, bounded HTTP adapter for the actual upstream Hermes runtime."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import threading
from uuid import UUID

from agent_task import REVISION

MAX_REQUEST_BYTES = 512 * 1024
MAX_DEADLINE_SECONDS = 180
RUN_SLOT = threading.Lock()


class RunError(Exception):
    def __init__(self, code, status=502):
        self.code, self.status = code, status


def validate_request(value):
    if not isinstance(value, dict) or set(value) - {"task_id", "token", "packet", "prior_goals"}:
        raise RunError("HERMES_INVALID_REQUEST", 400)
    try:
        value["task_id"] = str(UUID(value["task_id"]))
    except (KeyError, ValueError, TypeError, AttributeError):
        raise RunError("HERMES_INVALID_REQUEST", 400) from None
    if (not isinstance(value.get("token"), str)
            or not re.fullmatch(r"[A-Za-z0-9_.~-]{16,512}", value["token"])
            or not isinstance(value.get("packet"), dict)
            or not isinstance(value.get("prior_goals", []), list)):
        raise RunError("HERMES_INVALID_REQUEST", 400)
    return value


def run_isolated(request, *, deadline=MAX_DEADLINE_SECONDS):
    """No profile, credentials, environment or background process survives a task."""
    deadline = min(MAX_DEADLINE_SECONDS, max(1, deadline))
    with tempfile.TemporaryDirectory(prefix="narma-hermes-") as directory:
        profile = Path(directory)
        # Inherit only non-secret runtime plumbing. Never forward provider keys/proxies.
        environment = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "TZ") if key in os.environ}
        environment.update({
            "HERMES_HOME": directory,
            "HERMES_CONFIG": str(profile / "config.yaml"),
            "HERMES_DISABLE_LAZY_INSTALLS": "1",
            "HERMES_API_TIMEOUT": "160",
            "HERMES_BROKER_URL": os.environ.get("HERMES_BROKER_URL", "http://hermes-broker:8091/v1"),
            "NARMA_HERMES_UPSTREAM": os.environ.get("NARMA_HERMES_UPSTREAM", "/opt/hermes"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
            "XDG_CACHE_HOME": str(profile / "cache"),
            "XDG_CONFIG_HOME": str(profile / "config"),
        })
        output = profile / "result.json"
        child = subprocess.Popen(
            [sys.executable, str(Path(__file__).with_name("agent_task.py")), str(output)],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            cwd=directory, env=environment, start_new_session=True,
        )
        try:
            child.communicate(json.dumps(request, ensure_ascii=False).encode(), timeout=deadline)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=5)
            raise RunError("HERMES_DEADLINE_EXCEEDED", 504) from None
        finally:
            # Includes any background threads' subprocesses even after normal parent exit.
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if child.returncode or not output.is_file() or output.stat().st_size > 64 * 1024:
            raise RunError("HERMES_EXECUTION_FAILED")
        try:
            result = json.loads(output.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise RunError("HERMES_EXECUTION_FAILED") from None
        if result.get("runtime_revision") != REVISION:
            raise RunError("HERMES_REVISION_MISMATCH")
        return result


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *_args):
        pass

    def respond(self, status, value):
        raw = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        if self.path == "/healthz":
            self.respond(200, {"status": "ready", "runtime_revision": REVISION})
        else:
            self.respond(404, {"error": "NOT_FOUND"})

    def do_POST(self):
        if self.path != "/run":
            self.respond(404, {"error": "NOT_FOUND"})
            return
        if not RUN_SLOT.acquire(blocking=False):
            self.respond(429, {"error": "HERMES_BUSY"})
            return
        try:
            if self.headers.get("Transfer-Encoding"):
                raise RunError("HERMES_INVALID_REQUEST", 400)
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                raise RunError("HERMES_INVALID_REQUEST", 400) from None
            if not 0 < length <= MAX_REQUEST_BYTES:
                raise RunError("HERMES_INVALID_REQUEST", 413)
            try:
                request = json.loads(self.rfile.read(length))
            except (ValueError, TimeoutError):
                raise RunError("HERMES_INVALID_REQUEST", 400) from None
            result = run_isolated(validate_request(request))
            self.respond(200, result)
        except RunError as exc:
            self.respond(exc.status, {"error": exc.code})
        except Exception:
            self.respond(500, {"error": "HERMES_EXECUTION_FAILED"})
        finally:
            RUN_SLOT.release()


def main():
    # A healthy process means the actual pinned checkout imports successfully.
    run_isolated(None, deadline=30)
    print(json.dumps({"event": "hermes_runtime_ready", "runtime_revision": REVISION}), flush=True)
    ThreadingHTTPServer(("0.0.0.0", 8092), Handler).serve_forever()


if __name__ == "__main__":
    main()
