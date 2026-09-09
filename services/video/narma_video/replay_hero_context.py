"""A read-only hero lens for saved factual reports, with no provider dependency.

The caller verifies report ownership and match/source identity before attaching
manual position. Observed casts are aggregates, not proof of an ability being
available at an episode. Necrophos mechanics are a qualitative reading guide
from Valve's hero page/datafeed (checked 2026-09-07), not a replay patch model.
"""
from __future__ import annotations

from collections import Counter
import math
import re

from .role_context import get_role_context


SCHEMA = "narma.hero-context.v1"
_HERO = re.compile(r"^npc_dota_hero_[a-z0-9_]{1,80}$")
_NAME = re.compile(r"^[a-z0-9_]{1,100}$")
_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_HERO_LABELS = {"necrolyte": "Necrophos", "nevermore": "Shadow Fiend",
    "antimage": "Anti-Mage", "rattletrap": "Clockwerk", "furion": "Nature's Prophet",
    "wisp": "Io", "zuus": "Zeus", "skeleton_king": "Wraith King",
    "windrunner": "Windranger", "obsidian_destroyer": "Outworld Destroyer"}
_ABILITY_LABELS = {"necrolyte_death_pulse": "Death Pulse",
    "necrolyte_ghost_shroud": "Ghost Shroud", "necrolyte_heartstopper_aura": "Heartstopper Aura",
    "necrolyte_reapers_scythe": "Reaper's Scythe", "necrolyte_death_seeker": "Death Seeker",
    "necrolyte_sadist": "Sadist"}
_EVENT_LABELS = {"death": "смерть", "kill": "убийство", "assist": "участие в убийстве",
    "purchase": "приобретение предмета", "item_observed": "появление предмета в инвентаре",
    "item_used": "применение предмета", "tower": "добивание башни", "buyback": "выкуп"}
# The public hero page fetches these descriptions from Valve's own endpoint:
# https://www.dota2.com/datafeed/herodata?language=english&hero_id=36
_SOURCE = {"title": "Valve — способности Necrophos", "url": "https://www.dota2.com/hero/necrophos"}


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _time(value):
    return value if _number(value) and -86400 <= value <= 86400 else None


def _label(name, hero=None):
    if name in _ABILITY_LABELS:
        return _ABILITY_LABELS[name]
    short = name.removeprefix("npc_dota_hero_").removeprefix("item_")
    if hero:
        short = short.removeprefix(hero.removeprefix("npc_dota_hero_") + "_")
    return _HERO_LABELS.get(short, short.replace("_", " ").title())[:100]


def _abilities(report, hero):
    raw = report.get("ability_usage")
    if not isinstance(raw, list):
        return []
    # A valid parser has one aggregate per name. Do not pick an arbitrary total
    # from malformed duplicates or scan an unbounded legacy payload.
    if len(raw) > 256:
        return []
    counts = Counter(row.get("name") for row in raw if isinstance(row, dict)
                     and isinstance(row.get("name"), str))
    result = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        name, casts = row.get("name"), row.get("casts")
        if (not isinstance(name, str) or not _NAME.fullmatch(name) or name.startswith("item_")
                or counts[name] != 1 or type(casts) is not int or not 1 <= casts <= 1000000):
            continue
        first, last = _time(row.get("first_time")), _time(row.get("last_time"))
        if first is not None and last is not None and first > last:
            first = last = None
        result.append({"name": name, "label": _label(name, hero), "casts": casts,
                       "first_time": first, "last_time": last})
    return sorted(result, key=lambda r: (-r["casts"], r["name"]))[:24]


