"""Role coverage must change a hero's actual plan, not just its heading."""
import json
import unittest

from narma_video.build_reviews import CATALOG_PATH, adaptations


class RoleBuildGuidesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.guides = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))["guides"]
        cls.pairs = {(g["hero_slug"], g["position"]): g for g in cls.guides}

    def test_supported_alternate_roles_have_distinct_plans_and_inventories(self):
        for hero, roles in (("viper", (2, 3)), ("necrolyte", (2, 3)),
                            ("spirit_breaker", (3, 4)), ("rubick", (4, 5)),
                            ("crystal_maiden", (4, 5))):
            with self.subTest(hero=hero):
                first, second = (self.pairs[(hero, role)] for role in roles)
                for field in ("summary", "lane_plan", "core_items", "next_game_check"):
                    self.assertNotEqual(first[field], second[field], field)
                self.assertNotEqual({i["id"] for i in first["final_items"]},
                                    {i["id"] for i in second["final_items"]})
                for guide in (first, second):
                    self.assertEqual(len(guide["final_items"]), 6)
                    self.assertTrue(adaptations(guide))

    def test_viper_offlane_is_available_without_fabricating_support_build(self):
        guide = self.pairs[("viper", 3)]
        self.assertIn("pipe", {i["id"] for i in guide["core_items"]})
        self.assertNotIn(("viper", 5), self.pairs)
        self.assertIn("не копируй", guide["summary"])

    def test_new_support_guides_budget_for_allied_lane_and_safe_rotations(self):
        for hero, position, ally in (("rubick", 5, "керри"), ("crystal_maiden", 4, "офлейнер")):
            guide = self.pairs[(hero, position)]
            text = " ".join(guide["lane_plan"]).lower()
            self.assertIn(ally, text)
            self.assertIn("мид", text)
            self.assertIn("волн", text)
            self.assertTrue("свободн" in text, "Support farm is conditional, not forbidden.")
            self.assertTrue("руне" in text or "руной" in text)

    def test_alternate_role_items_do_not_inherit_another_heros_ability_or_swap(self):
        for key in ("viper-offlane-pressure", "necrophos-offlane-frontline", "spirit-breaker-offlane-space",
                    "rubick-hard-support-save", "crystal-maiden-support-rotation"):
            guide = next(g for g in self.guides if g["id"] == key)
            text = json.dumps(guide, ensure_ascii=False)
            with self.subTest(guide=key):
                if guide["hero_slug"] != "crystal_maiden":
                    self.assertNotIn("Freezing Field", text)
                self.assertNotIn("Отказ от Lens", text)
                if guide["hero_slug"] == "viper":
                    self.assertNotIn("Witch Blade", text)


if __name__ == "__main__":
    unittest.main()
