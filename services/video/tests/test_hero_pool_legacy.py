"""Longitudinal statistics use observed facts, stable identity and real counts."""
from datetime import datetime, timezone
import os
from uuid import uuid4

from fastapi import HTTPException
import pytest
from psycopg.types.json import Jsonb

from narma_video import hero_pool_legacy as pool
from narma_video.db import database, migrate

HERO = "npc_dota_hero_necrolyte"
OTHER = "npc_dota_hero_axe"
OWNER = "portal_synthetic_hero_pool"


def projected(index, *, outcome="win", position=3, hero=HERO, **changes):
    row = {"job_id": str(uuid4()), "account_id": 1000, "match_id": str(8900000000 + index),
        "uploaded_at": datetime(2026, 1, 1, tzinfo=timezone.utc), "hero": hero,
        "outcome": outcome, "position": position, "focus": None, "reflection": None, "note": "",
        "metrics": {"duration_seconds": 2400, "confirmed_dead_seconds": 120,
            "deaths": 2, "confirmed_death_intervals": 2, "total_earned_gold": 24000},
        "checkpoint": {"time": 600, "last_hits": index * 10, "net_worth": 4000 + index * 100, "deaths": 0},
        "unclosed_death_intervals": 0, "deaths": [], "items": [], "engine_build": None}
    return dict(row, **changes)


def test_winrate_excludes_unknown_and_duplicate_uploads_with_real_zero_kept():
    rows = [projected(1), projected(2, outcome="loss"), projected(3, outcome=None)]
    rows.append(dict(rows[0], job_id=str(uuid4())))
    result = pool.build_pool(rows, {"account_id": 1000, "nickname": "Synthetic"})
    assert result["summary"] == {"matches": 3, "wins": 1, "losses": 1, "unknown": 1, "winrate": 50.0}
    assert result["matches"][0]["match_id"] == "8900000003"
    assert result["matches"][0]["metrics"]["deaths10"] == 0
    assert result["matches"][0]["metrics"]["dead_pct"] == 5.0
    assert result["matches"][0]["metrics"]["gpm"] == 600.0
    assert result["scope"]["chronology"] == "match_id"
    assert "_deaths" not in result["matches"][0]
    assert pool.build_pool([projected(1, outcome=None)])["summary"]["winrate"] is None


def test_unknown_roles_separate_and_filters_do_not_hide_hero_selector_choices():
    rows = [projected(1), projected(2, position=4), projected(3, position=None), projected(4, hero=OTHER)]
    result = pool.build_pool(rows, hero=HERO, position="3")
    assert result["summary"]["matches"] == 1
    assert len(result["heroes"]) == 2
    necro = next(h for h in result["heroes"] if h["hero"] == HERO)
    assert {p["position"] for p in necro["positions"]} == {3, 4, None}
    unknown = pool.build_pool(rows, hero=HERO, position="unknown")
    assert unknown["matches"][0]["position"] is None
    assert unknown["trends"]["status"] == "choose_hero_position"


def test_small_sample_never_claims_trend_or_skill_improvement():
    result = pool.build_pool([projected(i) for i in range(1, 6)], hero=HERO, position=3)
    assert result["trends"]["status"] == "insufficient"
    assert result["trends"]["metrics"] == []
    result = pool.build_pool([projected(i) for i in range(1, 7)], hero=HERO, position=3)
    trend = result["trends"]
    assert trend["status"] == "ready"
    lh = next(m for m in trend["metrics"] if m["key"] == "lh10")
    assert (lh["older"], lh["recent"], lh["delta"]) == (20, 50, 30)
    assert lh["older_count"] == lh["recent_count"] == 3
    assert "Версия игры не подтверждена" in trend["note"]
    assert "score" not in result
    # Same matches aggregated across roles are intentionally not a comparison.
    assert pool.build_pool([projected(i) for i in range(7)], hero=HERO)["trends"]["status"] == "choose_hero_position"


def test_missing_nonfinite_stale_or_short_game_metrics_stay_unknown():
    rows = [projected(i) for i in range(1, 7)]
    rows[-1]["checkpoint"].update(last_hits=None)
    trend = pool.build_pool(rows, hero=HERO, position=3)["trends"]
    assert "lh10" not in {m["key"] for m in trend["metrics"]}
    for time in (400, float("nan"), None):
        row = projected(1, checkpoint={"time": time, "last_hits": 90, "net_worth": 5000, "deaths": 0})
        metrics = pool.build_pool([row])["matches"][0]["metrics"]
        assert metrics["lh10"] is metrics["nw10"] is metrics["deaths10"] is None
    row = projected(1, metrics={"duration_seconds": 500, "total_earned_gold": float("inf")}, unclosed_death_intervals=1)
    metrics = pool.build_pool([row])["matches"][0]["metrics"]
    assert all(v is None for v in metrics.values())
    row = projected(1, checkpoint={"time": 600, "last_hits": True, "deaths": -1})
    assert pool.build_pool([row])["matches"][0]["metrics"]["lh10"] is None