def _events(report):
    raw = report.get("evidence")
    if not isinstance(raw, list) or len(raw) > 4000:
        return []
    counts = Counter(row.get("id") for row in raw if isinstance(row, dict)
                     and isinstance(row.get("id"), str))
    result = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        ident, time, kind = row.get("id"), _time(row.get("time")), row.get("type")
        if (not isinstance(ident, str) or not _ID.fullmatch(ident) or counts[ident] != 1
                or time is None or time < 0 or not isinstance(kind, str) or kind not in _EVENT_LABELS):
            continue
        result.append({"id": ident, "time": time, "type": kind,
                       "data": row["data"] if isinstance(row.get("data"), dict) else {}})
    return sorted(result, key=lambda r: (r["time"], r["id"]))


def _observation(event):
    time = int(event["time"])
    return f"В реплее на {time // 60}:{time % 60:02d} записано событие: {_EVENT_LABELS[event['type']]}."


def _item(report, events):
    insights = report.get("insights")
    raw = insights.get("items") if isinstance(insights, dict) else None
    if not isinstance(raw, list):
        return None
    by_id = {event["id"]: event for event in events}
    for item in raw[:40]:
        if not isinstance(item, dict):
            continue
        name, ident = item.get("item"), item.get("event_id")
        if (not isinstance(name, str) or not name.startswith("item_") or not _NAME.fullmatch(name)
                or not isinstance(ident, str) or ident not in by_id):
            continue
        event = by_id[ident]
        data = event["data"]
        observed = data.get("items")
        if ((event["type"] == "purchase" and data.get("item") == name)
                or (event["type"] == "item_observed" and isinstance(observed, list) and name in observed)):
            return {"name": name, "label": _label(name), "event": event}
    return None


