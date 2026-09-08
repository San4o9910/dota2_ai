"""Durable, source-bound jobs for the separately isolated, pinned Hermes runtime.

The runtime only receives a short-lived task credential. Provider authorization
and budget reservation happen together in the private broker, never here.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import urllib.request
from uuid import uuid4

from psycopg.types.json import Jsonb

from .budget import MODEL, RESERVATION, status as budget_status
from .db import database
from .hermes_bridge import (MAX_EXPORT_BYTES, MAX_REVIEW_BYTES, Review,
    _sources_available, build_snapshot, canonical_bytes, packet_for, validate_review)

RUNTIME_REVISION = "9fd44b4dfc44138b9e5d5689acb56c438364ff7b"
LEASE_SECONDS = 240
RUNNER_TIMEOUT_SECONDS = 200
TOKEN = re.compile(r"^[A-Za-z0-9_-]{43}$")
ERROR_CODES = frozenset({"HERMES_RUNTIME_UNAVAILABLE", "HERMES_RUNTIME_REVISION",
    "HERMES_RUNNER_TIMEOUT", "HERMES_RUNNER_FAILED", "HERMES_REVIEW_INVALID",
    "HERMES_SOURCE_CHANGED", "HERMES_LEASE_EXPIRED", "HERMES_CALL_NOT_SETTLED"})


def enqueue_eligible():
    """Discover newly ready snapshots without making any provider request."""
    from .hero_pool import get_pool
    with database() as connection:
        owners = connection.execute("""SELECT p.owner_id FROM portal_dota_profiles p
            JOIN replay_jobs r ON r.owner_id=p.owner_id AND r.account_id=p.account_id
            WHERE r.state='ready' GROUP BY p.owner_id
            HAVING count(DISTINCT r.match_id)>=2 ORDER BY p.owner_id LIMIT 250""").fetchall()
    added = 0
    for owner in owners:
        owner_id = owner["owner_id"]
        snapshot, digest, sources = build_snapshot(get_pool(owner_id, include_coaching=False))
        # Without evidence from two games there can be no supported repetition.
        if sum(bool(row["evidence"]) for row in snapshot["observations"]) < 2:
            continue
        with database() as connection:
            connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (owner_id,))
            if not _sources_available(connection, owner_id, sources):
                continue
            connection.execute("""UPDATE hermes_tasks SET state='stale',
                error_code='HERMES_SOURCE_CHANGED',finished_at=now()
                WHERE owner_id=%s AND account_id=%s AND state='queued' AND snapshot_sha256<>%s""",
                (owner_id, snapshot["player"]["account_id"], digest))
            row = connection.execute("""INSERT INTO hermes_tasks
                (id,owner_id,account_id,snapshot_sha256,snapshot,source_jobs)
                VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (owner_id,account_id,snapshot_sha256)
                DO NOTHING RETURNING id""", (uuid4(), owner_id, snapshot["player"]["account_id"],
                    digest, Jsonb(snapshot), Jsonb(sources))).fetchone()
            added += bool(row)
    return added


def claim_task():
    """One lifetime runner attempt; expired leases become terminal, never retried."""
    with database() as connection:
        connection.execute("SELECT pg_advisory_xact_lock(643847215)")
        busy = connection.execute("""SELECT
            EXISTS(SELECT 1 FROM replay_jobs WHERE state IN ('queued','processing'))
            OR EXISTS(SELECT 1 FROM video_jobs WHERE state='processing')
            OR EXISTS(SELECT 1 FROM hermes_tasks WHERE state='running' AND lease_until>clock_timestamp()) AS busy""").fetchone()
        if busy["busy"]:
            return None
        allowance = budget_status(connection)
        if not allowance["enabled"] or allowance.get("available_microusd", 0) < RESERVATION:
            return None
        connection.execute("""UPDATE hermes_tasks SET state='failed',error_code='HERMES_LEASE_EXPIRED',
            finished_at=now(),credential_sha256=NULL WHERE state='running' AND lease_until<=clock_timestamp()""")
        # Skip stale queued snapshots and let another scheduler claim independent
        # rows safely. The one-attempt budget index is a second concurrency fence.
        for _ in range(250):
            row = connection.execute("""SELECT t.* FROM hermes_tasks t WHERE t.state='queued'
                AND t.attempts=0 AND (SELECT count(*) FROM video_provider_calls c
                    WHERE c.owner_id=t.owner_id AND c.created_at>now()-interval '1 day')<250
                ORDER BY t.created_at,t.id FOR UPDATE OF t SKIP LOCKED LIMIT 1""").fetchone()
            if not row:
                return None
            if not _sources_available(connection, row["owner_id"], row["source_jobs"]):
                connection.execute("""UPDATE hermes_tasks SET state='stale',
                    error_code='HERMES_SOURCE_CHANGED',finished_at=now() WHERE id=%s""", (row["id"],))
                continue
            token, lease_token = secrets.token_urlsafe(32), uuid4()
            claimed = connection.execute("""UPDATE hermes_tasks SET state='running',attempts=1,
                lease_token=%s,credential_sha256=%s,lease_until=clock_timestamp()+%s*interval '1 second',
                started_at=clock_timestamp() WHERE id=%s RETURNING *""", (lease_token,
                    hashlib.sha256(token.encode()).hexdigest(), LEASE_SECONDS, row["id"])).fetchone()
            return {**claimed, "token": token}
    return None


def authorize_call(connection, token):
    """Hold the task/source locks until the broker's reservation is committed."""
    if not isinstance(token, str) or not TOKEN.fullmatch(token):
        raise ValueError("HERMES_TOKEN_INVALID")
    credential = hashlib.sha256(token.encode()).hexdigest()
    identity = connection.execute("SELECT owner_id FROM hermes_tasks WHERE credential_sha256=%s", (credential,)).fetchone()
    if not identity:
        raise ValueError("HERMES_TOKEN_INVALID")
    connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,1))", (identity["owner_id"],))
    row = connection.execute("""SELECT * FROM hermes_tasks
        WHERE credential_sha256=%s FOR UPDATE""", (credential,)).fetchone()
    if not row:
        raise ValueError("HERMES_TOKEN_INVALID")
    if row["state"] != "running" or not _lease_valid(connection, row):
        raise ValueError("HERMES_LEASE_EXPIRED")
    if not _sources_available(connection, row["owner_id"], row["source_jobs"]):
        raise ValueError("HERMES_SOURCE_CHANGED")
    if not _lease_valid(connection, row):
        raise ValueError("HERMES_LEASE_EXPIRED")
    return row


