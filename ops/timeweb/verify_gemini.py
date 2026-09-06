"""One controlled vision attempt on the VPS; never retry an uncertain attempt."""
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys

os.umask(0o077)
release = sys.argv[1]
if not re.fullmatch(r"[0-9a-f]{40}", release):
    raise SystemExit(2)
lock = open("/var/lock/narma-deploy.lock", "a")
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
directory = Path("/opt/narma/checks")
directory.mkdir(mode=0o700, exist_ok=True)
record = directory / "gemini-vision-20260906.json"
if record.exists():
    previous = json.loads(record.read_text())
    if previous.get("state") == "passed":
        print("NARMA_GEMINI_CHECK:previously_passed", flush=True)
        raise SystemExit(0)
    print("NARMA_GEMINI_CHECK:previous_attempt_unresolved", flush=True)
    raise SystemExit(4)
with record.open("x") as stream:
    json.dump({"state":"attempted", "release":release, "maximum_provider_attempts":1}, stream)
    stream.flush()
    os.fsync(stream.fileno())
for parent in (directory, directory.parent):
    descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
container = "narma-gemini-check-" + release[:12]
owned_container = False
try:
    root = Path("/opt/narma/releases") / release
    exists = subprocess.run(["docker", "container", "inspect", container],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
    if exists.returncode == 0:
        raise ValueError("existing_check_container")
    owned_container = True
    result = subprocess.run(["docker", "compose", "--project-name", "narma-video",
        "--env-file", "/opt/narma/secrets/video.env", "--profile", "analysis",
        "run", "--build", "--rm", "--name", container, "--no-deps", "--volume", str(root / "ops/timeweb") + ":/checks:ro",
        "--env", "PYTHONPATH=/app", "worker", "python", "/checks/vision_smoke.py"],
        cwd=root / "services/video", stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180)
    if result.returncode:
        raise ValueError("check_failed")
    items = [json.loads(line) for line in result.stdout.splitlines() if line.startswith(b'{"event":')]
    report = next(item for item in items if item.get("event") == "gemini_vision_smoke_passed")
    if report.get("provider_requests") != 1 or report.get("frames_sent") != 4 or report.get("reviewed_frame_ids") != [0,1,2,3]:
        raise ValueError("invalid_check_result")
    usage = {field:value for field,value in report.get("usage", {}).items()
        if field in {"total_input_tokens","total_output_tokens","total_thought_tokens","total_tokens"}
        and type(value) is int and 0 <= value <= 2000000}
    record.write_text(json.dumps({"state":"passed", "release":release,
        "provider_requests":1, "frames":4, "usage":usage, "scope":"synthetic_transport_only"}))
    print("NARMA_GEMINI_CHECK:passed", flush=True)
    for field, value in usage.items():
        print(f"NARMA_GEMINI_USAGE:{field}:{value}", flush=True)
except Exception:
    # Preserve the attempted reservation: an interrupted call must not be retried.
    print("NARMA_GEMINI_CHECK:failed", flush=True)
    raise SystemExit(1)
finally:
    if owned_container:
        subprocess.run(["docker", "rm", "--force", container],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
