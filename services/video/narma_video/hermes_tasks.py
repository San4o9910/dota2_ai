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
# JSON-object provider output, as requested by native Hermes; the full Review
# schema remains in the prompt and strict local validation. This immutable input
# change never resets an earlier task or its provider accounting.
RUNTIME_CONTRACT = "narma.hermes.json-object.v1"
CHATGPT_MODEL = "gpt-5.4"
CHATGPT_PROVIDER = "chatgpt_subscription"
CHATGPT_CONTRACT = "narma.hermes.chatgpt-auth.v1"
OPENAI_PROVIDER = "openai_api"
OPENAI_MODEL = "gpt-5.6-sol"
OPENAI_CONTRACT = "narma.hermes.openai-api.v1"
LEASE_SECONDS = 240
RUNNER_TIMEOUT_SECONDS = 200
TOKEN = re.compile(r"^[A-Za-z0-9_-]{43}$")
ERROR_CODES = frozenset({"HERMES_RUNTIME_UNAVAILABLE", "HERMES_RUNTIME_REVISION",
    "HERMES_RUNNER_TIMEOUT", "HERMES_RUNNER_FAILED", "HERMES_REVIEW_INVALID",
    "HERMES_SOURCE_CHANGED", "HERMES_LEASE_EXPIRED", "HERMES_CALL_NOT_SETTLED",
    "HERMES_UPSTREAM_INIT_FAILED", "HERMES_UPSTREAM_CALL_FAILED", "HERMES_OUTPUT_EMPTY",
    "HERMES_OUTPUT_TOO_LARGE", "HERMES_OUTPUT_JSON_INVALID", "HERMES_RUNTIME_INVARIANT",
    "HERMES_REVISION_MISMATCH", "HERMES_EXECUTION_FAILED", "HERMES_DEADLINE_EXCEEDED",
    "HERMES_CONNECTION_CHANGED", "HERMES_MODEL_UNSUPPORTED"})


def configured_provider():
    """Every provider is explicit; no failure falls through to another biller."""
    value = os.environ.get("HERMES_PROVIDER", "gemini")
    return value if value in ("gemini", CHATGPT_PROVIDER, OPENAI_PROVIDER) else "disabled"


def _openai_context():
    return {"provider": OPENAI_PROVIDER, "model": OPENAI_MODEL,
        "runtime_revision": RUNTIME_REVISION}


def _openai_available(connection):
    from . import openai_budget, openai_provider
    allowance = openai_budget.status(connection)
    return bool(openai_provider.configured() and allowance["enabled"]
        and allowance.get("price_valid", False)
        and allowance.get("available_microusd", 0) >= openai_budget.estimate_reservation(
            openai_budget.MAX_INPUT_TOKENS, 4096))


def _connection_current(connection, owner_id, generation=None, *, require_available=True):
    from .chatgpt_auth import current_connection
    current = current_connection(connection, owner_id)
    return bool(current and current["connected"] and (not require_available or current["available"]) and
                (generation is None or str(current["generation"]) == str(generation)))


