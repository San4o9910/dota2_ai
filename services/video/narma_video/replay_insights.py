"""Selected-player visual facts, derived from replay events without a model.

Gold reasons follow Valve's EDOTA_ModifyGold_Reason schema, tracked at
SteamTracking/GameTracking-Dota2, blob 3eb0dcd14e08ea2d3441cd5c6af068c6b0e24f9c.
Counters such as SharedGold overlap other summary counters: never add them to
an event stream. Only the separate passive-income counter fills missing tick
awards. An unexplained difference remains visible, never labelled as farming.
"""
from __future__ import annotations

import math
from collections import defaultdict

SCHEMA = "narma.replay-insights.v1"
GOLD_REASONS = {
    0: ("unspecified", "Неуточнённое поступление"),
    1: ("death", "Потери при смерти"), 2: ("buyback", "Выкуп"),
    3: ("consumable", "Расходники"), 4: ("purchase", "Покупки предметов"),
    5: ("redistribution", "Перераспределение золота"), 6: ("sale", "Продажа предметов"),
    7: ("ability_cost", "Стоимость способности"), 8: ("other", "Прочее изменение"),
    9: ("selection_penalty", "Штраф выбора"), 10: ("passive", "Пассивный доход"),
    11: ("buildings", "Постройки"), 12: ("heroes", "Убийства и участие"),
    13: ("lane_creeps", "Крипы на линиях"), 14: ("neutrals", "Нейтральные крипы"),
    15: ("roshan", "Рошан"), 16: ("courier_team", "Курьер: командная награда"),
    17: ("bounty", "Руны богатства"), 18: ("shared_event", "Командная награда из журнала"),
    19: ("ability_gold", "Золото от способностей"), 20: ("wards", "Уничтоженные варды"),
    21: ("courier_last_hit", "Курьер: добивание"), 22: ("summons", "Призванные существа"),
}
# This is an item selector, not a recommendation, price list or patch benchmark.
KEY_ITEMS = {
    "blink", "overwhelming_blink", "swift_blink", "arcane_blink", "black_king_bar",
    "radiance", "heart", "shivas_guard", "ultimate_scepter", "ultimate_scepter_2",
    "aghanims_shard", "travel_boots", "travel_boots_2", "cyclone", "wind_waker",
    "kaya_and_sange", "sange_and_yasha", "yasha_and_kaya", "kaya", "sange", "yasha",
    "manta", "butterfly", "satanic", "skadi", "abyssal_blade", "basher", "bfury",
    "mjollnir", "maelstrom", "gungir", "gleipnir", "bloodthorn", "orchid", "sheepstick",
    "refresher", "octarine_core", "bloodstone", "sphere", "lotus_orb", "blade_mail",
    "crimson_guard", "pipe", "guardian_greaves", "mekansm", "assault", "solar_crest",
    "heavens_halberd", "force_staff", "hurricane_pike", "glimmer_cape", "aeon_disk",
    "nullifier", "desolator", "lesser_crit", "greater_crit", "monkey_king_bar", "rapier",
    "ethereal_blade", "dagon", "dagon_2", "dagon_3", "dagon_4", "dagon_5", "diffusal_blade",
    "disperser", "vladmir", "helm_of_the_dominator", "helm_of_the_overlord", "harpoon",
    "echo_sabre", "silver_edge", "invis_sword", "hand_of_midas", "phylactery", "khanda",
    "falcon_blade", "rod_of_atos", "atos", "spirit_vessel", "urn_of_shadows", "witch_blade",
    "revenants_brooch", "parasma", "meteor_hammer", "pavise", "holy_locket", "aether_lens",
}
PASSIVE_ITEMS = {"radiance", "heart", "ultimate_scepter", "ultimate_scepter_2", "aghanims_shard", "travel_boots",
    "travel_boots_2", "kaya_and_sange", "sange_and_yasha", "yasha_and_kaya", "kaya", "sange", "yasha",
    "butterfly", "skadi", "basher", "bfury", "maelstrom", "octarine_core", "sphere", "assault",
    "aeon_disk", "desolator", "lesser_crit", "greater_crit", "monkey_king_bar", "rapier", "vladmir",
    "echo_sabre", "phylactery", "khanda", "falcon_blade", "witch_blade", "parasma", "aether_lens"}
ITEM_LABELS = {"black_king_bar": "Black King Bar", "radiance": "Radiance", "heart": "Heart of Tarrasque",
    "shivas_guard": "Shiva’s Guard", "ultimate_scepter": "Aghanim’s Scepter", "ultimate_scepter_2": "Aghanim’s Blessing",
    "aghanims_shard": "Aghanim’s Shard", "travel_boots": "Boots of Travel", "travel_boots_2": "Boots of Travel 2",
    "cyclone": "Eul’s Scepter", "kaya_and_sange": "Kaya and Sange", "sphere": "Linken’s Sphere",
    "bfury": "Battle Fury", "greater_crit": "Daedalus", "sheepstick": "Scythe of Vyse"}


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def rounded(value):
    return round(value, 3)


