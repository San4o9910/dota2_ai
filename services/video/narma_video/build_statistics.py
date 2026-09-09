"""Validated purchase aggregation and six-slot selection; no network or secrets."""
from copy import deepcopy
import json
import math
from pathlib import Path
import re

RANKS = {
    "HERALD_GUARDIAN": "Herald / Guardian",
    "CRUSADER_ARCHON": "Crusader / Archon",
    "LEGEND_ANCIENT": "Legend / Ancient",
    "DIVINE_IMMORTAL": "Divine / Immortal",
}
BOOTS = {"power_treads", "phase_boots", "arcane_boots", "tranquil_boots", "travel_boots", "travel_boots_2", "boots_of_bearing"}
# Reviewed relationships in the existing 7.41e guides. STRATZ currently returns
# null components for some finished items, so those omissions must not allow both.
UPGRADES = {"maelstrom":"mjollnir", "dragon_lance":"hurricane_pike", "witch_blade":"devastator",
            "cyclone":"wind_waker", "blink":"overwhelming_blink", "urn_of_shadows":"spirit_vessel"}
ROOT = Path(__file__).parent
GUIDES = {g["id"]: g for g in json.loads((ROOT / "static/build-guides.json").read_text())["guides"]}
HERO_IDS = {h["slug"]: h["id"] for h in json.loads((ROOT / "data/explore_snapshot.json").read_text())["heroes"]["heroes"]}

class SourceError(ValueError):
    pass


def integer(value, low=0, high=10**10):
    if type(value) is not int or not low <= value <= high:
        raise SourceError("invalid_source")
    return value


def catalog(data):
    rows = data["constants"]["items"]
    if not isinstance(rows, list) or len(rows) > 5000:
        raise SourceError("invalid_source")
    items = {}
    for row in rows:
        item_id = integer(row["id"], 1, 32767)
        slug = str(row.get("name") or "").removeprefix("item_")
        if not re.fullmatch(r"[a-z0-9_]{1,80}", slug):
            continue
        stat = row.get("stat") or {}
        name = row.get("displayName") or slug.replace("_", " ").title()
        if not isinstance(name, str) or len(name) > 120:
            continue
        items[item_id] = {"id": slug, "name": name,
            "cost": integer(stat.get("cost") or 0, 0, 100000),
            "eligible": stat.get("isRecipe") is not True and stat.get("isPurchasable") is True,
            "components": [integer(c["componentId"], 1, 32767) for c in row.get("components") or []]}
    versions = [v for v in data["constants"]["gameVersions"] or []
                if type(v.get("asOfDateTime")) is int and isinstance(v.get("name"), str)
                and re.fullmatch(r"\d+\.\d+[a-z]?", v["name"])]
    if not items or not versions:
        raise SourceError("invalid_source")
    return items, max(versions, key=lambda v:v["asOfDateTime"])["name"]


def wilson(wins, count):
    p, z = wins / count, 1.96
    return (p + z*z/(2*count) - z*math.sqrt(p*(1-p)/count + z*z/(4*count*count))) / (1+z*z/count)


def purchases(rows, items, hero, position, rank):
    if not isinstance(rows, list) or len(rows) > 25000:
        raise SourceError("invalid_source")
    grouped, weeks, seen = {}, set(), set()
    for row in rows:
        if integer(row.get("heroId"), 1, 1000) != hero:
            raise SourceError("cohort_mismatch")
        if row.get("position") not in {None, "FILTERED", f"POSITION_{position}"} or row.get("bracketBasicIds") not in {None, "FILTERED", rank}:
            error=SourceError("cohort_mismatch")
            error.context={"hero_id":hero,
                "position":row.get("position") if row.get("position") in {None,"ALL","UNKNOWN","FILTERED",*(f"POSITION_{n}" for n in range(1,6))} else "UNRECOGNIZED",
                "rank":row.get("bracketBasicIds") if row.get("bracketBasicIds") in {None,"ALL","UNCALIBRATED","FILTERED",*RANKS} else "UNRECOGNIZED"}
            raise error
        week = integer(row.get("week"), 2000, 10000)
        weeks.add(week)
        instance = integer(row.get("instance"), 0, 100)
        if instance != 0:
            continue  # Never count repeated purchases of an item as additional matches.
        item_id = integer(row.get("itemId"), 1, 32767)
        minute = integer(row.get("time"), 0, 75)
        count = integer(row.get("matchCount"), 1)
        wins = integer(row.get("winCount"), 0, count)
        key = (week, item_id, instance, minute)
        if key in seen:
            raise SourceError("duplicate_bucket")
        seen.add(key)
        if item_id not in items or not items[item_id]["eligible"]:
            continue
        value = grouped.setdefault(item_id, {"matches":0, "wins":0, "minute_total":0})
        value["matches"] += count
        value["wins"] += wins
        value["minute_total"] += count * minute
    if len(weeks) > 1:
        raise SourceError("mixed_weeks")
    result = {}
    for key, row in grouped.items():
        item = items[key]
        result[item["id"]] = {"id":item["id"], "name":item["name"], "matches":row["matches"],
            "wins":row["wins"], "winrate":round(100*row["wins"]/row["matches"], 1),
            "average_minute":round(row["minute_total"]/row["matches"], 1),
            "lower_bound":wilson(row["wins"], row["matches"])}
    return result, next(iter(weeks), None)


def suggestions(guide, evidence, items, mode):
    minimum = 100 if mode == "winrate" else 30
    # Curated hero/role pool prevents irrelevant expensive items from becoming advice.
    pool = {r["id"]:r for key in ("core_items", "situational_items", "final_items") for r in guide.get(key, [])}
    by_slug = {v["id"]:(k,v) for k,v in items.items()}
    candidates = [key for key in pool if key in evidence and evidence[key]["matches"] >= minimum
                  and key in by_slug and by_slug[key][1]["eligible"]
                  and not (key in UPGRADES and UPGRADES[key] in pool)
                  and (by_slug[key][1]["cost"] >= 1200 or key in BOOTS)]
    candidates.sort(key=lambda k: (evidence[k]["lower_bound"] if mode == "winrate" else evidence[k]["matches"], evidence[k]["matches"], k), reverse=True)
    requires_boots = any(r["id"] in BOOTS for r in guide["final_items"])
    selected = []
    if requires_boots:
        boots = next((k for k in candidates if k in BOOTS), None)
        if boots is None:
            return []
        selected.append(boots)

    def components(item_id, visited=None):
        visited = set() if visited is None else visited
        if item_id in visited or len(visited) > 100:
            return visited
        visited.add(item_id)
        for child in items.get(item_id, {}).get("components", []):
            components(child, visited)
        return visited

    for candidate in candidates:
        if candidate in BOOTS or candidate in selected:
            continue
        item_id = by_slug[candidate][0]
        if any(by_slug[other][0] in components(item_id) or item_id in components(by_slug[other][0]) for other in selected):
            continue
        selected.append(candidate)
        if len(selected) == 6:
            break
    if len(selected) != 6:
        return []  # Never fill missing evidence with an invented sixth recommendation.
    return [{**deepcopy(pool[k]), "evidence":deepcopy(evidence[k])} for k in selected]
