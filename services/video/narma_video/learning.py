"""Owned practice plans and explicit player reflections, without inference.

The current canonical replay and manual role are revalidated on every read.
Self reports never become evidence of correct play, detected opportunities or
mastery. Duplicate uploads and old/undated games cannot inflate practice counts.
"""
from __future__ import annotations

import re
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from starlette.concurrency import run_in_threadpool

from . import curriculum
from .db import database
from .hero_pool import HERO, _load_history, timestamp, valid_report
from .role_context import get_role_context
from .web import account_required, csrf, reject

SCHEMA = "narma.learning.v1"
ASSESSMENTS = ("applied", "partial", "not_applied", "no_opportunity", "uncertain")


class PlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: UUID
    exercise_id: str = Field(min_length=1, max_length=60, pattern=r"^[a-z0-9_-]+$")


class PlanUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["active", "paused", "completed"]


class CheckUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: UUID
    evidence_id: str | None = Field(default=None, min_length=1, max_length=160)
    answer: str = Field(min_length=1, max_length=1500)
    self_assessment: Literal["applied", "partial", "not_applied", "no_opportunity", "uncertain"]

    @field_validator("answer")
    @classmethod
    def clean_answer(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("An answer is required")
        return value


async def _body(request, model):
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        reject(415, "LEARNING_JSON", "Нужен JSON-запрос.")
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > 16384:
            reject(413, "LEARNING_BODY", "Слишком большой запрос.")
        raw.extend(chunk)
    try:
        return model.model_validate_json(raw)
    except (ValidationError, ValueError):
        reject(400, "LEARNING_FIELDS", "Проверь упражнение, ответ и выбранный эпизод.")


def _context(connection, owner_id, *, write=False):
    # Use the role editor's lock, so creating a scope and changing the manual
    # position cannot race. Canonical history is still shared with hero pool.
    if write:
        connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (owner_id,))
    else:
        # The factual projection and full evidence must describe one database
        # snapshot even if a replay worker publishes a refreshed report midway.
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
    return _load_history(connection, owner_id, persist=write)


def _full_report(connection, owner_id, account_id, job_id, *, lock=False, expected_report_sha256=None):
    row = connection.execute("""SELECT r.id,r.match_id,r.account_id,r.source_sha256,
        CASE WHEN r.state='ready' THEN r.result_payload ELSE archived.report END AS result_payload,
        encode(sha256(convert_to((CASE WHEN r.state='ready' THEN r.result_payload
            ELSE archived.report END)::text,'UTF8')),'hex') AS report_sha256
        FROM replay_jobs r LEFT JOIN LATERAL (
            SELECT h.report FROM replay_report_history h WHERE r.state<>'ready'
              AND h.job_id=r.id AND h.source_sha256=r.source_sha256 AND h.match_id=r.match_id
              AND h.account_id=r.account_id AND h.report->>'schema_version'='narma.replay-report.v1'
              AND h.report#>>'{coverage,complete}'='true' ORDER BY h.id DESC LIMIT 1
        ) archived ON true WHERE r.id=%s AND r.owner_id=%s AND r.account_id=%s
            AND r.state<>'deleted'""" + (" FOR SHARE OF r" if lock else ""), (job_id, owner_id, account_id)).fetchone()
    if row and expected_report_sha256 is not None and row["report_sha256"] != expected_report_sha256:
        return None
    return valid_report(row) if row else None


def _owned_match(connection, owner_id, profile, history, job_id, *, lock=False):
    # Authorize the actual supplied upload; a known public match ID is no grant.
    supplied = connection.execute("""SELECT id,account_id,match_id FROM replay_jobs
        WHERE id=%s AND owner_id=%s AND state<>'deleted'""" + (" FOR SHARE" if lock else ""), (job_id, owner_id)).fetchone()
    if not profile or not supplied or supplied["account_id"] != profile["account_id"]:
        reject(404, "LEARNING_REPORT_NOT_FOUND", "Готовый разбор этого игрока не найден.")
    fact = next((r for r in history if r["match_id"] == supplied["match_id"]), None)
    report = _full_report(connection, owner_id, profile["account_id"], fact["job_id"], lock=lock,
                          expected_report_sha256=fact["report_sha256"]) if fact else None
    if not report:
        if fact:
            reject(409, "LEARNING_REPORT_CHANGED", "Разбор обновился. Открой его заново перед сохранением проверки.")
        reject(404, "LEARNING_REPORT_NOT_FOUND", "Готовый разбор этого игрока не найден.")
    return fact, report