def task_model(task):
    provider = task.get("provider", "gemini")
    model = task.get("model", MODEL)
    if ((provider == "gemini" and model == MODEL and task.get("connection_generation") is None)
            or (provider == CHATGPT_PROVIDER and model == CHATGPT_MODEL
                and task.get("connection_generation") is not None)
            or (provider == OPENAI_PROVIDER and model == OPENAI_MODEL
                and task.get("connection_generation") is None
                and task.get("snapshot", {}).get("runtime_contract") == OPENAI_CONTRACT
                and task.get("snapshot", {}).get("provider_context") == _openai_context())):
        return model
    raise ValueError("HERMES_MODEL_UNSUPPORTED")


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
        provider = configured_provider()
        if provider == "disabled":
            continue
        if provider == OPENAI_PROVIDER:
            from .openai_provider import configured
            if not configured():
                continue
        generation = None
        if provider == CHATGPT_PROVIDER:
            from .chatgpt_auth import current_connection
            with database() as connection:
                auth = current_connection(connection, owner_id)
            if not auth or not auth["available"]:
                continue
            generation = str(auth["generation"])
        snapshot, _, sources = build_snapshot(get_pool(owner_id, include_coaching=False))
        # Without evidence from two games there can be no supported repetition.
        if sum(bool(row["evidence"]) for row in snapshot["observations"]) < 2:
            continue
        snapshot = {**snapshot, "runtime_contract": {"gemini": RUNTIME_CONTRACT,
            CHATGPT_PROVIDER: CHATGPT_CONTRACT, OPENAI_PROVIDER: OPENAI_CONTRACT}[provider]}
        model = {"gemini": MODEL, CHATGPT_PROVIDER: CHATGPT_MODEL, OPENAI_PROVIDER: OPENAI_MODEL}[provider]
        if provider == CHATGPT_PROVIDER:
            snapshot["provider_context"] = {"provider": provider, "model": model,
                "connection_generation": generation}
        elif provider == OPENAI_PROVIDER:
            snapshot["provider_context"] = _openai_context()
        digest = hashlib.sha256(canonical_bytes(snapshot)).hexdigest()
        with database() as connection:
            connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (owner_id,))
            if provider == CHATGPT_PROVIDER and not _connection_current(connection, owner_id, generation):
                continue
            if not _sources_available(connection, owner_id, sources):
                continue
            if provider == CHATGPT_PROVIDER and _subscription_attempted_facts(connection, owner_id,
                    snapshot["player"]["account_id"], snapshot):
                # Reconnecting never grants permission to resend an uncertain
                # request for these same facts under a new credential generation.
                continue
            if provider == OPENAI_PROVIDER and _openai_attempted_facts(connection, owner_id,
                    snapshot["player"]["account_id"], snapshot):
                # A model/contract change is not permission to repeat an unknown
                # paid attempt. New evidence may create a genuinely new task.
                continue
            if _completed_facts(connection, owner_id, snapshot["player"]["account_id"], snapshot):
                # A corrected transport does not justify buying another review
                # of facts already reviewed successfully under an older contract.
                continue
            connection.execute("""UPDATE hermes_tasks SET state='stale',
                error_code='HERMES_SOURCE_CHANGED',finished_at=now()
                WHERE owner_id=%s AND account_id=%s AND state='queued' AND snapshot_sha256<>%s""",
                (owner_id, snapshot["player"]["account_id"], digest))
            row = connection.execute("""INSERT INTO hermes_tasks
                (id,owner_id,account_id,snapshot_sha256,snapshot,source_jobs,provider,model,connection_generation)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (owner_id,account_id,snapshot_sha256)
                DO NOTHING RETURNING id""", (uuid4(), owner_id, snapshot["player"]["account_id"],
                    digest, Jsonb(snapshot), Jsonb(sources), provider, model, generation)).fetchone()
            added += bool(row)
    return added


def _completed_facts(connection, owner_id, account_id, snapshot):
    facts = {key: value for key, value in snapshot.items() if key not in ("runtime_contract", "provider_context")}
    return bool(connection.execute("""SELECT 1 FROM hermes_tasks
        WHERE owner_id=%s AND account_id=%s AND state='succeeded'
        AND snapshot-'runtime_contract'-'provider_context'=%s LIMIT 1""", (owner_id, account_id, Jsonb(facts))).fetchone())


def _subscription_attempted_facts(connection, owner_id, account_id, snapshot):
    facts = {key: value for key, value in snapshot.items() if key not in ("runtime_contract", "provider_context")}
    return bool(connection.execute("""SELECT 1 FROM hermes_tasks t
        WHERE t.owner_id=%s AND t.account_id=%s AND t.provider='chatgpt_subscription'
        AND t.snapshot-'runtime_contract'-'provider_context'=%s
        AND EXISTS(SELECT 1 FROM chatgpt_calls c WHERE c.task_id=t.id AND c.owner_id=t.owner_id
            AND c.started_at IS NOT NULL) LIMIT 1""", (owner_id, account_id, Jsonb(facts))).fetchone())