def _lease_valid(connection, row):
    # Run this after lock acquisition: transaction-start now(), and a computed
    # SELECT expression evaluated before a row lock wait, can both be stale.
    current = connection.execute("""SELECT lease_until>clock_timestamp() AS valid
        FROM hermes_tasks WHERE id=%s AND lease_token=%s""", (row["id"], row["lease_token"])).fetchone()
    return bool(current and current["valid"])


def fail_task(task_id, lease_token, code):
    code = code if code in ERROR_CODES else "HERMES_RUNNER_FAILED"
    with database() as connection:
        connection.execute("""UPDATE hermes_tasks SET state='failed',error_code=%s,
            finished_at=now(),credential_sha256=NULL WHERE id=%s AND lease_token=%s AND state='running'""",
            (code, task_id, lease_token))


def complete_task(task_id, lease_token, final_response, revision):
    if revision != RUNTIME_REVISION:
        raise ValueError("HERMES_RUNTIME_REVISION")
    if not isinstance(final_response, str) or len(final_response.encode()) > MAX_REVIEW_BYTES:
        raise ValueError("HERMES_REVIEW_INVALID")
    try:
        review = Review.model_validate_json(final_response)
    except ValueError as error:
        raise ValueError("HERMES_REVIEW_INVALID") from error
    with database() as connection:
        row = connection.execute("""SELECT * FROM hermes_tasks
            WHERE id=%s AND lease_token=%s FOR UPDATE""", (task_id, lease_token)).fetchone()
        if not row or (row["state"] != "succeeded" and (row["state"] != "running" or not _lease_valid(connection, row))):
            raise ValueError("HERMES_LEASE_EXPIRED")
        if not _sources_available(connection, row["owner_id"], row["source_jobs"]):
            raise ValueError("HERMES_SOURCE_CHANGED")
        try:
            validated = validate_review(review, row["snapshot"], row["snapshot_sha256"])
        except ValueError as error:
            raise ValueError("HERMES_REVIEW_INVALID") from error
        # Provenance comes from the installed runtime and the settled broker call,
        # never from the model's self-description or an external imported review.
        calls = connection.execute("""SELECT model,billing_status FROM video_provider_calls
            WHERE hermes_task_id=%s AND call_kind='hermes'""", (row["id"],)).fetchall()
        if len(calls) != 1 or calls[0]["billing_status"] != "settled" or calls[0]["model"] != MODEL:
            raise ValueError("HERMES_CALL_NOT_SETTLED")
        validated["producer"] = {"name": "NousResearch/hermes-agent", "version": RUNTIME_REVISION, "model": MODEL}
        if row["state"] == "succeeded":
            if row["review"] != validated:
                raise ValueError("HERMES_REVIEW_INVALID")
            return str(row["id"])
        saved = connection.execute("""UPDATE hermes_tasks SET state='succeeded',review=%s,
            runtime_revision=%s,finished_at=now(),credential_sha256=NULL
            WHERE id=%s AND lease_until>clock_timestamp() RETURNING id""",
            (Jsonb(validated), RUNTIME_REVISION, row["id"])).fetchone()
        if not saved:
            raise ValueError("HERMES_LEASE_EXPIRED")
    return str(task_id)


