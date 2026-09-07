"""Private longitudinal replay facts and measurable personal practice goals.

Nothing in this module infers a role from a hero, invents a match date or calls a
provider. A win rate includes only verified outcomes. Trends compare one hero
and a manually declared role and keep the source of chronology visible.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import math
import re
from statistics import mean
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request
from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.concurrency import run_in_threadpool

from .db import database
from .replay_report import display_unit
from .web import account_required, csrf, reject
# The first deployed coach-context contract remains supported independently.
from .hero_pool_legacy import build_pool

SCHEMA = "narma.hero-pool.v1"
HERO = r"^npc_dota_hero_[a-z0-9_]{1,80}$"
MIN_GROUP = 3
UTC = timezone.utc
TREND_METRICS = {
    "last_hits_10": ("Добивания к 10-й минуте", "доб.", "higher"),
    "net_worth_10": ("Стоимость героя к 10-й минуте", "зол.", "higher"),
    "deaths_per_30": ("Смертей на 30 минут", "смертей", "lower"),
    "repeated_deaths": ("Повторные смерти за 3 минуты", "эпизодов", "lower"),
    "item_delay_seconds": ("От активного слота до первого применения", "с", "lower"),
}
PATTERNS = {
    "repeat-death": {
        "title": "Повторный вход после смерти", "metric": "repeated_deaths", "threshold": 0,
        "action": "После возрождения перед возвращением проверь союзников, доступные способности и цель входа. После игры пересмотри смерти с промежутком до трёх минут.",
        "note": "Близкие смерти — повод проверить решения, а не доказательство ошибки.",
    },
    "item-delay": {
        "title": "Первое применение активного предмета", "metric": "item_delay_seconds", "threshold": 120,
        "action": "Перед покупкой выбери задачу предмета. После доставки проверь активный слот и после игры разберись, что определило время первого применения.",
        "note": "120 секунд — личная проверочная отметка, не норма силы игры. Отсутствие применения не доказывает отсутствие пользы.",
    },
}


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def timestamp(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime) or value.tzinfo is None:
        return None
    return value.astimezone(UTC)


def iso(value):
    return value.isoformat() if value else None


def valid_report(row):
    report = row.get("result_payload")
    if not isinstance(report, dict):
        return None
    player, coverage = report.get("player"), report.get("coverage")
    if (report.get("schema_version") != "narma.replay-report.v1"
            or not isinstance(player, dict) or not isinstance(coverage, dict)
            or coverage.get("complete") is not True
            or type(player.get("account_id")) is not int
            or player["account_id"] != row["account_id"]
            or str(report.get("match_id")) != row["match_id"]
            or coverage.get("source_sha256") != row["source_sha256"]
            or not isinstance(player.get("hero"), str) or not re.fullmatch(HERO, player["hero"])
            or player.get("team") not in ("radiant", "dire")):
        return None
    return report


def match_facts(row, metadata):
    report = valid_report(row)
    if not report:
        return None
    raw = report.get("metrics") or {}
    metrics = {key: raw[key] for key in (
        "duration_seconds", "kills", "deaths", "assists", "last_hits", "net_worth",
        "total_earned_gold", "xp", "confirmed_dead_seconds") if finite(raw.get(key)) and raw[key] >= 0}
    duration = metrics.get("duration_seconds", 0)
    if duration > 0:
        for source, target, scale in (("total_earned_gold", "gpm", 60), ("xp", "xpm", 60), ("deaths", "deaths_per_30", 1800)):
            if source in metrics:
                metrics[target] = round(metrics[source] * scale / duration, 2)
    economy = [r for r in report.get("economy", []) if isinstance(r, dict) and finite(r.get("time")) and 565 <= r["time"] <= 600]
    if duration >= 600 and economy:
        checkpoint = max(economy, key=lambda r: r["time"])
        for key in ("last_hits", "net_worth"):
            if finite(checkpoint.get(key)) and checkpoint[key] >= 0:
                metrics[key + "_10"] = checkpoint[key]
    evidence = [{"id": e["id"], "type": e["type"], "time": e["time"]}
                for e in report.get("evidence", []) if isinstance(e, dict)
                and isinstance(e.get("id"), str) and e.get("type") == "death" and finite(e.get("time"))]
    deaths = sorted(evidence, key=lambda e: e["time"])
    # Coverage is observable: incomplete death evidence is unknown, never zero.
    if "deaths" in metrics and len(deaths) == metrics["deaths"]:
        metrics["repeated_deaths"] = sum(0 < b["time"] - a["time"] <= 180 for a, b in zip(deaths, deaths[1:]))
    items = []
    for item in (report.get("insights") or {}).get("items", []):
        if not isinstance(item, dict) or not isinstance(item.get("item"), str):
            continue
        realization = item.get("realization") or {}
        compact = {key: item.get(key) for key in ("item", "label", "time", "event_id", "acquisition")}
        compact["realization"] = {key: realization.get(key) for key in (
            "status", "delay_from_active_seconds", "delay_seconds", "first_use_time", "first_use_event_id", "evidence_ids")}
        items.append(compact)
        if isinstance(realization.get("first_use_event_id"), str) and finite(realization.get("first_use_time")):
            evidence.append({"id": realization["first_use_event_id"], "type": "item_use", "time": realization["first_use_time"]})
        if isinstance(item.get("event_id"), str) and finite(item.get("time")):
            evidence.append({"id": item["event_id"], "type": "item_acquisition", "time": item["time"]})
    delays = [i["realization"]["delay_from_active_seconds"] for i in items
              if finite(i["realization"].get("delay_from_active_seconds")) and i["realization"]["delay_from_active_seconds"] >= 0]
    if delays:
        metrics["item_delay_seconds"] = round(mean(delays), 2)
    # Reserve replay dates for the explicitly sourced future parser contract.
    replay_date = timestamp(report.get("played_at")) if report.get("played_at_source") == "replay" else None
    now = datetime.now(UTC)
    if replay_date and not datetime(2010, 1, 1, tzinfo=UTC) <= replay_date <= now + timedelta(days=1):
        replay_date = None
    played_at = replay_date or metadata.get("played_at")
    source = "replay" if replay_date else "user" if played_at else "analysis"
    analyzed = metadata["first_analyzed_at"]
    return {"job_id": str(row["id"]), "match_id": row["match_id"], "source_sha256": row["source_sha256"],
            "report_sha256": row.get("report_sha256"), "report_state": row.get("state", "ready"),
            "report_is_previous": row.get("report_is_previous", False),
            "pool_metadata": {"position": metadata.get("position"), "played_at": iso(metadata.get("played_at"))},
            "focus": metadata.get("focus"), "reflection": metadata.get("reflection"), "note": metadata.get("note") or "",
            "engine_build": report["coverage"].get("engine_build"),
            "hero": report["player"]["hero"], "label": display_unit(report["player"]["hero"]),
            "position": metadata.get("position"), "outcome": report.get("outcome") if report.get("outcome") in ("win", "loss") else None,
            "played_at": iso(played_at), "date_source": source, "chronology_at": iso(played_at or analyzed),
            "analyzed_at": iso(analyzed), "metrics": metrics, "items": items, "evidence": evidence}


def summary(matches):
    wins = sum(r["outcome"] == "win" for r in matches)
    losses = sum(r["outcome"] == "loss" for r in matches)
    known = wins + losses
    return {"matches": len(matches), "wins": wins, "losses": losses, "known_outcomes": known,
            "unknown_outcomes": len(matches) - known, "winrate_pct": round(100 * wins / known, 1) if known else None,
            "unknown_positions": sum(r["position"] is None for r in matches),
            "dated_matches": sum(r["date_source"] != "analysis" for r in matches),
            "analysis_dated_matches": sum(r["date_source"] == "analysis" for r in matches)}


def trends_for(matches):
    groups = defaultdict(list)
    for row in matches:
        if row["position"] is not None:
            groups[(row["hero"], row["position"])].append(row)
    result = []
    for (hero, position), rows in sorted(groups.items()):
        sources = {r["date_source"] for r in rows}
        builds = {str(r["engine_build"]) if r.get("engine_build") is not None else None for r in rows}
        for metric, (label, unit, desired) in TREND_METRICS.items():
            available = sorted([r for r in rows if finite(r["metrics"].get(metric))], key=lambda r: (r["chronology_at"], r["match_id"]))
            n = min(10, len(available) // 2)
            status = "mixed_chronology" if len(sources) > 1 else "ready" if n >= MIN_GROUP else "insufficient"
            if len(builds) > 1:
                status = "mixed_builds"
            early, recent = (available[:n], available[-n:]) if n else ([], [])
            # Identical recorded dates cannot establish temporal direction.
            if status == "ready" and early[-1]["chronology_at"] >= recent[0]["chronology_at"]:
                status = "ambiguous_chronology"
            a = round(mean(r["metrics"][metric] for r in early), 2) if status == "ready" else None
            b = round(mean(r["metrics"][metric] for r in recent), 2) if status == "ready" else None
            result.append({"hero": hero, "hero_label": display_unit(hero), "position": position,
                "metric": metric, "label": label, "unit": unit, "status": status,
                "chronology_basis": next(iter(sources)) if len(sources) == 1 else "mixed",
                "engine_build": next(iter(builds)) if len(builds) == 1 else None,
                "build_note": "Версия игры не подтверждена." if builds == {None} else "Версии игры различаются или часть версий неизвестна." if len(builds) > 1 else "",
                "early_n": len(early), "recent_n": len(recent), "early_mean": a, "recent_mean": b,
                "delta": round(b - a, 2) if a is not None else None,
                "direction": "up" if a is not None and b > a else "down" if a is not None and b < a else "flat" if a is not None else None,
                "desired_direction": desired,
                "early_match_ids": [r["match_id"] for r in early], "recent_match_ids": [r["match_id"] for r in recent]})
    return result


def patterns_for(matches):
    groups = defaultdict(list)
    for row in matches:
        if row["position"] is not None:
            groups[(row["hero"], row["position"])].append(row)
    result = []
    for (hero, position), rows in sorted(groups.items()):
        rows = sorted(rows, key=lambda r: (r["chronology_at"], r["match_id"]), reverse=True)[:20]
        builds = {str(r["engine_build"]) if r.get("engine_build") is not None else None for r in rows}
        if len(builds) > 1:
            continue
        for ident, definition in PATTERNS.items():
            eligible = [r for r in rows if finite(r["metrics"].get(definition["metric"]))]
            occurrences = [r for r in eligible if r["metrics"][definition["metric"]] > definition["threshold"]]
            if len(eligible) < 3 or len(occurrences) < 2:
                continue
            result.append({"id": ident, "hero": hero, "label": display_unit(hero), "position": position,
                "title": definition["title"], "metric": definition["metric"], "occurrences": len(occurrences),
                "eligible_matches": len(eligible), "observation": f"Наблюдается в {len(occurrences)} из {len(eligible)} доступных матчей. {definition['note']}",
                "action": definition["action"], "evidence": [{"job_id": r["job_id"], "match_id": r["match_id"],
                    "value": r["metrics"][definition["metric"]], "evidence_ids": [e["id"] for e in r["evidence"]
                        if e["type"] == ("death" if ident == "repeat-death" else "item_use")][:12]} for r in occurrences[:12]]})
    return result


def _load_history(connection, owner_id):
    profile = connection.execute("SELECT account_id,nickname FROM portal_dota_profiles WHERE owner_id=%s", (owner_id,)).fetchone()
    if profile is None:
        return None, []
    # Project only fields used here; leave the full reports in their existing API.
    rows = connection.execute("""WITH reports AS (
        SELECT r.id,r.account_id,r.match_id,r.source_sha256,r.state,
            CASE WHEN r.state='ready' THEN r.result_payload ELSE archived.report END AS result_payload,
            CASE WHEN r.state='ready' THEN r.updated_at ELSE archived.created_at END AS updated_at,
            r.state<>'ready' AS report_is_previous
        FROM replay_jobs r LEFT JOIN LATERAL (
            SELECT h.report,h.created_at FROM replay_report_history h WHERE r.state<>'ready'
                AND h.job_id=r.id AND h.source_sha256=r.source_sha256 AND h.match_id=r.match_id
                AND h.account_id=r.account_id AND h.report->>'schema_version'='narma.replay-report.v1'
                AND h.report#>>'{coverage,complete}'='true'
            ORDER BY h.id DESC LIMIT 1
        ) archived ON true
        WHERE r.owner_id=%s AND r.account_id=%s AND r.state<>'deleted'
    ) SELECT id,account_id,match_id,source_sha256,updated_at,state,report_is_previous,
        encode(sha256(convert_to(result_payload::text,'UTF8')), 'hex') AS report_sha256,
        jsonb_build_object('schema_version',result_payload->'schema_version','player',result_payload->'player',
          'match_id',result_payload->'match_id','coverage',result_payload->'coverage',
          'outcome',result_payload->'outcome','played_at',result_payload->'played_at','played_at_source',result_payload->'played_at_source',
          'metrics',result_payload->'metrics','economy',coalesce(result_payload->'economy','[]'::jsonb),
          'evidence',jsonb_path_query_array(result_payload,'$.evidence[*] ? (@.type == "death")'),
          'insights',jsonb_build_object('items',coalesce(result_payload#>'{insights,items}','[]'::jsonb))) AS result_payload
        FROM reports WHERE result_payload IS NOT NULL
        ORDER BY updated_at DESC,id DESC""", (owner_id, profile["account_id"])).fetchall()
    canonical, first_dates = {}, {}
    for row in rows:
        if valid_report(row):
            canonical.setdefault(row["match_id"], row)
            first_dates[row["match_id"]] = min(first_dates.get(row["match_id"], row["updated_at"]), row["updated_at"])
    # Stable lock order across simultaneous reads and metadata mutations.
    for match_id, when in sorted(first_dates.items()):
        connection.execute("""INSERT INTO hero_pool_matches(owner_id,account_id,match_id,first_analyzed_at)
            VALUES (%s,%s,%s,%s) ON CONFLICT(owner_id,account_id,match_id) DO UPDATE
            SET first_analyzed_at=excluded.first_analyzed_at
            WHERE excluded.first_analyzed_at<hero_pool_matches.first_analyzed_at""",
            (owner_id, profile["account_id"], match_id, when))
    metadata = {r["match_id"]: r for r in connection.execute("""SELECT m.*,n.focus,n.reflection,n.note
        FROM hero_pool_matches m LEFT JOIN hero_pool_match_notes n ON n.owner_id=m.owner_id
            AND n.account_id=m.account_id AND n.match_id=m.match_id
        WHERE m.owner_id=%s AND m.account_id=%s""", (owner_id, profile["account_id"])).fetchall()}
    history = [match_facts(row, metadata[match_id]) for match_id, row in canonical.items()]
    return profile, sorted(history, key=lambda r: (r["chronology_at"], r["match_id"]), reverse=True)


def _goals(connection, owner_id, account_id, history):
    goals = connection.execute("SELECT * FROM hero_pool_goals WHERE owner_id=%s AND account_id=%s ORDER BY created_at DESC", (owner_id, account_id)).fetchall()
    by_match = {r["match_id"]: r for r in history}
    result = []
    for goal in goals:
        for row in history:
            if (goal["status"] != "active" or row["hero"] != goal["hero"] or row["position"] != goal["position"]
                    or row["match_id"] in goal["baseline_match_ids"] or timestamp(row["analyzed_at"]) <= goal["created_at"]):
                continue
            value = row["metrics"].get(goal["metric"])
            # Uploading an undated historical match cannot satisfy a new goal.
            status = "unknown" if not finite(value) or row["date_source"] == "analysis" else "reached" if value <= goal["threshold"] else "review"
            if row["played_at"] and timestamp(row["played_at"]) <= goal["created_at"]:
                status = "predates_goal"
            connection.execute("""INSERT INTO hero_pool_goal_checks(goal_id,match_id,value,status,chronology_basis)
                VALUES (%s,%s,%s,%s,%s) ON CONFLICT(goal_id,match_id) DO UPDATE
                SET value=excluded.value,status=excluded.status,chronology_basis=excluded.chronology_basis,checked_at=now()""",
                (goal["id"], row["match_id"], value if finite(value) else None, status, row["date_source"]))
        checks = connection.execute("SELECT match_id,value,status,chronology_basis FROM hero_pool_goal_checks WHERE goal_id=%s ORDER BY checked_at DESC,match_id DESC", (goal["id"],)).fetchall()
        # Deleted reports and changed role assignments do not remain visible through a goal.
        checks = [{**check, "job_id": by_match[check["match_id"]]["job_id"]} for check in checks
                  if check["match_id"] in by_match and by_match[check["match_id"]]["hero"] == goal["hero"]
                  and by_match[check["match_id"]]["position"] == goal["position"]]
        result.append({key: goal[key] for key in ("id", "status", "title", "action", "created_at", "hero", "position", "pattern_id", "metric", "threshold")} | {"checks": checks})
    return result


def get_pool(owner_id, window="all", hero=None, position=None, favorites_only=False):
    if window not in ("30", "90", "all") or (hero is not None and not re.fullmatch(HERO, hero)) or position not in (None, "unknown", "1", "2", "3", "4", "5"):
        reject(400, "POOL_FILTER", "Проверьте фильтры пула героев.")
    with database() as connection:
        profile, all_history = _load_history(connection, owner_id)
        favorites = connection.execute("SELECT hero,position FROM hero_pool_favorites WHERE owner_id=%s AND account_id=%s ORDER BY hero,position", (owner_id, profile["account_id"])).fetchall() if profile else []
        goals = _goals(connection, owner_id, profile["account_id"], all_history) if profile else []
    favorite_keys = {(r["hero"], r["position"]) for r in favorites}
    since = datetime.now(UTC) - timedelta(days=int(window)) if window != "all" else None
    selected = [r for r in all_history if (not hero or r["hero"] == hero)
                and (position is None or r["position"] == (None if position == "unknown" else int(position)))
                and (not since or timestamp(r["chronology_at"]) >= since)
                and (not favorites_only or (r["hero"], r["position"]) in favorite_keys)]
    groups = defaultdict(list)
    for row in selected:
        groups[(row["hero"], row["position"])].append(row)
    heroes = [{"hero": key[0], "label": display_unit(key[0]), "position": key[1],
               "favorite": key in favorite_keys, **summary(rows)} for key, rows in groups.items()]
    heroes.sort(key=lambda r: (-r["matches"], r["hero"], r["position"] or 0))
    return {"schema_version": SCHEMA, "profile": profile,
        "filters": {"window": window, "hero": hero, "position": position, "favorites_only": favorites_only},
        "summary": summary(selected), "heroes": heroes,
        "available_heroes": [{"hero": h, "label": display_unit(h)} for h in sorted({r["hero"] for r in all_history})],
        "favorites": [{**r, "label": display_unit(r["hero"])} for r in favorites], "history": selected,
        "practice": {"tracked": sum(bool(r["focus"]) for r in selected),
            **{key: sum(bool(r["focus"]) and r["reflection"] == key for r in selected) for key in ("done", "partial", "not_done")},
            "unreviewed": sum(bool(r["focus"]) and r["reflection"] is None for r in selected)},
        "trends": trends_for(selected), "patterns": patterns_for(selected),
        "goals": [g for g in goals if (not hero or g["hero"] == hero)
                  and (position is None or str(g["position"]) == position)
                  and (not favorites_only or (g["hero"], g["position"]) in favorite_keys)],
        "limitations": [
            "Учтены завершённые разборы закреплённого игрока; во время обновления доступен предыдущий полный отчёт. Повторные загрузки одного матча считаются один раз.",
            "Винрейт считается по матчам с известным результатом. Позицию указывает игрок; герой не определяет позицию.",
            "Если дата игры не записана, период и порядок используют дату сохранённого анализа. Дату игры можно указать вручную.",
            "Динамика сравнивает одного героя и позицию: минимум 3 ранних и 3 последних матча, максимум по 10. Разные источники дат не смешиваются.",
            "Изменение показателя не измеряет понимание игры: патч, соперники, длительность и контекст могут влиять на результат.",
            "Известные разные сборки игры и известная сборка вместе с неизвестной не сравниваются. Отметки выполнения задач — самооценка игрока.",
            "Матч без даты игры не засчитывается как выполнение новой цели: неизвестно, состоялся ли он после её постановки.",
        ]}


class MatchUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    position: int | None = Field(default=None, ge=1, le=5, strict=True)
    played_at: datetime | None = None
    focus: Literal["item_plan", "farm_checkpoint", "safe_return"] | None = None
    reflection: Literal["done", "partial", "not_done"] | None = None
    note: str = Field(default="", max_length=500, strict=True)

    @field_validator("note")
    @classmethod
    def plain_note(cls, value):
        if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", value):
            raise ValueError("Заметка содержит недопустимые символы.")
        return value.strip()

    @field_validator("played_at")
    @classmethod
    def real_date(cls, value):
        if value is not None and (value.tzinfo is None or not datetime(2010, 1, 1, tzinfo=UTC) <= value <= datetime.now(UTC) + timedelta(days=1)):
            raise ValueError("Укажите дату игры с часовым поясом.")
        return value


class Favorite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hero: str = Field(pattern=HERO)
    position: int = Field(ge=1, le=5, strict=True)


class GoalCreate(Favorite):
    pattern_id: str = Field(pattern=r"^(repeat-death|item-delay)$")


class GoalUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = Field(pattern=r"^(active|paused|completed)$")


async def body_for(request, model):
    from pydantic import ValidationError
    if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
        reject(415, "POOL_JSON", "Нужен JSON-запрос.")
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > 8192:
            reject(413, "POOL_BODY", "Слишком большой запрос.")
        raw.extend(chunk)
    try:
        return model.model_validate_json(raw)
    except (ValidationError, ValueError):
        reject(400, "POOL_FIELDS", "Проверьте героя, позицию и дату игры.")


def update_match(owner_id, job_id, body):
    with database() as connection:
        # Same lock as the deployed numeric Match ID form: position sync touches
        # both tables, so serialize cross-version edits before either row lock.
        connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (owner_id,))
        profile, history = _load_history(connection, owner_id)
        # Authorize the exact supplied upload too; never accept a foreign job
        # merely because its public match ID is present in this owner's history.
        row = connection.execute("SELECT * FROM replay_jobs WHERE id=%s AND owner_id=%s AND state<>'deleted' FOR UPDATE", (job_id, owner_id)).fetchone()
        if (not row or not profile or row["account_id"] != profile["account_id"]
                or not any(r["match_id"] == row["match_id"] for r in history)):
            reject(404, "POOL_MATCH_NOT_FOUND", "Готовый разбор этого игрока не найден.")
        fields, args = [], []
        for key in ("position", "played_at"):
            if key in body.model_fields_set:
                fields.append(key + "=%s")
                args.append(getattr(body, key))
        if not body.model_fields_set:
            reject(400, "POOL_FIELDS", "Укажите позицию, дату матча или заметку.")
        if fields:
            connection.execute("UPDATE hero_pool_matches SET " + ",".join(fields) + ",updated_at=now() WHERE owner_id=%s AND account_id=%s AND match_id=%s",
                               (*args, owner_id, profile["account_id"], row["match_id"]))
        note_fields = body.model_fields_set & {"focus", "reflection", "note"}
        if note_fields:
            previous = connection.execute("SELECT * FROM hero_pool_match_notes WHERE owner_id=%s AND account_id=%s AND match_id=%s FOR UPDATE",
                (owner_id, profile["account_id"], row["match_id"])).fetchone() or {"focus": None, "reflection": None, "note": ""}
            values = {key: getattr(body, key) if key in note_fields else previous[key] for key in ("focus", "reflection", "note")}
            if values["reflection"] is not None and values["focus"] is None:
                reject(400, "POOL_FIELDS", "Сначала выберите задачу для этого матча.")
            position = connection.execute("SELECT position FROM hero_pool_matches WHERE owner_id=%s AND account_id=%s AND match_id=%s", (owner_id, profile["account_id"], row["match_id"])).fetchone()["position"]
            connection.execute("""INSERT INTO hero_pool_match_notes(owner_id,account_id,match_id,position,focus,reflection,note)
                VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(owner_id,account_id,match_id) DO UPDATE
                SET focus=excluded.focus,reflection=excluded.reflection,note=excluded.note,updated_at=now()""",
                (owner_id, profile["account_id"], row["match_id"], position, values["focus"], values["reflection"], values["note"]))
    return {"saved": True}


def save_favorite(owner_id, body):
    with database() as connection:
        profile, history = _load_history(connection, owner_id)
        if not profile or not any(r["hero"] == body.hero for r in history):
            reject(404, "POOL_HERO_NOT_FOUND", "Сначала добавьте разбор своей игры на этом герое.")
        connection.execute("INSERT INTO hero_pool_favorites(owner_id,account_id,hero,position) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                           (owner_id, profile["account_id"], body.hero, body.position))
    return {"saved": True}


def create_goal(owner_id, body):
    snapshot = get_pool(owner_id)
    pattern = next((p for p in snapshot["patterns"] if (p["id"], p["hero"], p["position"]) == (body.pattern_id, body.hero, body.position)), None)
    if not pattern:
        reject(409, "POOL_PATTERN_UNAVAILABLE", "Для этой цели пока недостаточно подтверждённых наблюдений.")
    definition = PATTERNS[body.pattern_id]
    with database() as connection:
        # Serialize a user's practice changes; duplicate clicks are idempotent.
        connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,1))", (owner_id,))
        existing = connection.execute("SELECT id FROM hero_pool_goals WHERE owner_id=%s AND account_id=%s AND hero=%s AND position=%s AND pattern_id=%s AND status='active'",
            (owner_id, snapshot["profile"]["account_id"], body.hero, body.position, body.pattern_id)).fetchone()
        if existing:
            return {"saved": True, "goal": existing}
        row = connection.execute("""INSERT INTO hero_pool_goals(id,owner_id,account_id,hero,position,pattern_id,title,action,metric,threshold,baseline_match_ids)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id,status,title""",
            (uuid4(), owner_id, snapshot["profile"]["account_id"], body.hero, body.position, body.pattern_id,
             definition["title"], definition["action"], definition["metric"], definition["threshold"],
             Jsonb([r["match_id"] for r in snapshot["history"]]))).fetchone()
    return {"saved": True, "goal": row}


def attach_hero_pool(app):
    router = APIRouter(prefix="/api/hero-pool")

    @router.get("")
    def get(window: str = "all", hero: str | None = None, position: str | None = None,
            favorites_only: bool = False, account=Depends(account_required)):
        return get_pool(account["owner_id"], window=window, hero=hero, position=position, favorites_only=favorites_only)

    @router.put("/matches/{job_id:uuid}", dependencies=[Depends(csrf)])
    @router.patch("/matches/{job_id:uuid}", dependencies=[Depends(csrf)])
    async def match(job_id: UUID, request: Request, account=Depends(account_required)):
        body = await body_for(request, MatchUpdate)
        return await run_in_threadpool(update_match, account["owner_id"], job_id, body)

    @router.put("/favorites", dependencies=[Depends(csrf)])
    async def favorite(request: Request, account=Depends(account_required)):
        body = await body_for(request, Favorite)
        return await run_in_threadpool(save_favorite, account["owner_id"], body)

    @router.delete("/favorites/{hero}/{position}", dependencies=[Depends(csrf)])
    def delete_favorite(hero: str, position: int, account=Depends(account_required)):
        if not re.fullmatch(HERO, hero) or position not in range(1, 6):
            reject(400, "POOL_FIELDS", "Проверьте героя и позицию.")
        with database() as connection:
            connection.execute("DELETE FROM hero_pool_favorites f USING portal_dota_profiles p WHERE f.owner_id=%s AND p.owner_id=f.owner_id AND p.account_id=f.account_id AND f.hero=%s AND f.position=%s",
                               (account["owner_id"], hero, position))
        return {"deleted": True}

    @router.post("/goals", dependencies=[Depends(csrf)], status_code=201)
    async def goal(request: Request, account=Depends(account_required)):
        body = await body_for(request, GoalCreate)
        return await run_in_threadpool(create_goal, account["owner_id"], body)

    @router.patch("/goals/{goal_id}", dependencies=[Depends(csrf)])
    async def goal_status(goal_id: UUID, request: Request, account=Depends(account_required)):
        body = await body_for(request, GoalUpdate)
        def save():
            try:
                with database() as connection:
                    row = connection.execute("""UPDATE hero_pool_goals g SET status=%s,updated_at=now()
                        FROM portal_dota_profiles p WHERE g.id=%s AND g.owner_id=%s
                        AND p.owner_id=g.owner_id AND p.account_id=g.account_id RETURNING g.id,g.status""",
                        (body.status, goal_id, account["owner_id"])).fetchone()
                    if not row:
                        reject(404, "POOL_GOAL_NOT_FOUND", "Цель не найдена.")
            except UniqueViolation:
                reject(409, "POOL_GOAL_ACTIVE", "Такая цель уже активна.")
            return {"saved": True, "goal": row}
        return await run_in_threadpool(save)

    app.include_router(router)
