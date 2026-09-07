"""Failure-sensitive checks for identity, full traversal and factual evidence."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

try:
    from narma_video.replay_report import build_report, ReportError
except ImportError:
    from replay_report import build_report, ReportError


class ReplayReportTests(unittest.TestCase):
    def fixture(self):
        # The selected player's footer position is zero, resource index is seven
        # and team slot is three. All three identifiers are deliberately unlike.
        steam = str(76561197960265728 + 123)
        hero = "npc_dota_hero_necrolyte"
        summary = {"parser": "clarity-test", "complete": True, "sha256": "a" * 64,
            "matchId": "8984479726", "lastTick": 2000, "playbackTicks": 2000,
            "gameStartTimeRaw": 100, "gameEndTimeRaw": 800, "gameWinnerRaw": 2,
            "players": [{"steamId": steam, "name": "Selected", "hero": hero, "team": 2},
                        {"steamId": "76561197960266184", "name": "PRIVATE_OTHER_PLAYER", "hero": "npc_dota_hero_lina", "team": 2}]}
        metadata = {k: v for k, v in summary.items() if k not in ("complete", "lastTick")}
        job = {"source_sha256": "a" * 64, "match_id": "8984479726", "account_id": 123, "nickname": "oldnickname"}
        resource = {"m_vecPlayerData.0007.m_iPlayerSteamID": steam,
            "m_vecPlayerTeamData.0007.m_iTeamSlot": 3, "m_vecPlayerTeamData.0007.m_hSelectedHero": 900,
            "m_vecPlayerTeamData.0007.m_iKills": 2, "m_vecPlayerTeamData.0007.m_iDeaths": 2,
            "m_vecPlayerTeamData.0007.m_iAssists": 3, "m_vecPlayerTeamData.0007.m_iLevel": 15,
            "m_vecPlayerTeamData.0000.m_iKills": 99}
        team = {"m_vecDataTeam.0003.m_iPlayerSteamID": steam,
            "m_vecDataTeam.0003.m_iNetWorth": 9000, "m_vecDataTeam.0003.m_iLastHitCount": 100,
            "m_vecDataTeam.0003.m_iTotalEarnedXP": 12000, "m_vecDataTeam.0003.m_iDenyCount": 4,
            "m_vecDataTeam.0003.m_iTotalEarnedGold": 9500, "m_vecDataTeam.0000.m_iNetWorth": 99999}
        events = [{"type": "source", "metadata": metadata},
            {"type": "player_snapshot", "class": "CDOTA_PlayerResource", "gameTimeDerivedFromServerTicks": 95, "properties": resource},
            {"type": "hero_life", "entityName": hero, "team": 2, "entityHandle": 900, "playerId": 4, "lifeState": 0, "gameTimeDerivedFromServerTicks": 95},
            {"type": "hero_life", "entityName": hero, "team": 2, "entityHandle": 901, "playerId": 7, "lifeState": 0, "gameTimeDerivedFromServerTicks": 95},
            {"type": "combat", "combatType": "DOTA_COMBATLOG_PURCHASE", "target": hero, "combatTimestamp": 110, "value": 487321, "valueName": "item_radiance"},
            {"type": "hero_life", "entityName": hero, "team": 2, "entityHandle": 901, "playerId": 7, "lifeState": 1, "gameTimeDerivedFromServerTicks": 112},
            {"type": "hero_life", "entityName": hero, "team": 2, "entityHandle": 901, "playerId": 7, "lifeState": 0, "gameTimeDerivedFromServerTicks": 119},
            {"type": "combat", "combatType": "DOTA_COMBATLOG_DEATH", "target": hero, "targetHero": True, "targetIllusion": False, "attacker": "npc_dota_hero_lina", "combatTimestamp": 120, "value": 777777},
            {"type": "hero_life", "entityName": hero, "team": 2, "entityHandle": 900, "playerId": 4, "lifeState": 1, "gameTimeDerivedFromServerTicks": 120.034},
            {"type": "scope_left", "entityName": hero, "entityHandle": 900, "gameTimeDerivedFromServerTicks": 121},
            {"type": "hero_life", "entityName": hero, "team": 2, "entityHandle": 900, "playerId": 4, "lifeState": 2, "gameTimeDerivedFromServerTicks": 122},
            {"type": "combat", "combatType": "DOTA_COMBATLOG_BUYBACK", "value": 7, "combatTimestamp": 124},
            {"type": "combat", "combatType": "DOTA_COMBATLOG_BUYBACK", "value": 0, "combatTimestamp": 124.1},
            {"type": "hero_life", "entityName": hero, "team": 2, "entityHandle": 900, "playerId": 4, "lifeState": 0, "gameTimeDerivedFromServerTicks": 125.034},
            {"type": "combat", "combatType": "DOTA_COMBATLOG_DEATH", "target": hero, "targetHero": True, "targetIllusion": False, "attacker": "npc_dota_hero_lina", "combatTimestamp": 130},
            {"type": "hero_life", "entityName": hero, "team": 2, "entityHandle": 900, "playerId": 4, "lifeState": 1, "gameTimeDerivedFromServerTicks": 130.034},
            {"type": "combat", "combatType": "DOTA_COMBATLOG_DEATH", "target": "npc_dota_hero_lina", "targetHero": True, "targetIllusion": False, "attacker": "npc_dota_hero_axe", "assistPlayerIds": [7], "willReincarnate": True, "combatTimestamp": 135},
            {"type": "player_snapshot", "class": "CDOTA_PlayerResource", "gameTimeDerivedFromServerTicks": 800, "properties": resource},
            {"type": "player_snapshot", "class": "CDOTA_DataRadiant", "gameTimeDerivedFromServerTicks": 800, "properties": team},
            {"type": "summary", "summary": summary}]
        for number, event in enumerate(events, 1):
            event["eventId"] = number
        return events, summary, job

    def run_report(self, events, summary, job):
        with tempfile.TemporaryDirectory() as directory:
            events_file, summary_file = Path(directory) / "events.jsonl", Path(directory) / "summary.json"
            events_file.write_text("".join(json.dumps(event) + "\n" for event in events))
            summary_file.write_text(json.dumps(summary))
            return build_report(events_file, summary_file, job)

    def test_steam_resource_and_direct_team_identity_override_roster_position(self):
        report = self.run_report(*self.fixture())
        self.assertEqual(report["player"]["account_id"], 123)
        self.assertEqual(report["player"]["nickname"], "Selected")
        self.assertEqual(report["metrics"]["kills"], 2)
        self.assertEqual(report["metrics"]["net_worth"], 9000)
        self.assertEqual(report["metrics"]["duration_seconds"], 700)
        self.assertEqual(report["outcome"], "win")
        self.assertNotIn("PRIVATE_OTHER_PLAYER", json.dumps(report))
        self.assertNotIn("76561197960266184", json.dumps(report))

    def test_buyback_attributed_to_resource_and_death_amount_is_not_gold(self):
        report = self.run_report(*self.fixture())
        self.assertEqual(report["metrics"]["buybacks"], 1)
        self.assertEqual(report["inventory"][0]["time"], 10)
        self.assertNotIn("487321", json.dumps(report))
        self.assertNotIn("777777", json.dumps(report))
        finding = next(f for f in report["findings"] if f["id"].startswith("buyback-"))
        self.assertIn("6.0 с", finding["observation"])

    def test_life_handle_excludes_illusion_pvs_and_unclosed_interval(self):
        report = self.run_report(*self.fixture())
        self.assertEqual(report["metrics"]["confirmed_dead_seconds"], 5)
        self.assertEqual(report["metrics"]["confirmed_death_intervals"], 1)
        self.assertEqual(report["coverage"]["unclosed_death_intervals"], 1)

    def test_reincarnation_is_not_an_assist_or_ordinary_death(self):
        report = self.run_report(*self.fixture())
        self.assertEqual(sum(e["type"] == "reincarnation" for e in report["evidence"]), 1)
        self.assertEqual(sum(e["type"] == "assist" for e in report["evidence"]), 0)

    def test_incomplete_footer_or_event_gap_cannot_publish(self):
        for change in ("missing", "after", "gap", "summary", "finaltick", "incomplete"):
            with self.subTest(change=change):
                events, summary, job = self.fixture()
                if change == "missing": events.pop()
                elif change == "after": events.append({"eventId": len(events)+1, "type": "clock_anchor"})
                elif change == "gap": events[4]["eventId"] += 1
                elif change == "summary": events[-1]["summary"] = dict(summary, sha256="b" * 64)
                elif change == "finaltick": summary["lastTick"] -= 1
                else: summary["complete"] = False
                with self.assertRaises(ReportError): self.run_report(events, summary, job)

    def test_source_hash_match_and_account_must_match(self):
        for field, value in (("source_sha256", "b" * 64), ("match_id", "8984479727"), ("account_id", 987654)):
            events, summary, job = self.fixture()
            job[field] = value
            with self.assertRaises(ReportError): self.run_report(events, summary, job)

    def test_other_team_and_wrong_team_slot_are_never_used(self):
        events, summary, job = self.fixture()
        events[-2]["class"] = "CDOTA_DataDire"
        with self.assertRaises(ReportError): self.run_report(events, summary, job)
        events, summary, job = self.fixture()
        events[-2]["properties"] = {k.replace(".0003.", ".0002."): v for k, v in events[-2]["properties"].items()}
        with self.assertRaisesRegex(ReportError, "TEAM_IDENTITY_MISMATCH"): self.run_report(events, summary, job)

    def test_report_is_reproducible_and_bounded(self):
        first = self.run_report(*self.fixture())
        second = self.run_report(*self.fixture())
        self.assertEqual(first, second)
        self.assertLess(len(json.dumps(first, ensure_ascii=False).encode()), 300_000)


if __name__ == "__main__":
    unittest.main()