def latest_valid_review(owner_id):
    """Only the current bound player's still-verifiable runtime review is public."""
    with database() as connection:
        rows = connection.execute("""SELECT t.* FROM hermes_tasks t
            JOIN portal_dota_profiles p ON p.owner_id=t.owner_id AND p.account_id=t.account_id
            WHERE t.owner_id=%s AND t.state='succeeded' AND t.runtime_revision=%s
            ORDER BY t.finished_at DESC,t.id DESC LIMIT 30""", (owner_id, RUNTIME_REVISION)).fetchall()
        for row in rows:
            if _sources_available(connection, owner_id, row["source_jobs"]):
                return {"id": str(row["id"]), "created_at": row["finished_at"], "source": "hermes_runtime",
                    "runtime_verified": True, "interpretation_verified": False,
                    "runtime_revision": row["runtime_revision"], "snapshot_sha256": row["snapshot_sha256"],
                    "snapshot": row["snapshot"], "source_jobs": row["source_jobs"], "review": row["review"]}
    return None


def get_runtime_status(owner_id):
    with database() as connection:
        worker = connection.execute("""SELECT *,last_seen>now()-interval '150 seconds' AS fresh
            FROM hermes_workers WHERE id='scheduler'""").fetchone()
        last = connection.execute("""SELECT t.state,t.finished_at,t.runtime_revision FROM hermes_tasks t
            JOIN portal_dota_profiles p ON p.owner_id=t.owner_id AND p.account_id=t.account_id
            WHERE t.owner_id=%s ORDER BY t.created_at DESC,t.id DESC LIMIT 1""", (owner_id,)).fetchone()
        executed = connection.execute("""SELECT max(finished_at) AS last_success_at FROM hermes_tasks
            WHERE state='succeeded' AND runtime_revision=%s""", (RUNTIME_REVISION,)).fetchone()
    connected = bool(worker and worker["fresh"] and worker["runtime_revision"] == RUNTIME_REVISION
        and executed["last_success_at"])
    return {"runtime_connected": connected,
        "automatic_tracking": bool(connected and worker["automatic_tracking"]),
        "last_seen": worker["last_seen"] if worker else None,
        "runtime_revision": worker["runtime_revision"] if connected else None,
        "last_success_at": executed["last_success_at"], "state": last["state"] if last else "waiting"}