def build_hero_context(report, position=None):
    """Return a bounded presentation layer; never edit the original report."""
    if not isinstance(report, dict) or not isinstance(report.get("player"), dict):
        return None
    hero = report["player"].get("hero")
    if not isinstance(hero, str) or not _HERO.fullmatch(hero):
        return None
    position = position if type(position) is int and 1 <= position <= 5 else None
    role = get_role_context(position)
    label = _label(hero)
    abilities, events = _abilities(report, hero), _events(report)
    names = {row["name"] for row in abilities}
    focus, plans = [], []
    limits = [
        "Число применений включает записанные события до начала матча; это не частота нажатий и не оценка качества игры.",
        "Сводка способностей не подтверждает их готовность, цель или эффект в отдельном эпизоде. Отсутствие записи не означает, что способность не использовалась.",
        "Позиция учитывается только из твоей отметки для этого матча. Нормы фарма и покупок по роли, рейтингу и патчу не задаются.",
    ]
    summary = (f"{label}: в журнале есть применения " + ", ".join(row["label"] for row in abilities[:4]) + "."
               if abilities else f"Герой этого матча — {label}. Сводка применений способностей в сохранённом разборе отсутствует или неполна.")

    def add(ident, title, advice, action, measure, event):
        refs = [event["id"]]
        focus.append({"title": title, "observation": _observation(event), "advice": advice, "evidence_ids": refs})
        plans.append({"id": ident, "title": title, "action": action, "measure": measure, "evidence_ids": list(refs)})

    death = next((event for event in events if event["type"] == "death"), None)
    combat = next((event for event in events if event["type"] in ("kill", "assist")), None)
    episode = death or combat
    necrophos = hero == "npc_dota_hero_necrolyte"
    if necrophos and "necrolyte_ghost_shroud" in names and death:
        add("hero-survival", "Necrophos: защита перед смертью",
            "Проверь перед этой смертью, от чего нужно было защищаться. Ghost Shroud мешает обычным атакам по герою, но усиливает получаемый магический урон. Был ли он доступен и подходил ли против угрозы — нужно проверить в эпизоде.",
            "Перед следующим применением Ghost Shroud на Necrophos оцени, угрожают ли обычные атаки или магический урон, и выбери, куда отойти.",
            "В следующем реплее пересмотри такое применение: какая угроза была до него и удалось ли пережить эпизод. Не считай любую смерть доказательством неверного нажатия.", death)
    elif necrophos and "necrolyte_death_pulse" in names and episode:
        add("hero-pulse", "Necrophos: позиция для Death Pulse",
            "Death Pulse наносит урон врагам рядом и лечит союзников. В этом эпизоде проверь, кто попадал под волну, была ли способность доступна и можно ли было получить пользу без опасного сближения.",
            "На Necrophos перед Death Pulse выбирай позицию с учётом врагов и союзников рядом. Если нужная позиция опасна, сначала проверь возможность отхода.",
            "После игры пересмотри выбранный эпизод: кому досталась волна и чем закончился выход. Счётчик применений сам по себе этого не показывает.", episode)
    if necrophos and "necrolyte_reapers_scythe" in names and combat:
        add("hero-scythe", "Necrophos: выбор цели для Reaper's Scythe",
            "Урон Reaper's Scythe зависит от недостающего здоровья цели. Пересмотри это участие в убийстве: какая цель была доступна, сколько здоровья она потеряла и была ли коса готова. Запись убийства не доказывает применение косы.",
            "На Necrophos перед Reaper's Scythe оцени потерянное здоровье цели и возможность команды продолжить эпизод. Не выбирай цель только потому, что она ближе.",
            "В следующем реплее проверь выбор цели и результат применения. Не используй универсальный порог здоровья: защита цели и условия эпизода различаются.", combat)

    item = _item(report, events)
    if len(focus) < 2 and item:
        interaction = f"применением {abilities[0]['label']}" if abilities else "возможностями героя"
        add("hero-item-task", f"{label}: задача для {item['label']}",
            f"В отчёте зафиксирован {item['label']}. Сопоставь задачу этого предмета с {interaction}: что требовалось в следующем эпизоде и хватало ли условий для этого? Само приобретение не доказывает готовность вступать в драку.",
            f"Играя на {label}, перед следующим ключевым предметом назови его задачу и проверь, как она сочетается с {interaction}. После доставки выбери подходящий эпизод для этой задачи.",
            "После игры сопоставь приобретение, доставку и итог выбранного эпизода. Постоянный эффект предмета не требует отдельного нажатия.", item["event"])
    if not focus and abilities and episode:
        spell = abilities[0]["label"]
        add("hero-ability-review", f"{label}: решение с {spell}",
            f"В сводке {label} есть применения {spell}. В отмеченном эпизоде проверь, была ли способность доступна, какую задачу могла решить и какие условия ей мешали. Сводка не подтверждает применение именно здесь.",
            f"В следующей игре на {label} перед похожим эпизодом проверь готовность {spell} и назови задачу, для которой хочешь её использовать.",
            "После игры найди этот эпизод и сопоставь выбранную задачу с результатом. Для сравнения используй того же героя и свою указанную позицию.", episode)
    if role:
        # The event remains the only observed fact. Role priorities supply a
        # different review question, never an invented account of the lane.
        if not focus and events:
            add("role-decision", f"{label} · {role['label']}: задача в эпизоде",
                role["review_question"], role["next_game_action"], role["measurement"],
                episode or events[0])
        else:
            for point in focus:
                point["advice"] += " " + role["review_question"]
            for plan in plans:
                plan["action"] += " " + (role["item_priority"] if plan["id"] == "hero-item-task"
                                            else role["next_game_action"])
    if necrophos:
        limits.append("Механика Necrophos приведена как справка Valve, проверенная 7 сентября 2026 года. Она не устанавливает патч этого реплея; советы предлагают проверку эпизода, а не диагноз ошибки.")
    if not focus:
        limits.append("Для привязки героевых упражнений к эпизодам недостаточно подтверждённых событий. Повторный анализ автоматически не запускается.")
    return {"schema_version": SCHEMA, "hero": hero, "label": label, "position": position,
        "position_label": f"Позиция {position} · указана тобой" if position else "Позиция не указана",
        "role_context": role,
        "summary": summary, "abilities": abilities, "focus": focus[:2], "training_plan": plans[:2],
        "limits": limits, "sources": [dict(_SOURCE)] if necrophos else []}
