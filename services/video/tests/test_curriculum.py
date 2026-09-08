"""Curriculum boundary checks use synthetic facts and no model/network calls."""
from copy import deepcopy
import math

import pytest

from narma_video import curriculum


HERO = "npc_dota_hero_viper"


def report(events=None, items=None):
    return {"schema_version": "narma.replay-report.v1", "match_id": "8986400328",
            "player": {"hero": HERO, "account_id": 1000},
            "coverage": {"complete": True, "source_sha256": "a" * 64},
            "metrics": {"duration_seconds": 1800}, "evidence": events or [],
            "insights": {"items": items or []}}


def item_report(name="item_desolator"):
    return report([
        {"id": "purchase", "type": "purchase", "time": 700, "data": {"item": name}},
        {"id": "kill", "type": "kill", "time": 705},
        {"id": "death", "type": "death", "time": 800},
    ], [{"item": name, "event_id": "purchase", "time": 700,
         "realization": {"status": "passive_item", "first_use_event_id": None, "first_use_time": None}}])


def test_catalog_stage_order_uniqueness_and_complete_card_contract():
    one, five = curriculum.get_catalog(1), curriculum.get_catalog(5)
    assert one["schema_version"] == one["version"] == curriculum.VERSION
    assert [stage["order"] for stage in one["stages"]] == list(range(1, 7))
    assert [stage["id"] for stage in one["stages"]] == ["lane", "map", "risk", "items", "fights", "decisions"]
    all_cards = {card["id"]: card for card in one["exercises"] + five["exercises"]}
    assert set(all_cards) == {"l1", "l2", "m1", "v1", "r1", "r2", "i1", "i2", "f1", "f2", "a1", "a2", "a3"}
    assert len(one["exercises"]) == len({card["id"] for card in one["exercises"]}) == 11
    assert len(five["exercises"]) == 12
    source_ids = {source["id"] for source in one["sources"]}
    required_text = ("title", "decision_question", "signal", "action", "why", "exception",
                     "drill", "measurement", "mini_lesson", "focus_window_note")
    for card in all_cards.values():
        assert all(isinstance(card[key], str) and card[key].strip() for key in required_text)
        assert 3 <= card["focus_window_matches"] <= 5
        assert set(card["source_refs"]) <= source_ids
        assert card["review_mode"] in {"manual_context", "episode_review"}
    for stage in one["stages"]:
        assert all(all_cards[ident]["stage_id"] == stage["id"] for ident in stage["exercise_ids"])


@pytest.mark.parametrize("position", [None, 0, 6, True, "3", 3.0, [], {}])
def test_unknown_or_invalid_position_never_gets_role_specific_prescription(position):
    catalog = curriculum.get_catalog(position)
    assert catalog["position"] is None and catalog["position_required"] is True
    assert len(catalog["exercises"]) == 10
    assert all(not card["roles"] for card in catalog["exercises"])
    assert curriculum.get_exercise("l1", position) is None
    assert curriculum.get_exercise("l2", position) is None
    assert curriculum.get_exercise("v1", position) is None
    assert curriculum.suggest_exercises(report(), position)[0]["exercise_id"] == "a1"


def test_core_and_support_choices_are_separate_and_hero_required_for_suggestion():
    assert curriculum.get_exercise("l1", 3)["roles"] == [1, 2, 3]
    assert curriculum.get_exercise("l1", 5) is None
    assert curriculum.get_exercise("l2", 1) is None
    assert curriculum.suggest_exercises(report(), 5)[0]["exercise_id"] == "l2"
    assert curriculum.suggest_exercises(report(), 1)[0]["exercise_id"] == "l1"
    invalid_hero = report()
    invalid_hero["player"]["hero"] = "Viper"
    suggestion = curriculum.suggest_exercises(invalid_hero, 1)[0]
    assert suggestion["exercise_id"] == "a1" and suggestion["hero"] is None


def test_callers_cannot_mutate_the_catalog_or_original_report():
    before = report([{"id": "death", "type": "death", "time": 200}])
    original = deepcopy(before)
    first = curriculum.get_catalog(1)
    first["stages"][0]["exercise_ids"].clear()
    first["exercises"][0]["roles"].append(5)
    first["sources"][0]["url"] = "tampered"
    card = curriculum.get_exercise("l1", 1)
    card["roles"].append(5)
    assert curriculum.get_catalog(1)["stages"][0]["exercise_ids"] == ["l1"]
    assert curriculum.get_exercise("l1", 5) is None
    assert curriculum.get_catalog(1)["sources"][0]["url"].startswith("https://")
    curriculum.suggest_exercises(before, 3)
    assert before == original


def test_candidates_are_deterministic_questions_with_existing_evidence_only():
    payload = item_report()
    actual = curriculum.suggest_exercises(payload, 3)
    assert actual == curriculum.suggest_exercises(payload, 3)
    assert [candidate["exercise_id"] for candidate in actual] == ["r1", "i1", "f1"]
    valid_ids = {event["id"] for event in payload["evidence"]}
    for candidate in actual:
        assert candidate["hero"] == HERO and candidate["position"] == 3
        assert candidate["kind"] == "episode_review"
        assert set(candidate["evidence_ids"]) <= valid_ids
        assert "не установленная ошибка" in candidate["limitation"]
        assert "score" not in candidate and "mastery" not in candidate


