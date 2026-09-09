"""Authored build reviews, independent of statistics-provider availability.

A feed refresh is evidence about the latest patch, never an editorial review.
This module only reads the bundled catalog and an already bounded Valve feed.
It has no network, credentials, background jobs or user-data dependencies.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re

SCHEMA = "narma.build-reviews.v1"
REVIEW_INTERVAL_DAYS = 7
FEED_MAX_AGE = timedelta(minutes=30)
MAX_CLOCK_SKEW = timedelta(minutes=5)
CATALOG_PATH = Path(__file__).with_name("static") / "build-guides.json"
BOOT_IDS = {"boots", "power_treads", "phase_boots", "arcane_boots", "tranquil_boots",
            "travel_boots", "travel_boots_2", "boots_of_bearing", "guardian_greaves"}
# Authored alternatives are small and explicitly reviewed; reject known upgrade
# conflicts as well as duplicate slots. This is not a global item recipe engine.
UPGRADE_PAIRS = {
    ("maelstrom", "mjollnir"), ("dragon_lance", "hurricane_pike"),
    ("force_staff", "hurricane_pike"), ("witch_blade", "devastator"),
    ("cyclone", "wind_waker"), ("blink", "overwhelming_blink"),
    ("urn_of_shadows", "spirit_vessel"), ("vanguard", "crimson_guard"),
    ("travel_boots", "travel_boots_2"), ("arcane_boots", "guardian_greaves"),
}


def _date(value):
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            # Editorial review dates have day precision in the catalog.
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                return None
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _iso(value):
    return value.isoformat().replace("+00:00", "Z")


def _patch(value):
    return value if isinstance(value, str) and re.fullmatch(r"\d{1,2}\.\d{1,3}[a-z]?", value) else None


def _item_id(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[a-z0-9_]{1,80}", value))


def adaptations(guide):
    """Return only complete, compatible six-slot alternatives from this guide."""
    final = guide.get("final_items", [])
    if not isinstance(final, list) or len(final) != 6:
        return []
    final_ids = [row.get("id") if isinstance(row, dict) else None for row in final]
    if not all(_item_id(value) for value in final_ids) or len(set(final_ids)) != 6:
        return []
    pool = {row["id"]: row for row in guide.get("situational_items", [])
            if isinstance(row, dict) and _item_id(row.get("id"))}
    result, seen = [], set()
    rows = guide.get("adaptations", [])
    if not isinstance(rows, list):
        return []
    for row in rows[:12]:
        if not isinstance(row, dict):
            continue
        key, replace, item = row.get("id"), row.get("replace_item_id"), row.get("item")
        if not isinstance(key, str) or not re.fullmatch(r"[a-z0-9-]{1,80}", key) or key in seen:
            continue
        if replace not in final_ids or replace in BOOT_IDS or not isinstance(item, dict):
            continue
        candidate = item.get("id")
        if not _item_id(candidate) or candidate not in pool or candidate in final_ids:
            continue
        if not all(isinstance(row.get(field), str) and 0 < len(row[field]) <= 1000 for field in ("label", "when")):
            continue
        if not all(isinstance(pool[candidate].get(field), str) and pool[candidate][field] for field in ("name", "why", "condition")):
            continue
        inventory = set(final_ids) - {replace} | {candidate}
        if any(parent in inventory and upgrade in inventory for parent, upgrade in UPGRADE_PAIRS):
            continue
        result.append({"id": key, "label": row["label"], "when": row["when"],
                       "replace_item_id": replace, "item": deepcopy(pool[candidate])})
        seen.add(key)
    return result


def review_payload(updates, now=None, guides=None):
    """Build public status without changing authored dates or claiming win rates.

    ``guides`` is injectable for tests; production reads the checked-in catalog.
    ``updates`` is the existing explore.get_payload("updates") result, or {} when
    the official feed cannot be loaded. No exception text is copied into output.
    """
    now = now or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("now must be a timezone-aware datetime")
    now = now.astimezone(timezone.utc)
    if guides is None:
        guides = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))["guides"]
    elif isinstance(guides, dict):
        guides = list(guides.values())
    updates = updates if isinstance(updates, dict) else {}
    latest = updates.get("latest_patch")
    latest = latest if isinstance(latest, dict) else {}
    version, published = _patch(latest.get("version")), _date(latest.get("published_at"))
    checked = _date(updates.get("checked_at"))
    fresh = bool(version and published and published <= now + MAX_CLOCK_SKEW
                 and checked and -MAX_CLOCK_SKEW <= now - checked < FEED_MAX_AGE
                 and updates.get("stale") is False and updates.get("errors") == [])
    latest_public = {"version": version, "published_at": _iso(published) if published else None,
                     "url": "https://www.dota2.com/patches/" + version} if version else None
    result = {}
    for guide in guides:
        if not isinstance(guide, dict) or not isinstance(guide.get("id"), str):
            continue
        reviewed_patch = _patch(guide.get("verified_patch"))
        reviewed = _date(guide.get("checked_at"))
        due = reviewed + timedelta(days=REVIEW_INTERVAL_DAYS) if reviewed else None
        if not fresh:
            state, reason = "unknown", "Актуальную версию патча пока не удалось подтвердить."
        elif not reviewed_patch or not reviewed or reviewed > now:
            state, reason = "unknown", "Дата или патч проверки руководства не подтверждены."
        elif version != reviewed_patch:
            state, reason = "patch_changed", f"Вышел патч {version}. Этот план проверен для {reviewed_patch} и требует пересмотра."
        elif now >= due:
            state, reason = "review_due", "Нужна новая проверка плана: приоритеты покупок меняются и внутри патча."
        else:
            state, reason = "reviewed", f"Механика проверена для {reviewed_patch}. Это авторский план, без оценки винрейта."
        result[guide["id"]] = {
            "state": state, "stale": state != "reviewed", "reason": reason,
            "verified_patch": reviewed_patch, "checked_at": guide.get("checked_at") if reviewed else None,
            "final_checked_at": guide.get("final_checked_at") if _date(guide.get("final_checked_at")) else None,
            "review_due_at": _iso(due) if due else None,
            "adaptations": adaptations(guide),
            "adaptations_checked_at": guide.get("adaptations_checked_at") if _date(guide.get("adaptations_checked_at")) else None,
            "adaptations_verified_patch": _patch(guide.get("adaptations_verified_patch")),
            "patch_notes": deepcopy(guide.get("patch_notes", [])),
        }
    return {"schema_version": SCHEMA, "evaluated_at": _iso(now), "latest_patch": latest_public,
            "feed_checked_at": _iso(checked) if checked else None, "feed_fresh": fresh,
            "review_interval_days": REVIEW_INTERVAL_DAYS, "guides": result}