def _openai_attempted_facts(connection, owner_id, account_id, snapshot):
    facts = {key: value for key, value in snapshot.items() if key not in ("runtime_contract", "provider_context")}
    return bool(connection.execute("""SELECT 1 FROM hermes_tasks t
        WHERE t.owner_id=%s AND t.account_id=%s AND t.provider='openai_api'
        AND t.snapshot-'runtime_contract'-'provider_context'=%s
        AND EXISTS(SELECT 1 FROM openai_api_calls c WHERE c.task_id=t.id AND c.owner_id=t.owner_id
            AND c.started_at IS NOT NULL) LIMIT 1""", (owner_id, account_id, Jsonb(facts))).fetchone())


def _subscription_allowance(connection, owner_id, generation):
    from .chatgpt_provider import daily_limit
    blocked = connection.execute("""SELECT 1 FROM chatgpt_calls WHERE owner_id=%s AND connection_generation=%s
        AND error_code='CHATGPT_QUOTA' AND (pause_until IS NULL OR pause_until>clock_timestamp()) LIMIT 1""",
        (owner_id, generation)).fetchone()
    count = connection.execute("""SELECT count(*) AS count FROM chatgpt_calls WHERE owner_id=%s
        AND created_at >= date_trunc('day',clock_timestamp() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'""",
        (owner_id,)).fetchone()["count"]
    return not blocked and count < daily_limit()


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
        provider = configured_provider()
        if provider == "disabled":
            return None
        if provider == "gemini":
            allowance = budget_status(connection)
            if not allowance["enabled"] or allowance.get("available_microusd", 0) < RESERVATION:
                return None
        if provider == OPENAI_PROVIDER and not _openai_available(connection):
            return None
        connection.execute("""UPDATE hermes_tasks SET state='failed',error_code='HERMES_LEASE_EXPIRED',
            finished_at=now(),credential_sha256=NULL WHERE state='running' AND lease_until<=clock_timestamp()""")
        # Skip stale queued snapshots and let another scheduler claim independent
        # rows safely. The one-attempt budget index is a second concurrency fence.
        rows = connection.execute("""SELECT t.* FROM hermes_tasks t WHERE t.state='queued'
            AND t.attempts=0 AND t.provider=%s
            AND (t.provider<>'gemini' OR (SELECT count(*) FROM video_provider_calls c
                WHERE c.owner_id=t.owner_id AND c.created_at>now()-interval '1 day')<250)
            ORDER BY t.created_at,t.id FOR UPDATE OF t SKIP LOCKED LIMIT 250""", (provider,)).fetchall()
        for row in rows:
            if provider == OPENAI_PROVIDER:
                try:
                    task_model(row)
                except ValueError:
                    connection.execute("""UPDATE hermes_tasks SET state='stale',
                        error_code='HERMES_MODEL_UNSUPPORTED',finished_at=now() WHERE id=%s""", (row["id"],))
                    continue
            if provider == CHATGPT_PROVIDER and not _connection_current(connection, row["owner_id"],
                    row["connection_generation"]):
                continue
            if provider == CHATGPT_PROVIDER and not _subscription_allowance(connection, row["owner_id"],
                    row["connection_generation"]):
                continue
            if not _sources_available(connection, row["owner_id"], row["source_jobs"]):
                connection.execute("""UPDATE hermes_tasks SET state='stale',
                    error_code='HERMES_SOURCE_CHANGED',finished_at=now() WHERE id=%s""", (row["id"],))
                continue
            if _completed_facts(connection, row["owner_id"], row["account_id"], row["snapshot"]):
                connection.execute("""UPDATE hermes_tasks SET state='stale',
                    error_code='HERMES_FACTS_ALREADY_REVIEWED',finished_at=now() WHERE id=%s""", (row["id"],))
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
    task_model(row)
    if row.get("provider", "gemini") != configured_provider():
        raise ValueError("HERMES_CONNECTION_CHANGED")
    if row.get("provider") == OPENAI_PROVIDER:
        from .openai_provider import configured
        if not configured():
            raise ValueError("HERMES_CONNECTION_CHANGED")
    if row.get("provider") == CHATGPT_PROVIDER and not _connection_current(connection,
            row["owner_id"], row["connection_generation"]):
        raise ValueError("HERMES_CONNECTION_CHANGED")
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
        model = task_model(row)
        if row.get("provider") == CHATGPT_PROVIDER:
            from .chatgpt_provider import verified_call
            if not _connection_current(connection, row["owner_id"], row["connection_generation"], require_available=False):
                raise ValueError("HERMES_CONNECTION_CHANGED")
            if not verified_call(connection, owner_id=row["owner_id"], task_id=row["id"],
                    expected_generation=str(row["connection_generation"]), model=model, output_text=final_response):
                raise ValueError("HERMES_CALL_NOT_SETTLED")
            if validated["producer"] != {"name": "NousResearch/hermes-agent", "version": RUNTIME_REVISION, "model": model}:
                raise ValueError("HERMES_REVIEW_INVALID")
        elif row.get("provider") == OPENAI_PROVIDER:
            from .openai_provider import verified_call
            if not verified_call(connection, owner_id=row["owner_id"], task_id=row["id"],
                    model=model, output_text=final_response):
                raise ValueError("HERMES_CALL_NOT_SETTLED")
            if validated["producer"] != {"name": "NousResearch/hermes-agent", "version": RUNTIME_REVISION, "model": model}:
                raise ValueError("HERMES_REVIEW_INVALID")
        else:
            calls = connection.execute("""SELECT model,billing_status FROM video_provider_calls
                WHERE hermes_task_id=%s AND call_kind='hermes'""", (row["id"],)).fetchall()
            if len(calls) != 1 or calls[0]["billing_status"] != "settled" or calls[0]["model"] != model:
                raise ValueError("HERMES_CALL_NOT_SETTLED")
        validated["producer"] = {"name": "NousResearch/hermes-agent", "version": RUNTIME_REVISION, "model": model}
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
            if _sources_available(connection, owner_id, row["source_jobs"], lock=False):
                return {"id": str(row["id"]), "created_at": row["finished_at"], "source": "hermes_runtime",
                    "runtime_verified": True, "interpretation_verified": False,
                    "runtime_revision": row["runtime_revision"], "snapshot_sha256": row["snapshot_sha256"],
                    "snapshot": row["snapshot"], "source_jobs": row["source_jobs"], "review": row["review"],
                    "provider": row.get("provider", "gemini"), "model": row.get("model", MODEL),
                    "connection_generation": str(row["connection_generation"]) if row.get("connection_generation") else None}
    return None