def _runner_json(path, body=None, timeout=10):
    base = os.environ.get("HERMES_RUNNER_URL", "http://hermes-runner:8092").rstrip("/")
    # This address is deployment configuration, never player-controlled input.
    request = urllib.request.Request(base + path,
        data=canonical_bytes(body) if body is not None else None,
        headers={"Content-Type": "application/json"} if body is not None else {})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(MAX_EXPORT_BYTES + MAX_REVIEW_BYTES + 1)
    if len(raw) > MAX_EXPORT_BYTES + MAX_REVIEW_BYTES:
        raise ValueError("HERMES_RUNNER_FAILED")
    return json.loads(raw)


def refresh_heartbeat():
    health = _runner_json("/healthz")
    if not isinstance(health, dict) or health.get("status") != "ready" or health.get("runtime_revision") != RUNTIME_REVISION:
        raise ValueError("HERMES_RUNTIME_REVISION")
    with database() as connection:
        connection.execute("""INSERT INTO hermes_workers(id,runtime_revision,automatic_tracking)
            VALUES ('scheduler',%s,%s) ON CONFLICT (id) DO UPDATE SET
            runtime_revision=excluded.runtime_revision,automatic_tracking=excluded.automatic_tracking,last_seen=now()""",
            (RUNTIME_REVISION, os.environ.get("HERMES_RUNTIME_ENABLED") == "1"))
    return health


def process_once():
    """One bounded review, usable by both the scheduler and activation gate."""
    try:
        refresh_heartbeat()
    except (OSError, ValueError):
        return {"status": "failed", "error_code": "HERMES_RUNTIME_UNAVAILABLE"}
    enqueue_eligible()
    task = claim_task()
    if not task:
        return {"status": "idle"}
    task_id, lease_token = task["id"], task["lease_token"]
    packet = packet_for(task)["packet"]
    packet["instructions"] += (
        " Analyze each hero and the explicitly recorded position separately; never infer position from hero."
        " Unknown abilities, build, patch, match conditions and dates remain unknown."
        " Different heroes/positions are not interchangeable evidence for hero-specific advice."
        " Return producer name NousResearch/hermes-agent, version " + RUNTIME_REVISION + " and model " + MODEL + ".")
    previous = latest_valid_review(task["owner_id"])
    if previous:
        # Prior prose remains labeled as an interpretation, never promoted to
        # facts. Only current packet evidence IDs may support this response.
        packet["prior_goals"] = {"classification": "unverified_interpretation",
            "snapshot_sha256": previous["snapshot_sha256"],
            "goals": previous["review"]["goals"]}
    try:
        result = _runner_json("/run", {"task_id": str(task_id), "token": task["token"],
            "packet": packet}, timeout=RUNNER_TIMEOUT_SECONDS)
        if not isinstance(result, dict):
            raise ValueError("HERMES_RUNNER_FAILED")
        review_id = complete_task(task_id, lease_token, result.get("final_response"), result.get("runtime_revision"))
        return {"status": "succeeded", "task_id": str(task_id), "review_id": review_id}
    except TimeoutError:
        code = "HERMES_RUNNER_TIMEOUT"
    except (OSError, ValueError) as error:
        code = str(error) if str(error) in ERROR_CODES else "HERMES_RUNNER_FAILED"
    finally:
        # The scheduler heartbeat does not extend task credentials or leases.
        try:
            refresh_heartbeat()
        except (OSError, ValueError):
            pass
    fail_task(task_id, lease_token, code)
    return {"status": "failed", "task_id": str(task_id), "error_code": code}