def _validity(plan, by_match, visible_jobs):
    fact = by_match.get(plan["source_match_id"])
    if not fact or str(plan["source_job_id"]) not in visible_jobs:
        return "source_unavailable"
    if (fact["hero"], fact["position"]) != (plan["hero"], plan["position"]):
        return "scope_changed"
    if (fact["source_sha256"], fact["report_sha256"]) != (plan["source_sha256"], plan["report_sha256"]):
        return "source_changed"
    if plan["curriculum_version"] != curriculum.VERSION or not curriculum.get_exercise(plan["exercise_id"], plan["position"]):
        return "source_changed"
    return "current"


def resolve_active_exercise(connection, owner_id, account_id, hero, position):
    """Resolve the same canonical source as practice UI for model context.

    Caller supplies a read-only repeatable-read transaction shared with the
    worker lease/role validation. No self reports or model history are returned.
    """
    if type(position) is not int or not 1 <= position <= 5:
        return None
    profile, history = _load_history(connection, owner_id, persist=False)
    if not profile or profile["account_id"] != account_id:
        return None
    plan = connection.execute("""SELECT * FROM learning_plans WHERE owner_id=%s AND account_id=%s
        AND hero=%s AND position=%s AND status='active'""", (owner_id, account_id, hero, position)).fetchone()
    if not plan:
        return None
    by_match = {fact["match_id"]: fact for fact in history}
    visible_jobs = {str(row["id"]) for row in connection.execute("""SELECT id FROM replay_jobs
        WHERE owner_id=%s AND account_id=%s AND state<>'deleted'""", (owner_id, account_id)).fetchall()}
    if _validity(plan, by_match, visible_jobs) != "current":
        return None
    fact = by_match[plan["source_match_id"]]
    if not _full_report(connection, owner_id, account_id, fact["job_id"],
                        expected_report_sha256=fact["report_sha256"]):
        return None
    return plan["exercise_id"]


def chronology(plan, fact):
    if fact["match_id"] in plan["baseline_match_ids"]:
        return "baseline"
    played = timestamp(fact.get("played_at"))
    if played is None or fact.get("date_source") not in ("replay", "user"):
        return "date_unknown"
    if played <= plan["created_at"]:
        return "predates_plan"
    # A manually entered future date cannot establish completed practice.
    from datetime import datetime, timezone
    if played > datetime.now(timezone.utc):
        return "date_unknown"
    return "after_plan"


