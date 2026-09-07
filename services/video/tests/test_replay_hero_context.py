"""Saved report personalization without provider calls, invented casts or writes."""
from copy import deepcopy
import json

import pytest

from narma_video.replay_hero_context import build_hero_context


def report(hero="npc_dota_hero_necrolyte"):
    return {"player": {"hero": hero, "account_id": 42, "nickname": "private name"},
        "ability_usage": [
            {"name": "necrolyte_death_pulse", "casts": 37, "first_time": -15.25, "last_time": 1600},
            {"name": "necrolyte_ghost_shroud", "casts": 9, "first_time": 202, "last_time": 1500},
            {"name": "necrolyte_reapers_scythe", "casts": 4, "first_time": 310, "last_time": 1530}],
        "evidence": [
            {"id": "event-death", "type": "death", "time": 415, "data": {"attacker": "npc_dota_hero_lina"}},
            {"id": "event-kill", "type": "kill", "time": 620, "data": {"target_hero": "npc_dota_hero_axe"}},
            {"id": "event-item", "type": "purchase", "time": 800, "data": {"item": "item_radiance"}}],
        "insights": {"items": [{"item": "item_radiance", "event_id": "event-item", "time": 800}]},
        "coaching": {"status": "ready", "summary": "An older saved comment", "next_game": []}}


def test_necrophos_decisions_use_verified_mechanics_and_existing_episode_references():
    context = build_hero_context(report(), position=3)
    assert context["schema_version"] == "narma.hero-context.v1"
    assert (context["hero"], context["label"], context["position"]) == ("npc_dota_hero_necrolyte", "Necrophos", 3)
    assert context["position_label"] == "Позиция 3 · указана тобой"
    assert len(context["focus"]) == len(context["training_plan"]) == 2
    defense, target = context["focus"]
    assert "Ghost Shroud" in defense["advice"] and "магический урон" in defense["advice"]
    assert "был ли он доступен" in defense["advice"].lower()
    assert defense["evidence_ids"] == ["event-death"]
    assert "недостающего здоровья" in target["advice"]
    assert "не доказывает применение косы" in target["advice"]
    assert target["evidence_ids"] == ["event-kill"]
    assert context["sources"] == [{"title": "Valve — способности Necrophos", "url": "https://www.dota2.com/hero/necrophos"}]
    assert any("не устанавливает патч" in text for text in context["limits"])


def test_existing_cast_counts_and_signed_times_are_not_reinterpreted_or_mutated():
    original = report()
    before = json.dumps(original, ensure_ascii=False, sort_keys=True)
    context = build_hero_context(original)
    pulse = next(row for row in context["abilities"] if row["name"] == "necrolyte_death_pulse")
    assert (pulse["casts"], pulse["first_time"], pulse["last_time"]) == (37, -15.25, 1600)
    assert any("до начала матча" in text for text in context["limits"])
    assert all("evidence_ids" not in row for row in context["abilities"])
    assert "private name" not in json.dumps(context)
    context["abilities"][0]["casts"] = 999
    context["focus"][0]["evidence_ids"].append("changed")
    assert json.dumps(original, ensure_ascii=False, sort_keys=True) == before


def test_death_pulse_review_is_hero_specific_without_claiming_observed_positions():
    original = report()
    original["ability_usage"] = original["ability_usage"][:1]
    context = build_hero_context(original)
    assert context["training_plan"][0]["id"] == "hero-pulse"
    assert "лечит союзников" in context["focus"][0]["advice"]
    assert "проверь, кто попадал" in context["focus"][0]["advice"]
    assert context["training_plan"][1]["id"] == "hero-item-task"
    assert "Radiance" in context["training_plan"][1]["title"]
    assert "Постоянный эффект" in context["training_plan"][1]["measure"]


