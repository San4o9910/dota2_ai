from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from narma_video import workshop_builds as w


NOW = datetime(2026, 9, 9, 12, tzinfo=timezone.utc)
AUTHORS = {"123": "Test author"}
HEROES = {"viper": "Viper"}
ITEMS = {key: key.title() for key in ("tango", "branches", "boots", "arcane_boots", "guardian_greaves", "power_treads", "force_staff", "dragon_lance", "hurricane_pike", "black_king_bar", "aghanims_shard", "manta", "skadi")}
BUILD = b'''"guidedata" {
 "Hero" "viper" "Title" "Example Position 2" "GameplayVersion" "7.41e"
 "Role" "#DOTA_HeroGuide_Role_Core" "Overview" "Private prose must not be retained."
 "ItemBuild" {
  "Items" {
   "#DOTA_Item_Build_Starting_Items" { "item" "item_tango" "item" "item_branches" "item" "item_branches" }
   "#DOTA_Item_Build_Early_Game" { "item" "item_boots" "item" "item_power_treads" }
   "#DOTA_Item_Build_Core_Items" { "item" "item_dragon_lance" "item" "item_hurricane_pike" "item" "item_black_king_bar" "item" "item_aghanims_shard" }
   "Extension Items" { "item" "item_manta" "item" "item_skadi" }
   "#DOTA_Item_Build_Situational_Items" { "item" "item_force_staff" }
   "VISIT EXAMPLE SPONSOR" { "item" "item_skadi" }
  }
  "ItemTooltips" { "item_tango" "Protected prose, not part of the extracted facts." }
 }
}'''


def metadata():
    return {"publishedfileid": "12345", "creator": "123", "result": 1, "consumer_app_id": 570,
            "visibility": 0, "banned": False, "time_updated": int((NOW - timedelta(days=1)).timestamp()),
            "file_url": "https://cdn.steamusercontent.com/ugc/123/ABCDEF/"}


def guide():
    return w.parse_guide(metadata(), BUILD, HEROES, ITEMS, AUTHORS, w._iso(NOW))


def snapshot():
    return {"schema_version": w.SCHEMA, "checked_at": w._iso(NOW), "authors": AUTHORS,
            "heroes": HEROES, "items": ITEMS, "guides": [guide()], "errors": []}


def feed():
    return {"checked_at": w._iso(NOW), "stale": False, "errors": [],
            "latest_patch": {"version": "7.41e", "published_at": "2026-07-30T00:00:00Z"}}