def get_runtime_status(owner_id):
    provider = configured_provider()
    auth = None
    subscription_available = False
    openai_configured = openai_available = False
    with database() as connection:
        worker = connection.execute("""SELECT *,last_seen>now()-interval '150 seconds' AS fresh
            FROM hermes_workers WHERE id='scheduler'""").fetchone()
        last = connection.execute("""SELECT t.state,t.finished_at,t.runtime_revision,t.provider,
            t.connection_generation,t.attempts,t.error_code FROM hermes_tasks t
            JOIN portal_dota_profiles p ON p.owner_id=t.owner_id AND p.account_id=t.account_id
            WHERE t.owner_id=%s ORDER BY t.created_at DESC,t.id DESC LIMIT 1""", (owner_id,)).fetchone()
        if provider == CHATGPT_PROVIDER:
            from .chatgpt_auth import current_connection
            auth = current_connection(connection, owner_id)
            subscription_available = bool(auth and auth["available"] and
                _subscription_allowance(connection, owner_id, auth["generation"]))
        elif provider == OPENAI_PROVIDER:
            from .openai_provider import configured
            openai_configured = configured()
            openai_available = _openai_available(connection)
    latest = latest_valid_review(owner_id)
    services_ready = bool(worker and worker["fresh"] and worker["runtime_revision"] == RUNTIME_REVISION)
    connection_ready = provider == "gemini" or bool(auth and auth["connected"]) or openai_configured
    available = provider == "gemini" or subscription_available or openai_available
    verified = bool(latest and latest["provider"] == provider and (provider != CHATGPT_PROVIDER
        or (auth and latest["connection_generation"] == str(auth["generation"])))
        and (provider != OPENAI_PROVIDER or latest["model"] == OPENAI_MODEL))
    connected = bool(services_ready and connection_ready and verified)
    current_task = bool(last and last["provider"] == provider and (provider != CHATGPT_PROVIDER
        or (auth and str(last["connection_generation"]) == str(auth["generation"]))))
    readiness = ("services_unavailable" if not services_ready else
        ("waiting_api_key" if provider == OPENAI_PROVIDER else "waiting_auth") if not connection_ready
        else "paused" if not available else "running" if current_task and last["state"] == "running"
        else "verified" if verified else "requires_review" if last and last["provider"] == provider and last["state"] == "failed"
        and last["attempts"] else "ready")
    return {"runtime_connected": connected,
        "automatic_tracking": bool(connected and available and worker["automatic_tracking"]),
        "runtime_verified": verified, "services_ready": services_ready,
        "provider_configured": connection_ready,
        "connection_ready": connection_ready, "provider": provider, "readiness": readiness,
        "last_seen": worker["last_seen"] if worker else None,
        "runtime_revision": worker["runtime_revision"] if connected else None,
        "last_success_at": latest["created_at"] if latest else None,
        "state": last["state"] if last else "waiting"}