def _plans(connection, owner_id, profile, history):
    if not profile:
        return []
    rows = connection.execute("""SELECT * FROM learning_plans WHERE owner_id=%s AND account_id=%s
        ORDER BY created_at DESC,id DESC""", (owner_id, profile["account_id"])).fetchall()
    if not rows:
        return []
    by_match = {r["match_id"]: r for r in history}
    visible_jobs = {str(r["id"]) for r in connection.execute("""SELECT id FROM replay_jobs
        WHERE owner_id=%s AND account_id=%s AND state<>'deleted'""", (owner_id, profile["account_id"])).fetchall()}
    # Full reports are loaded lazily only for saved evidence bindings.
    report_cache = {}
    result = []
    for plan in rows:
        validity = _validity(plan, by_match, visible_jobs)
        checks, stale = [], 0
        baseline = by_match.get(plan["source_match_id"], {})
        counts = dict.fromkeys(ASSESSMENTS, 0)
        for check in connection.execute("SELECT * FROM learning_checks WHERE plan_id=%s ORDER BY checked_at DESC,match_id DESC", (plan["id"],)).fetchall():
            fact = by_match.get(check["match_id"])
            if not fact or str(check["job_id"]) not in visible_jobs:
                # Deleted replay content and answers are not resurrected here.
                stale += 1
                continue
            check_validity = "current"
            if (fact["hero"], fact["position"]) != (plan["hero"], plan["position"]) or check["position"] != fact["position"]:
                check_validity = "scope_changed"
            elif (fact["source_sha256"], fact["report_sha256"]) != (check["source_sha256"], check["report_sha256"]):
                check_validity = "report_changed"
            elif check["evidence_id"]:
                if fact["job_id"] not in report_cache:
                    report_cache[fact["job_id"]] = _full_report(connection, owner_id, profile["account_id"], fact["job_id"],
                                                              expected_report_sha256=fact["report_sha256"])
                report = report_cache[fact["job_id"]]
                anchors = curriculum.evidence_candidates(report, plan["exercise_id"], plan["position"]) if report else []
                if check["evidence_id"] not in {e["evidence_id"] for e in anchors}:
                    check_validity = "evidence_changed"
            when = chronology(plan, fact)
            baseline_build, match_build = baseline.get("engine_build"), fact.get("engine_build")
            build_status = ("unknown_build" if baseline_build is None or match_build is None else
                            "same_build" if str(baseline_build) == str(match_build) else "different_build")
            chronological = check_validity == "current" and validity == "current" and when == "after_plan"
            training = chronological and build_status != "different_build"
            if training:
                counts[check["self_assessment"]] += 1
            if check_validity != "current":
                stale += 1
            checks.append({key: check[key] for key in ("match_id", "evidence_id", "answer", "self_assessment", "checked_at")} | {
                "job_id": fact["job_id"], "source": "player_self_report",
                "context_source": "replay_anchor" if check["evidence_id"] else "player_context",
                "validity": check_validity, "chronology_status": when, "is_training": training,
                "chronology_eligible": chronological, "build_status": build_status,
                "mode_status": "unknown_mode",
                "date_source": fact["date_source"]})
        result.append({key: plan[key] for key in ("id", "exercise_id", "curriculum_version", "hero", "position", "status", "created_at", "updated_at", "source_job_id", "source_match_id")} | {
            "hero_label": next((f["label"] for f in history if f["hero"] == plan["hero"]), plan["hero"].removeprefix("npc_dota_hero_").replace("_", " ").title()),
            "exercise": curriculum.get_exercise(plan["exercise_id"], plan["position"]),
            "validity": validity, "can_check": validity == "current" and plan["status"] == "active",
            "checks": checks, "stale_checks": stale, "self_report_counts": counts,
            "training_matches": sum(counts.values()),
            "post_plan_self_reports": sum(c["chronology_eligible"] for c in checks),
            "reviewed_matches": sum(c["validity"] == "current" for c in checks),
            "progress_source": "player_self_report", "completion_source": "player" if plan["status"] == "completed" else None,
            "progress_note": "Это твои ответы после просмотра. Они не подтверждают автоматически правильность решения или освоение навыка.",
            "comparison_note": "Режим игры не подтверждён; версия игры может быть неизвестна. Матчи с известными разными версиями не входят в серию практики. Счётчик ответов не является оценкой сопоставимости или освоения навыка."})
    return result


def _scope(hero, position):
    if hero is not None and (not isinstance(hero, str) or not re.fullmatch(HERO, hero)):
        reject(400, "LEARNING_FILTERS", "Проверь выбранного героя.")
    if position not in (None, "unknown", "1", "2", "3", "4", "5", 1, 2, 3, 4, 5) or isinstance(position, bool):
        reject(400, "LEARNING_FILTERS", "Проверь выбранную позицию.")
    return int(position) if position not in (None, "unknown") else None


def get_learning(owner_id, hero=None, position=None):
    numeric_position = _scope(hero, position)
    with database() as connection:
        profile, history = _context(connection, owner_id)
        plans = _plans(connection, owner_id, profile, history)
    def included(row):
        return (hero is None or row["hero"] == hero) and (position is None or row["position"] == numeric_position)
    return {"schema_version": SCHEMA, "profile": profile, "scope": {"hero": hero, "position": numeric_position},
            "role_context": get_role_context(numeric_position),
            "catalog": curriculum.get_catalog(numeric_position),
            "plans": [p for p in plans if included(p)], "history": [h for h in history if included(h)],
            "progress_source": "player_self_report"}


