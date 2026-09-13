"""Bounded operational monitor for the existing VM; no deploy or provider call.

The existing Timeweb API credential installs one ephemeral SSH key for the
read-only probe and removes its binding/key in finally. No storage is created,
no application state/budget is changed, and no third-party message is sent.
"""
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import urllib.request

from pilot import Cloud, CheckError, NoRedirect, command, event, validate_pinned_server
from coaching_evidence import collect_rollout_snapshot

SERVER = 9037783
HOST = "72.56.98.68"
SITE = "https://narma-72-56-98-68.sslip.io"
REPOSITORY = "San4o9910/dota2_ai"
BACKUP_MAX_AGE_SECONDS = 36 * 3600
SEVERITIES = {"ok": 0, "warning": 1, "critical": 2}
SNAPSHOT_NAMES = {f"{name}_{kind}" for name in ("replay", "video", "hermes")
                  for kind in ("worker", "queue")} | {
    "media_disk", "openai_budget", "openai_accounting", "gemini_budget", "snapshot_unavailable"}
METRIC_NAMES = {"expected", "heartbeat_age_seconds", "queued", "processing", "expired_leases",
    "oldest_queued_seconds", "failed_last_day", "total_bytes", "free_bytes", "free_percent",
    "readable", "configured", "enabled", "frozen", "limit_microusd", "spent_microusd",
    "reserved_microusd", "available_microusd", "expires_at", "expiry_seconds", "consistent",
    "unknown_calls", "unknown_reserved_microusd", "stale_reserved_calls"}


def receipt(name, severity="ok", **metrics):
    return {"name": name, "severity": severity, "metrics": metrics}


def parse_snapshot(raw):
    """Fail closed rather than forward arbitrary remote stdout into Actions."""
    if len(raw) > 65536:
        raise CheckError("monitor_snapshot_invalid")
    value = json.loads(raw)
    if (not isinstance(value, dict) or set(value) != {"schema", "status", "checks"}
            or value["schema"] != "narma.operations-health.v1"
            or value["status"] not in SEVERITIES or not isinstance(value["checks"], list)
            or not 1 <= len(value["checks"]) <= len(SNAPSHOT_NAMES)):
        raise CheckError("monitor_snapshot_invalid")
    names = set()
    for row in value["checks"]:
        if (not isinstance(row, dict) or set(row) != {"name", "severity", "metrics"}
                or row["name"] not in SNAPSHOT_NAMES or row["name"] in names
                or row["severity"] not in SEVERITIES or not isinstance(row["metrics"], dict)):
            raise CheckError("monitor_snapshot_invalid")
        names.add(row["name"])
        for key, metric in row["metrics"].items():
            if key not in METRIC_NAMES:
                raise CheckError("monitor_snapshot_invalid")
            if key == "expires_at":
                if not isinstance(metric, str) or not re.fullmatch(
                        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?\+00:00", metric):
                    raise CheckError("monitor_snapshot_invalid")
            elif metric is not None and type(metric) not in (int, float, bool):
                raise CheckError("monitor_snapshot_invalid")
            elif type(metric) is float and not math.isfinite(metric):
                raise CheckError("monitor_snapshot_invalid")
    if value["status"] != max((r["severity"] for r in value["checks"]), key=SEVERITIES.get):
        raise CheckError("monitor_snapshot_invalid")
    required = SNAPSHOT_NAMES - {"snapshot_unavailable"}
    if names != required and names != {"snapshot_unavailable"}:
        raise CheckError("monitor_snapshot_incomplete")
    return value["checks"]


def get_json(url, *, token=None):
    headers = {"Accept": "application/json", "User-Agent": "Narma-operational-monitor"}
    if token:
        headers["Authorization"] = "Bearer " + token
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=20) as response:
        raw = response.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise CheckError("monitor_response_oversized")
    return json.loads(raw)


def public_health():
    try:
        value = get_json(SITE + "/livez")
        return receipt("public_https", "ok" if value == {"status": "alive"} else "critical")
    except Exception:
        return receipt("public_https", "critical")


