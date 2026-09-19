"""Private, read-only operational snapshot. Never calls an AI provider.

Run inside the API container: python -m narma_video.operations_health
The public application deliberately has no route for this information.
"""
from __future__ import annotations

from datetime import timezone
import json
import os
from pathlib import Path
import shutil

from .db import database

SCHEMA = "narma.operations-health.v1"
GIB = 1024 ** 3
SEVERITIES = {"ok": 0, "warning": 1, "critical": 2}


def check(name, severity="ok", **metrics):
    return {"name": name, "severity": severity, "metrics": metrics}


def snapshot_result(checks):
    return {"schema": SCHEMA,
            "status": max((row["severity"] for row in checks), key=SEVERITIES.get, default="ok"),
            "checks": checks}


def worker_check(name, row, expected):
    age = row.get("age_seconds")
    # Parsing/provider calls can occupy a worker for several minutes. A five
    # second idle polling interval is not a valid busy-worker heartbeat limit.
    severity = "critical" if expected and (age is None or age > 900) else "ok"
    return check(name + "_worker", severity, expected=expected,
                 heartbeat_age_seconds=None if age is None else max(0, int(age)))


def queue_check(name, row):
    age = row.get("oldest_queued_seconds")
    expired = int(row["expired_leases"])
    severity = ("critical" if expired or (age is not None and age >= 7200) else
                "warning" if age is not None and age >= 1800 else "ok")
    return check(name + "_queue", severity, queued=int(row["queued"]),
                 processing=int(row["processing"]), expired_leases=expired,
                 oldest_queued_seconds=None if age is None else max(0, int(age)),
                 failed_last_day=int(row["failed_last_day"]))


def disk_check(total, free):
    fraction = free / total if total > 0 else 0
    severity = ("critical" if free < 2 * GIB or fraction < .05 else
                "warning" if free < 4 * GIB or fraction < .10 else "ok")
    return check("media_disk", severity, total_bytes=total, free_bytes=free,
                 free_percent=round(fraction * 100, 1))


def allowance_check(name, budget, expected):
    if not budget:
        return check(name, "critical" if expected else "ok", configured=False)
    spent, reserved, limit = (int(budget[key]) for key in
                              ("spent_microusd", "reserved_microusd", "limit_microusd"))
    available = max(0, limit - spent - reserved)
    expiry = int(budget["expiry_seconds"])
    frozen = bool(budget["frozen"])
    severity = "ok"
    if expected:
        if not budget["enabled"] or frozen or expiry <= 0 or available == 0:
            severity = "critical"
        elif expiry <= 48 * 3600 or available <= limit * .2:
            severity = "warning"
    return check(name, severity, configured=True, expected=expected,
                         enabled=bool(budget["enabled"]), frozen=frozen,
                         limit_microusd=limit, spent_microusd=spent,
                         reserved_microusd=reserved, available_microusd=available,
                         expires_at=budget["expires_at"].astimezone(timezone.utc).isoformat(),
                         expiry_seconds=expiry)


def openai_checks(budget, calls, expected):
    budget_check = allowance_check("openai_budget", budget, expected)
    if not budget:
        return [budget_check, check("openai_accounting", "critical", consistent=False)]
    spent, reserved = int(budget["spent_microusd"]), int(budget["reserved_microusd"])
    unknown = int(calls["unknown_calls"])
    stale = int(calls["stale_reserved_calls"])
    consistent = spent == int(calls["charged_microusd"]) and reserved == int(calls["held_microusd"])
    accounting = check("openai_accounting", "critical" if not consistent else
                       "warning" if unknown or stale else "ok",
                       consistent=consistent, unknown_calls=unknown,
                       unknown_reserved_microusd=int(calls["unknown_reserved_microusd"]),
                       stale_reserved_calls=stale)
    return [budget_check, accounting]


