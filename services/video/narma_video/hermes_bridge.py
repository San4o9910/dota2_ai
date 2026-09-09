"""Bounded evidence exchange for an independently operated Hermes Agent.

This module never invokes a model, subprocess, HTTP client or agent runtime.
Imported producer metadata is a claim, not proof that Hermes executed it.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import UTC, date, datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator
from starlette.concurrency import run_in_threadpool

from .db import database
from .role_context import get_role_context
from .web import account_required, csrf, reject

MAX_MATCHES = 30
MAX_EVIDENCE_PER_MATCH = 80
MAX_EXPORT_BYTES = 384 * 1024
MAX_REVIEW_BYTES = 32 * 1024
MAX_EXPORTS_PER_DAY = 10
MAX_STORED_EXPORTS = 50
MATCH_ID = re.compile(r"^[1-9][0-9]{7,11}$")
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
METRIC_KEYS = frozenset({"last_hits_10", "net_worth_10", "deaths_per_30", "repeated_deaths",
    "item_delay_seconds", "gpm", "xpm", "kills", "deaths", "assists", "last_hits",
    "denies", "duration_seconds", "tower_damage", "hero_damage"})

Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,100}$")]
MatchId = Annotated[str, StringConstraints(pattern=r"^[1-9][0-9]{7,11}$")]
ShortText = Annotated[str, StringConstraints(min_length=1, max_length=500, strip_whitespace=True)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    @field_validator("*", mode="after")
    @classmethod
    def plain_strings(cls, value):
        if isinstance(value, str) and (not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise ValueError("control characters are not allowed")
        return value


class EvidenceRef(StrictModel):
    match_id: MatchId
    evidence_id: Identifier


class Producer(StrictModel):
    name: Literal["NousResearch/hermes-agent"]
    version: Annotated[str, StringConstraints(min_length=1, max_length=80)]
    model: Annotated[str, StringConstraints(min_length=1, max_length=120)]


class Pattern(StrictModel):
    id: Identifier
    title: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    observation: ShortText
    confidence: Literal["low", "medium", "high"]
    evidence: list[EvidenceRef] = Field(min_length=2, max_length=12)


class Goal(StrictModel):
    id: Identifier
    pattern_id: Identifier
    action: ShortText
    success_criterion: ShortText
    evaluate_after_matches: int = Field(ge=3, le=20)
    evidence: list[EvidenceRef] = Field(min_length=1, max_length=12)


class Review(StrictModel):
    schema_version: Literal[1]
    snapshot_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    producer: Producer
    patterns: list[Pattern] = Field(max_length=5)
    goals: list[Goal] = Field(max_length=3)


class ImportReview(StrictModel):
    # String UUID avoids strict JSON-versus-Python parsing differences.
    export_id: Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F-]{36}$")]
    review: Review

    @field_validator("export_id")
    @classmethod
    def valid_uuid(cls, value):
        return str(UUID(value))


def canonical_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _date(value):
    if isinstance(value, datetime):
        # PostgreSQL renders timestamptz in the connection's session timezone.
        # Compare instants, not equivalent local offset spellings.
        return value.astimezone(UTC).isoformat() if value.tzinfo is not None else None
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and len(value) <= 40:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.astimezone(UTC).isoformat() if parsed.tzinfo is not None else None
    return None


def build_snapshot(pool):
    """Allowlist facts and stable game identity, never contacts or narrative prompts."""
    observations, sources, seen = [], {}, set()
    account_id = (pool.get("profile") or {}).get("account_id")
    if type(account_id) is not int or not 1 <= account_id <= 4294967294:
        account_id = None
    for row in pool.get("history", []):
        # The pool can show its last completed archive during re-analysis.
        # Hermes packets require a current ready report for source validation.
        if row.get("report_is_previous") or row.get("report_state", "ready") != "ready":
            continue
        match_id = str(row.get("match_id", ""))
        if not MATCH_ID.fullmatch(match_id) or match_id in seen:
            continue
        try:
            job_id = str(UUID(str(row["job_id"])))
        except (ValueError, KeyError, TypeError):
            continue
        hero = row.get("hero")
        source_sha256, report_sha256 = row.get("source_sha256"), row.get("report_sha256")
        pool_metadata = row.get("pool_metadata")
        if (not isinstance(hero, str) or not SAFE_ID.fullmatch(hero) or account_id is None
                or not isinstance(source_sha256, str) or not SHA256.fullmatch(source_sha256)
                or not isinstance(report_sha256, str) or not SHA256.fullmatch(report_sha256)
                or not isinstance(pool_metadata, dict)):
            continue
        metadata = {"position": pool_metadata.get("position"), "played_at": _date(pool_metadata.get("played_at"))}
        if metadata["position"] is not None and (type(metadata["position"]) is not int or not 1 <= metadata["position"] <= 5):
            continue
        metadata_digest = hashlib.sha256(canonical_bytes(metadata)).hexdigest()
        metrics = {key: value for key, value in row.get("metrics", {}).items()
                   if key in METRIC_KEYS and type(value) in (int, float) and math.isfinite(value)}
        evidence, seen_evidence = [], set()
        for event in row.get("evidence", []):
            event_id, kind, at = event.get("id"), event.get("type"), event.get("time")
            if (not isinstance(event_id, str) or not SAFE_ID.fullmatch(event_id) or event_id in seen_evidence
                    or not isinstance(kind, str) or not SAFE_ID.fullmatch(kind)
                    or type(at) not in (int, float) or not math.isfinite(at) or not -600 <= at <= 86400):
                continue
            evidence.append({"id": event_id, "type": kind, "time": at})
            seen_evidence.add(event_id)
        evidence.sort(key=lambda event: (event["time"], event["id"]))
        exported_ids = {event["id"] for event in evidence[:MAX_EVIDENCE_PER_MATCH]}
        items = []
        for item in row.get("items", []):
            name, at, event_id = item.get("item"), item.get("time"), item.get("event_id")
            if (not isinstance(name, str) or not SAFE_ID.fullmatch(name) or event_id not in exported_ids
                    or type(at) not in (int, float) or not math.isfinite(at)):
                continue
            fact = {"item": name, "time": at, "evidence_id": event_id}
            realization = item.get("realization") or {}
            use_id, use_at = realization.get("first_use_event_id"), realization.get("first_use_time")
            if use_id in exported_ids and type(use_at) in (int, float) and math.isfinite(use_at):
                fact.update(first_use_evidence_id=use_id, first_use_time=use_at)
            delay = realization.get("delay_from_active_seconds")
            if type(delay) in (int, float) and math.isfinite(delay) and delay >= 0:
                fact["delay_from_active_seconds"] = delay
            items.append(fact)
            if len(items) >= 30:
                break
        position = row.get("position")
        observations.append({"match_id": match_id, "hero": hero,
            "position": position if type(position) is int and 1 <= position <= 5 else None,
            "outcome": row.get("outcome") if row.get("outcome") in {"win", "loss", "unknown"} else "unknown",
            "played_at": _date(row.get("played_at")), "analyzed_at": _date(row.get("analyzed_at")),
            "date_source": row.get("date_source") if row.get("date_source") in {"match", "replay", "user", "analysis", "analyzed_at", "unknown"} else "unknown",
            "source": {"replay_sha256": source_sha256, "report_sha256": report_sha256, "metadata_sha256": metadata_digest},
            "metrics": metrics, "items": items, "evidence": evidence[:MAX_EVIDENCE_PER_MATCH],
            "evidence_truncated": len(evidence) > MAX_EVIDENCE_PER_MATCH})
        sources[match_id] = {"job_id": job_id, "account_id": account_id,
                            "source_sha256": source_sha256, "report_sha256": report_sha256,
                            "pool_metadata": metadata}
        seen.add(match_id)
        if len(observations) == MAX_MATCHES:
            break
    # Source order is irrelevant to the digest and identifiers remain match-local.
    observations.sort(key=lambda row: row["match_id"])
    snapshot = {"schema_version": 1, "player": {"account_id": account_id}, "observations": observations,
        "role_contexts": {str(position): get_role_context(position)
                          for position in sorted({row["position"] for row in observations if row["position"] is not None})},
        "limits": {"max_matches": MAX_MATCHES, "max_evidence_per_match": MAX_EVIDENCE_PER_MATCH},
        "notes": ["A missing value is unknown, never zero.",
                  "Win rate is an outcome, not proof of improved game understanding.",
                  "Only the listed evidence IDs may support recommendations.",
                  "Item-specific advice may use only the explicit item facts; unlisted item identity is unknown.",
                  "Narrative interpretations remain unverified and never become game statistics."]}
    encoded = canonical_bytes(snapshot)
    if len(encoded) > MAX_EXPORT_BYTES:
        reject(413, "HERMES_EXPORT_SIZE", "Слишком много данных для обмена.")
    return snapshot, hashlib.sha256(encoded).hexdigest(), sources


def validate_review(review, snapshot, digest):
    """Reject fabricated references and cross-pattern goals before persistence."""
    if review.snapshot_sha256 != digest:
        raise ValueError("snapshot mismatch")
    available = {(row["match_id"], event["id"]) for row in snapshot["observations"] for event in row["evidence"]}
    patterns, goals = {}, set()
    for pattern in review.patterns:
        refs = {(ref.match_id, ref.evidence_id) for ref in pattern.evidence}
        if (pattern.id in patterns or len(refs) != len(pattern.evidence) or not refs <= available
                or len({match for match, _ in refs}) < 2):
            raise ValueError("pattern requires distinct verified matches and evidence")
        patterns[pattern.id] = refs
    for goal in review.goals:
        refs = {(ref.match_id, ref.evidence_id) for ref in goal.evidence}
        if (goal.id in goals or goal.pattern_id not in patterns or len(refs) != len(goal.evidence)
                or not refs <= patterns[goal.pattern_id]):
            raise ValueError("goal must refer to its pattern evidence")
        goals.add(goal.id)
    return review.model_dump()


def _sources_available(connection, owner_id, sources, *, lock=True):
    if not sources:
        return False
    query = """SELECT r.id,r.match_id,r.account_id,r.source_sha256,m.position,m.played_at,
        encode(sha256(convert_to(r.result_payload::text,'UTF8')),'hex') AS report_sha256 FROM replay_jobs r
        JOIN portal_dota_profiles p ON p.owner_id=r.owner_id AND p.account_id=r.account_id
        JOIN hero_pool_matches m ON m.owner_id=r.owner_id AND m.account_id=r.account_id AND m.match_id=r.match_id
        WHERE r.owner_id=%s AND r.id=ANY(%s) AND r.state='ready'"""
    if lock:
        query += " FOR SHARE OF r,p,m"
    rows = connection.execute(query, (owner_id, [UUID(value["job_id"]) for value in sources.values()])).fetchall()
    return {str(row["match_id"]): {"job_id": str(row["id"]), "account_id": row["account_id"],
            "source_sha256": row["source_sha256"], "report_sha256": row["report_sha256"],
            "pool_metadata": {"position": row["position"], "played_at": _date(row["played_at"])}} for row in rows} == sources


def _owned_export(connection, owner_id, export_id):
    row = connection.execute("""SELECT * FROM hermes_exports WHERE id=%s AND owner_id=%s
        AND created_at>now()-interval '7 days' FOR UPDATE""", (export_id, owner_id)).fetchone()
    if row is None or not _sources_available(connection, owner_id, row["source_jobs"]):
        reject(404, "HERMES_EXPORT_UNAVAILABLE", "Пакет устарел или исходный разбор удалён. Подготовьте новый пакет.")
    return row


def packet_for(row):
    packet = {"export_id": str(row["id"]), "snapshot_sha256": row["snapshot_sha256"],
        "packet": {"purpose": "Narma Vision longitudinal coaching evidence",
            "snapshot_sha256": row["snapshot_sha256"], "snapshot": row["snapshot"],
            "response_schema": Review.model_json_schema(),
            "instructions": "Find at most five repeated gameplay patterns using evidence from at least two distinct matches per pattern. Return only JSON matching response_schema. Never invent events, account identity, item identity or missing metrics. The observation field is an unverified reflection question or cautious interpretation, never a claim about MMR, intent or causes. Suggest at most three measurable future actions. A small sample does not establish a trend. Text fields must be plain Russian text. Empty patterns and goals are valid when evidence is insufficient."}}
    packet["packet"]["instructions"] += (
        " Keep heroes and declared positions separate. The role_contexts mapping is practice guidance, not match evidence."
        " Use the corresponding position's priorities and leave missing positions unknown."
        " Low support last hits or GPM do not establish an error; check allied lane needs and the cost of moving."
        " Never invent rune help, pulls, vision, lane safety or created space from generic counters.")
    return packet


def create_export(owner_id):
    from .hero_pool import get_pool
    snapshot, digest, sources = build_snapshot(get_pool(owner_id))
    if not snapshot["observations"]:
        reject(409, "HERMES_NO_EVIDENCE", "Сначала завершите разбор своего реплея.")
    with database() as connection:
        connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (owner_id,))
        if not _sources_available(connection, owner_id, sources):
            reject(409, "HERMES_SOURCE_CHANGED", "История разборов изменилась. Повторите запрос.")
        existing = connection.execute("""SELECT * FROM hermes_exports WHERE owner_id=%s
            AND snapshot_sha256=%s AND created_at>now()-interval '7 days' ORDER BY created_at DESC LIMIT 1""",
            (owner_id, digest)).fetchone()
        if existing:
            return packet_for(existing)
        limits = connection.execute("""SELECT count(*) AS stored,
            count(*) FILTER (WHERE created_at>now()-interval '1 day') AS daily
            FROM hermes_exports WHERE owner_id=%s""", (owner_id,)).fetchone()
        if limits["daily"] >= MAX_EXPORTS_PER_DAY or limits["stored"] >= MAX_STORED_EXPORTS:
            reject(429, "HERMES_EXPORT_QUOTA", "Лимит пакетов обмена достигнут. Удалите старые пакеты или повторите позже.")
        row = connection.execute("""INSERT INTO hermes_exports(id,owner_id,snapshot_sha256,snapshot,source_jobs)
            VALUES (%s,%s,%s,%s,%s) RETURNING *""", (uuid4(), owner_id, digest, Jsonb(snapshot), Jsonb(sources))).fetchone()
    return packet_for(row)


def get_export(owner_id, export_id):
    with database() as connection:
        return packet_for(_owned_export(connection, owner_id, export_id))


def import_review(owner_id, command):
    with database() as connection:
        row = _owned_export(connection, owner_id, UUID(command.export_id))
        try:
            review = validate_review(command.review, row["snapshot"], row["snapshot_sha256"])
        except ValueError:
            reject(400, "HERMES_EVIDENCE_INVALID", "Рекомендации должны ссылаться на события и матчи из этого пакета.")
        digest = hashlib.sha256(canonical_bytes(review)).hexdigest()
        existing = connection.execute("SELECT * FROM hermes_reviews WHERE export_id=%s AND owner_id=%s", (row["id"], owner_id)).fetchone()
        if existing:
            if existing["review_sha256"] != digest:
                reject(409, "HERMES_REVIEW_EXISTS", "Для этого пакета уже сохранён другой ответ.")
            return {"review": public_review(existing)}
        saved = connection.execute("""INSERT INTO hermes_reviews(id,export_id,owner_id,review_sha256,review)
            VALUES (%s,%s,%s,%s,%s) RETURNING *""", (uuid4(), row["id"], owner_id, digest, Jsonb(review))).fetchone()
    return {"review": public_review(saved)}


def public_review(row):
    return {"id": str(row["id"]), "created_at": row["created_at"], "source": "external_import",
            "runtime_verified": False, "interpretation_verified": False, "review": row["review"]}


def bridge_status(owner_id):
    from .hermes_tasks import get_runtime_status, latest_valid_review
    with database() as connection:
        rows = connection.execute("""SELECT r.*,e.source_jobs FROM hermes_reviews r JOIN hermes_exports e ON e.id=r.export_id
            WHERE r.owner_id=%s ORDER BY r.created_at DESC LIMIT 50""", (owner_id,)).fetchall()
        active = [row for row in rows if _sources_available(connection, owner_id, row["source_jobs"], lock=False)]
        exports = connection.execute("SELECT id,created_at FROM hermes_exports WHERE owner_id=%s ORDER BY created_at DESC LIMIT 50", (owner_id,)).fetchall()
    runtime = get_runtime_status(owner_id)
    latest = latest_valid_review(owner_id)
    return {"stage": "runtime" if runtime["runtime_connected"] else "offline_bridge", **runtime,
        "review_count": len(active) + int(latest is not None),
        "last_review": ({key: latest[key] for key in ("id", "created_at", "source", "runtime_verified", "interpretation_verified", "runtime_revision", "review")}
                        if latest else public_review(active[0]) if active else None),
        "exports": [{"id": str(row["id"]), "created_at": row["created_at"]} for row in exports]}


async def review_body(request):
    if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
        reject(415, "HERMES_JSON", "Нужен JSON-файл с рекомендациями.")
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_REVIEW_BYTES:
            reject(413, "HERMES_REVIEW_SIZE", "Ответ слишком большой.")
        data.extend(chunk)
    try:
        return ImportReview.model_validate_json(data)
    except (ValueError, ValidationError):
        reject(400, "HERMES_REVIEW_FORMAT", "Ответ не соответствует формату обмена Hermes.")


def attach_hermes(app):
    router = APIRouter(prefix="/api/hermes")

    @router.get("")
    def status(account=Depends(account_required)):
        return bridge_status(account["owner_id"])

    @router.post("/exports", dependencies=[Depends(csrf)], status_code=201)
    def export(account=Depends(account_required)):
        return create_export(account["owner_id"])

    @router.get("/exports/{export_id}")
    def detail(export_id: UUID, account=Depends(account_required)):
        return get_export(account["owner_id"], export_id)

    @router.delete("/exports/{export_id}", dependencies=[Depends(csrf)])
    def remove(export_id: UUID, account=Depends(account_required)):
        with database() as connection:
            connection.execute("DELETE FROM hermes_exports WHERE id=%s AND owner_id=%s", (export_id, account["owner_id"]))
        return {"deleted": True}

    @router.post("/reviews", dependencies=[Depends(csrf)], status_code=201)
    async def review(request: Request, account=Depends(account_required)):
        command = await review_body(request)
        return await run_in_threadpool(import_review, account["owner_id"], command)

    app.include_router(router)