def backup_health(runs, *, now=None, active=True):
    """Evidence is a successful restore-drill workflow, not a fresh S3 audit."""
    now = now or datetime.now(timezone.utc)
    if not active:
        return receipt("backup_restore_drill", "critical", reason="workflow_inactive")
    relevant = [r for r in runs if r.get("head_branch") == "main"
                and r.get("event") in {"schedule", "workflow_dispatch"}]
    relevant.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    successes = [r for r in relevant if r.get("status") == "completed" and r.get("conclusion") == "success"]
    if not successes:
        return receipt("backup_restore_drill", "critical", reason="no_success_evidence")
    successful = successes[0]
    # created_at conservatively includes queue/restore time, instead of pretending
    # a delayed job's completion timestamp is the source snapshot's timestamp.
    age = int((now - datetime.fromisoformat(successful["created_at"].replace("Z", "+00:00"))).total_seconds())
    if age < -300:
        return receipt("backup_restore_drill", "critical", reason="timestamp_invalid")
    failed = any(r.get("status") == "completed" and r.get("conclusion") != "success"
                 for r in relevant if r["created_at"] > successful["created_at"])
    stale = age > BACKUP_MAX_AGE_SECONDS
    return receipt("backup_restore_drill", "critical" if stale or failed else "ok",
                   last_success_age_seconds=max(0, age),
                   last_success_run_id=int(successful["id"]), newer_failure=failed,
                   reason="stale_success" if stale else "newer_failure" if failed else "success_evidence")


def inspect_backup():
    try:
        token = os.environ.get("GITHUB_TOKEN", "")
        if not token:
            raise CheckError("monitor_github_token_missing")
        base = f"https://api.github.com/repos/{REPOSITORY}/actions/workflows/timeweb-backup-daily.yml"
        workflow = get_json(base, token=token)
        runs = get_json(base + "/runs?per_page=50", token=token)["workflow_runs"]
        return backup_health(runs, active=workflow.get("state") == "active")
    except Exception:
        return receipt("backup_restore_drill", "critical", reason="evidence_unavailable")


def private_health(cloud):
    server = cloud.call("GET", f"/api/v1/servers/{SERVER}")["server"]
    validate_pinned_server(server)
    key_id = None
    cleanup_failed = False
    result = []
    with tempfile.TemporaryDirectory(prefix="narma-monitor-") as tmp:
        temporary = Path(tmp)
        private = temporary / "ssh-key"
        command(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(private)])
        try:
            key_id = int(cloud.call("POST", "/api/v1/ssh-keys", {
                "name": "narma-monitor-" + str(os.getpid()),
                "body": private.with_suffix(".pub").read_text().strip(), "is_default": False})["ssh_key"]["id"])
            cloud.call("POST", f"/api/v1/servers/{SERVER}/ssh-keys", {"ssh_key_ids": [key_id]})
            ssh = ["ssh", "-i", str(private), "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
                   "-o", "StrictHostKeyChecking=accept-new", "-o", "UserKnownHostsFile=" + str(temporary / "known_hosts"),
                   "-o", "ConnectTimeout=8", "root@" + HOST]
            for attempt in range(6):
                try:
                    command(ssh + ["true"], timeout=15)
                    break
                except (CheckError, subprocess.TimeoutExpired):
                    if attempt == 5:
                        raise CheckError("monitor_ssh_unavailable") from None
                    time.sleep(5)
            remote = ("cd /opt/narma/current/services/video && "
                      "docker compose --project-name narma-video --env-file /opt/narma/secrets/video.env "
                      "exec -T api python -m narma_video.operations_health")
            result = parse_snapshot(command(ssh + [remote], timeout=90))
            collect_rollout_snapshot(ssh, '/opt/narma/current', command, event)
        finally:
            if key_id is not None:
                try:
                    cloud.call("DELETE", f"/api/v1/servers/{SERVER}/ssh-keys/{key_id}")
                except Exception:
                    cleanup_failed = True
                try:
                    cloud.call("DELETE", f"/api/v1/ssh-keys/{key_id}")
                except Exception:
                    cleanup_failed = True
                if cleanup_failed:
                    event("operations_monitor_check", **receipt("ephemeral_key_cleanup", "critical"))
                    raise CheckError("monitor_key_cleanup_unconfirmed")
    return result


def main():
    os.umask(0o077)
    checks = [public_health(), inspect_backup()]
    try:
        checks.extend(private_health(Cloud()))
    except Exception:
        checks.append(receipt("private_snapshot", "critical"))
    for row in checks:
        event("operations_monitor_check", **row)
        if row["severity"] in {"warning", "critical"}:
            level = "error" if row["severity"] == "critical" else "warning"
            print(f"::{level} title=NARMA operational check::{row['name']}: {row['severity']}")
    status = max((row["severity"] for row in checks), key=SEVERITIES.get)
    event("operations_monitor_complete", status=status, provider_calls=0, application_writes=0)
    # Warnings (e.g. allowance expires in 48 h) must produce a failed workflow
    # too, so configured Actions failure notifications can reach the operator
    # before service is unavailable. This does not itself prove delivery.
    return 1 if status != "ok" else 0


if __name__ == "__main__":
    raise SystemExit(main())