def label(item):
    short = item.removeprefix("item_")
    return ITEM_LABELS.get(short, short.replace("_", " ").title())


def clock(value):
    value = int(max(0, value))
    return f"{value // 60}:{value % 60:02d}"


def source(reason):
    if reason is None:
        return ("unclassified", "Источник не указан")
    return GOLD_REASONS.get(reason, (f"unclassified_{reason}", f"Неопределённый источник ({reason})"))


def gold_facts(gold_events, passive_samples, duration, total_earned_gold):
    cadence = max(60, math.ceil(duration / 180 / 60) * 60)
    bins = [{"start": start, "end": rounded(min(start + cadence, duration)),
             "income": 0, "loss": 0, "by_source": {}} for start in range(0, math.ceil(duration), cadence)]
    ledger, other, losses, labels = [], defaultdict(float), defaultdict(float), {}
    # Never combine event GameTick with the same passive counter. Counter deltas
    # have sample-level timing, labelled below, rather than invented tick times.
    has_passive_events = any(r.get("reason") == 10 and 0 <= r["time"] <= duration for r in gold_events)
    for row in gold_events:
        time, value, reason = row["time"], row["gold"], row.get("reason")
        if not finite(time) or not finite(value) or time > duration:
            continue
        key, title = source(reason)
        labels[key] = title
        if time < 0:
            if value > 0:
                other["pregame"] += value
                labels["pregame"] = "До начала матча (включая стартовое золото)"
            continue
        if value < 0:
            losses[key] += -value
            bins[min(int(time // cadence), len(bins) - 1)]["loss"] += -value
        elif value > 0 and (reason is None or reason >= 10 or reason == 0):
            ledger.append({"time": time, "gold": value, "key": key})
        elif value > 0:
            other[key] += value
    passive_gap = False
    if not has_passive_events:
        previous = None
        final_snapshot_seen = False
        for sample in sorted(passive_samples, key=lambda r: r["time"]):
            time, value = sample["time"], sample["gold"]
            if not finite(value) or value < 0 or not finite(time):
                continue
            if time > duration:
                if final_snapshot_seen:
                    continue
                final_snapshot_seen = True
                time = duration
            if previous is not None and value >= previous["gold"] and time >= 0:
                delta = value - previous["gold"]
                if delta:
                    ledger.append({"time": min(time, duration), "gold": delta, "key": "passive"})
            elif previous is not None and value < previous["gold"]:
                passive_gap = True
            elif time >= 0 and value:
                # Without a baseline its value cannot be placed on a timeline.
                passive_gap = True
            previous = {"time": time, "gold": value}
        labels["passive"] = "Пассивный доход"
    totals = defaultdict(float)
    for row in ledger:
        cell = bins[min(int(row["time"] // cadence), len(bins) - 1)]
        cell["income"] += row["gold"]
        cell["by_source"][row["key"]] = cell["by_source"].get(row["key"], 0) + row["gold"]
        totals[row["key"]] += row["gold"]
    income = sum(totals.values())
    difference = rounded(total_earned_gold - income) if finite(total_earned_gold) else None
    note = ("Награды — по времени событий. " + ("Пассивный доход — по событиям журнала. " if has_passive_events else "Пассивный доход — по изменениям счётчика между снимками. ") + "Продажи и потери показаны отдельно.")
    if difference not in (None, 0):
        note += f" Разница с итоговым заработком: {difference:+g}; источник этой разницы не установлен."
    if passive_gap:
        note += " Часть интервалов пассивного дохода не подтверждена."
    return {"method": "combat_log_and_passive_counter" if ledger else "unavailable", "bins": bins,
        "sources": [{"key": key, "label": labels.get(key, key), "gold": rounded(value)} for key, value in sorted(totals.items(), key=lambda p: (-p[1], p[0]))],
        "other_flows": [{"key": key, "label": labels.get(key, key), "gold": rounded(value)} for key, value in sorted(other.items())],
        "losses": [{"key": key, "label": labels.get(key, key), "gold": rounded(value)} for key, value in sorted(losses.items())],
        "recorded_income": rounded(income), "recorded_loss": rounded(sum(losses.values())),
        "total_earned_gold": total_earned_gold if finite(total_earned_gold) else None,
        "reconciliation_difference": difference, "reconciled": difference == 0,
        "cadence_seconds": cadence, "coverage_note": note}, sorted(ledger, key=lambda r: r["time"])


def pace_facts(economy, evidence, duration):
    cadence = max(60, math.ceil(duration / 180 / 60) * 60)
    samples = sorted(economy, key=lambda r: r["time"])
    result = []
    def nearest_before(time):
        eligible = [r for r in samples if r["time"] <= time and time - r["time"] <= 35]
        return eligible[-1] if eligible else None
    for start in range(0, math.ceil(duration), cadence):
        end = min(start + cadence, duration)
        a, b = nearest_before(start), nearest_before(end)
        row = {"start": start, "end": rounded(end)}
        for metric in ("last_hits", "earned_gold", "xp"):
            row[metric] = rounded(b[metric] - a[metric]) if a and b and finite(a.get(metric)) and finite(b.get(metric)) and b[metric] >= a[metric] else None
        events = [e for e in evidence if start <= e["time"] < end or (end == duration and e["time"] == end)]
        for typ, metric in (("kill", "kills"), ("death", "deaths"), ("assist", "assists")):
            row[metric] = sum(e["type"] == typ for e in events)
        row["sample_start"] = a["time"] if a else None
        row["sample_end"] = b["time"] if b else None
        result.append(row)
    return result


def item_facts(inventory, sightings, casts, evidence, ledger, duration):
    acquisitions = []
    seen = set()
    for purchase in sorted(inventory, key=lambda r: r["time"]):
        item = purchase["item"]
        if item.removeprefix("item_") not in KEY_ITEMS or purchase["time"] < 0:
            continue
        # Purchase and assembled notifications may share a tick. Keep true
        # repurchases, but collapse duplicate same-item notifications in 1 sec.
        if any(r["item"] == item and abs(r["time"] - purchase["time"]) <= 1 for r in acquisitions):
            continue
        acquisitions.append(dict(purchase, acquisition="purchase"))
        seen.add(item)
    for sight in sightings:
        for item in sight["items"]:
            name = item["itemName"]
            if name not in seen and name.removeprefix("item_") in KEY_ITEMS and sight["time"] >= 0:
                acquisitions.append({"time": sight["time"], "item": name, "event_id": sight["event_id"], "acquisition": "inventory"})
                seen.add(name)
    acquisitions.sort(key=lambda r: r["time"])
    combinations = {"item_kaya": {"item_kaya_and_sange", "item_yasha_and_kaya"},
                    "item_sange": {"item_kaya_and_sange", "item_sange_and_yasha"},
                    "item_yasha": {"item_yasha_and_kaya", "item_sange_and_yasha"}}
    acquisitions = [r for r in acquisitions if not any(
        q["item"] in combinations.get(r["item"], set()) and 0 <= q["time"] - r["time"] <= 15
        for q in acquisitions)]
    result = []
    previous_time = 0
    for index, acquisition in enumerate(acquisitions[:40]):
        item, time = acquisition["item"], acquisition["time"]
        next_time = next((r["time"] for r in acquisitions[index + 1:] if r["item"] == item), duration + 1)
        matching = [(s["time"], i["slot"]) for s in sightings if time - .2 <= s["time"] < next_time
                    for i in s["items"] if i["itemName"] == item]
        held = next((t for t, slot in matching if 0 <= slot <= 8 or slot in (15, 16)), None)
        active = next((t for t, slot in matching if 0 <= slot <= 5), None)
        item_casts = [r for r in casts if r["item"] == item and time <= r["time"] < next_time]
        first = item_casts[0]["time"] if item_casts else None
        window_end = min(time + 120, duration, next_time)
        after = [e for e in evidence if time <= e["time"] <= window_end and e["type"] in ("kill", "assist", "death", "tower", "ward_destroyed")]
        counts = {key: sum(e["type"] == typ for e in after) for key, typ in (("kills", "kill"), ("assists", "assist"), ("deaths", "death"))}
        counts["objectives"] = sum(e["type"] in ("tower", "ward_destroyed") for e in after)
        used = [r for r in item_casts if r["time"] <= window_end]
        passive = item.removeprefix("item_") in PASSIVE_ITEMS
        status = "used_soon" if used else "used_later" if first is not None else "passive_item" if passive else "no_recorded_use"
        if window_end <= time:
            status = "no_window"
        if first is not None:
            note = f"Первое применение на {clock(first)}, через {rounded(first - time):g} с после приобретения."
        elif passive:
            note = "Число применений не отражает постоянные эффекты этого предмета. По отсутствию нажатия нельзя оценить его пользу."
        else:
            note = "Применение после приобретения не записано. Это не доказывает, что предмет не принёс пользы."
        if held is not None and held > time + 1:
            note += f" В вещах героя впервые виден на {clock(held)}."
        note += " Убийства и цели в этом окне — события после покупки, а не доказанный результат предмета."
        funding_rows = [r for r in ledger if (previous_time < r["time"] <= time) or (index == 0 and r["time"] == 0)]
        funding = defaultdict(float)
        for row in funding_rows:
            funding[row["key"]] += row["gold"]
        result.append({"id": "item-" + acquisition["event_id"] + "-" + item, "item": item, "label": label(item),
            "time": rounded(time), "event_id": acquisition["event_id"], "acquisition": acquisition["acquisition"],
            "stage": "opening" if time < 600 else "midgame" if time < 2100 else "late",
            "timing": {"status": "no_reference", "label": "Нет подтверждённой нормы", "basis": "Роль, рейтинг, патч и условия линии не заданы; время покупки не оценивается как раннее или позднее."},
            "first_hero_inventory_time": held, "first_active_inventory_time": active,
            "realization": {"window_seconds": 120, "observed_seconds": rounded(window_end - time),
                "first_use_time": first, "first_use_event_id": item_casts[0]["event_id"] if item_casts else None, "delay_seconds": rounded(first - time) if first is not None else None,
                "delay_from_active_seconds": rounded(first - active) if first is not None and active is not None and first >= active else None,
                "casts": len(used), **counts, "evidence_ids": ([item_casts[0]["event_id"]] if item_casts else []) + [e["id"] for e in after[:15]], "status": status, "note": note},
            "funding": {"start": rounded(previous_time), "end": rounded(time), "income": rounded(sum(funding.values())),
                "by_source": {key: rounded(value) for key, value in funding.items()},
                "note": "Доход между ключевыми приобретениями. Покупки компонентов, продажи и запас золота не позволяют приписать всю сумму этому предмету."}})
        previous_time = time
    return result


def training_plan(items, spans, evidence, economy):
    tasks = []
    active_items = [r for r in items if r["realization"]["status"] in ("used_later", "no_recorded_use")]
    selected = active_items[0] if active_items else (items[0] if items else None)
    if selected:
        r = selected["realization"]
        tasks.append({"id": "item-plan", "title": "Подготовь действие под новый предмет",
            "action": f"Перед следующим ключевым предметом выбери задачу: фарм, вход в драку или защита цели. Дождись доставки и проверь слот. В этом матче {selected['label']} появился на {clock(selected['time'])}.",
            "measure": "После следующей игры сравни время приобретения, появления в активном слоте и первого применения; отдельно запиши результат первого эпизода.",
            "evidence_ids": [selected["event_id"]] + r["evidence_ids"][:2]})
    deaths = [e for e in evidence if e["type"] == "death"]
    clustered = next(((a, b) for a, b in zip(deaths, deaths[1:]) if 0 < b["time"] - a["time"] <= 180), None)
    if clustered:
        a, b = clustered
        tasks.append({"id": "return-after-death", "title": "Проверь повторный вход после смерти",
            "action": f"В этом матче смерти на {clock(a['time'])} и {clock(b['time'])} разделяет меньше трёх минут. После возрождения перед телепортом проверь союзников рядом, доступные способности и цель возвращения.",
            "measure": "В следующем реплее пересмотри каждую повторную смерть в течение трёх минут и проверь, что изменилось перед вторым входом.",
            "evidence_ids": [a["id"], b["id"]]})
    elif spans:
        longest = max(spans, key=lambda r: r["seconds"])
        nearby = [e["id"] for e in deaths if abs(e["time"] - longest["start"]) <= 2]
        tasks.append({"id": "death-review", "title": "Разбери самый долгий выход из игры",
            "action": f"Начни с смерти около {clock(longest['start'])}: подтверждённое время до возвращения — {clock(longest['seconds'])}. Перед похожим выходом в следующей игре проверь, кто может помочь и как отойти.",
            "measure": "Выбери одну такую ситуацию в следующей игре и сопоставь решение до контакта с результатом.", "evidence_ids": nearby})
    if economy:
        tasks.append({"id": "farm-check", "title": "Проверяй фарм по отрезкам",
            "action": "На 10-й и 20-й минутах зафиксируй добивания и ближайший предмет. Если покупка сдвигается, после игры сопоставь этот отрезок со смертями, перемещениями и источниками дохода.",
            "measure": "Две отметки: добивания, общая стоимость и время следующего предмета. Сравнивай с предыдущей своей игрой на той же роли, а не с произвольной нормой.", "evidence_ids": []})
    return tasks[:3]


def build_insights(*, economy, metrics, evidence, inventory, gold_events, passive_samples, sightings, casts, spans, duration):
    gold, ledger = gold_facts(gold_events, passive_samples, duration, metrics.get("total_earned_gold"))
    items = item_facts(inventory, sightings, casts, evidence, ledger, duration)
    return {"schema_version": SCHEMA, "gold": gold, "pace": pace_facts(economy, evidence, duration),
        "death_intervals": spans, "items": items, "training_plan": training_plan(items, spans, evidence, economy)}
