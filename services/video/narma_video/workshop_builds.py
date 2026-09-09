"""Public Steam guide facts, with attribution and source-owned freshness.

Only public item identifiers and their stages are retained. Guide prose, item
tooltips, account information and game statistics are never copied. Refreshes
use a fixed, reviewed list of published IDs; they cannot enumerate accounts.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlsplit
from concurrent.futures import ThreadPoolExecutor

import httpx

SCHEMA = "narma.workshop-builds.v1"
SEED_PATH = Path(__file__).with_name("data") / "workshop_builds.json"
METADATA_URL = "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
CDN_HOSTS = frozenset({"cdn.steamusercontent.com", "steamusercontent-a.akamaihd.net"})
MAX_BYTES = 2 * 1024 * 1024
REFRESH_SECONDS = 24 * 3600
SOURCE_REVIEW_DAYS = 30
GROUP_KEYS = ("starting_items", "early_items", "core_items", "extension_items", "situational_items", "luxury_items")
BOOTS = {"boots", "power_treads", "phase_boots", "arcane_boots", "tranquil_boots", "travel_boots", "travel_boots_2", "guardian_greaves", "boots_of_bearing"}
CONSUMABLES = {"aghanims_shard", "ultimate_scepter_2", "moon_shard", "tango", "flask", "clarity", "enchanted_mango", "faerie_fire", "tpscroll", "ward_observer", "ward_sentry", "dust", "smoke_of_deceit", "tome_of_knowledge", "cheese", "refresher_shard", "aegis"}
# The projection removes known components in favour of their actual later
# recommendation. It does not buy upgrades the author did not recommend.
UPGRADES = {
    "hurricane_pike": {"dragon_lance", "force_staff"}, "mjollnir": {"maelstrom"},
    "gungir": {"maelstrom", "rod_of_atos"}, "devastator": {"witch_blade"},
    "wind_waker": {"cyclone"}, "overwhelming_blink": {"blink"},
    "swift_blink": {"blink"}, "arcane_blink": {"blink"},
    "abyssal_blade": {"basher", "vanguard"}, "silver_edge": {"invis_sword"},
    "spirit_vessel": {"urn_of_shadows"}, "crimson_guard": {"vanguard", "buckler"},
    "guardian_greaves": {"arcane_boots", "mekansm", "buckler"},
    "boots_of_bearing": {"tranquil_boots", "ancient_janggo"},
    "travel_boots_2": {"travel_boots"}, "sange_and_yasha": {"sange", "yasha"},
    "kaya_and_sange": {"kaya", "sange"}, "yasha_and_kaya": {"yasha", "kaya"},
    "manta": {"yasha"}, "satanic": {"lifesteal"}, "bloodthorn": {"orchid"},
    "helm_of_the_overlord": {"helm_of_the_dominator"}, "disperser": {"diffusal_blade"},
    "ethereal_blade": {"ghost", "aether_lens"}, "shivas_guard": {"veil_of_discord"},
}


class WorkshopError(ValueError):
    def __init__(self, code="invalid_source"):
        super().__init__(code)
        self.code = code if code in {"invalid_source", "source_unavailable", "access_denied", "source_too_large"} else "invalid_source"


def _now():
    return datetime.now(timezone.utc)


def _iso(value):
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _date(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result if result.tzinfo else None
    except (ValueError, TypeError, AttributeError):
        return None


def _safe_text(value, maximum=180):
    if not isinstance(value, str) or not 0 < len(value.strip()) <= maximum or re.search(r"[<>\x00-\x1f\x7f]", value):
        raise WorkshopError()
    return value.strip()


def parse_keyvalues(content):
    """Small bounded Valve KeyValues parser preserving repeated item keys."""
    if not isinstance(content, bytes) or len(content) > MAX_BYTES:
        raise WorkshopError("source_too_large")
    try:
        text = content.decode("utf-16" if content.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig").rstrip("\x00")
    except UnicodeError:
        raise WorkshopError() from None
    token_re = re.compile(r'\s+|//[^\n]*|"((?:[^"\\]|\\.)*)"|([{}])')
    tokens, pos = [], 0
    while pos < len(text):
        match = token_re.match(text, pos)
        if not match:
            raise WorkshopError()
        pos = match.end()
        if match.group(1) is not None:
            tokens.append(re.sub(r'\\(["\\])', r'\1', match.group(1)))
        elif match.group(2):
            tokens.append(match.group(2))
        if len(tokens) > 50000:
            raise WorkshopError()
    cursor = 0
    def parse(depth=0):
        nonlocal cursor
        if depth > 12:
            raise WorkshopError()
        result = []
        while cursor < len(tokens) and tokens[cursor] != "}":
            key = tokens[cursor]
            cursor += 1
            if key in {"{", "}"} or cursor >= len(tokens):
                raise WorkshopError()
            value = tokens[cursor]
            cursor += 1
            if value == "{":
                value = parse(depth + 1)
                if cursor >= len(tokens) or tokens[cursor] != "}":
                    raise WorkshopError()
                cursor += 1
            elif value == "}":
                raise WorkshopError()
            result.append((key, value))
        return result
    rows = parse()
    if cursor != len(tokens) or len(rows) != 1 or rows[0][0] != "guidedata" or not isinstance(rows[0][1], list):
        raise WorkshopError()
    return rows[0][1]


def _get(rows, key, default=None):
    return next((value for name, value in rows if name == key), default) if isinstance(rows, list) else default


def group_name(value):
    value = value.lower()
    if "starting" in value: return "starting_items"
    if "early" in value: return "early_items"
    if "situational" in value: return "situational_items"
    if "extension" in value: return "extension_items"
    if "luxury" in value or "late" in value: return "luxury_items"
    if "core" in value or "mid_game" in value: return "core_items"
    return None  # Sponsorship headers, arbitrary prose and other sections are omitted.


def inventory_projection(groups):
    """Up to six factual item choices; empty slots remain empty in the UI."""
    priority = groups["core_items"] + groups["extension_items"]
    early_boots = [x for x in groups["early_items"] if x["id"] in BOOTS]
    boots = [x for x in priority if x["id"] in BOOTS][-1:] or early_boots[-1:]
    priority = boots + [x for x in priority if x["id"] not in BOOTS]
    values = {x["id"] for x in priority}
    components = set().union(*(UPGRADES.get(x, set()) for x in values)) if values else set()
    result, seen = [], set()
    for item in priority:
        key = item["id"]
        if key not in seen and key not in CONSUMABLES and key not in components and not key.startswith("recipe_"):
            seen.add(key)
            result.append(deepcopy(item))
    return result[:6]


def parse_guide(metadata, content, heroes, items, authors, fetched_at=None):
    guide_id = str(metadata.get("publishedfileid", ""))
    creator = str(metadata.get("creator", ""))
    if (not re.fullmatch(r"[0-9]{1,20}", guide_id) or metadata.get("result") != 1
            or metadata.get("consumer_app_id") != 570 or metadata.get("visibility") != 0
            or metadata.get("banned") or creator not in authors):
        raise WorkshopError()
    data = parse_keyvalues(content)
    slug = _get(data, "Hero")
    if slug not in heroes:
        raise WorkshopError()
    title = _safe_text(_get(data, "Title"))
    patch = _get(data, "GameplayVersion")
    if not isinstance(patch, str) or not re.fullmatch(r"\d{1,2}\.\d{1,3}[a-z]?", patch):
        raise WorkshopError()
    timestamp = metadata.get("time_updated")
    if type(timestamp) is not int:
        raise WorkshopError()
    updated = datetime.fromtimestamp(timestamp, timezone.utc)
    if not datetime(2013, 1, 1, tzinfo=timezone.utc) <= updated <= _now() + timedelta(minutes=5):
        raise WorkshopError()
    role_source = _get(data, "Role", "")
    role = "support" if "Support" in role_source else "offlane" if "Offlane" in role_source else "core" if "Core" in role_source else "unknown"
    explicit = re.search(r"\bpos(?:ition)?\.?\s*([1-5])\b", title, re.I)
    position = int(explicit.group(1)) if explicit else (2 if re.search(r"\bmid(?:lane)?\b", title, re.I) else 3 if re.search(r"\bofflan[er]*\b", title, re.I) else 1 if re.search(r"\bcarry\b", title, re.I) else None)
    # The author's explicit position is more precise than Steam's three broad
    # tags, some of which persist after an author changes a guide's position.
    if position is not None:
        role = "support" if position >= 4 else "offlane" if position == 3 else "core"
    positions = [position] if position else [4, 5] if role == "support" else [3] if role == "offlane" else [1, 2, 3] if role == "core" else []
    groups = {key: [] for key in GROUP_KEYS}
    source_items = _get(_get(data, "ItemBuild"), "Items")
    if not isinstance(source_items, list):
        raise WorkshopError()
    for header, values in source_items:
        group = group_name(header)
        if not group or not isinstance(values, list):
            continue
        for key, value in values:
            if key != "item" or not isinstance(value, str): continue
            identifier = value.removeprefix("item_")
            if identifier not in items: continue
            if len(groups[group]) >= 24: break
            groups[group].append({"id": identifier, "name": items[identifier]})
    if not groups["core_items"]:
        raise WorkshopError()
    return {"id": "steam-" + guide_id, "workshop_id": guide_id, "hero_slug": slug,
            "hero_name": heroes[slug], "title": title, "position": position, "positions": positions,
            "position_exact": position is not None, "role": role, "author": authors[creator],
            "creator_id": creator, "source_url": "https://steamcommunity.com/sharedfiles/filedetails/?id=" + guide_id,
            "source_patch": patch, "source_updated_at": _iso(updated), "fetched_at": fetched_at or _iso(_now()),
            **groups, "final_items": inventory_projection(groups),
            "final_note": "План слотов Narma из основных покупок автора. Это не обязательный порядок покупок: условия матча важнее заполненного инвентаря. Шард и расходуемые улучшения показаны в этапах, отдельно от слотов."}


def _cdn_url(url):
    if not isinstance(url, str): raise WorkshopError()
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        raise WorkshopError() from None
    if (parsed.scheme != "https" or parsed.hostname not in CDN_HOSTS or parsed.username or parsed.password
            or port not in (None, 443) or not re.fullmatch(r"/ugc/[0-9]+/[A-Fa-f0-9]+/", parsed.path)
            or parsed.query or parsed.fragment):
        raise WorkshopError()
    return url


def _request(url, data=None):
    if url != METADATA_URL: _cdn_url(url)
    started = time.monotonic()
    try:
        with httpx.Client(timeout=httpx.Timeout(12, connect=4), follow_redirects=False, trust_env=False) as client:
            with client.stream("POST" if data is not None else "GET", url, data=data,
                               headers={"User-Agent": "NarmaVision-PublicGuides/1.0", "Accept-Encoding": "identity"}) as response:
                if response.status_code in (401, 403): raise WorkshopError("access_denied")
                if response.status_code != 200: raise WorkshopError("source_unavailable")
                result = bytearray()
                for chunk in response.iter_bytes():
                    if time.monotonic() - started > 18: raise WorkshopError("source_unavailable")
                    result.extend(chunk)
                    if len(result) > MAX_BYTES: raise WorkshopError("source_too_large")
                return bytes(result)
    except httpx.HTTPError:
        raise WorkshopError("source_unavailable") from None


def fetch_metadata(ids):
    if not 1 <= len(ids) <= 30 or any(not re.fullmatch(r"[0-9]{1,20}", str(x)) for x in ids):
        raise WorkshopError()
    params = {"itemcount": str(len(ids)), **{f"publishedfileids[{i}]": str(value) for i, value in enumerate(ids)}}
    try:
        rows = json.loads(_request(METADATA_URL, params))["response"]["publishedfiledetails"]
    except (ValueError, KeyError, TypeError):
        raise WorkshopError() from None
    if not isinstance(rows, list) or len(rows) > 30: raise WorkshopError()
    return rows


def refresh_snapshot(snapshot):
    snapshot = deepcopy(snapshot)
    old = {g["workshop_id"]: g for g in snapshot["guides"]}
    ids, errors, blocked = list(old), [], False
    withdrawn = set(snapshot.get("withdrawn_ids", []))
    fetched_at = _iso(_now())
    for offset in range(0, len(ids), 30):
        batch = ids[offset:offset + 30]
        try:
            metadata = fetch_metadata(batch)
        except WorkshopError as error:
            errors.append(error.code)
            for key in batch: old[key]["source_error"] = error.code
            if error.code == "access_denied": blocked = True; break
            continue
        returned_ids = {str(row.get("publishedfileid")) for row in metadata if isinstance(row, dict)}
        if returned_ids != set(batch):
            errors.append("invalid_source")
            for key in set(batch) - returned_ids: old[key]["source_error"] = "invalid_source"
        def update(row):
            key = str(row.get("publishedfileid", ""))
            if key not in batch: raise WorkshopError()
            previous = old[key]
            if (row.get("result") != 1 or row.get("visibility") != 0 or row.get("banned")
                    or str(row.get("creator")) != previous["creator_id"] or row.get("consumer_app_id") != 570):
                # Unpublished/private/removed records must stop being served.
                return key, None
            source_time = datetime.fromtimestamp(row["time_updated"], timezone.utc)
            if _iso(source_time) == previous["source_updated_at"]:
                refreshed = {**previous, "fetched_at": fetched_at}
                refreshed.pop("source_error", None)
                return key, refreshed
            content = _request(_cdn_url(row.get("file_url")))
            return key, parse_guide(row, content, snapshot["heroes"], snapshot["items"], snapshot["authors"], fetched_at)
        with ThreadPoolExecutor(max_workers=3) as pool:
            for row, future in [(row, pool.submit(update, row)) for row in metadata]:
                try:
                    key, result = future.result()
                    if result is None:
                        old.pop(key, None)
                        withdrawn.add(key)
                    else: old[key] = result
                except (WorkshopError, ValueError, KeyError, TypeError, OverflowError) as error:
                    code = error.code if isinstance(error, WorkshopError) else "invalid_source"
                    errors.append(code)
                    key = str(row.get("publishedfileid", ""))
                    if key in old: old[key]["source_error"] = code
                    if code == "access_denied": blocked = True
        if blocked: break
    snapshot["guides"] = list(old.values())
    snapshot["withdrawn_ids"] = sorted(withdrawn)
    snapshot["checked_at"] = fetched_at
    snapshot["errors"] = sorted(set(errors))
    return snapshot, blocked


def public_payload(snapshot, updates, now=None):
    now = now or _now()
    feed_checked = _date(updates.get("checked_at")) if isinstance(updates, dict) else None
    latest = updates.get("latest_patch") if isinstance(updates, dict) else None
    patch = latest.get("version") if isinstance(latest, dict) else None
    feed_fresh = bool(feed_checked and -timedelta(minutes=5) <= now - feed_checked < timedelta(minutes=30)
                      and updates.get("stale") is False and updates.get("errors") == [])
    guides = []
    for stored in snapshot.get("guides", []):
        guide = deepcopy(stored)
        guide.pop("creator_id", None)
        fetched, updated = _date(guide.get("fetched_at")), _date(guide.get("source_updated_at"))
        source_error = guide.pop("source_error", None)
        if source_error or not fetched or now - fetched >= timedelta(seconds=REFRESH_SECONDS): status = "stale"
        elif not feed_fresh or not re.fullmatch(r"\d{1,2}\.\d{1,3}[a-z]?", str(patch)): status = "unknown"
        elif guide.get("source_patch") != patch: status = "patch_changed"
        elif not updated or now - updated > timedelta(days=SOURCE_REVIEW_DAYS): status = "review_due"
        else: status = "current_patch"
        guide["status"] = status
        guides.append(guide)
    return {"schema_version": SCHEMA, "checked_at": snapshot.get("checked_at"),
            "stale": bool(snapshot.get("errors")) or any(g["status"] == "stale" for g in guides),
            "latest_patch": patch if feed_fresh else None, "refresh_interval_seconds": REFRESH_SECONDS,
            "source_review_days": SOURCE_REVIEW_DAYS,
            "coverage": {"heroes": len({g["hero_slug"] for g in guides}), "total_heroes": len(snapshot.get("heroes", {})),
                         "guides": len(guides), "current_patch_guides": sum(g["status"] == "current_patch" for g in guides)},
            "guides": guides, "errors": snapshot.get("errors", [])}


class WorkshopCache:
    def __init__(self, path=None):
        self.path = path or Path(os.environ.get("VIDEO_STORAGE_PATH", "/var/lib/narma/video")) / "public/workshop-builds.json"
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self.blocked = False
        self.snapshot = json.loads(SEED_PATH.read_text(encoding="utf-8")) if SEED_PATH.exists() else {"schema_version": SCHEMA, "guides": [], "heroes": {}, "items": {}, "authors": {}}
        try:
            cached = json.loads(self.path.read_text(encoding="utf-8"))
            # A deployment's reviewed catalog remains the allowlist. Cache data
            # may update those IDs, never add arbitrary guide URLs or creators.
            allowed = {g["workshop_id"] for g in self.snapshot["guides"]}
            if cached.get("schema_version") == SCHEMA and cached.get("authors") == self.snapshot.get("authors"):
                withdrawn = set(cached.get("withdrawn_ids", [])) & allowed
                self.snapshot["withdrawn_ids"] = sorted(withdrawn)
                self.snapshot["guides"] = [g for g in self.snapshot["guides"] if g["workshop_id"] not in withdrawn]
                newer = {g["workshop_id"]: g for g in cached.get("guides", []) if g.get("workshop_id") in allowed}
                for index, row in enumerate(self.snapshot["guides"]):
                    other = newer.get(row["workshop_id"])
                    if other and (_date(other.get("fetched_at")) or datetime.min.replace(tzinfo=timezone.utc)) > (_date(row.get("fetched_at")) or datetime.min.replace(tzinfo=timezone.utc)):
                        self.snapshot["guides"][index] = other
                cached_checked, seed_checked = _date(cached.get("checked_at")), _date(self.snapshot.get("checked_at"))
                if cached_checked and (not seed_checked or cached_checked > seed_checked):
                    self.snapshot["checked_at"] = cached["checked_at"]
                    self.snapshot["errors"] = cached.get("errors", [])
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def start(self):
        if (os.environ.get("NARMA_WORKSHOP_REFRESH_ENABLED", "1") != "1"
                or os.environ.get("NARMA_EXPLORE_REFRESH_ENABLED", "1") != "1"):
            return
        with self.lock:
            if self.thread is not None or not self.snapshot["guides"]: return
            self.stop_event.clear()
            self.thread = threading.Thread(target=self._loop, daemon=True, name="narma-workshop-guides")
            self.thread.start()

    def _loop(self):
        while not self.stop_event.is_set() and not self.blocked:
            with self.lock:
                snapshot = deepcopy(self.snapshot)
            checked = _date(snapshot.get("checked_at"))
            due = not checked or (_now() - checked).total_seconds() >= REFRESH_SECONDS
            if due:
                try:
                    refreshed, self.blocked = refresh_snapshot(snapshot)
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = self.path.with_suffix(".tmp")
                    temporary.write_text(json.dumps(refreshed, ensure_ascii=False), encoding="utf-8")
                    temporary.replace(self.path)
                    with self.lock: self.snapshot = refreshed
                except (OSError, WorkshopError, ValueError, TypeError, KeyError):
                    with self.lock: self.snapshot["errors"] = ["source_unavailable"]
                    self.stop_event.wait(6 * 3600)
            self.stop_event.wait(60)

    def get(self, updates):
        with self.lock: snapshot = deepcopy(self.snapshot)
        return public_payload(snapshot, updates)

    def stop(self):
        self.stop_event.set()
        thread = self.thread
        if thread is not None:
            thread.join(timeout=1)
        with self.lock:
            if thread is None or not thread.is_alive():
                self.thread = None


cache = WorkshopCache()


def get_payload(updates):
    return cache.get(updates)


def check_source():
    """Two public, credential-free requests through the production transport."""
    snapshot = cache.snapshot
    candidates = snapshot.get("guides", [])
    if not candidates: raise WorkshopError()
    selected = max(candidates, key=lambda g: g.get("source_updated_at", ""))
    rows = fetch_metadata([selected["workshop_id"]])
    if len(rows) != 1 or str(rows[0].get("publishedfileid")) != selected["workshop_id"]:
        raise WorkshopError()
    row = rows[0]
    if (row.get("visibility") != 0 or row.get("result") != 1 or row.get("banned")
            or str(row.get("creator")) not in snapshot["authors"] or row.get("consumer_app_id") != 570):
        raise WorkshopError()
    parsed = parse_guide(row, _request(_cdn_url(row.get("file_url"))), snapshot["heroes"], snapshot["items"], snapshot["authors"])
    return {"status": "ok", "workshop_id": parsed["workshop_id"], "patch": parsed["source_patch"],
            "item_count": sum(len(parsed[key]) for key in GROUP_KEYS), "final_slots": len(parsed["final_items"])}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Validate the public Steam guide source without credentials.")
    parser.add_argument("--check-source", action="store_true")
    args = parser.parse_args()
    if args.check_source:
        try:
            print(json.dumps(check_source(), sort_keys=True))
        except (WorkshopError, ValueError, KeyError, TypeError) as error:
            print(json.dumps({"status": "error", "code": error.code if isinstance(error, WorkshopError) else "invalid_source"}))
            raise SystemExit(1) from None
