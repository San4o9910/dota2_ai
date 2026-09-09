"""Import only public guide item facts; no secrets, accounts, or guide prose.

Run explicitly in trusted CI. Published-ID candidates from old public lists are
validated through Steam's ordinary API before any guide file is downloaded.
No private author profile is enumerated. Runtime refresh uses only seed IDs.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import sys
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/video"))
from narma_video import workshop_builds as w

ITEMS_URL = "https://www.dota2.com/datafeed/itemlist?language=english"
HEROES_URL = "https://www.dota2.com/datafeed/herolist?language=english"
PATCHES_URL = "https://www.dota2.com/datafeed/patchnoteslist?language=english"
PUBLIC_COLLECTION = "https://steamcommunity.com/id/ImmortalFaith/myworkshopfiles/?section=guides&numperpage=30&p="
PUBLIC_SEARCH = "https://steamcommunity.com/app/570/guides/?searchText=Torte+de+Lini&browsefilter=trend&filetype=12&requiredtags%5B%5D=Largo&numperpage=30"
AUTHORS = {"76561198064078512": "ImmortalFaith", "76561197997348592": "Torte de Lini"}
CATALOG = ROOT / "services/video/narma_video/data/workshop_builds.json"
CANDIDATES = ROOT / "services/video/narma_video/data/workshop-guide-ids.json"


def read_fixed_url(url):
    allowed = {ITEMS_URL, HEROES_URL, PATCHES_URL, PUBLIC_SEARCH} | {PUBLIC_COLLECTION + str(page) for page in range(1, 9)}
    if url not in allowed:
        raise w.WorkshopError()
    started = time.monotonic()
    with httpx.Client(timeout=httpx.Timeout(12, connect=4), follow_redirects=False, trust_env=False) as client:
        with client.stream("GET", url, headers={"User-Agent": "NarmaVision-PublicGuides/1.0", "Accept-Encoding": "identity"}) as response:
            if response.status_code in (401, 403): raise w.WorkshopError("access_denied")
            if response.status_code != 200: raise w.WorkshopError("source_unavailable")
            content = bytearray()
            for chunk in response.iter_bytes():
                if time.monotonic() - started > 18: raise w.WorkshopError("source_unavailable")
                content.extend(chunk)
                if len(content) > w.MAX_BYTES: raise w.WorkshopError("source_too_large")
            return bytes(content)


def discover_public_ids():
    candidates = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    ids = set(candidates["ids"])
    for page in range(1, 9):
        html = read_fixed_url(PUBLIC_COLLECTION + str(page)).decode("utf-8")
        # This is an ordinary, previously verified public collection. An empty
        # or private listing ends discovery; do not change routes to bypass it.
        found = set(re.findall(r'sharedfiles/filedetails/\?id=([0-9]{1,20})', html))
        if not found:
            break
        ids.update(found)
        print(json.dumps({"event": "public_collection_page", "page": page, "ids": len(found)}), flush=True)
        if len(found) < 30:
            break
    # The new Largo guide did not exist in the old public ID lists. Search
    # Valve's ordinary global public Hero Build index, never a private profile.
    html = read_fixed_url(PUBLIC_SEARCH).decode("utf-8")
    found = set(re.findall(r'sharedfiles/filedetails/\?id=([0-9]{1,20})', html))
    ids.update(found)
    print(json.dumps({"event": "global_public_hero_search", "hero": "largo", "candidate_ids": len(found)}), flush=True)
    if not 1 <= len(ids) <= 450:
        raise w.WorkshopError()
    return sorted(ids)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--emit-json", action="store_true")
    args = parser.parse_args()
    started = time.monotonic()
    item_rows = json.loads(read_fixed_url(ITEMS_URL))["result"]["data"]["itemabilities"]
    items = {}
    for row in item_rows:
        name = row.get("name_english_loc")
        # Valve also returns hidden/deprecated/internal entries without a
        # localized player-facing name. They are not valid inventory choices.
        if (row.get("neutral_item_tier") != -1
                or not re.fullmatch(r"item_[a-z0-9_]{1,80}", row.get("name", ""))
                or not isinstance(name, str) or not 0 < len(name.strip()) <= 180
                or re.search(r"[<>\x00-\x1f\x7f]", name)):
            continue
        items[row["name"].removeprefix("item_")] = name.strip()
    if len(items) < 100:
        raise w.WorkshopError()
    print(json.dumps({"event": "item_catalog_validated", "items": len(items), "source_rows": len(item_rows)}), flush=True)
    hero_rows = json.loads(read_fixed_url(HEROES_URL))["result"]["data"]["heroes"]
    print(json.dumps({"event": "hero_catalog_received", "rows": len(hero_rows)}), flush=True)
    heroes = {row["name"].removeprefix("npc_dota_hero_"): w._safe_text(row["name_english_loc"])
              for row in hero_rows if re.fullmatch(r"npc_dota_hero_[a-z0-9_]{1,80}", row.get("name", ""))}
    patches = json.loads(read_fixed_url(PATCHES_URL))["patches"]
    latest = max(patches, key=lambda row: row["patch_timestamp"])["patch_number"]
    ids = discover_public_ids()
    metadata, ignored = [], []
    for offset in range(0, len(ids), 30):
        if time.monotonic() - started > 1000: raise w.WorkshopError("source_unavailable")
        batch = ids[offset:offset + 30]
        rows = w.fetch_metadata(batch)
        returned = {str(row.get("publishedfileid")) for row in rows if isinstance(row, dict)}
        if returned != set(batch): raise w.WorkshopError()
        for row in rows:
            key = str(row.get("publishedfileid"))
            if (row.get("result") != 1 or row.get("visibility") != 0 or row.get("banned")
                    or row.get("consumer_app_id") != 570 or str(row.get("creator")) not in AUTHORS):
                ignored.append({"id": key, "reason": "not_public_approved_guide"})
                continue
            # Metadata's description and user fields are deliberately discarded.
            fields = {"publishedfileid", "creator", "result", "consumer_app_id", "visibility", "banned", "time_updated", "file_url"}
            metadata.append({key: value for key, value in row.items() if key in fields})
        print(json.dumps({"event": "metadata_checked", "candidates": min(offset + 30, len(ids)), "approved": len(metadata)}), flush=True)
    checked = w._iso(w._now())
    guides, failures = [], []
    def download(row):
        if time.monotonic() - started > 1000: raise w.WorkshopError("source_unavailable")
        return w.parse_guide(row, w._request(w._cdn_url(row.get("file_url"))), heroes, items, AUTHORS, checked)
    # Small batches ensure an access denial stops subsequent requests. There
    # are at most three already-in-flight public reads when an error arrives.
    for offset in range(0, len(metadata), 3):
        with ThreadPoolExecutor(max_workers=3) as pool:
            pending = [(row, pool.submit(download, row)) for row in metadata[offset:offset + 3]]
            for row, future in pending:
                try:
                    guides.append(future.result())
                except w.WorkshopError as error:
                    if error.code == "access_denied": raise
                    failures.append({"id": row["publishedfileid"], "reason": error.code})
        if (offset + 3) % 30 == 0:
            print(json.dumps({"event": "guide_facts_read", "complete": len(guides), "failed": len(failures)}), flush=True)
    if not guides: raise w.WorkshopError()
    guides.sort(key=lambda row: (row["hero_slug"], row["author"], row["position"] or 0, row["id"]))
    snapshot = {"schema_version": w.SCHEMA, "checked_at": checked, "authors": AUTHORS,
                "heroes": heroes, "items": items, "guides": guides, "errors": [], "withdrawn_ids": [],
                "import_receipt": {"latest_patch": latest, "candidate_ids": len(ids), "ignored": ignored, "failures": failures,
                                   "source_urls": [ITEMS_URL, HEROES_URL, PATCHES_URL, PUBLIC_COLLECTION + "1"]}}
    content = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
    CATALOG.write_text(content + "\n", encoding="utf-8")
    covered = {row["hero_slug"] for row in guides}
    report = {"event": "workshop_coverage", "guides": len(guides), "heroes": len(covered),
              "total_heroes": len(heroes), "missing": sorted(set(heroes) - covered),
              "latest_patch": latest, "matching_patch_guides": sum(row["source_patch"] == latest for row in guides),
              "failures": failures, "sha256": hashlib.sha256(content.encode()).hexdigest()}
    print(json.dumps(report, ensure_ascii=False), flush=True)
    if args.emit_json:
        pieces = [content[index:index + 16000] for index in range(0, len(content), 16000)]
        for index, piece in enumerate(pieces):
            print("NARMA_WORKSHOP_SEED:" + json.dumps({"index": index, "total": len(pieces), "content": piece}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (w.WorkshopError, httpx.HTTPError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"event": "workshop_import_failed", "code": error.code if isinstance(error, w.WorkshopError) else "invalid_source"}), flush=True)
        raise SystemExit(1) from None
