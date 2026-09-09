"""STRATZ purchase evidence and constrained six-slot suggestions.

Item outcomes are never represented as a joint build win rate. One bounded
background worker refreshes public cohorts; clients cannot issue provider queries.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import threading
import time

import httpx
from fastapi import APIRouter, HTTPException, Query, Response

ENDPOINT = "https://api.stratz.com/graphql"
HOUR = 3600
WEEK = 604800
MAX_BYTES = 2 * 1024 * 1024
SAFE_ERRORS = {"source_unavailable","rate_limited","configuration","response_limit","invalid_source",
               "cohort_mismatch","duplicate_bucket","mixed_weeks","empty_source",
               "authentication_failed","access_denied","source_timeout","connection_error","network_error"}
META_QUERY = """query NarmaBuildCatalog {
  constants { gameVersions { id name asOfDateTime }
    items(language:ENGLISH) { id name displayName shortName
      stat { cost isRecipe isPurchasable } components { componentId } }
  }
}"""
PURCHASE_QUERY = """query NarmaBuildPurchases($hero:Short!,$position:[MatchPlayerPositionType],$rank:[RankBracketBasicEnum]) {
  heroStats { itemFullPurchase(heroId:$hero,positionIds:$position,bracketBasicIds:$rank,
    minTime:0,maxTime:75,matchLimit:1) {
      heroId week position bracketBasicIds itemId instance time matchCount winCount
    }
  }
}"""


from .build_statistics import (SourceError, GUIDES, HERO_IDS, RANKS, catalog, purchases, suggestions)


def graphql(token, query, operation, variables=None):
    if not re.fullmatch(r"[A-Za-z0-9._~+/-]+={0,2}", token or "") or len(token) > 8192:
        raise SourceError("configuration")
    try:
        with httpx.Client(timeout=12, follow_redirects=False, trust_env=False) as client:
            with client.stream("POST", ENDPOINT,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json",
                             # Required API-client identification: https://stratz.com/api
                             "User-Agent": "STRATZ_API"},
                    json={"query": query, "operationName": operation, "variables": variables or {}}) as response:
                if response.status_code != 200:
                    raise SourceError({401:"authentication_failed",403:"access_denied",429:"rate_limited"}.get(response.status_code,"source_unavailable"))
                body = bytearray()
                deadline = time.monotonic() + 15
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_BYTES or time.monotonic() > deadline:
                        raise SourceError("response_limit")
        data = json.loads(body)
        if not isinstance(data, dict) or data.get("errors") or not isinstance(data.get("data"), dict):
            raise SourceError("invalid_source")
        return data["data"]
    except SourceError:
        raise
    except httpx.TimeoutException:
        raise SourceError("source_timeout") from None
    except httpx.ConnectError:
        raise SourceError("connection_error") from None
    except httpx.RequestError:
        raise SourceError("network_error") from None
    except Exception:
        raise SourceError("source_unavailable") from None


class BuildCache:
    def __init__(self, path=None, fetch=graphql, now=time.time):
        self.path, self.fetch, self.now = path, fetch, now
        self.lock, self.stop_event = threading.Lock(), threading.Event()
        self.thread = None
        self.blocked = False
        self.data, self.due, self.errors = {}, {}, set()
        self.items, self.source_patch, self.metadata_at = {}, None, 0
        self.requested = {(g, "HERALD_GUARDIAN") for g in GUIDES}
        if path and path.is_file():
            try:
                if path.stat().st_size <= 4*MAX_BYTES:
                    saved = json.loads(path.read_text())
                    if saved.get("schema") == 1:
                        for row in saved.get("rows", []):
                            key = (row["guide"], row["rank"])
                            if key[0] in GUIDES and key[1] in RANKS and isinstance(row.get("items"), dict):
                                self.data[key] = row
                                self.due[key] = min(row["checked_at"] + HOUR, self.now())
            except (OSError, ValueError, KeyError, TypeError):
                self.data = {}

    def start(self):
        if not os.environ.get("STRATZ_API_TOKEN") or os.environ.get("NARMA_STRATZ_REFRESH_ENABLED", "1") != "1":
            return
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.blocked = False
        self.thread = threading.Thread(target=self.run, name="narma-build-statistics", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def refresh(self, key):
        token = os.environ.get("STRATZ_API_TOKEN", "")
        if self.now() - self.metadata_at >= HOUR:
            self.items, self.source_patch = catalog(self.fetch(token, META_QUERY, "NarmaBuildCatalog"))
            self.metadata_at = self.now()
        guide_id, rank = key
        guide = GUIDES[guide_id]
        hero = HERO_IDS[guide["hero_slug"]]
        data = self.fetch(token, PURCHASE_QUERY, "NarmaBuildPurchases",
            {"hero":hero, "position":[f"POSITION_{guide['position']}"], "rank":[rank]})
        evidence, week = purchases(data["heroStats"]["itemFullPurchase"] or [], self.items, hero, guide["position"], rank)
        result = {"guide":guide_id, "rank":rank, "checked_at":self.now(), "week":week,
                  "source_patch":self.source_patch, "items":evidence,
                  "plans":{mode:suggestions(guide, evidence, self.items, mode) for mode in ("popular", "winrate")}}
        with self.lock:
            self.data[key] = result
            self.errors.discard(key)
            self.due[key] = self.now() + HOUR
            if self.path:
                try:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = self.path.with_suffix(".tmp")
                    temporary.write_text(json.dumps({"schema":1, "rows":list(self.data.values())}, separators=(",", ":")))
                    temporary.replace(self.path)
                except OSError:
                    pass  # The validated in-memory snapshot remains available.

    def run(self):
        while not self.stop_event.is_set():
            with self.lock:
                pending = sorted((k for k in self.requested if self.due.get(k, 0) <= self.now()), key=lambda k:self.due.get(k, 0))
            if pending:
                key = pending[0]
                try:
                    self.refresh(key)
                except Exception as exc:
                    with self.lock:
                        self.errors.add(key)
                        self.due[key] = self.now() + 300
                    code = str(exc) if isinstance(exc, SourceError) and str(exc) in SAFE_ERRORS else "invalid_source"
                    print(json.dumps({"event":"build_statistics_refresh_failed","code":code}),flush=True)
                    if code in {"authentication_failed","access_denied","configuration"}:
                        self.blocked = True
                        break  # Stop access attempts until an explicit service restart/configuration change.
                    if self.stop_event.wait(300):
                        break  # One global backoff prevents a provider outage from multiplying requests.
            self.stop_event.wait(2 if pending else 30)

    def get(self, guide_id, rank):
        key = (guide_id, rank)
        with self.lock:
            self.requested.add(key)
            row = deepcopy(self.data.get(key))
            error = key in self.errors
            if row is None and not error:
                self.due[key] = min(self.due.get(key, 0), -1)
        configured = bool(os.environ.get("STRATZ_API_TOKEN"))
        base = {"schema_version":"narma.build-meta.v1", "source":"STRATZ",
                "source_url":"https://stratz.com/heroes/" + str(HERO_IDS[GUIDES[guide_id]["hero_slug"]]),
                "guide":guide_id, "rank":rank, "rank_label":RANKS[rank], "minimum_matches":{"popular":30,"winrate":100},
                "joint_build_winrate":None, "period":"current_source_week", "purchase_minutes":[0,75]}
        if not row:
            waiting=configured and not self.blocked and os.environ.get("NARMA_STRATZ_REFRESH_ENABLED","1")=="1"
            return {**base,"status":"loading" if waiting else "unavailable", "stale":True,"items":{},"plans":{}}
        age = self.now() - row["checked_at"]
        stale = self.blocked or error or not configured or age < 0 or age >= 2*HOUR or row["week"] != int(self.now() // WEEK)
        # A weekly aggregate can straddle a new patch. Wait for a full subsequent
        # week and a matching reviewed hero pool before generating suggestions.
        from .explore import get_payload
        patch_status = "unknown"
        try:
            feed = get_payload("updates")
            patch = feed["latest_patch"]
            published = datetime.fromisoformat(patch["published_at"].replace("Z", "+00:00")).timestamp()
            if feed.get("stale") is False and not feed.get("errors"):
                patch_status = "transition" if self.now()-published < WEEK else "pool_review" if patch["version"] != GUIDES[guide_id]["verified_patch"] else "after_patch_release"
        except Exception:
            pass
        return {**base, **row, "status":"stale" if stale else "ready", "stale":stale, "patch_status":patch_status,
                "checked_at":datetime.fromtimestamp(row["checked_at"],timezone.utc).isoformat(),
                "plans":{} if stale or patch_status != "after_patch_release" else row["plans"]}


cache = BuildCache(Path(os.environ.get("VIDEO_STORAGE_PATH", "/var/lib/narma/video")) / "public/build-statistics.json")
router = APIRouter(prefix="/api/explore")


@router.get("/builds")
def build_statistics(response:Response, guide:str=Query(max_length=90), rank:str="HERALD_GUARDIAN"):
    if guide not in GUIDES or rank not in RANKS:
        raise HTTPException(422, "Выбери существующее руководство и ранг.")
    response.headers["Cache-Control"] = "public, max-age=30"
    return cache.get(guide, rank)


if __name__ == "__main__":
    import sys
    if sys.argv[1:] != ["--check"]:
        raise SystemExit(2)
    try:
        probe = BuildCache()
        key = ("viper-mid-pressure", "HERALD_GUARDIAN")
        probe.refresh(key)
        row = probe.data[key]
        receipt = {"event":"stratz_adapter_verified", "guide":key[0], "rank":key[1],
            "item_count":len(row["items"]), "week":row["week"], "source_catalog_patch":row["source_patch"],
            "popular_slots":len(row["plans"]["popular"]), "winrate_slots":len(row["plans"]["winrate"]),
            "provider_requests":2, "ai_generation_requests":0, "joint_build_winrate":None}
        if not row["items"]:
            raise SourceError("empty_source")
    except Exception as exc:
        code = str(exc) if isinstance(exc,SourceError) and str(exc) in SAFE_ERRORS else "invalid_source"
        print(json.dumps({"event":"stratz_adapter_check_failed","code":code,
                          "validated_context":getattr(exc,"context",None) if code=="cohort_mismatch" else None}))
        raise SystemExit(1) from None
    print(json.dumps(receipt))