def _runner_json(path, body=None, timeout=10):
    base = os.environ.get("HERMES_RUNNER_URL", "http://hermes-runner:8092").rstrip("/")
    # This address is deployment configuration, never player-controlled input.
    request = urllib.request.Request(base + path,
        data=canonical_bytes(body) if body is not None else None,
        headers={"Content-Type": "application/json"} if body is not None else {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_EXPORT_BYTES + MAX_REVIEW_BYTES + 1)
    except urllib.error.HTTPError as error:
        code = "HERMES_RUNNER_FAILED"
        try:
            body = json.loads(error.read(1025))
            if isinstance(body, dict) and body.get("error") in ERROR_CODES:
                code = body["error"]
        except (OSError, ValueError, TypeError):
            pass
        finally:
            error.close()
        raise ValueError(code) from None
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
        " role_contexts contains practice guidance keyed by the observation's position, not observed evidence."
        " Use its distinct lane, map and item priorities."
        " Never judge support performance from carry last-hit or GPM goals. Support farm is contextual."
        " Rune help, pulls, vision and allied lane safety need episode evidence; ask review questions when absent."
        " Support rotations are conditional on the ally's safety and an achievable purpose, never mandatory roaming."
        " Unknown abilities, build, patch, match conditions and dates remain unknown."
        " Different heroes/positions are not interchangeable evidence for hero-specific advice."
        " Return producer name NousResearch/hermes-agent, version " + RUNTIME_REVISION + " and model " + task_model(task) + ".")
    previous = latest_valid_review(task["owner_id"])
    if previous:
        # Prior prose remains labeled as an interpretation, never promoted to
        # facts. Only current packet evidence IDs may support this response.
        packet["prior_goals"] = {"classification": "unverified_interpretation",
            "snapshot_sha256": previous["snapshot_sha256"],
            "goals": previous["review"]["goals"]}
    try:
        result = _runner_json("/run", {"task_id": str(task_id), "token": task["token"],
            "packet": packet, "model": task_model(task)}, timeout=RUNNER_TIMEOUT_SECONDS)
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