def test_mixed_known_builds_or_known_and_unknown_do_not_compare():
    rows = [projected(i, engine_build=10836) for i in range(1, 7)]
    assert pool.build_pool(rows, hero=HERO, position=3)["trends"]["status"] == "ready"
    for different in (10837, None):
        rows[-1]["engine_build"] = different
        result = pool.build_pool(rows, hero=HERO, position=3)
        assert result["trends"]["status"] == "insufficient"
        assert result["trends"]["metrics"] == []
        assert len(result["matches"]) == 6


def test_missing_or_partial_life_telemetry_is_not_zero_downtime():
    for deaths, pairs, seconds in ((2, 0, 0), (2, 1, 60), (2, None, 120),
                                   (None, 2, 120), (2, 3, 120), (2, 2, 0), (0, 0, 10)):
        row = projected(1)
        row["metrics"].update(deaths=deaths, confirmed_death_intervals=pairs,
                              confirmed_dead_seconds=seconds)
        assert pool.build_pool([row])["matches"][0]["metrics"]["dead_pct"] is None
    row = projected(1, unclosed_death_intervals=1)
    assert pool.build_pool([row])["matches"][0]["metrics"]["dead_pct"] is None
    row = projected(1)
    row["metrics"].update(deaths=0, confirmed_death_intervals=0, confirmed_dead_seconds=0)
    assert pool.build_pool([row])["matches"][0]["metrics"]["dead_pct"] == 0
    # A missing recent observation cannot manufacture an improving trend.
    rows = [projected(i) for i in range(1, 7)]
    rows[-1]["metrics"].update(confirmed_death_intervals=0, confirmed_dead_seconds=0)
    result = pool.build_pool(rows, hero=HERO, position=3)
    assert "dead_pct" not in {metric["key"] for metric in result["trends"]["metrics"]}


def with_observations(index):
    return projected(index, deaths=[{"id": "event-1", "time": 400}, {"id": "event-2", "time": 500}],
        items=[{"item": "item_black_king_bar", "label": "BKB", "time": 1000, "event_id": "event-3",
            "first_active_inventory_time": 1010, "first_use_time": 1210,
            "first_use_event_id": "event-4"}])


def test_recurrence_has_three_distinct_matches_and_links_without_causal_judgment():
    assert pool.build_pool([with_observations(i) for i in (1, 2)], hero=HERO, position=3)["patterns"] == []
    result = pool.build_pool([with_observations(i) for i in (1, 2, 3)], hero=HERO, position=3)
    patterns = {p["id"]: p for p in result["patterns"]}
    assert set(patterns) == {"safe_return", "item_plan_item_black_king_bar"}
    death = patterns["safe_return"]
    assert death["matches"] == 3 and len(death["evidence"]) == 3
    assert {e["match_id"] for e in death["evidence"]} == {"8900000001", "8900000002", "8900000003"}
    assert "не доказанная ошибка" in death["observation"]
    item = patterns["item_plan_item_black_king_bar"]
    assert all(e["delay_seconds"] == 200 for e in item["evidence"])
    assert "Сам интервал не показывает" in item["observation"]
    # Missing recorded first use is not a long delay or failed use.
    rows = [with_observations(i) for i in (1, 2, 3)]
    rows[-1]["items"][0]["first_use_time"] = None
    assert {p["id"] for p in pool.build_pool(rows, hero=HERO, position=3)["patterns"]} == {"safe_return"}


def test_old_habits_expire_after_latest_twenty_and_manual_checks_stay_separate():
    rows = [with_observations(i) for i in range(1, 4)] + [projected(i) for i in range(4, 24)]
    rows[-1].update(focus="safe_return", reflection="done", note="I checked the return")
    result = pool.build_pool(rows, hero=HERO, position=3)
    assert result["patterns"] == []
    assert result["practice"] == {"tracked": 1, "done": 1, "partial": 0, "not_done": 0, "unreviewed": 0}
    assert result["scope"]["position_source"] == "self_reported"


@pytest.mark.parametrize("position", [0, 6, True, "all", "3x", 1.5])
def test_invalid_position_rejected_before_database_access(position):
    with pytest.raises(HTTPException) as caught:
        pool.get_pool(OWNER, position=position)
    assert caught.value.status_code == 400


@pytest.fixture
def isolated_database(monkeypatch):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set isolated TEST_DATABASE_URL")
    monkeypatch.setenv("DATABASE_URL", url)
    migrate()
    with database() as connection:
        connection.execute("TRUNCATE portal_accounts CASCADE")
        connection.execute("INSERT INTO portal_accounts(owner_id,email,password_hash) VALUES (%s,'pool@example.test','unused')", (OWNER,))
        connection.execute("""INSERT INTO portal_dota_profiles(owner_id,account_id,nickname,match_id,hero_name,side,source_sha256)
            VALUES (%s,1000,'Synthetic','8900000001',%s,'radiant',%s)""", (OWNER, HERO, "a" * 64))
    yield
    with database() as connection:
        connection.execute("TRUNCATE portal_accounts CASCADE")