def get_report_learning(owner_id, job_id):
    with database() as connection:
        profile, history = _context(connection, owner_id)
        fact, report = _owned_match(connection, owner_id, profile, history, job_id)
        plans = [p for p in _plans(connection, owner_id, profile, history) if (p["hero"], p["position"]) == (fact["hero"], fact["position"])]
    return {"schema_version": SCHEMA, "job_id": fact["job_id"], "requested_job_id": str(job_id),
            "match_id": fact["match_id"], "hero": fact["hero"], "hero_label": fact["label"],
            "position": fact["position"], "position_required": fact["position"] is None,
            "role_context": get_role_context(fact["position"]),
            "position_source": "user" if fact["position"] is not None else "unknown",
            "catalog": curriculum.get_catalog(fact["position"]), "plans": plans,
            "suggestions": curriculum.suggest_exercises(report, fact["position"]),
            "review_candidates": curriculum.evidence_candidates(report, position=fact["position"]),
            "exercise_candidates": {e["id"]: curriculum.evidence_candidates(report, e["id"], fact["position"])
                                    for e in curriculum.get_catalog(fact["position"])["exercises"]}}


def _plan_row(connection, owner_id, profile, plan_id):
    row = connection.execute("""SELECT * FROM learning_plans WHERE id=%s AND owner_id=%s
        AND account_id=%s FOR UPDATE""", (plan_id, owner_id, profile["account_id"] if profile else -1)).fetchone()
    if not row:
        reject(404, "LEARNING_PLAN_NOT_FOUND", "Задание не найдено.")
    return row


def _saved(connection, owner_id, profile, history, plan_id):
    plan = next(p for p in _plans(connection, owner_id, profile, history) if str(p["id"]) == str(plan_id))
    return {"saved": True, "plan": plan}


def _lock_plan_source(connection, owner_id, profile, plan):
    # Replay workers use row locks rather than the owner's practice lock. Keep
    # the original source stable until the plan/check transaction commits.
    if not _full_report(connection, owner_id, profile["account_id"], plan["source_job_id"],
                        lock=True, expected_report_sha256=plan["report_sha256"]):
        reject(409, "LEARNING_PLAN_STALE", "Источник задания изменился. Открой актуальный разбор и выбери задание заново.")