class WorkshopBuildTests(unittest.TestCase):
    def test_extracts_only_attributed_facts_and_duplicates_in_purchase_stages(self):
        row = guide()
        self.assertEqual([x["id"] for x in row["starting_items"]], ["tango", "branches", "branches"])
        self.assertEqual(row["positions"], [2])
        self.assertTrue(row["position_exact"])
        self.assertEqual(row["source_patch"], "7.41e")
        self.assertEqual(row["author"], "Test author")
        serialized = json.dumps(row)
        self.assertNotIn("Protected prose", serialized)
        self.assertNotIn("Private prose", serialized)
        self.assertNotIn("SPONSOR", serialized)
        self.assertNotIn("winrate", serialized)

    def test_parser_supports_utf16_and_rejects_malformed_or_oversized_documents(self):
        self.assertEqual(w.parse_keyvalues(BUILD), w.parse_keyvalues(BUILD.decode().encode("utf-16")))
        self.assertEqual(w.parse_keyvalues(BUILD), w.parse_keyvalues(BUILD + b"\x00"))
        for content in (b'"guidedata" {', b'"guidedata" }', b'"guidedata" {} garbage', b'"other" {}'):
            with self.assertRaises(w.WorkshopError): w.parse_keyvalues(content)
        with self.assertRaises(w.WorkshopError): w.parse_keyvalues(b"x" * (w.MAX_BYTES + 1))

    def test_private_wrong_creator_wrong_game_and_future_metadata_are_rejected(self):
        for field, value in (("visibility", 1), ("creator", "999"), ("consumer_app_id", 730), ("banned", True), ("result", 9)):
            row = {**metadata(), field: value}
            with self.subTest(field=field), self.assertRaises(w.WorkshopError):
                w.parse_guide(row, BUILD, HEROES, ITEMS, AUTHORS)
        with patch.object(w, "_now", return_value=NOW), self.assertRaises(w.WorkshopError):
            w.parse_guide({**metadata(), "time_updated": int((NOW + timedelta(days=1)).timestamp())}, BUILD, HEROES, ITEMS, AUTHORS)

    def test_explicit_position_changes_role_but_unspecified_support_remains_unspecified(self):
        row = w.parse_guide(metadata(), BUILD.replace(b"Position 2", b"Position 5"), HEROES, ITEMS, AUTHORS)
        self.assertEqual((row["position"], row["role"], row["positions"]), (5, "support", [5]))
        unknown = BUILD.replace(b"Example Position 2", b"Example Support").replace(b"Role_Core", b"Role_Support")
        row = w.parse_guide(metadata(), unknown, HEROES, ITEMS, AUTHORS)
        self.assertIsNone(row["position"])
        self.assertEqual(row["positions"], [4, 5])
        self.assertFalse(row["position_exact"])

    def test_projection_never_invents_padding_or_keeps_known_components(self):
        row = guide()
        self.assertEqual([x["id"] for x in row["final_items"]], ["power_treads", "hurricane_pike", "black_king_bar", "manta", "skadi"])
        self.assertEqual(len(row["final_items"]), 5)
        self.assertIn("aghanims_shard", [x["id"] for x in row["core_items"]])
        groups = {key: [] for key in w.GROUP_KEYS}
        groups["early_items"] = [{"id": "arcane_boots", "name": "Arcane Boots"}]
        groups["core_items"] = [{"id": "guardian_greaves", "name": "Guardian Greaves"}]
        self.assertEqual([x["id"] for x in w.inventory_projection(groups)], ["guardian_greaves"])

    def test_public_payload_separates_author_review_from_network_refresh(self):
        data = snapshot()
        self.assertEqual(w.public_payload(data, feed(), NOW)["guides"][0]["status"], "current_patch")
        data["guides"][0]["source_updated_at"] = w._iso(NOW - timedelta(days=31))
        self.assertEqual(w.public_payload(data, feed(), NOW)["guides"][0]["status"], "review_due")
        data["guides"][0]["source_patch"] = "7.41d"
        self.assertEqual(w.public_payload(data, feed(), NOW)["guides"][0]["status"], "patch_changed")
        self.assertEqual(w.public_payload(data, {}, NOW)["guides"][0]["status"], "unknown")
        data["guides"][0]["fetched_at"] = w._iso(NOW - timedelta(days=2))
        public = w.public_payload(data, feed(), NOW)
        self.assertEqual(public["guides"][0]["status"], "stale")
        self.assertTrue(public["stale"])
        self.assertNotIn("creator_id", public["guides"][0])
        self.assertEqual(public["coverage"]["heroes"], 1)

    def test_unchanged_metadata_does_not_download_guide_again_or_change_authored_date(self):
        data = snapshot()
        with patch.object(w, "_now", return_value=NOW + timedelta(days=1)), patch.object(w, "fetch_metadata", return_value=[metadata()]), patch.object(w, "_request") as request:
            result, blocked = w.refresh_snapshot(data)
        request.assert_not_called()
        self.assertFalse(blocked)
        self.assertEqual(result["guides"][0]["source_updated_at"], data["guides"][0]["source_updated_at"])
        self.assertNotEqual(result["guides"][0]["fetched_at"], data["guides"][0]["fetched_at"])

    def test_missing_metadata_or_failed_refresh_keeps_last_facts_and_their_fetch_date(self):
        for result in ([], w.WorkshopError("source_unavailable")):
            with patch.object(w, "fetch_metadata", side_effect=result if isinstance(result, Exception) else None,
                              return_value=result if isinstance(result, list) else None):
                refreshed, _ = w.refresh_snapshot(snapshot())
            self.assertEqual(refreshed["guides"][0]["source_updated_at"], snapshot()["guides"][0]["source_updated_at"])
            self.assertEqual(refreshed["guides"][0]["fetched_at"], snapshot()["guides"][0]["fetched_at"])
            self.assertEqual(w.public_payload(refreshed, feed(), NOW)["guides"][0]["status"], "stale")
            self.assertTrue(refreshed["errors"])

    def test_private_withdrawal_persists_through_cache_restart(self):
        with patch.object(w, "fetch_metadata", return_value=[{**metadata(), "visibility": 1}]):
            withdrawn, _ = w.refresh_snapshot(snapshot())
        self.assertEqual(withdrawn["guides"], [])
        self.assertEqual(withdrawn["withdrawn_ids"], ["12345"])
        with tempfile.TemporaryDirectory() as directory:
            seed, cache = Path(directory) / "seed.json", Path(directory) / "cache.json"
            seed.write_text(json.dumps(snapshot()))
            cache.write_text(json.dumps(withdrawn))
            with patch.object(w, "SEED_PATH", seed): loaded = w.WorkshopCache(cache)
            self.assertEqual(loaded.snapshot["guides"], [])

    def test_access_denial_stops_further_batches(self):
        data = snapshot()
        data["guides"] = [{**guide(), "workshop_id": str(i + 1)} for i in range(65)]
        with patch.object(w, "fetch_metadata", side_effect=w.WorkshopError("access_denied")) as fetch:
            result, blocked = w.refresh_snapshot(data)
        self.assertTrue(blocked)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(len(result["guides"]), len(data["guides"]))
        self.assertEqual(result["guides"][0]["source_error"], "access_denied")

    def test_background_refresh_respects_offline_flags(self):
        for flag in ("NARMA_WORKSHOP_REFRESH_ENABLED", "NARMA_EXPLORE_REFRESH_ENABLED"):
            with tempfile.TemporaryDirectory() as directory:
                instance = w.WorkshopCache(Path(directory) / "absent.json")
                instance.snapshot = snapshot()
                with patch.dict(w.os.environ, {flag: "0"}), patch.object(w.threading, "Thread") as thread:
                    instance.start()
                thread.assert_not_called()

    def test_download_url_cannot_redirect_to_arbitrary_hosts_or_include_credentials(self):
        self.assertEqual(w._cdn_url(metadata()["file_url"]), metadata()["file_url"])
        for url in ("http://cdn.steamusercontent.com/ugc/1/AB/", "https://127.0.0.1/ugc/1/AB/",
                    "https://cdn.steamusercontent.com.evil.test/ugc/1/AB/", "https://u:p@cdn.steamusercontent.com/ugc/1/AB/",
                    "https://cdn.steamusercontent.com/ugc/1/AB/?url=https://example.org"):
            with self.subTest(url=url), self.assertRaises(w.WorkshopError): w._cdn_url(url)


if __name__ == "__main__":
    unittest.main()
