"""A bounded, deterministic, selected-player report from a full Clarity pass.

This module consumes private parser output, never a browser payload. A report
requires matching source metadata and the final EOF summary. It has no network
or model dependency. Combat-log amounts on DEATH/PURCHASE are deliberately not
interpreted as kill rewards or item prices.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

from .replay_insights import build_insights, KEY_ITEMS

STEAM_BASE = 76561197960265728
MAX_EVENTS_BYTES = 50 * 1024**2
MAX_LINE_BYTES = 1024**2
MAX_REPORT_BYTES = 300_000
SCHEMA = "narma.replay-report.v1"


class ReportError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def fail(code):
    raise ReportError("REPLAY_" + code)


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def clean_name(value, limit=128):
    if not isinstance(value, str) or not value or len(value) > limit or re.search(r"[\x00-\x1f\x7f]", value):
        fail("IDENTITY_INVALID")
    return value


def seconds(value):
    return round(float(value), 3)


def clock_text(value):
    value = int(max(0, value))
    return f"{value // 60}:{value % 60:02d}"


def display_unit(value):
    if not isinstance(value, str):
        return "не указан"
    known = {"necrolyte": "Necrophos", "nevermore": "Shadow Fiend", "antimage": "Anti-Mage",
             "rattletrap": "Clockwerk", "furion": "Nature's Prophet", "wisp": "Io", "zuus": "Zeus"}
    short = value.removeprefix("npc_dota_hero_").removeprefix("npc_dota_").removeprefix("item_")
    return known.get(short, short.replace("_", " ").title())[:100]


def rows(path):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > MAX_EVENTS_BYTES:
        fail("EVENTS_INVALID")
    with path.open("rb") as stream:
        for line in stream:
            if len(line) > MAX_LINE_BYTES:
                fail("EVENTS_LIMIT")
            try:
                row = json.loads(line)
            except (UnicodeDecodeError, ValueError):
                fail("EVENTS_INVALID")
            if not isinstance(row, dict):
                fail("EVENTS_INVALID")
            yield row


RESOURCE_METRICS = {
    "m_iKills": "kills", "m_iDeaths": "deaths", "m_iAssists": "assists", "m_iLevel": "level",
}
TEAM_METRICS = {
    "m_iNetWorth": "net_worth", "m_iTotalEarnedXP": "xp", "m_iTotalEarnedGold": "total_earned_gold",
    "m_iLastHitCount": "last_hits", "m_iDenyCount": "denies", "m_flHeroDamage": "hero_damage",
    "m_flTowerDamage": "tower_damage", "m_fHealing": "healing", "m_iGoldLostToDeath": "gold_lost_to_death",
    "m_iGoldSpentOnBuybacks": "gold_spent_on_buybacks", "m_iObserverWardsPlaced": "observer_wards_placed",
    "m_iSentryWardsPlaced": "sentry_wards_placed", "m_iWardsDestroyed": "wards_destroyed",
    "m_iTowerKills": "tower_last_hits", "m_iCampsStacked": "camps_stacked",
}
GOLD_SOURCES = {
    "m_iHeroKillGold": "Убийства героев", "m_iCreepKillGold": "Крипы на линиях",
    "m_iNeutralKillGold": "Нейтральные крипы", "m_iBuildingGold": "Постройки",
    "m_iBountyGold": "Bounty", "m_iWardKillGold": "Уничтоженные варды",
    "m_iIncomeGold": "Пассивный доход", "m_iSharedGold": "Общее золото команды",
}


def copy_metrics(properties, prefix, names):
    result = {}
    for field, key in names.items():
        value = properties.get(prefix + field)
        if number(value) and value >= 0:
            result[key] = round(value, 2) if isinstance(value, float) else value
    return result


def event_time(event, start):
    raw = event.get("combatTimestamp") if event.get("type") == "combat" else event.get("gameTimeDerivedFromServerTicks")
    if number(raw):
        return seconds(raw - start)
    value = event.get("matchTime")
    if not number(value):
        value = event.get("matchTimeEstimate")
    return seconds(value) if number(value) else None


def build_report(events_path, summary_path, job):
    """Validate the complete source and return only ``job.account_id`` data."""
    summary_path = Path(summary_path)
    if not summary_path.is_file() or summary_path.stat().st_size > MAX_LINE_BYTES:
        fail("SUMMARY_INVALID")
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        fail("SUMMARY_INVALID")
    if not isinstance(summary, dict) or summary.get("complete") is not True:
        fail("INCOMPLETE")
    digest = job.get("source_sha256")
    match_id = str(job.get("match_id", ""))
    account_id = job.get("account_id")
    if (not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest)
            or not re.fullmatch(r"[1-9][0-9]{7,11}", match_id)
            or type(account_id) is not int or not 0 < account_id < 2**32):
        fail("IDENTITY_INVALID")
    if summary.get("sha256") != digest or str(summary.get("matchId")) != match_id:
        fail("SOURCE_MISMATCH")
    final_tick = summary.get("lastTick")
    if type(final_tick) is not int or final_tick <= 0 or final_tick != summary.get("playbackTicks"):
        fail("INCOMPLETE")
    start = summary.get("gameStartTimeRaw")
    if not number(start) or start <= 0:
        fail("CLOCK_UNAVAILABLE")
    steam_id = str(STEAM_BASE + account_id)
    roster = summary.get("players")
    if not isinstance(roster, list):
        fail("IDENTITY_UNAVAILABLE")
    candidates = [p for p in roster if isinstance(p, dict) and str(p.get("steamId")) == steam_id]
    if len(candidates) != 1:
        fail("IDENTITY_UNAVAILABLE")
    selected = candidates[0]
    hero = clean_name(selected.get("hero"))
    nickname = clean_name(selected.get("name"))
    if not re.fullmatch(r"npc_dota_hero_[a-z0-9_]+", hero) or selected.get("team") not in (2, 3):
        fail("IDENTITY_INVALID")
    # Combat target names cannot distinguish two real heroes with the same name.
    unique_hero = sum(p.get("hero") == hero for p in roster if isinstance(p, dict)) == 1
    team = selected["team"]
    selected_class = "CDOTA_DataRadiant" if team == 2 else "CDOTA_DataDire"
    metrics, samples, pending_combat, hero_lives, handle_set = {}, {}, [], [], set()
    gold_sources = []
    passive_samples, pending_inventories = [], []
    resource_index = team_slot = None
    final_resource = final_team = False
    total_events = 0
    saw_summary = False
    game_end = summary.get("gameEndTimeRaw")
    game_end = game_end - start if number(game_end) and game_end > start else None
    post_game_events = []
    observed_until = 0.0

    for event in rows(events_path):
        total_events += 1
        if saw_summary or event.get("eventId") != total_events:
            fail("EVENTS_INCOMPLETE")
        kind = event.get("type")
        if total_events == 1:
            source = event.get("metadata")
            if (kind != "source" or not isinstance(source, dict)
                    or source.get("sha256") != digest or str(source.get("matchId")) != match_id
                    or source.get("playbackTicks") != final_tick or source.get("players") != roster):
                fail("SOURCE_MISMATCH")
            continue
        if kind == "summary":
            if event.get("summary") != summary:
                fail("SUMMARY_MISMATCH")
            saw_summary = True
            continue
        time = event_time(event, start)
        if kind == "combat" and event.get("combatType") == "DOTA_COMBATLOG_GAME_STATE":
            if event.get("value") == 6 and time is not None and time >= 0:
                post_game_events.append(time)
            continue
        if kind in ("player_snapshot", "player_schema"):
            p = event.get("properties", {})
            if not isinstance(p, dict):
                fail("EVENTS_INVALID")
            if event.get("class") == "CDOTA_PlayerResource":
                keys = [key for key, value in p.items() if re.fullmatch(r"m_vecPlayerData\.[0-9]{4}\.m_iPlayerSteamID", key) and str(value) == steam_id]
                if len(keys) > 1:
                    fail("IDENTITY_AMBIGUOUS")
                if keys:
                    index = int(keys[0].split(".")[1])
                    if resource_index is not None and index != resource_index:
                        fail("RESOURCE_IDENTITY_CHANGED")
                    resource_index = index
                    prefix = f"m_vecPlayerTeamData.{index:04d}."
                    slot = p.get(prefix + "m_iTeamSlot")
                    if type(slot) is int and 0 <= slot < 5:
                        team_slot = slot
                    handle = p.get(prefix + "m_hSelectedHero")
                    if type(handle) is int and 0 <= handle < 16777215:
                        handle_set.add(handle)
                    values = copy_metrics(p, prefix, RESOURCE_METRICS)
                    if time is not None and time >= 0:
                        metrics.update(values)
                        final_resource = bool(values)
                        observed_until = max(observed_until, time)
                        sample = samples.setdefault(time, {"time": time})
                        sample.update(values)
            elif event.get("class") == selected_class:
                # Direct Steam ID is authoritative. Never select the footer row
                # number, nor assume the opposite team's slot is this player.
                keys = [key for key, value in p.items() if re.fullmatch(r"m_vecDataTeam\.[0-9]{4}\.m_iPlayerSteamID", key) and str(value) == steam_id]
                if len(keys) > 1:
                    fail("IDENTITY_AMBIGUOUS")
                if keys:
                    slot = int(keys[0].split(".")[1])
                    if team_slot is not None and slot != team_slot:
                        fail("TEAM_IDENTITY_MISMATCH")
                    prefix = f"m_vecDataTeam.{slot:04d}."
                    values = copy_metrics(p, prefix, TEAM_METRICS)
                    passive = p.get(prefix + "m_iIncomeGold")
                    if time is not None and number(passive) and passive >= 0:
                        passive_samples.append({"time": time, "gold": passive})
                    if time is not None and time >= 0:
                        metrics.update(values)
                        final_team = bool(values)
                        observed_until = max(observed_until, time)
                        sample = samples.setdefault(time, {"time": time})
                        for key in ("net_worth", "xp", "last_hits", "denies", "total_earned_gold"):
                            if key in values:
                                sample["earned_gold" if key == "total_earned_gold" else key] = values[key]
                        gold_sources = [{"source": field, "label": label, "gold": p[prefix + field]}
                            for field, label in GOLD_SOURCES.items() if number(p.get(prefix + field)) and p[prefix + field] >= 0]
            continue
        if kind == "hero_inventory" and time is not None:
            pending_inventories.append((time, event))
            continue
        if kind == "hero_life" and event.get("entityName") == hero and event.get("team") == team:
            if time is not None:
                hero_lives.append((time, event))
            continue
        if kind == "combat" and time is not None:
            pending_combat.append((time, event))
    if not saw_summary or not final_resource or not final_team or resource_index is None:
        fail("INCOMPLETE_PLAYER_DATA")
    if game_end is None and post_game_events:
        game_end = min(post_game_events)
    if game_end is None or not 0 < game_end < 24 * 3600:
        fail("GAME_END_UNAVAILABLE")
    duration = seconds(game_end)
    metrics["duration_seconds"] = duration

    evidence, inventory, deaths, buybacks = [], [], [], []
    ability_usage, item_usage = {}, {}
    gold_events, item_casts = [], []
    first_item_casts = set()

    def emit(event, time, typ, title, details, data=None):
        row = {"id": f"event-{event['eventId']}", "type": typ, "time": seconds(time),
               "title": title, "details": details, "data": data or {}}
        evidence.append(row)
        return row

    for time, event in pending_combat:
        if time > duration + 0.2:
            continue
        typ, target, attacker = event.get("combatType"), event.get("target"), event.get("attacker")
        own_target = unique_hero and target == hero
        own_attacker = unique_hero and attacker == hero and event.get("attackerIllusion") is not True
        if typ in ("DOTA_COMBATLOG_ABILITY", "DOTA_COMBATLOG_ITEM") and own_attacker:
            inflictor = event.get("inflictor")
            if isinstance(inflictor, str) and re.fullmatch(r"[a-z0-9_]{1,100}", inflictor):
                usage = item_usage if typ == "DOTA_COMBATLOG_ITEM" else ability_usage
                entry = usage.setdefault(inflictor, {"name": inflictor, "casts": 0, "first_time": time, "last_time": time})
                entry["casts"] += 1
                entry["last_time"] = time
                if typ == "DOTA_COMBATLOG_ITEM":
                    item_casts.append({"time": time, "item": inflictor, "event_id": f"event-{event['eventId']}"})
                    if inflictor.removeprefix("item_") in KEY_ITEMS and inflictor not in first_item_casts and time >= 0:
                        emit(event, time, "item_used", display_unit(inflictor),
                             "Первое записанное применение этого предмета выбранным героем.", {"item": inflictor})
                        first_item_casts.add(inflictor)
        if typ == "DOTA_COMBATLOG_GOLD" and own_target:
            amount = event.get("value")
            reason = event.get("goldReason")
            if type(amount) is int and -(2**31) <= amount < 2**32:
                # Some decoders expose protobuf uint32 rather than signed deltas.
                amount = amount - 2**32 if amount >= 2**31 else amount
                gold_events.append({"time": time, "gold": amount, "reason": reason if type(reason) is int and 0 <= reason <= 10000 else None})
        if typ == "DOTA_COMBATLOG_PURCHASE" and own_target:
            item = event.get("valueName")
            if isinstance(item, str) and re.fullmatch(r"item_[a-z0-9_]{1,100}", item):
                first_item_casts.discard(item)
                row = emit(event, time, "purchase", display_unit(item), "Предмет зафиксирован в журнале приобретений.", {"item": item})
                inventory.append({"time": time, "item": item, "event_id": row["id"]})
        elif typ == "DOTA_COMBATLOG_BUYBACK" and event.get("value") == resource_index:
            row = emit(event, time, "buyback", "Выкуп", "Игрок использовал выкуп. Стоимость берётся из статистики матча, а не из номера события.")
            buybacks.append(row)
        elif typ == "DOTA_COMBATLOG_DEATH":
            real_hero = event.get("targetHero") is True and event.get("targetIllusion") is False
            if real_hero and event.get("willReincarnate") is True:
                if own_target or own_attacker or resource_index in event.get("assistPlayerIds", []):
                    emit(event, time, "reincarnation", "Потеря жизни с возрождением", "Журнал пометил возрождение: событие не добавляется к обычным убийствам, смертям и ассистам.", {"target_hero": target})
            elif own_target and real_hero:
                row = emit(event, time, "death", "Смерть", f"Добивающий источник: {display_unit(attacker)}.",
                           {"attacker": attacker if isinstance(attacker, str) else None,
                            "ability": event.get("inflictor"), "reincarnation": event.get("willReincarnate") is True})
                deaths.append(row)
            elif real_hero and own_attacker:
                emit(event, time, "kill", "Убийство героя", f"Добит {display_unit(target)}. Награда за убийство здесь не вычисляется.", {"target_hero": target})
            elif real_hero and not own_target and resource_index in event.get("assistPlayerIds", []):
                emit(event, time, "assist", "Участие в убийстве", f"Журнал указал участие игрока в убийстве {display_unit(target)}.", {"target_hero": target})
            elif own_attacker and isinstance(target, str) and ("tower" in target or "ward" in target):
                is_tower = "tower" in target
                emit(event, time, "tower" if is_tower else "ward_destroyed",
                     "Башня уничтожена" if is_tower else "Вард уничтожен", "Добивающий удар принадлежит выбранному герою.", {"target": target})
        elif typ == "DOTA_COMBATLOG_ITEM" and own_attacker and event.get("inflictor") in ("item_ward_observer", "item_ward_sentry", "item_ward_dispenser"):
            emit(event, time, "ward_item_used", "Использован предмет с вардами", "Это событие применения предмета; координаты и тип поставленного варда им не подтверждаются.", {"item": event["inflictor"]})

    sightings = []
    observed_items = {row["item"] for row in inventory}
    for time, event in pending_inventories:
        if (event.get("heroHandle") not in handle_set or event.get("team") != team
                or event.get("illusion") is True or time > duration
                or (event.get("selectedPlayerIndex") is not None and event.get("selectedPlayerIndex") != resource_index)):
            continue
        source_items = event.get("items")
        if not isinstance(source_items, list) or len(source_items) > 17:
            continue
        items = [{"slot": item["slot"], "itemName": item["itemName"]}
            for item in source_items if isinstance(item, dict) and type(item.get("slot")) is int
            and 0 <= item["slot"] <= 16 and isinstance(item.get("itemName"), str)
            and re.fullmatch(r"item_[a-z0-9_]{1,100}", item["itemName"])]
        sight = {"time": time, "event_id": f"event-{event['eventId']}", "items": items}
        sightings.append(sight)
        newly_seen = [item["itemName"] for item in items if item["itemName"] not in observed_items
                      and item["itemName"].removeprefix("item_") in KEY_ITEMS and time >= 0]
        if newly_seen:
            emit(event, time, "item_observed", "Предметы в инвентаре",
                 "Предметы впервые записаны в инвентаре героя; магазинное приобретение не подтверждено.", {"items": newly_seen})
            observed_items.update(newly_seen)
    sightings.sort(key=lambda row: row["time"])
    item_casts.sort(key=lambda row: row["time"])

    # Life state is tied to the selected entity handle, not an unreliable hero
    # playerId or network/PVS departure. Only paired death -> alive spans count.
    spans = []
    life_state, began = {}, {}
    for time, event in hero_lives:
        handle = event.get("entityHandle")
        if handle not in handle_set or event.get("lifeState") not in (0, 1, 2) or time > duration:
            continue
        state, old = event["lifeState"], life_state.get(handle)
        life_state[handle] = state
        if old == 0 and state in (1, 2) and time >= 0:
            began[handle] = (time, event)
        elif state == 0 and old in (1, 2) and handle in began:
            since, death_event = began.pop(handle)
            if time >= since:
                span = {"start": seconds(since), "end": seconds(time), "seconds": seconds(time - since)}
                spans.append(span)
                emit(event, time, "respawn", "Возвращение в игру", f"Герой снова жив. Подтверждённое время после смерти: {span['seconds']:.1f} с.", span)
    metrics["confirmed_dead_seconds"] = seconds(sum(span["seconds"] for span in spans))
    metrics["confirmed_death_intervals"] = len(spans)
    metrics["buybacks"] = len(buybacks)

    economy = []
    last = {}
    for time, sample in sorted(samples.items()):
        last.update(sample)
        if "net_worth" not in last or "xp" not in last:
            continue
        row = dict(last, time=seconds(min(time, duration)))
        if economy and economy[-1]["time"] == row["time"]:
            economy[-1] = row
        else:
            economy.append(row)
    # Long matches keep endpoints and a bounded, explicitly stated cadence.
    if len(economy) > 601:
        count = len(economy)
        economy = [economy[round(index * (count - 1) / 600)] for index in range(601)]
    evidence.sort(key=lambda row: (row["time"], int(row["id"].split("-")[1])))
    if len(evidence) > 650:
        fail("REPORT_EVENT_LIMIT")

    findings = []
    if deaths:
        findings.append({"id": "deaths", "title": "Смерти и время вне игры",
            "observation": f"Смертей по итоговой статистике: {metrics.get('deaths', '—')}. Подтверждённые интервалы от смерти до возвращения: {clock_text(metrics['confirmed_dead_seconds'])}.",
            "advice": "Начни просмотр со смертей, после которых дольше всего не мог участвовать в игре. Причину каждого решения нужно проверять в контексте эпизода.",
            "evidence_ids": [row["id"] for row in deaths]})
        clustered = [(b["time"] - a["time"], a, b) for a, b in zip(deaths, deaths[1:]) if 0 < b["time"] - a["time"] <= 180]
        if clustered:
            gap, a, b = min(clustered, key=lambda value: value[0])
            findings.append({"id": "repeat-death", "title": "Две смерти за короткий промежуток",
                "observation": f"Смерти на {clock_text(a['time'])} и {clock_text(b['time'])}; между ними {gap:.1f} с.",
                "advice": "Пересмотри, зачем возвращался в этот эпизод после первой смерти и что изменилось к повторному входу.",
                "evidence_ids": [a["id"], b["id"]]})
    for buyback in buybacks:
        later = next((row for row in deaths if buyback["time"] < row["time"] <= buyback["time"] + 120), None)
        if later:
            gap = later["time"] - buyback["time"]
            findings.append({"id": "buyback-" + buyback["id"], "title": "Смерть вскоре после выкупа",
                "observation": f"Выкуп на {clock_text(buyback['time'])}; следующая смерть через {gap:.1f} с.",
                "advice": "Проверь цель выкупа и возможность выполнить её до повторного вступления в драку. Сам факт быстрой смерти не доказывает, что выкуп был ошибкой.",
                "evidence_ids": [buyback["id"], later["id"]]})
    checkpoints = []
    for target in (600, 1200, 1800):
        before = [row for row in economy if row["time"] <= target and "last_hits" in row]
        if before and target - before[-1]["time"] <= 35:
            checkpoints.append(before[-1])
    if checkpoints:
        findings.append({"id": "farm-checkpoints", "title": "Как рос фарм",
            "observation": "; ".join(f"{clock_text(row['time'])}: {row['last_hits']} добиваний, {row['net_worth']} общей стоимости" for row in checkpoints) + ".",
            "advice": "Сравни прирост между этими отметками со своими перемещениями и смертями. Эти числа не задают норму для роли или рейтинга.",
            "evidence_ids": []})
    limits = [
        "Выводы основаны на событиях и статистике реплея; причины решений, MMR и видимость не угадываются.",
        "Журнал приобретений не подтверждает доставку. Появление в слотах и применение показаны отдельно, когда эти события записаны.",
        "Значения DEATH и PURCHASE не считаются полученным золотом или ценой предмета.",
        "Время вне игры учитывает только подтверждённые пары переходов состояния героя; незавершённые интервалы исключены.",
        "Счётчики источников золота приводятся как записаны игрой; их сумма может содержать пересечения.",
    ]
    if not unique_hero:
        limits.append("В матче повторяются имена героев: события, которые нельзя однозначно приписать игроку, исключены.")
    report = {"schema_version": SCHEMA, "match_id": match_id,
        "player": {"account_id": account_id, "nickname": nickname, "hero": hero, "team": "radiant" if team == 2 else "dire"},
        "metrics": metrics, "economy": economy, "gold_sources": gold_sources,
        "outcome": ("win" if summary.get("gameWinnerRaw") == team else "loss") if summary.get("gameWinnerRaw") in (2, 3) else None,
        "ability_usage": sorted(ability_usage.values(), key=lambda value: (-value["casts"], value["name"])),
        "item_usage": sorted(item_usage.values(), key=lambda value: (-value["casts"], value["name"])),
        "evidence": evidence, "inventory": inventory, "findings": findings,
        "coverage": {"complete": True, "source_sha256": digest, "parser": summary.get("parser"),
            "final_tick": final_tick, "playback_ticks": summary["playbackTicks"], "events_read": total_events,
            "economy_samples": len(economy), "stats_observed_until": seconds(observed_until),
            "unclosed_death_intervals": len(began), "limits": limits}}
    report["insights"] = build_insights(economy=economy, metrics=metrics, evidence=evidence,
        inventory=inventory, gold_events=gold_events, passive_samples=passive_samples,
        sightings=sightings, casts=item_casts, spans=spans, duration=duration)
    report["coverage"]["insights_version"] = report["insights"]["schema_version"]
    if len(json.dumps(report, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")) > MAX_REPORT_BYTES:
        fail("REPORT_SIZE_LIMIT")
    return report