def create_plan(owner_id, body):
    with database() as connection:
        profile, history = _context(connection, owner_id, write=True)
        fact, _ = _owned_match(connection, owner_id, profile, history, body.job_id, lock=True)
        if fact["position"] is None:
            reject(409, "LEARNING_POSITION_REQUIRED", "Сначала укажи позицию в этом матче.")
        if not curriculum.get_exercise(body.exercise_id, fact["position"]):
            reject(400, "LEARNING_EXERCISE", "Выбери упражнение для своей позиции.")
        existing = connection.execute("""SELECT * FROM learning_plans WHERE owner_id=%s
            AND account_id=%s AND hero=%s AND position=%s AND status='active' FOR UPDATE""",
            (owner_id, profile["account_id"], fact["hero"], fact["position"])).fetchone()
        if existing:
            if existing["exercise_id"] != body.exercise_id:
                reject(409, "LEARNING_FOCUS_ACTIVE", "Сначала заверши или приостанови текущее задание на этом герое и позиции.")
            _lock_plan_source(connection, owner_id, profile, existing)
            saved = _saved(connection, owner_id, profile, history, existing["id"])
            if saved["plan"]["validity"] != "current":
                reject(409, "LEARNING_PLAN_STALE", "Источник текущего задания изменился. Приостанови его и начни заново по актуальному разбору.")
            return saved
        plan_id = uuid4()
        connection.execute("""INSERT INTO learning_plans(id,owner_id,account_id,hero,position,exercise_id,
            curriculum_version,source_job_id,source_match_id,source_sha256,report_sha256,baseline_match_ids)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (plan_id, owner_id, profile["account_id"], fact["hero"], fact["position"], body.exercise_id,
             curriculum.VERSION, fact["job_id"], fact["match_id"], fact["source_sha256"], fact["report_sha256"],
             Jsonb([h["match_id"] for h in history])))
        return _saved(connection, owner_id, profile, history, plan_id)


def update_plan(owner_id, plan_id, body):
    with database() as connection:
        profile, history = _context(connection, owner_id, write=True)
        row = _plan_row(connection, owner_id, profile, plan_id)
        if body.status == "active":
            _lock_plan_source(connection, owner_id, profile, row)
            view = _saved(connection, owner_id, profile, history, plan_id)["plan"]
            if view["validity"] != "current":
                reject(409, "LEARNING_PLAN_STALE", "Источник задания изменился. Выбери задание заново по актуальному разбору.")
            other = connection.execute("""SELECT id FROM learning_plans WHERE owner_id=%s AND account_id=%s
                AND hero=%s AND position=%s AND status='active' AND id<>%s""",
                (owner_id, profile["account_id"], row["hero"], row["position"], plan_id)).fetchone()
            if other:
                reject(409, "LEARNING_FOCUS_ACTIVE", "На этом герое и позиции уже есть активное задание.")
        if row["status"] != body.status:
            connection.execute("UPDATE learning_plans SET status=%s,updated_at=now() WHERE id=%s", (body.status, plan_id))
        return _saved(connection, owner_id, profile, history, plan_id)


def save_check(owner_id, plan_id, body):
    with database() as connection:
        profile, history = _context(connection, owner_id, write=True)
        row = _plan_row(connection, owner_id, profile, plan_id)
        _lock_plan_source(connection, owner_id, profile, row)
        current = _saved(connection, owner_id, profile, history, plan_id)["plan"]
        if not current["can_check"]:
            reject(409, "LEARNING_PLAN_INACTIVE", "Для проверки нужно актуальное активное задание.")
        fact, report = _owned_match(connection, owner_id, profile, history, body.job_id, lock=True)
        if (fact["hero"], fact["position"]) != (row["hero"], row["position"]):
            reject(409, "LEARNING_SCOPE", "Проверка относится к тому же герою и указанной позиции, что и задание.")
        exercise = curriculum.get_exercise(row["exercise_id"], row["position"])
        candidates = curriculum.evidence_candidates(report, row["exercise_id"], row["position"])
        if body.evidence_id and body.evidence_id not in {e["evidence_id"] for e in candidates}:
            reject(400, "LEARNING_EVIDENCE", "Выбери актуальный эпизод этого упражнения из своего разбора.")
        if (body.evidence_id is None and body.self_assessment not in ("uncertain", "no_opportunity")
                and exercise.get("review_mode") != "manual_context"):
            reject(400, "LEARNING_EVIDENCE_REQUIRED", "Для оценки конкретного эпизода выбери отметку из разбора.")
        connection.execute("""INSERT INTO learning_checks(plan_id,match_id,job_id,evidence_id,answer,self_assessment,
            source_sha256,report_sha256,position) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(plan_id,match_id) DO UPDATE SET job_id=excluded.job_id,evidence_id=excluded.evidence_id,
                answer=excluded.answer,self_assessment=excluded.self_assessment,source_sha256=excluded.source_sha256,
                report_sha256=excluded.report_sha256,position=excluded.position,checked_at=now()
            WHERE (learning_checks.job_id,learning_checks.evidence_id,learning_checks.answer,learning_checks.self_assessment,
                learning_checks.source_sha256,learning_checks.report_sha256,learning_checks.position)
                IS DISTINCT FROM (excluded.job_id,excluded.evidence_id,excluded.answer,excluded.self_assessment,
                excluded.source_sha256,excluded.report_sha256,excluded.position)""",
            (plan_id, fact["match_id"], fact["job_id"], body.evidence_id, body.answer, body.self_assessment,
             fact["source_sha256"], fact["report_sha256"], fact["position"]))
        return _saved(connection, owner_id, profile, history, plan_id)


def attach_learning(app):
    router = APIRouter(prefix="/api/learning")

    @router.get("")
    def get(hero: str | None = None, position: str | None = None, account=Depends(account_required)):
        return get_learning(account["owner_id"], hero, position)

    @router.get("/reports/{job_id:uuid}")
    def report(job_id: UUID, account=Depends(account_required)):
        return get_report_learning(account["owner_id"], job_id)

    @router.post("/plans", dependencies=[Depends(csrf)], status_code=201)
    async def create(request: Request, account=Depends(account_required)):
        body = await _body(request, PlanCreate)
        return await run_in_threadpool(create_plan, account["owner_id"], body)

    @router.patch("/plans/{plan_id:uuid}", dependencies=[Depends(csrf)])
    async def update(plan_id: UUID, request: Request, account=Depends(account_required)):
        body = await _body(request, PlanUpdate)
        return await run_in_threadpool(update_plan, account["owner_id"], plan_id, body)

    @router.put("/plans/{plan_id:uuid}/checks", dependencies=[Depends(csrf)])
    async def check(plan_id: UUID, request: Request, account=Depends(account_required)):
        body = await _body(request, CheckUpdate)
        return await run_in_threadpool(save_check, account["owner_id"], plan_id, body)

    app.include_router(router)
