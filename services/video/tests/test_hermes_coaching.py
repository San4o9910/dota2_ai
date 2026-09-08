"""Runtime interpretations stay scoped to visible evidence and separate from facts."""
from copy import deepcopy
import json

import pytest

from narma_video.hermes_coaching import coaching_for
from narma_video.hero_pool import summary


@pytest.fixture
def history():
    return [
        {"match_id": "100", "job_id": "job-100", "hero": "npc_dota_hero_necrolyte",
         "position": 2, "outcome": "win", "date_source": "user", "metrics": {"gpm": 450}},
        {"match_id": "101", "job_id": "job-101", "hero": "npc_dota_hero_necrolyte",
         "position": 2, "outcome": "loss", "date_source": "user", "metrics": {"gpm": 390}},
        {"match_id": "102", "job_id": "job-102", "hero": "npc_dota_hero_lion",
         "position": 5, "outcome": None, "date_source": "analysis", "metrics": {"gpm": 210}},
    ]


@pytest.fixture
def review():
    def pattern(identifier, matches):
        return {"id": identifier, "title": "Проверь возвращение после смерти",
                "observation": "Два эпизода требуют проверки.", "confidence": "medium",
                "evidence": [{"match_id": match, "evidence_id": "death-1"} for match in matches]}

    return {"runtime_verified": True, "created_at": "2026-09-08T06:00:00Z",
        "runtime_revision": "internal-pinned-revision", "snapshot_sha256": "private-snapshot",
        "token": "private-task-credential", "owner_id": "private-owner",
        "snapshot": {"account_id": 42, "observations": [
            {"match_id": match, "evidence": [{"id": "death-1", "time": time, "type": "death"}]}
            for match, time in [("100", 600), ("101", 720), ("102", 840)]]},
        "review": {"patterns": [pattern("same-context", ["100", "101"]),
                                pattern("mixed-context", ["100", "102"])],
                   "goals": [
                       {"id": "goal-same", "pattern_id": "same-context", "action": "Проверь готовность предмета.",
                        "success_criterion": "Найди по одному эпизоду в следующих матчах.",
                        "evaluate_after_matches": 2},
                       {"id": "goal-mixed", "pattern_id": "mixed-context", "action": "Проверь задачу позиции.",
                        "success_criterion": "Сопоставь эпизоды с задачей своей позиции.",
                        "evaluate_after_matches": 3}]}}


@pytest.mark.parametrize("verified", [None, False, 1, "true"])
def test_manual_or_unverified_reviews_never_become_customer_coaching(review, history, verified):
    review["runtime_verified"] = verified
    assert coaching_for(review, history) is None
    assert coaching_for(None, history) is None


def test_all_cited_matches_must_survive_hero_position_or_period_filters(review, history):
    selected = [row for row in history if row["hero"] == "npc_dota_hero_necrolyte" and row["position"] == 2]
    result = coaching_for(review, selected)
    assert [pattern["id"] for pattern in result["patterns"]] == ["same-context"]
    assert [goal["id"] for goal in result["patterns"][0]["goals"]] == ["goal-same"]
    assert result["patterns"][0]["heroes"] == [
        {"hero": "npc_dota_hero_necrolyte", "label": "Necrophos", "position": 2}]
    # A single visible match cannot retain a two-match conclusion or its goals.
    assert coaching_for(review, selected[:1]) is None
    assert coaching_for(review, history[2:]) is None
    assert coaching_for(review, []) is None


def test_episode_ids_resolve_within_their_own_match_and_keep_actual_roles(review, history):
    result = coaching_for(review, history)
    same, mixed = result["patterns"]
    assert same["evidence"] == [
        {"match_id": "100", "evidence_id": "death-1", "job_id": "job-100", "time": 600, "type": "death"},
        {"match_id": "101", "evidence_id": "death-1", "job_id": "job-101", "time": 720, "type": "death"},
    ]
    assert mixed["evidence"][1]["time"] == 840
    assert {(row["label"], row["position"]) for row in mixed["heroes"]} == {("Necrophos", 2), ("Lion", 5)}


def test_interpretations_do_not_mutate_facts_or_expose_runtime_metadata(review, history):
    original_review, original_history = deepcopy(review), deepcopy(history)
    measured_before = summary(history)
    result = coaching_for(review, history)
    assert summary(history) == measured_before
    assert measured_before["winrate_pct"] == 50 and measured_before["known_outcomes"] == 2
    assert measured_before["unknown_outcomes"] == 1
    assert history == original_history and review == original_review
    assert set(result) == {"updated_at", "patterns"}
    serialized = json.dumps(result)
    for private in ["internal-pinned-revision", "private-snapshot", "private-task-credential", "private-owner",
                    "runtime_revision", "snapshot", "token", "account_id", "metrics", "winrate_pct"]:
        assert private not in serialized
    result["patterns"][0]["evidence"][0]["time"] = 999
    result["patterns"][0]["goals"][0]["action"] = "changed"
    assert review == original_review and history == original_history


def test_coaching_text_is_preserved_for_safe_dom_rendering_without_reinterpreting_it(review, history):
    malicious = '<img src=x onerror=alert(1)>'
    review["review"]["patterns"][0]["observation"] = malicious
    review["review"]["goals"][0]["action"] = malicious
    result = coaching_for(review, history)
    assert result["patterns"][0]["observation"] == malicious
    assert result["patterns"][0]["goals"][0]["action"] == malicious
