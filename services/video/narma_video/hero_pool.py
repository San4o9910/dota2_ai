"""Private longitudinal observations from verified, selected-player replays.

No model calls, external match lookup, inferred rank/role or skill score. Role
and practice reflections are explicitly supplied by the owner. Unknown facts
stay unknown, and uploading the same match twice never increases its weight.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from statistics import mean

from .db import database
from .replay_report import display_unit
from .web import reject

SCHEMA = "narma.hero-pool.v1"
LIMIT = 1000
FOCUSES = {"item_plan", "farm_checkpoint", "safe_return"}
REFLECTIONS = {"done", "partial", "not_done"}
METRICS = {
    "lh10": ("Добивания к 10-й минуте", "LH"),
    "nw10": ("Стоимость героя к 10-й минуте", "золото"),
    "deaths10": ("Смерти к 10-й минуте", "смертей"),
    "dead_pct": ("Подтверждённое время вне игры", "%"),
    "gpm": ("Средний доход за матч", "GPM"),
}

# Distinct identities are selected BEFORE projecting report fields. The API
# never loads entire 300 KB reports for every match. Even a long history sends
# only one checkpoint, death markers and compact item-use records per match.
POOL_SQL = """
WITH latest AS (
    SELECT DISTINCT ON (r.account_id, r.match_id)
        r.id, r.owner_id, r.account_id, r.match_id, r.created_at, r.updated_at,
        r.result_payload
    FROM replay_jobs r
    JOIN portal_dota_profiles p ON p.owner_id=r.owner_id AND p.account_id=r.account_id
    WHERE r.owner_id=%s AND r.state='ready'
      AND r.result_payload->>'schema_version'='narma.replay-report.v1'
      AND r.result_payload#>>'{coverage,complete}'='true'
      AND r.result_payload#>>'{coverage,source_sha256}'=r.source_sha256
      AND r.result_payload->>'match_id'=r.match_id
      AND r.result_payload#>>'{player,account_id}'=r.account_id::text
    ORDER BY r.account_id, r.match_id, r.updated_at DESC, r.id DESC
), bounded AS (
    SELECT *, count(*) OVER() AS total_available FROM latest
    ORDER BY match_id::bigint DESC LIMIT %s
)
SELECT r.id AS job_id, r.account_id, r.match_id, r.created_at AS uploaded_at,
    r.total_available,
    r.result_payload#>>'{player,hero}' AS hero,
    r.result_payload->>'outcome' AS outcome,
    r.result_payload->'metrics' AS metrics,
    r.result_payload#>'{coverage,engine_build}' AS engine_build,
    r.result_payload#>'{coverage,unclosed_death_intervals}' AS unclosed_death_intervals,
    (SELECT e FROM jsonb_array_elements(CASE WHEN jsonb_typeof(r.result_payload->'economy')='array'
         THEN r.result_payload->'economy' ELSE '[]'::jsonb END) e
     WHERE jsonb_typeof(e->'time')='number' AND (e->>'time')::numeric BETWEEN 0 AND 600
     ORDER BY (e->>'time')::numeric DESC LIMIT 1) AS checkpoint,
    (SELECT coalesce(jsonb_agg(jsonb_build_object('id', e->'id', 'time', e->'time')), '[]'::jsonb)
     FROM jsonb_array_elements(CASE WHEN jsonb_typeof(r.result_payload->'evidence')='array'
         THEN r.result_payload->'evidence' ELSE '[]'::jsonb END) e
     WHERE e->>'type'='death') AS deaths,
    (SELECT coalesce(jsonb_agg(jsonb_build_object(
         'item', i->'item', 'label', i->'label', 'time', i->'time', 'event_id', i->'event_id',
         'first_active_inventory_time', i->'first_active_inventory_time',
         'first_use_time', i#>'{realization,first_use_time}',
         'first_use_event_id', i#>'{realization,first_use_event_id})), '[]'::jsonb)
     FROM jsonb_array_elements(CASE WHEN jsonb_typeof(r.result_payload#>'{insights,items}')='array'
         THEN r.result_payload#>'{insights,items}' ELSE '[]'::jsonb END) i) AS items,
    n.position, n.focus, n.reflection, coalesce(n.note, '') AS note
FROM bounded r LEFT JOIN hero_pool_match_notes n
    ON n.owner_id=r.owner_id AND n.account_id=r.account_id AND n.match_id=r.match_id
ORDER BY r.match_id::bigint DESC
"""


def _number(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            if math.isfinite(value) and value >= 0:
                return value
        except OverflowError:
            pass
    return None


def _position(value, *, filter_value=False):
    if value is None or (filter_value and value == "unknown"):
        return value
    if filter_value and isinstance(value, str) and value in {"1", "2", "3", "4", "5"}:
        return int(value)
    if type(value) is int and 1 <= value <= 5:
        return value
    reject(400, "HERO_POOL_POSITION", "Выберите позицию от 1 до 5 или оставьте её незаданной.")


def _hero(value):
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"npc_dota_hero_[a-z0-9_]{1,80}", value):
        reject(400, "HERO_POOL_HERO", "Выберите героя из своего пула.")
    return value


def _counts(matches):
    wins = sum(m["outcome"] == "win" for m in matches)
    losses = sum(m["outcome"] == "loss" for m in matches)
    return {"matches": len(matches), "wins": wins, "losses": losses,
            "unknown": len(matches) - wins - losses,
            "winrate": round(wins * 100 / (wins + losses), 1) if wins + losses else None}


def _normalize(row):
    metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
    duration = _number(metrics.get("duration_seconds"))
    checkpoint = row.get("checkpoint") if isinstance(row.get("checkpoint"), dict) else {}
    sample_time = _number(checkpoint.get("time"))
    # A very old sample, or a game ending before ten minutes, is not a 10m value.
    valid_checkpoint = duration is not None and duration >= 600 and sample_time is not None and 565 <= sample_time <= 600
    dead = _number(metrics.get("confirmed_dead_seconds"))
    earned = _number(metrics.get("total_earned_gold"))
    available = {
        "lh10": _number(checkpoint.get("last_hits")) if valid_checkpoint else None,
        "nw10": _number(checkpoint.get("net_worth")) if valid_checkpoint else None,
        "deaths10": _number(checkpoint.get("deaths")) if valid_checkpoint else None,
        "dead_pct": round(dead * 100 / duration, 2) if duration and dead is not None and dead <= duration
            and row.get("unclosed_death_intervals") == 0 else None,
        "gpm": round(earned * 60 / duration, 1) if duration and earned is not None else None,
    }
    uploaded = row.get("uploaded_at")
    return {"match_id": str(row["match_id"]), "job_id": str(row["job_id"]),
            "hero": row["hero"], "hero_label": display_unit(row["hero"]),
            "position": row.get("position"),
            "outcome": row.get("outcome") if row.get("outcome") in ("win", "loss") else None,
            "uploaded_at": uploaded.isoformat() if hasattr(uploaded, "isoformat") else uploaded,
            "metrics": available, "checkpoint_seconds": sample_time if valid_checkpoint else None,
            "engine_build": row.get("engine_build"),
            "focus": row.get("focus"), "reflection": row.get("reflection"), "note": row.get("note") or "",
            "_deaths": [e for e in (row.get("deaths") or []) if isinstance(e, dict) and _number(e.get("time")) is not None],
            "_items": [i for i in (row.get("items") or []) if isinstance(i, dict)]}


def _compatible_builds(matches):
    # Unknown versions may be compared descriptively with the explicit caveat.
    # Known different builds, or known mixed with unknown, cannot be pooled.
    builds = {str(m.get("engine_build")) if m.get("engine_build") is not None else None for m in matches}
    return len(builds) <= 1


def _trends(matches, hero, position):
    result = {"status": "choose_hero_position", "eligible_matches": len(matches),
              "note": "Выберите одного героя и позицию, чтобы сравнить похожие по роли матчи.",
              "older_match_ids": [], "recent_match_ids": [], "metrics": []}
    if hero is None or type(position) is not int:
        return result
    result.update(status="insufficient", note="Для сравнения нужны минимум шесть матчей на этом герое и позиции: три предыдущих и три последних.")
    if len(matches) < 6:
        return result
    recent, older = matches[:3], matches[3:6]
    if not _compatible_builds(recent + older):
        result["note"] = "Версии игры в последних шести матчах различаются или часть версий неизвестна. История доступна; средние между ними не сравниваются."
        return result
    result["older_match_ids"] = [m["match_id"] for m in reversed(older)]
    result["recent_match_ids"] = [m["match_id"] for m in reversed(recent)]
    for key, (label, unit) in METRICS.items():
        old_values = [m["metrics"][key] for m in older if m["metrics"][key] is not None]
        new_values = [m["metrics"][key] for m in recent if m["metrics"][key] is not None]
        if len(old_values) < 3 or len(new_values) < 3:
            continue
        old, new = round(mean(old_values), 2), round(mean(new_values), 2)
        result["metrics"].append({"key": key, "label": label, "unit": unit,
            "older": old, "recent": new, "delta": round(new - old, 2),
            "older_count": len(old_values), "recent_count": len(new_values)})
    if result["metrics"]:
        result.update(status="ready", note="Три предыдущих матча → три последних, по Match ID. Изменение показателей само по себе не доказывает улучшение понимания игры; составы, рейтинг и условия матчей не сопоставлены.")
        if recent[0].get("engine_build") is None:
            result["note"] += " Версия игры не подтверждена."
    else:
        result["note"] = "В каждой группе нужны три записанных значения одного показателя. Пропуски не заменяются нулями."
    return result


def _patterns(matches, hero, position):
    if hero is None or type(position) is not int or len(matches) < 3:
        return []
    # Recurrence uses the latest 20 comparable games; older habits do not keep
    # reappearing forever after the owner changes their play.
    recent = matches[:20]
    if not _compatible_builds(recent):
        return []
    patterns, repeated = [], []
    for match in recent:
        deaths = sorted(match["_deaths"], key=lambda e: e["time"])
        pair = next(((a, b) for a, b in zip(deaths, deaths[1:]) if 0 < b["time"] - a["time"] <= 180), None)
        if pair:
            repeated.append({"match_id": match["match_id"], "job_id": match["job_id"],
                "time": pair[1]["time"], "event_id": pair[1].get("id"),
                "previous_time": pair[0]["time"], "previous_event_id": pair[0].get("id")})
    if len(repeated) >= 3:
        patterns.append({"id": "safe_return", "title": "Повторные смерти за три минуты",
            "observation": f"В {len(repeated)} из {len(recent)} последних матчей на этом герое и позиции записаны две смерти с промежутком не более трёх минут. Это повод проверить решение, а не доказанная ошибка.",
            "action": "После возрождения перед возвращением к драке назови цель, проверь союзников рядом и путь отхода. После игры пересмотри повторный вход.",
            "measure": "Отметь, выполнил ли эту проверку; сравни контекст повторных смертей в следующих трёх матчах.",
            "matches": len(repeated), "eligible_matches": len(recent), "evidence": repeated[:6]})
    items = defaultdict(list)
    for match in recent:
        seen = set()
        for item in match["_items"]:
            name = item.get("item")
            active, used = _number(item.get("first_active_inventory_time")), _number(item.get("first_use_time"))
            if not isinstance(name, str) or name in seen or active is None or used is None or used < active:
                continue
            seen.add(name)
            items[name].append((match, item, used - active))
    for name, observations in sorted(items.items()):
        delayed = [(match, item, delay) for match, item, delay in observations if delay > 120]
        if len(delayed) < 3:
            continue
        patterns.append({"id": "item_plan_" + name, "title": "План первого применения: " + display_unit(name),
            "observation": f"В {len(delayed)} из {len(observations)} матчей с записанным первым применением прошло больше двух минут с появления предмета в активном слоте. Сам интервал не показывает, был ли момент для применения.",
            "action": "Перед покупкой назови задачу предмета. В первом подходящем эпизоде проверь, помог ли он её выполнить; при ожидании запиши причину.",
            "measure": "В следующих трёх матчах сравни активный слот, первое применение и результат эпизода. Не нажимай предмет только ради сокращения интервала.",
            "matches": len(delayed), "eligible_matches": len(observations),
            "evidence": [{"match_id": m["match_id"], "job_id": m["job_id"], "item": name,
                "time": i["first_use_time"], "event_id": i.get("first_use_event_id"),
                "active_time": i["first_active_inventory_time"], "delay_seconds": round(delay, 2)}
                for m, i, delay in delayed[:6]]})
    return patterns[:4]


def build_pool(rows, profile=None, hero=None, position=None):
    """Pure aggregation of the bounded, already ownership-checked projection."""
    hero, position = _hero(hero), _position(position, filter_value=True)
    # SQL performs authoritative deduplication. This defensive pass also keeps
    # duplicate projected inputs from weighting pure aggregation twice.
    all_matches, seen = [], set()
    for row in rows:
        identity = (row.get("account_id"), str(row.get("match_id")))
        name = row.get("hero")
        if identity in seen or not isinstance(name, str) or not re.fullmatch(r"npc_dota_hero_[a-z0-9_]{1,80}", name):
            continue
        seen.add(identity)
        all_matches.append(_normalize(row))
    all_matches.sort(key=lambda m: int(m["match_id"]), reverse=True)
    grouped = defaultdict(list)
    for match in all_matches:
        grouped[match["hero"]].append(match)
    heroes = []
    for name, matches in sorted(grouped.items(), key=lambda pair: (-len(pair[1]), display_unit(pair[0]))):
        positions = defaultdict(list)
        for match in matches:
            positions[match["position"]].append(match)
        heroes.append({"hero": name, "hero_label": display_unit(name), **_counts(matches),
            "positions": [{"position": pos, **_counts(values)} for pos, values in
                          sorted(positions.items(), key=lambda pair: pair[0] or 6)]})
    matches = [m for m in all_matches if (hero is None or m["hero"] == hero) and (
        position is None or (m["position"] is None if position == "unknown" else m["position"] == position))]
    total = max([int(r.get("total_available") or 0) for r in rows] + [len(all_matches)])
    practice = {"tracked": sum(bool(m["focus"]) for m in matches)}
    practice.update({key: sum(bool(m["focus"]) and m["reflection"] == key for m in matches) for key in REFLECTIONS})
    practice["unreviewed"] = sum(bool(m["focus"]) and m["reflection"] is None for m in matches)
    result = {"schema_version": SCHEMA,
        "scope": {"account_id": profile.get("account_id") if profile else None,
            "nickname": profile.get("nickname") if profile else None, "hero": hero, "position": position,
            "chronology": "match_id", "chronology_label": "Порядок матчей", "source": "uploaded_replays",
            "total_available": total, "limit": LIMIT, "truncated": total > LIMIT,
            "position_source": "self_reported",
            "context": "Учтены только загруженные и завершённые разборы закреплённого игрока. Позиция и выполнение задачи указаны вами. Рейтинг, соперники и патч не сопоставлены: это наблюдения, а не оценка понимания игры."},
        "summary": _counts(matches), "heroes": heroes, "matches": [],
        "trends": _trends(matches, hero, position), "patterns": _patterns(matches, hero, position), "practice": practice}
    result["matches"] = [{k: v for k, v in match.items() if not k.startswith("_")} for match in matches]
    return result


def get_pool(owner_id, hero=None, position=None):
    # Validation precedes the database query; no caller-supplied account ID.
    hero, position = _hero(hero), _position(position, filter_value=True)
    with database() as connection:
        profile = connection.execute("SELECT account_id,nickname FROM portal_dota_profiles WHERE owner_id=%s", (owner_id,)).fetchone()
        rows = connection.execute(POOL_SQL, (owner_id, LIMIT)).fetchall() if profile else []
    return build_pool(rows, profile, hero, position)


def update_match(owner_id, match_id, *, position=None, focus=None, reflection=None, note=""):
    position = _position(position)
    if not isinstance(match_id, str) or not re.fullmatch(r"[1-9][0-9]{7,11}", match_id):
        reject(400, "HERO_POOL_MATCH", "Укажите Match ID из своей истории.")
    if focus is not None and focus not in FOCUSES or reflection is not None and reflection not in REFLECTIONS:
        reject(400, "HERO_POOL_NOTE", "Выберите задачу и отметку выполнения из списка.")
    if not isinstance(note, str) or len(note) > 500 or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", note):
        reject(400, "HERO_POOL_NOTE", "Заметка должна содержать не больше 500 символов.")
    if reflection is not None and focus is None:
        reject(400, "HERO_POOL_NOTE", "Сначала выберите задачу для этого матча.")
    with database() as connection:
        # Same owner lock as replay profile binding; never changes that binding.
        connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (owner_id,))
        profile = connection.execute("SELECT account_id FROM portal_dota_profiles WHERE owner_id=%s FOR UPDATE", (owner_id,)).fetchone()
        report = connection.execute("""SELECT id FROM replay_jobs WHERE owner_id=%s AND account_id=%s
            AND match_id=%s AND state='ready'
            AND result_payload->>'schema_version'='narma.replay-report.v1'
            AND result_payload#>>'{coverage,complete}'='true'
            AND result_payload#>>'{coverage,source_sha256}'=source_sha256
            AND result_payload->>'match_id'=match_id
            AND result_payload#>>'{player,account_id}'=account_id::text
            LIMIT 1 FOR SHARE""", (owner_id, profile["account_id"], match_id)).fetchone() if profile else None
        if report is None:
            reject(404, "HERO_POOL_MATCH", "Завершённый разбор этого матча не найден у закреплённого игрока.")
        connection.execute("""INSERT INTO hero_pool_match_notes(owner_id,account_id,match_id,position,focus,reflection,note)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(owner_id,account_id,match_id) DO UPDATE SET
                position=excluded.position,focus=excluded.focus,reflection=excluded.reflection,
                note=excluded.note,updated_at=now()""",
            (owner_id, profile["account_id"], match_id, position, focus, reflection, note.strip()))
    return {"saved": True, "match_id": match_id, "position": position,
            "focus": focus, "reflection": reflection, "note": note.strip()}