def collect(connection, *, environment=None, disk_usage=shutil.disk_usage):
    """Caller must supply a read-only transaction; queries return aggregates only."""
    environment = os.environ if environment is None else environment
    selective = environment.get("VIDEO_ANALYSIS_MODE") == "selective_v1"
    openai = environment.get("REPLAY_COACH_PROVIDER") == "openai_api"
    hermes = environment.get("HERMES_PROVIDER") == "openai_api"
    checks = []
    for name, expected in (("replay", True), ("video", selective), ("hermes", hermes)):
        # Table identifiers come exclusively from this fixed tuple.
        row = connection.execute(f"""SELECT extract(epoch FROM now()-max(last_seen)) AS age_seconds
            FROM {name}_workers""").fetchone()
        checks.append(worker_check(name, row, expected))
        table = "hermes_tasks" if name == "hermes" else name + "_jobs"
        processing = "running" if name == "hermes" else "processing"
        lease = "lease_until" if name == "hermes" else "lease_expires_at"
        updated = "finished_at" if name == "hermes" else "updated_at"
        queued_since = "created_at" if name == "hermes" else "updated_at"
        row = connection.execute(f"""SELECT count(*) FILTER (WHERE state='queued') AS queued,
            count(*) FILTER (WHERE state=%s) AS processing,
            count(*) FILTER (WHERE state=%s AND ({lease} IS NULL OR {lease}<now()-interval '5 minutes')) AS expired_leases,
            extract(epoch FROM now()-min({queued_since}) FILTER (WHERE state='queued')) AS oldest_queued_seconds,
            count(*) FILTER (WHERE state='failed' AND {updated}>now()-interval '1 day') AS failed_last_day
            FROM {table}""", (processing, processing)).fetchone()
        checks.append(queue_check(name, row))
    budget = connection.execute("""SELECT enabled,limit_microusd,spent_microusd,reserved_microusd,
        frozen_reason IS NOT NULL AS frozen,expires_at,
        extract(epoch FROM expires_at-now()) AS expiry_seconds FROM openai_api_budget WHERE id=1""").fetchone()
    calls = connection.execute("""SELECT count(*) FILTER (WHERE billing_status='unknown') AS unknown_calls,
        coalesce(sum(reserved_microusd) FILTER (WHERE billing_status='unknown'),0) AS unknown_reserved_microusd,
        count(*) FILTER (WHERE billing_status='reserved' AND expires_at<now()-interval '5 minutes') AS stale_reserved_calls,
        coalesce(sum(charged_microusd),0) AS charged_microusd,
        coalesce(sum(reserved_microusd) FILTER (WHERE billing_status IN ('reserved','unknown')),0) AS held_microusd
        FROM openai_api_calls""").fetchone()
    checks.extend(openai_checks(budget, calls, openai or selective or hermes))
    # Selective video still consumes Gemini vision allowance before OpenAI
    # coaching. Its ledger includes historical adjustments; do not equate that
    # older ledger's row sum with the OpenAI reconciliation invariant.
    gemini = connection.execute("""SELECT enabled,limit_microusd,spent_microusd,reserved_microusd,
        frozen_reason IS NOT NULL AS frozen,expires_at,
        extract(epoch FROM expires_at-now()) AS expiry_seconds FROM video_ai_budget WHERE id=1""").fetchone()
    checks.append(allowance_check("gemini_budget", gemini, selective))
    # Do not call config.media_root(): that helper creates a missing directory.
    try:
        disk = disk_usage(Path(environment.get("VIDEO_STORAGE_PATH", "/var/lib/narma/video")))
        checks.append(disk_check(disk.total, disk.free))
    except OSError:
        checks.append(check("media_disk", "critical", readable=False))
    return snapshot_result(checks)


def main():
    try:
        with database() as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            connection.execute("SET LOCAL statement_timeout = '10s'")
            result = collect(connection)
    except Exception:
        # No exception text: PostgreSQL errors can contain connection details.
        result = snapshot_result([check("snapshot_unavailable", "critical")])
    print(json.dumps(result, separators=(",", ":")))
    # The runner interprets status; keep the structured receipt even on failure.
    return result


if __name__ == "__main__":
    main()