def test_duplicate_ids_invalid_times_and_unrelated_types_are_not_anchors():
    payload = report([
        {"id": "duplicate", "type": "death", "time": 200},
        {"id": "duplicate", "type": "death", "time": 300},
        {"id": "early", "type": "death", "time": -1},
        {"id": "late", "type": "death", "time": 1801},
        {"id": "bool", "type": "death", "time": True},
        {"id": "nan", "type": "death", "time": math.nan},
        {"id": "inf", "type": "death", "time": math.inf},
        {"id": "unknown", "type": "made_up", "time": 600},
        {"id": "<unsafe>", "type": "death", "time": 700},
        {"id": "valid", "type": "death", "time": 800},
    ])
    assert [row["evidence_id"] for row in curriculum.evidence_candidates(payload, "r1")] == ["valid"]
    assert curriculum.evidence_candidates(payload, "i2") == []
    assert curriculum.evidence_candidates(payload, "missing") == []


@pytest.mark.parametrize("fault", ["schema", "digest", "match", "coverage", "hero"])
def test_incomplete_or_malformed_report_cannot_supply_factual_anchor(fault):
    payload = report([{"id": "death", "type": "death", "time": 200}])
    if fault == "schema":
        payload["schema_version"] = "unverified"
    elif fault == "digest":
        payload["coverage"]["source_sha256"] = "wrong"
    elif fault == "match":
        payload["match_id"] = None
    elif fault == "coverage":
        payload["coverage"]["complete"] = False
    else:
        payload["player"]["hero"] = None
    assert curriculum.evidence_candidates(payload) == []
    candidates = curriculum.suggest_exercises(payload, 3)
    assert all(row["kind"] == "manual_choice" and not row["evidence_ids"] for row in candidates)


def test_passive_item_is_reviewed_without_activation_requirement_or_failure():
    payload = item_report()
    anchors = curriculum.evidence_candidates(payload, "i2")
    assert [row["evidence_id"] for row in anchors] == ["purchase"]
    card = curriculum.get_exercise("i2")
    assert "Пассивному предмету не нужно отдельное нажатие" in card["exception"]
    assert "Если возможности не было, не считай это провалом" in card["measurement"]
    candidate = next(row for row in curriculum.suggest_exercises(payload, 3) if row["exercise_id"] == "i1")
    assert candidate["evidence_ids"] == ["purchase"]
    assert "не использовал" not in candidate["observation"]


@pytest.mark.parametrize("fault", ["item", "event", "time", "no_insights"])
def test_item_insight_must_match_acquisition_identity_and_time(fault):
    payload = item_report()
    if fault == "item":
        payload["insights"]["items"][0]["item"] = "item_blink"
    elif fault == "event":
        payload["insights"]["items"][0]["event_id"] = "death"
    elif fault == "time":
        payload["insights"]["items"][0]["time"] = 999
    else:
        payload["insights"] = {}
    assert curriculum.evidence_candidates(payload, "i1") == []
    assert curriculum.evidence_candidates(payload, "i2") == []


def test_inventory_observation_stays_observation_not_purchase():
    payload = item_report()
    payload["evidence"][0].update(type="item_observed", data={"items": ["item_desolator"]})
    anchors = curriculum.evidence_candidates(payload, "i1")
    assert anchors[0]["type"] == "item_observed"
    suggestion = next(row for row in curriculum.suggest_exercises(payload, 3) if row["exercise_id"] == "i1")
    assert "предмет в инвентаре" in suggestion["observation"]
    assert "приобретение" not in suggestion["observation"]


def test_use_anchor_requires_same_item_and_consistent_first_use_after_acquisition():
    payload = item_report("item_blink")
    payload["evidence"].append({"id": "use", "type": "item_used", "time": 720, "data": {"item": "item_blink"}})
    realization = payload["insights"]["items"][0]["realization"]
    realization.update(first_use_event_id="use", first_use_time=720, status="used_soon")
    assert [row["evidence_id"] for row in curriculum.evidence_candidates(payload, "i2")] == ["purchase", "use"]
    payload["evidence"][-1]["data"]["item"] = "item_black_king_bar"
    assert [row["evidence_id"] for row in curriculum.evidence_candidates(payload, "i2")] == ["purchase"]
    payload["evidence"][-1].update(time=600, data={"item": "item_blink"})
    realization["first_use_time"] = 600
    assert [row["evidence_id"] for row in curriculum.evidence_candidates(payload, "i2")] == ["purchase"]


def test_manual_practice_does_not_invent_missing_route_or_wave_evidence():
    payload = report([{"id": "death", "type": "death", "time": 200}])
    for ident in ("l1", "m1", "a1", "a2", "a3"):
        card = curriculum.get_exercise(ident, 1)
        assert card["review_mode"] == "manual_context"
        assert curriculum.evidence_candidates(payload, ident, 1) == []
    assert curriculum.suggest_exercises({}, None)[0]["episode_time"] is None


def test_ward_practice_is_manual_and_does_not_turn_ward_count_into_vision_claim():
    payload = report([{"id": "ward", "type": "ward_item_used", "time": 200}])
    card = curriculum.get_exercise("v1", 5)
    assert card["roles"] == [4, 5] and card["review_mode"] == "manual_context"
    assert curriculum.get_exercise("v1", 1) is None
    assert curriculum.evidence_candidates(payload, "v1", 5) == []
    assert "не доказывает, что враг был виден" in card["mini_lesson"]


def test_unsorted_evidence_orders_by_actual_time_and_never_generates_field_values():
    payload = report([{"id": "later", "type": "death", "time": 900},
                      {"id": "first", "type": "death", "time": 120}])
    candidate = curriculum.suggest_exercises(payload, 1)[0]
    assert candidate["evidence_ids"] == ["first"] and candidate["episode_time"] == 120
    assert "2:00" in candidate["observation"]
