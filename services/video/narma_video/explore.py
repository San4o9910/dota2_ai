"""Public Dota discovery. Official, bounded feeds; no account or model access.

The checked-in snapshot is the first response. Expired data refreshes in one
background thread per process; a feed failure cannot erase the last good data.
Valve's datafeed is public but undocumented, so all parsed fields are validated.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import json
import os
from pathlib import Path
import re
import threading
import time
import xml.etree.ElementTree as ET

import httpx
from fastapi import APIRouter, HTTPException, Query, Response

from .curriculum import get_catalog


SCHEMA = "narma.explore.v1"
HEROES_URL = "https://www.dota2.com/datafeed/herolist?language=russian"
NEWS_URL = "https://store.steampowered.com/feeds/news/app/570/?l=russian"
PATCHES_URL = "https://www.dota2.com/datafeed/patchnoteslist?language=russian"
SOURCE_URLS = frozenset((HEROES_URL, NEWS_URL, PATCHES_URL))
HERO_IMAGE_BASE = "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/"
NEWS_IMAGE_HOST = "clan.fastly.steamstatic.com"
MAX_BYTES = 512 * 1024
REFRESH_SECONDS = 15 * 60
RETRY_SECONDS = 5 * 60
FETCH_DEADLINE_SECONDS = 12
SNAPSHOT_PATH = Path(__file__).with_name("data") / "explore_snapshot.json"
ATTRIBUTES = ("strength", "agility", "intelligence", "universal")


class SourceError(ValueError):
    """Only a fixed, non-sensitive code is exposed to the public client."""

    def __init__(self, code="invalid_source", retry_after=None):
        super().__init__(code)
        self.code = code if code in {"invalid_source", "source_unavailable", "source_too_large", "source_timeout"} else "invalid_source"
        self.retry_after = retry_after


def _now():
    return datetime.now(timezone.utc)


def _iso(value):
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _text(value, maximum=200):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum:
        raise SourceError()
    if re.search(r"[<>\x00-\x1f\x7f]|\[(?:/?(?:url|img|b|i|h[1-6])(?:=|\]))", value, re.I):
        raise SourceError()
    return value.strip()


def _date(value):
    try:
        if type(value) is int:
            date = datetime.fromtimestamp(value, timezone.utc)
        elif isinstance(value, str):
            date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            raise ValueError()
        if date.tzinfo is None or not datetime(2010, 1, 1, tzinfo=timezone.utc) <= date <= _now() + timedelta(minutes=5):
            raise ValueError()
        return _iso(date)
    except (ValueError, TypeError, OverflowError, OSError):
        raise SourceError() from None


def fetch_bytes(url):
    """No user URLs, credentials, ambient proxy, redirects, or HTML responses."""
    if url not in SOURCE_URLS:
        raise SourceError()
    started = time.monotonic()
    try:
        with httpx.Client(timeout=httpx.Timeout(3.0), follow_redirects=False, trust_env=False) as client:
            with client.stream("GET", url, headers={"User-Agent": "NarmaVision-PublicFeeds/1.0", "Accept": "application/json, application/rss+xml, text/xml", "Accept-Encoding": "identity"}) as response:
                if response.status_code != 200:
                    retry_after = 3600 if response.status_code == 429 else RETRY_SECONDS
                    raw_retry = response.headers.get("retry-after", "")
                    try:
                        if re.fullmatch(r"[0-9]{1,9}", raw_retry):
                            retry_after = max(retry_after, int(raw_retry))
                        elif raw_retry:
                            retry_after = max(retry_after, (parsedate_to_datetime(raw_retry) - _now()).total_seconds())
                    except (ValueError, TypeError, OverflowError):
                        pass
                    raise SourceError("source_unavailable", retry_after=retry_after)
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise SourceError()
                content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                expected = {"text/xml", "application/rss+xml", "application/xml"} if url == NEWS_URL else {"application/json"}
                if content_type not in expected:
                    raise SourceError()
                declared = response.headers.get("content-length")
                if declared and (not declared.isdigit() or int(declared) > MAX_BYTES):
                    raise SourceError("source_too_large")
                body = bytearray()
                for chunk in response.iter_bytes(16 * 1024):
                    if time.monotonic() - started > FETCH_DEADLINE_SECONDS:
                        raise SourceError("source_timeout")
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        raise SourceError("source_too_large")
                return bytes(body)
    except httpx.TimeoutException:
        raise SourceError("source_timeout") from None
    except httpx.HTTPError:
        raise SourceError("source_unavailable") from None


def parse_heroes(payload):
    try:
        result = payload["result"]
        rows = result["data"]["heroes"]
        if (("status" in result and (type(result["status"]) is not int or result["status"] != 1))
                or not isinstance(rows, list) or not 100 <= len(rows) <= 300):
            raise SourceError()
        heroes, seen_ids, seen_names = [], set(), set()
        for row in rows:
            ident, name = row["id"], row["name"]
            attr, complexity = row["primary_attr"], row["complexity"]
            if (type(ident) is not int or not 1 <= ident <= 10000 or ident in seen_ids
                    or not isinstance(name, str) or not re.fullmatch(r"npc_dota_hero_[a-z0-9_]{1,64}", name) or name in seen_names
                    or type(attr) is not int or attr not in range(4)
                    or type(complexity) is not int or complexity not in (1, 2, 3)):
                raise SourceError()
            slug = name.removeprefix("npc_dota_hero_")
            # The official website route uses the localized English display name,
            # whereas the image filename uses Valve's canonical internal name.
            display_name = _text(row["name_loc"], 80)
            english_name = _text(row.get("name_english_loc", display_name), 80)
            page_slug = re.sub(r"[^a-z0-9]", "", english_name.lower())
            if not page_slug:
                raise SourceError()
            heroes.append({"id": ident, "name": name, "slug": slug,
                "display_name": display_name, "attribute": ATTRIBUTES[attr], "complexity": complexity,
                "image_url": HERO_IMAGE_BASE + slug + ".png",
                "official_url": "https://www.dota2.com/hero/" + page_slug})
            seen_ids.add(ident)
            seen_names.add(name)
        return sorted(heroes, key=lambda row: row["display_name"].casefold())
    except (KeyError, TypeError, AttributeError):
        raise SourceError() from None


def _news_link(value):
    value = _text(value, 240)
    if not re.fullmatch(r"https://store\.steampowered\.com/news/app/570/view/[0-9]{1,24}", value):
        raise SourceError()
    return value


def _news_image(value):
    if not isinstance(value, str) or len(value) > 400:
        return None
    if re.fullmatch(r"https://clan\.fastly\.steamstatic\.com/images/3703047/[a-fA-F0-9]{40}(?:/[a-z]+)?\.(?:png|jpg|jpeg|webp)", value):
        return value
    return None


def parse_updates(xml):
    if not isinstance(xml, bytes) or len(xml) > MAX_BYTES:
        raise SourceError()
    try:
        text = xml.decode("utf-8")
        if "\x00" in text or "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
            raise SourceError()
        root = ET.fromstring(text)
        rows = root.findall("./channel/item")
        if root.tag != "rss" or not 1 <= len(rows) <= 60:
            raise SourceError()
        result, seen = [], set()
        for row in rows:
            title = _text(row.findtext("title"), 240)
            url = _news_link(row.findtext("link"))
            if url in seen:
                continue
            published = parsedate_to_datetime(row.findtext("pubDate"))
            date = _date(published.isoformat())
            enclosure = row.find("enclosure")
            image_url = _news_image(enclosure.get("url")) if enclosure is not None else None
            if re.search(r"\b7\.\d+|обновлен|patch|update|чистк", title, re.I):
                category = "patch"
            elif re.search(r"international|карнавал|carnival|фэнтези|событи|турнир", title, re.I):
                category = "event"
            else:
                category = "news"
            result.append({"id": url, "title": title, "url": url, "published_at": date,
                           "image_url": image_url, "category": category})
            seen.add(url)
        return sorted(result, key=lambda row: row["published_at"], reverse=True)[:12]
    except (ET.ParseError, ValueError, TypeError, AttributeError, UnicodeError):
        raise SourceError() from None


def parse_patch(payload):
    try:
        rows = payload["patches"]
        if payload.get("success") is not True or not isinstance(rows, list) or not 1 <= len(rows) <= 500:
            raise SourceError()
        parsed, seen = [], set()
        for row in rows:
            version = row["patch_number"]
            if not isinstance(version, str) or not re.fullmatch(r"[0-9]{1,2}\.[0-9]{1,3}[a-z]?", version):
                raise SourceError()
            if version in seen:
                raise SourceError()
            date = _date(row["patch_timestamp"])
            parsed.append({"version": version, "published_at": date, "url": "https://www.dota2.com/patches/" + version})
            seen.add(version)
        def newest(row):
            major, minor, letter = re.fullmatch(r"([0-9]+)\.([0-9]+)([a-z]?)", row["version"]).groups()
            return row["published_at"], int(major), int(minor), letter
        return max(parsed, key=newest)
    except (KeyError, TypeError, AttributeError):
        raise SourceError() from None


def build_snapshot():
    """Explicit maintenance helper; never invoked at import or in a request."""
    heroes = parse_heroes(json.loads(fetch_bytes(HEROES_URL)))
    news = parse_updates(fetch_bytes(NEWS_URL))
    patch = parse_patch(json.loads(fetch_bytes(PATCHES_URL)))
    checked = _iso(_now())
    return {"schema_version": SCHEMA,
        "heroes": {"checked_at": checked, "source_url": HEROES_URL, "source_published_at": None, "heroes": heroes},
        "updates": {"checked_at": checked, "source_url": NEWS_URL, "patch_source_url": PATCHES_URL,
                    "source_published_at": news[0]["published_at"], "news": news, "latest_patch": patch}}


class PublicCache:
    def __init__(self, snapshot):
        if snapshot.get("schema_version") != SCHEMA:
            raise ValueError("Invalid explore snapshot version")
        self._data = deepcopy({kind: snapshot[kind] for kind in ("heroes", "updates")})
        for section in self._data.values():
            _date(section["checked_at"])
        self._errors = {"heroes": [], "updates": []}
        self._lock = threading.Lock()
        self._running = False
        self._last_attempt = None
        self._retry_after = RETRY_SECONDS

    def get(self, kind):
        if kind not in {"heroes", "updates"}:
            raise ValueError("Unknown public section")
        with self._lock:
            checked = datetime.fromisoformat(self._data[kind]["checked_at"].replace("Z", "+00:00"))
            stale = (_now() - checked).total_seconds() >= REFRESH_SECONDS
            retry_due = self._last_attempt is None or time.monotonic() - self._last_attempt >= self._retry_after
            if stale and retry_due and not self._running and os.environ.get("NARMA_EXPLORE_REFRESH_ENABLED", "1") == "1":
                self._running = True
                self._last_attempt = time.monotonic()
                self._retry_after = RETRY_SECONDS
                thread = threading.Thread(target=self._refresh, name="narma-public-feeds", daemon=True)
                try:
                    thread.start()
                except RuntimeError:
                    self._running = False
                    self._errors[kind] = ["source_unavailable"]
            return {"schema_version": SCHEMA, **deepcopy(self._data[kind]),
                    "stale": stale, "refreshing": self._running, "errors": list(self._errors[kind])}

    def _refresh(self):
        try:
            for kind in ("heroes", "updates"):
                try:
                    if kind == "heroes":
                        data = {"heroes": parse_heroes(json.loads(fetch_bytes(HEROES_URL)))}
                    else:
                        news = parse_updates(fetch_bytes(NEWS_URL))
                        data = {"news": news, "latest_patch": parse_patch(json.loads(fetch_bytes(PATCHES_URL))),
                                "source_published_at": news[0]["published_at"]}
                    with self._lock:
                        self._data[kind].update(data, checked_at=_iso(_now()))
                        self._errors[kind] = []
                except Exception as exc:
                    # Never return URLs from exceptions, raw XML, or a traceback.
                    with self._lock:
                        self._errors[kind] = [exc.code if isinstance(exc, SourceError) else "invalid_source"]
                        if isinstance(exc, SourceError) and exc.retry_after is not None:
                            self._retry_after = max(self._retry_after, exc.retry_after)
        finally:
            with self._lock:
                self._running = False


_cache = PublicCache(json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))) if SNAPSHOT_PATH.is_file() else None


def get_payload(kind):
    if _cache is None:
        raise HTTPException(503, "Официальные данные пока недоступны.")
    return _cache.get(kind)


router = APIRouter(prefix="/api/explore")


@router.get("/build-reviews")
def build_reviews(response: Response):
    from .build_reviews import review_payload
    response.headers["Cache-Control"] = "public, max-age=30"
    return review_payload(get_payload("updates"))


@router.get("/heroes")
def heroes(response: Response):
    response.headers["Cache-Control"] = "public, max-age=60"
    return get_payload("heroes")


@router.get("/updates")
def updates(response: Response):
    response.headers["Cache-Control"] = "public, max-age=60"
    return get_payload("updates")


@router.get("/learning")
def learning(response: Response, position: str | None = Query(default=None)):
    if position is not None and not re.fullmatch(r"[1-5]", position):
        raise HTTPException(422, "Выбери позицию от 1 до 5.")
    response.headers["Cache-Control"] = "public, max-age=300"
    return get_catalog(int(position) if position is not None else None)