def test_other_hero_uses_only_observed_abilities_and_does_not_inherit_necrophos_profile():
    original = report("npc_dota_hero_axe")
    original["ability_usage"] = [{"name": "axe_berserkers_call", "casts": 7,
                                  "first_time": 45, "last_time": 1550}]
    original["insights"]["items"] = []
    context = build_hero_context(original, position=5)
    assert context["label"] == "Axe" and context["sources"] == []
    assert context["abilities"][0]["label"] == "Berserkers Call"
    assert len(context["focus"]) == 1
    assert "Berserkers Call" in context["focus"][0]["advice"]
    assert "не подтверждает применение именно здесь" in context["focus"][0]["advice"]
    assert "Necrophos" not in json.dumps(context) and "Ghost Shroud" not in json.dumps(context)
    assert context["position"] == 5  # Never infer a different role from the hero.


@pytest.mark.parametrize("position", [None, True, False, "3", 0, 6, [], {}])
def test_invalid_or_absent_manual_position_stays_unknown(position):
    context = build_hero_context(report(), position=position)
    assert context["position"] is None and context["position_label"] == "Позиция не указана"


@pytest.mark.parametrize("bad", [None, [], {}, {"player": None}, {"player": {"hero": []}},
    {"player": {"hero": "<script>"}}, {"player": {"hero": "npc_dota_hero_"}},
    {"player": {"hero": "npc_dota_hero_" + "a" * 81}}])
def test_unusable_selected_hero_cannot_produce_a_context(bad):
    assert build_hero_context(bad) is None


def test_missing_telemetry_is_unknown_and_never_invents_a_cast_or_practice_episode():
    context = build_hero_context({"player": {"hero": "npc_dota_hero_necrolyte"}})
    assert context["abilities"] == context["focus"] == context["training_plan"] == []
    assert "отсутствует или неполна" in context["summary"]
    assert any("недостаточно подтверждённых событий" in text for text in context["limits"])


def test_malformed_duplicate_cast_aggregates_and_ambiguous_event_ids_are_excluded():
    original = report()
    original["ability_usage"] = [
        *original["ability_usage"], deepcopy(original["ability_usage"][0]),
        {"name": "necrolyte_fake", "casts": True},
        {"name": "necrolyte_zero", "casts": 0},
        {"name": "item_blink", "casts": 3},
        {"name": "<script>", "casts": 3},
        {"name": "necrolyte_bad_time", "casts": 2, "first_time": float("nan"), "last_time": float("inf")},
        {"name": "necrolyte_reverse", "casts": 2, "first_time": 20, "last_time": 10}]
    original["evidence"].append(deepcopy(original["evidence"][0]))
    context = build_hero_context(original)
    by_name = {row["name"]: row for row in context["abilities"]}
    assert set(by_name) == {"necrolyte_ghost_shroud", "necrolyte_reapers_scythe", "necrolyte_bad_time", "necrolyte_reverse"}
    assert by_name["necrolyte_bad_time"]["first_time"] is None
    assert by_name["necrolyte_bad_time"]["last_time"] is None
    assert by_name["necrolyte_reverse"]["first_time"] is None
    assert all("event-death" not in row["evidence_ids"] for row in context["focus"])
    json.dumps(context, allow_nan=False)


def test_item_claim_requires_matching_evidence_data_and_unknown_ids_are_not_linked():
    original = report("npc_dota_hero_lina")
    original["ability_usage"] = []
    original["insights"]["items"] = [
        {"item": "item_rapier", "event_id": "event-item"},
        {"item": "item_radiance", "event_id": "unknown-event"}]
    context = build_hero_context(original)
    assert context["focus"] == []
    original["insights"]["items"] = [{"item": "item_radiance", "event_id": "event-item"}]
    original["evidence"][-1].update(type="item_observed", data={"items": ["item_radiance"]})
    context = build_hero_context(original)
    assert len(context["focus"]) == 1
    assert context["focus"][0]["evidence_ids"] == ["event-item"]
    assert "появление предмета в инвентаре" in context["focus"][0]["observation"]


def test_output_and_legacy_input_sizes_are_bounded():
    original = report()
    original["ability_usage"] = [{"name": f"example_{index}", "casts": 1} for index in range(40)]
    assert len(build_hero_context(original)["abilities"]) == 24
    original["ability_usage"] *= 10
    original["evidence"] *= 1500
    context = build_hero_context(original)
    assert context["abilities"] == context["focus"] == []
