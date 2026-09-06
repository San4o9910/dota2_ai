"""Print only fixed diagnostic codes and allowlisted container status fields."""
import json
from pathlib import Path
import re
import subprocess
import sys

release = sys.argv[1]
if not re.fullmatch(r"[0-9a-f]{40}", release):
    raise SystemExit(2)
compose = ["docker", "compose", "--project-name", "narma-video", "--env-file",
           "/opt/narma/secrets/video.env"]
cwd = Path("/opt/narma/releases") / release / "services/video"
patterns = {
    "permission_denied": ("permission denied", "permissionerror"),
    "read_only_filesystem": ("read-only file system",),
    "connection_refused": ("connection refused",),
    "database_authentication_failed": ("password authentication failed",),
    "dns_failed": ("name or service not known", "temporary failure in name resolution"),
    "missing_module": ("modulenotfounderror",),
    "sql_syntax_error": ("syntaxerror", "syntax error at"),
    "database_operational_error": ("psycopg.operationalerror",),
    "image_pull_rate_limit": ("toomanyrequests", "pull rate limit"),
    "image_pull_denied": ("pull access denied", "manifest unknown"),
    "out_of_memory": ("out of memory", "cannot allocate memory"),
}
try:
    result = subprocess.run(compose + ["ps", "--all", "--format", "json"], cwd=cwd,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
    raw = result.stdout.decode("utf-8", errors="replace").strip()
    rows = json.loads(raw) if raw.startswith("[") else [json.loads(line) for line in raw.splitlines()]
    for row in rows:
        service, state, health, code = (row.get(key) for key in ("Service", "State", "Health", "ExitCode"))
        if service not in {"db", "migrate", "api", "worker"}:
            continue
        print(json.dumps({"event":"container_status", "service":service,
            "state":state if state in {"created","running","restarting","exited","paused","dead","removing"} else "unknown",
            "health":health if health in {"healthy","unhealthy","starting"} else "none",
            "exit_code":code if type(code) is int else None}), flush=True)
    for service in ("db", "migrate", "api"):
        logs = subprocess.run(compose + ["logs", "--no-color", "--no-log-prefix", "--tail", "80", service],
            cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
        private_text = (logs.stdout + logs.stderr).decode("utf-8", errors="replace").lower()
        for code, needles in patterns.items():
            if any(needle in private_text for needle in needles):
                print(json.dumps({"event":"container_diagnostic", "service":service, "code":code}), flush=True)
except Exception:
    print(json.dumps({"event":"container_diagnostics_unavailable"}), flush=True)