def insert_report(index, *, account_id=1000, complete=True, outcome="win", updated_seconds=0):
    job_id = str(uuid4())
    source = projected(index)
    report = {"schema_version": "narma.replay-report.v1", "match_id": source["match_id"],
        "player": {"account_id": account_id, "hero": HERO}, "outcome": outcome,
        "metrics": source["metrics"], "economy": [source["checkpoint"]], "evidence": [],
        "insights": {"items": []}, "coverage": {"complete": complete, "unclosed_death_intervals": 0,
            "source_sha256": "a" * 64}}
    with database() as connection:
        connection.execute("""INSERT INTO replay_jobs(id,owner_id,filename,size_bytes,requested_nickname,nickname,
            match_id,account_id,source_sha256,state,progress,result_payload,updated_at)
            VALUES (%s,%s,'synthetic.dem',100,'Synthetic','Synthetic',%s,%s,%s,'ready',100,%s,
                now()+(%s * interval '1 second'))""",
            (job_id, OWNER, source["match_id"], account_id, "a" * 64, Jsonb(report), updated_seconds))
    return job_id


def test_database_latest_ready_dedup_bound_identity_and_projection(isolated_database):
    insert_report(1, outcome="loss")
    latest = insert_report(1, outcome="win", updated_seconds=60)
    insert_report(2, account_id=2000)
    insert_report(3, complete=False)
    result = pool.get_pool(OWNER)
    assert result["summary"]["matches"] == result["summary"]["wins"] == 1
    assert result["matches"][0]["job_id"] == latest
    assert result["matches"][0]["metrics"]["deaths10"] == 0
    assert pool.get_pool("different-owner")["matches"] == []


def test_database_notes_survive_reupload_change_filters_and_cannot_switch_identity(isolated_database):
    insert_report(1)
    command = {"position": 3, "focus": "item_plan", "reflection": "partial", "note": "Check the next BKB"}
    assert pool.update_match(OWNER, "8900000001", **command)["saved"] is True
    assert pool.get_pool(OWNER, hero=HERO, position=3)["summary"]["matches"] == 1
    insert_report(1, updated_seconds=60)
    match = pool.get_pool(OWNER)["matches"][0]
    assert {key: match[key] for key in command} == command
    pool.update_match(OWNER, "8900000001", position=4)
    assert pool.get_pool(OWNER, position=3)["summary"]["matches"] == 0
    assert pool.get_pool(OWNER, position=4)["summary"]["matches"] == 1
    pool.update_match(OWNER, "8900000001", position=None)
    assert pool.get_pool(OWNER, position="unknown")["summary"]["matches"] == 1
    with pytest.raises(HTTPException) as caught:
        pool.update_match("different-owner", "8900000001", position=1)
    assert caught.value.status_code == 404
    insert_report(2, account_id=2000)
    with pytest.raises(HTTPException):
        pool.update_match(OWNER, "8900000002", position=1)
    with database() as connection:
        assert connection.execute("SELECT account_id FROM portal_dota_profiles WHERE owner_id=%s", (OWNER,)).fetchone()["account_id"] == 1000
        assert connection.execute("SELECT count(*) AS n FROM hero_pool_match_notes").fetchone()["n"] == 1


def test_note_validation_prevents_invalid_manual_progress_before_db():
    for command in ({"focus": "made_up"}, {"reflection": "done"}, {"note": "x" * 501}, {"note": "bad\x00text"}, {"position": True}):
        with pytest.raises(HTTPException) as caught:
            pool.update_match(OWNER, "8900000001", **command)
        assert caught.value.status_code == 400


def test_deleting_last_replay_copy_removes_private_reflection(isolated_database, monkeypatch, tmp_path):
    from narma_video.replay_jobs import delete_replay
    monkeypatch.setenv("VIDEO_STORAGE_PATH", str(tmp_path))
    first, second = insert_report(1), insert_report(1, updated_seconds=60)
    pool.update_match(OWNER, "8900000001", position=3, focus="safe_return", reflection="done", note="Private reflection")
    delete_replay(first, OWNER)
    assert pool.get_pool(OWNER)["matches"][0]["note"] == "Private reflection"
    delete_replay(second, OWNER)
    assert pool.get_pool(OWNER)["matches"] == []
    with database() as connection:
        assert connection.execute("SELECT count(*) AS n FROM hero_pool_match_notes").fetchone()["n"] == 0


def test_mismatched_source_report_not_visible_or_editable(isolated_database):
    job = insert_report(1)
    with database() as connection:
        connection.execute("""UPDATE replay_jobs SET result_payload=jsonb_set(result_payload,
            '{coverage,source_sha256}', to_jsonb(%s::text)) WHERE id=%s""", ("b" * 64, job))
    assert pool.get_pool(OWNER)["matches"] == []
    with pytest.raises(HTTPException) as caught:
        pool.update_match(OWNER, "8900000001", position=3)
    assert caught.value.status_code == 404
