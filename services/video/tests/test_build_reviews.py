import copy
from datetime import datetime, timedelta, timezone
import json
import unittest

from narma_video.build_reviews import CATALOG_PATH, adaptations, review_payload


NOW = datetime(2026, 9, 9, 12, tzinfo=timezone.utc)


def feed():
    return {"checked_at": NOW.isoformat(), "stale": False, "errors": [],
            "latest_patch": {"version": "7.41e", "published_at": "2026-07-30T00:00:00Z"}}


def guide():
    return copy.deepcopy(json.loads(CATALOG_PATH.read_text(encoding="utf-8"))["guides"][0])


def row(payload):
    return next(iter(payload["guides"].values()))


class BuildReviewsTests(unittest.TestCase):
    def test_independent_of_provider_and_does_not_mutate_review_dates(self):
        g, source = guide(), feed()
        before = copy.deepcopy(g)
        payload = review_payload(source, NOW, [g])
        self.assertEqual(row(payload)["state"], "reviewed")
        self.assertEqual(g, before)
        self.assertEqual(row(payload)["checked_at"], before["checked_at"])
        self.assertNotIn("winrate", json.dumps(payload))
        source["checked_at"] = (NOW + timedelta(days=8)).isoformat()
        self.assertEqual(row(review_payload(source, NOW + timedelta(days=8), [g]))["state"], "review_due")

    def test_new_patch_requires_actual_editorial_review(self):
        source = feed()
        source["latest_patch"]["version"] = "7.42"
        g = guide()
        payload = review_payload(source, NOW, [g])
        self.assertEqual(row(payload)["state"], "patch_changed")
        self.assertEqual(row(payload)["verified_patch"], "7.41e")
        self.assertEqual(row(payload)["checked_at"], g["checked_at"])

    def test_feed_failure_and_age_never_claim_current_review(self):
        for source in ({}, None, {**feed(), "errors": ["source_unavailable"]},
                       {**feed(), "stale": True},
                       {**feed(), "checked_at": (NOW - timedelta(minutes=30)).isoformat()},
                       {**feed(), "checked_at": (NOW + timedelta(minutes=6)).isoformat()}):
            with self.subTest(source=source):
                payload = review_payload(source, NOW, [guide()])
                self.assertFalse(payload["feed_fresh"])
                self.assertEqual(row(payload)["state"], "unknown")

    def test_seven_day_boundary_and_final_slot_date_do_not_extend_review(self):
        g = guide()
        g.update(checked_at="2026-09-02", final_checked_at="2026-09-09")
        payload = review_payload(feed(), NOW, [g])
        self.assertEqual(row(payload)["state"], "review_due")
        self.assertEqual(row(payload)["review_due_at"], "2026-09-09T00:00:00Z")
        self.assertEqual(payload["review_interval_days"], 7)

    def test_invalid_or_future_review_is_unknown(self):
        for value in ("not-a-date", "2026-09-10", "2026-09-09T09:00:00", None):
            g = guide()
            g["checked_at"] = value
            self.assertEqual(row(review_payload(feed(), NOW, [g]))["state"], "unknown")

    def test_official_patch_link_is_constructed_not_taken_from_input(self):
        source = feed()
        source["latest_patch"]["url"] = "https://untrusted.example/"
        payload = review_payload(source, NOW, [guide()])
        self.assertEqual(payload["latest_patch"]["url"], "https://www.dota2.com/patches/7.41e")
        source["latest_patch"]["version"] = "7.41e/../../../private"
        self.assertEqual(row(review_payload(source, NOW, [guide()]))["state"], "unknown")

    def test_each_catalog_guide_has_useful_six_unique_slot_alternative(self):
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))["guides"]
        self.assertEqual(len(catalog), 12)
        for g in catalog:
            with self.subTest(guide=g["id"]):
                rows = adaptations(g)
                self.assertGreaterEqual(len(rows), 1)
                for alternative in rows:
                    slots = [alternative["item"]["id"] if item["id"] == alternative["replace_item_id"] else item["id"]
                             for item in g["final_items"]]
                    self.assertEqual(len(slots), 6)
                    self.assertEqual(len(set(slots)), 6)
                    self.assertIn(alternative["item"]["id"], [x["id"] for x in g["situational_items"]])

    def test_duplicate_boot_and_unreviewed_alternatives_are_rejected(self):
        g = guide()
        candidate = {"id": "pipe", "name": "Pipe", "why": "Magic", "condition": "Group"}
        g["situational_items"].append(candidate)
        original = {"id": "magic", "label": "Magic", "when": "Group", "replace_item_id": "butterfly", "item": candidate}
        g["adaptations"] = [original]
        self.assertEqual(len(adaptations(g)), 1)
        for replacement in ("power_treads", "not_in_inventory"):
            g["adaptations"] = [{**original, "replace_item_id": replacement}]
            self.assertEqual(adaptations(g), [])
        for item_id in ("power_treads", "invented_item"):
            g["adaptations"] = [{**original, "item": {**candidate, "id": item_id}}]
            self.assertEqual(adaptations(g), [])

    def test_component_cannot_coexist_with_upgrade(self):
        g = guide()
        candidate = {"id": "maelstrom", "name": "Maelstrom", "why": "Farm", "condition": "Farm"}
        g["situational_items"].append(candidate)
        g["adaptations"] = [{"id": "farm", "label": "Farm", "when": "Farm", "replace_item_id": "butterfly", "item": candidate}]
        self.assertEqual(adaptations(g), [])


if __name__ == "__main__":
    unittest.main()
