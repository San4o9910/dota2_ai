"""Longitudinal facts, privacy and mutations; synthetic reports, no providers."""
from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
import pytest

from narma_video import hero_pool as pool
from narma_video.db import database, migrate
from narma_video.web import COOKIE

UTC = timezone.utc
ORIGIN = "https://pool.example.test"
OWNER = "portal_synthetic_pool_owner"
ACCOUNT = 1000
TOKEN = "P" * 43
HERO = "npc_dota_hero_axe"


@pytest.fixture
def browser(monkeypatch):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set isolated TEST_DATABASE_URL")
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("APP_ORIGIN", ORIGIN)
    migrate()
    with database() as connection:
        connection.execute("TRUNCATE portal_accounts CASCADE")
        connection.execute("INSERT INTO portal_accounts(owner_id,email,password_hash) VALUES (%s,'pool@example.test','unused')", (OWNER,))
        connection.execute("INSERT INTO portal_sessions(token_hash,owner_id,expires_at) VALUES (%s,%s,now()+interval '1 hour')", (hashlib.sha256(TOKEN.encode()).hexdigest(), OWNER))
        connection.execute("""INSERT INTO portal_dota_profiles(owner_id,account_id,nickname,match_id,hero_name,side,source_sha256)
            VALUES (%s,%s,'Player','8963624400',%s,'radiant',%s)""", (OWNER, ACCOUNT, HERO, "a" * 64))
    app = FastAPI()
    pool.attach_hero_pool(app)
    client = TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN})
    client.cookies.set(COOKIE, TOKEN)
    yield client
    with database() as connection:
        connection.execute("TRUNCATE portal_accounts CASCADE")


def report(match_id="8963624400", account=ACCOUNT, hero=HERO, outcome="win", repeats=False, last_hits=50):
    deaths = [{"id": "e10", "type": "death", "time": 200},
              {"id": "e20", "type": "death", "time": 250 if repeats else 800}]
    return {"schema_version": "narma.replay-report.v1", "match_id": match_id,
        "player": {"account_id": account, "nickname": "Player", "hero": hero, "team": "radiant"},
        "coverage": {"complete": True, "source_sha256": "a" * 64}, "outcome": outcome,
        "metrics": {"duration_seconds": 1800, "deaths": 2, "kills": 4, "assists": 5,
                    "last_hits": 200, "total_earned_gold": 15000, "xp": 18000},
        "economy": [{"time": 600, "last_hits": last_hits, "net_worth": 5000}],
        "evidence": deaths, "insights": {"items": []}}


def seed(payload=None, when=None, match_id="8963624400", account=ACCOUNT, state="ready"):
    payload = payload if payload is not None else report(match_id, account)
    job = uuid4()
    when = when or datetime.now(UTC) - timedelta(hours=1)
    with database() as connection:
        connection.execute("""INSERT INTO replay_jobs
            (id,owner_id,filename,size_bytes,requested_nickname,nickname,match_id,account_id,source_sha256,
             state,progress,result_payload,created_at,updated_at)
            VALUES (%s,%s,'synthetic.dem',20,'Player','Player',%s,%s,%s,%s,100,%s,%s,%s)""",
            (job, OWNER, match_id, account, "a" * 64, state, Jsonb(payload), when, when))
    return str(job)


def facts(payload=None, position=3, when=None, played_at=None):
    payload = payload or report()
    row = {"id": uuid4(), "match_id": payload["match_id"], "account_id": ACCOUNT,
           "source_sha256": "a" * 64, "result_payload": payload}
    return pool.match_facts(row, {"position": position, "played_at": played_at,
                                 "first_analyzed_at": when or datetime.now(UTC)})


def test_known_outcome_denominator_and_unknown_data():
    rows = [facts(report(outcome=value)) for value in ("win", "loss", None, "victory")]
    result = pool.summary(rows)
    assert result["winrate_pct"] == 50 and result["known_outcomes"] == 2
    assert result["unknown_outcomes"] == 2 and result["matches"] == 4
    assert pool.summary([facts(report(outcome=None))])["winrate_pct"] is None
    missing_death = report()
    missing_death["evidence"] = []
    assert "repeated_deaths" not in facts(missing_death)["metrics"]
    assert "item_delay_seconds" not in rows[0]["metrics"]


def test_no_role_inference_and_source_identity_validation():
    row = facts(position=None)
    assert row["position"] is None and row["date_source"] == "analysis" and row["played_at"] is None
    for broken in ("account", "match", "digest", "coverage", "schema"):
        payload = report()
        if broken == "account":
            payload["player"]["account_id"] = ACCOUNT + 1
        elif broken == "digest":
            payload["coverage"]["source_sha256"] = "b" * 64
        elif broken == "coverage":
            payload["coverage"]["complete"] = False
        elif broken == "schema":
            payload["schema_version"] = "synthetic"
        elif broken == "match":
            payload["match_id"] = "8963624401"
        raw = {"id": uuid4(), "match_id": "8963624400", "account_id": ACCOUNT,
               "source_sha256": "a" * 64, "result_payload": payload}
        assert pool.valid_report(raw) is None


def test_comparable_trends_require_three_each_same_role_and_chronology():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows = [facts(report(match_id=str(8963624400+i), last_hits=30+i*10), when=start+timedelta(days=i)) for i in range(6)]
    trend = next(r for r in pool.trends_for(rows) if r["metric"] == "last_hits_10")
    assert trend["status"] == "ready" and trend["early_n"] == trend["recent_n"] == 3
    assert trend["early_mean"] == 40 and trend["recent_mean"] == 70 and trend["delta"] == 30
    assert set(trend["early_match_ids"]).isdisjoint(trend["recent_match_ids"])
    assert all(r["status"] == "insufficient" for r in pool.trends_for(rows[:5]))
    rows[-1]["position"] = 4
    assert all(r["status"] == "insufficient" for r in pool.trends_for(rows))
    rows[-1]["position"] = 3
    rows[-1]["date_source"] = "user"
    assert all(r["status"] == "mixed_chronology" for r in pool.trends_for(rows))
    for row in rows:
        row["date_source"] = "analysis"
        row["chronology_at"] = start.isoformat()
    assert next(r for r in pool.trends_for(rows) if r["metric"] == "last_hits_10")["status"] == "ambiguous_chronology"


def test_item_delay_requires_active_slot_and_observed_use():
    payload = report()
    payload["insights"]["items"] = [{"item": "item_blink", "time": 700, "event_id": "buy1",
        "realization": {"delay_seconds": 500, "delay_from_active_seconds": None, "status": "used_later"}}]
    assert "item_delay_seconds" not in facts(payload)["metrics"]
    payload["insights"]["items"][0]["realization"].update(delay_from_active_seconds=100, first_use_time=900, first_use_event_id="use1")
    result = facts(payload)
    assert result["metrics"]["item_delay_seconds"] == 100
    assert {e["id"] for e in result["evidence"]} >= {"buy1", "use1"}


def test_progress_keeps_deployed_engine_build_comparison_guard():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows = []
    for i in range(6):
        payload = report(match_id=str(8963624400+i), repeats=True)
        payload["coverage"]["engine_build"] = 10836
        rows.append(facts(payload, when=start+timedelta(days=i)))
    assert next(r for r in pool.trends_for(rows) if r["metric"] == "last_hits_10")["status"] == "ready"
    for different in (10837, None):
        rows[-1]["engine_build"] = different
        assert all(r["status"] == "mixed_builds" and r["delta"] is None for r in pool.trends_for(rows))
        assert pool.patterns_for(rows) == []
    for row in rows:
        row["engine_build"] = None
    assert all("не подтверждена" in r["build_note"] for r in pool.trends_for(rows))


def test_patterns_need_multiple_matches_and_evidence():
    rows = [facts(report(match_id=str(8963624400+i), repeats=i < 2)) for i in range(3)]
    assert pool.patterns_for(rows[:2]) == []
    pattern = pool.patterns_for(rows)[0]
    assert pattern["id"] == "repeat-death" and pattern["occurrences"] == 2 and pattern["eligible_matches"] == 3
    assert len({e["match_id"] for e in pattern["evidence"]}) == 2
    assert pattern["evidence"][0]["evidence_ids"] == ["e10", "e20"]


def test_cookie_authorization_csrf_and_strict_mutations(browser):
    job = seed()
    anonymous = TestClient(browser.app, base_url=ORIGIN)
    assert anonymous.get("/api/hero-pool", headers={"X-Narma-Owner": OWNER, "Authorization": "Bearer synthetic"}).status_code == 401
    assert browser.put(f"/api/hero-pool/matches/{job}", json={"position": 3}, headers={"Origin": "https://evil.test"}).status_code == 403
    assert browser.put(f"/api/hero-pool/matches/{job}", json={"position": 3}, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    for command in ({"position": 0}, {"position": 6}, {"position": True}, {"position": "3"}, {"outcome": "win"}, {"account_id": 999}, {"played_at": "2026-01-01T00:00:00"}, {"played_at": "2099-01-01T00:00:00Z"}, {}):
        assert browser.put(f"/api/hero-pool/matches/{job}", json=command).status_code == 400
    assert browser.put(f"/api/hero-pool/matches/{uuid4()}", json={"position": 3}).status_code == 404
    other_account = seed(match_id="8963624401", account=999)
    assert browser.put(f"/api/hero-pool/matches/{other_account}", json={"position": 3}).status_code == 404
    assert browser.get("/api/hero-pool").json()["summary"]["matches"] == 1
    for path in ("/api/hero-pool?window=7", "/api/hero-pool?position=0", "/api/hero-pool?hero=bad"):
        assert browser.get(path).status_code == 400
    assert browser.put("/api/hero-pool/favorites", content=b"x" * 8193, headers={"Content-Type": "application/json"}).status_code == 413
    assert browser.put("/api/hero-pool/favorites", content=b"{}").status_code == 415


def test_history_backfill_dedup_source_deletion_and_nickname_independence(browser):
    first = seed(when=datetime.now(UTC)-timedelta(days=10))
    changed = report()
    changed["player"]["nickname"] = "Renamed player"
    second = seed(changed)
    invalid = report(match_id="8963624402")
    invalid["coverage"]["complete"] = False
    seed(invalid, match_id="8963624402")
    data = browser.get("/api/hero-pool").json()
    assert data["summary"]["matches"] == 1 and data["history"][0]["job_id"] == second
    chronology = data["history"][0]["chronology_at"]
    assert browser.put(f"/api/hero-pool/matches/{first}", json={"position": 3}).status_code == 200
    assert browser.get("/api/hero-pool").json()["history"][0]["position"] == 3
    with database() as connection:
        connection.execute("UPDATE replay_jobs SET storage_deleted_at=now() WHERE id=%s", (second,))
        connection.execute("UPDATE replay_jobs SET state='deleted' WHERE id=%s", (first,))
    data = browser.get("/api/hero-pool").json()
    assert data["summary"]["matches"] == 1 and data["history"][0]["chronology_at"] == chronology
    with database() as connection:
        assert connection.execute("SELECT count(*) AS n FROM hero_pool_matches").fetchone()["n"] == 1


def test_periods_role_favorites_and_dates_are_explicit(browser):
    recent = seed()
    old_id = "8963624401"
    old = seed(report(old_id, outcome="loss"), match_id=old_id, when=datetime.now(UTC)-timedelta(days=60))
    assert browser.get("/api/hero-pool?window=30").json()["summary"]["matches"] == 1
    assert browser.get("/api/hero-pool?window=90").json()["summary"]["matches"] == 2
    assert browser.get("/api/hero-pool?position=3").json()["summary"]["matches"] == 0
    assert browser.get("/api/hero-pool?position=unknown").json()["summary"]["matches"] == 2
    command = {"position": 3, "played_at": (datetime.now(UTC)-timedelta(days=100)).isoformat()}
    assert browser.put(f"/api/hero-pool/matches/{recent}", json=command).status_code == 200
    assert browser.get("/api/hero-pool?window=90").json()["summary"]["matches"] == 1
    assert browser.get("/api/hero-pool?position=3").json()["history"][0]["date_source"] == "user"
    assert browser.put(f"/api/hero-pool/matches/{recent}", json={"played_at": None}).status_code == 200
    assert browser.get("/api/hero-pool?position=3").json()["history"][0]["date_source"] == "analysis"
    assert browser.put("/api/hero-pool/favorites", json={"hero": "npc_dota_hero_lina", "position": 3}).status_code == 404
    for _ in range(2):
        assert browser.put("/api/hero-pool/favorites", json={"hero": HERO, "position": 3}).status_code == 200
    data = browser.get("/api/hero-pool?favorites_only=true").json()
    assert len(data["favorites"]) == 1 and data["summary"]["matches"] == 1
    assert data["heroes"][0]["favorite"] is True
    assert browser.delete(f"/api/hero-pool/favorites/{HERO}/3", headers={"Origin": "https://evil.test"}).status_code == 403
    assert browser.delete(f"/api/hero-pool/favorites/{HERO}/3").status_code == 200
    assert browser.get("/api/hero-pool?favorites_only=true").json()["summary"]["matches"] == 0


def test_history_is_not_capped_at_upload_list_thirty(browser):
    for i in range(35):
        match_id = str(8963624400+i)
        seed(report(match_id), match_id=match_id)
    data = browser.get("/api/hero-pool").json()
    assert data["summary"]["matches"] == len(data["history"]) == 35


def test_refresh_keeps_last_complete_facts_and_original_date(browser):
    when = datetime.now(UTC)-timedelta(days=8)
    job = seed(when=when)
    # No pool visit before refresh: the first-ready database trigger captures it.
    with database() as connection:
        connection.execute("UPDATE replay_jobs SET state='queued',result_payload=NULL,progress=0,updated_at=now() WHERE id=%s", (job,))
    data = browser.get("/api/hero-pool").json()
    assert data["summary"]["matches"] == 1 and data["summary"]["winrate_pct"] == 100
    row = data["history"][0]
    assert row["report_is_previous"] is True and row["report_state"] == "queued"
    assert pool.timestamp(row["analyzed_at"]) == when
    assert len(row["report_sha256"]) == 64
    assert browser.put(f"/api/hero-pool/matches/{job}", json={"position": 3}).status_code == 200
    with database() as connection:
        connection.execute("UPDATE replay_jobs SET state='failed',updated_at=now() WHERE id=%s", (job,))
    assert browser.get("/api/hero-pool").json()["summary"]["matches"] == 1
    with database() as connection:
        connection.execute("UPDATE replay_jobs SET state='deleted',updated_at=now() WHERE id=%s", (job,))
    assert browser.get("/api/hero-pool").json()["summary"]["matches"] == 0


def test_goals_persist_check_new_unique_matches_and_reject_unbacked_plans(browser):
    command = {"pattern_id": "repeat-death", "hero": HERO, "position": 3}
    assert browser.post("/api/hero-pool/goals", json=command).status_code == 409
    for i in range(3):
        match_id = str(8963624400+i)
        job = seed(report(match_id, repeats=True), match_id=match_id)
        assert browser.put(f"/api/hero-pool/matches/{job}", json={"position": 3}).status_code == 200
    response = browser.post("/api/hero-pool/goals", json=command)
    assert response.status_code == 201, response.text
    goal_id = response.json()["goal"]["id"]
    assert browser.post("/api/hero-pool/goals", json=command).json()["goal"]["id"] == goal_id
    before = browser.get("/api/hero-pool").json()["goals"][0]
    assert before["checks"] == []
    match_id = "8963624499"
    after_job = seed(report(match_id, repeats=False), match_id=match_id, when=datetime.now(UTC))
    assert browser.put(f"/api/hero-pool/matches/{after_job}", json={"position": 3}).status_code == 200
    after = browser.get("/api/hero-pool").json()["goals"][0]
    assert len(after["checks"]) == 1 and after["checks"][0]["status"] == "unknown"
    assert after["checks"][0]["chronology_basis"] == "analysis"
    assert browser.put(f"/api/hero-pool/matches/{after_job}", json={"played_at": datetime.now(UTC).isoformat()}).status_code == 200
    assert browser.get("/api/hero-pool").json()["goals"][0]["checks"][0]["status"] == "reached"
    duplicate = seed(report(match_id, repeats=False), match_id=match_id, when=datetime.now(UTC))
    assert len(browser.get("/api/hero-pool").json()["goals"][0]["checks"]) == 1
    assert browser.put(f"/api/hero-pool/matches/{duplicate}", json={"played_at": "2020-01-01T00:00:00Z"}).status_code == 200
    assert browser.get("/api/hero-pool").json()["goals"][0]["checks"][0]["status"] == "predates_goal"
    assert browser.patch(f"/api/hero-pool/goals/{uuid4()}", json={"status": "completed"}).status_code == 404
    assert browser.patch(f"/api/hero-pool/goals/{goal_id}", json={"status": "paused"}, headers={"Origin": "https://evil.test"}).status_code == 403
    assert browser.patch(f"/api/hero-pool/goals/{goal_id}", json={"status": "completed"}).status_code == 200
    assert browser.get("/api/hero-pool").json()["goals"][0]["status"] == "completed"
    with database() as connection:
        assert connection.execute("SELECT count(*) AS n FROM hero_pool_goals").fetchone()["n"] == 1
        assert connection.execute("SELECT count(*) AS n FROM hero_pool_goal_checks").fetchone()["n"] == 1


def test_legacy_reflections_and_new_progress_stay_in_sync(browser):
    from narma_video import hero_pool_legacy as legacy
    job = seed()
    fields = {"position": 3, "focus": "safe_return", "reflection": "partial", "note": "Моя заметка"}
    legacy.update_match(OWNER, "8963624400", **fields)
    current = browser.get("/api/hero-pool").json()
    assert {key: current["history"][0][key] for key in fields} == fields
    assert current["practice"]["partial"] == 1
    assert browser.patch(f"/api/hero-pool/matches/{job}", json={"position": 4}).status_code == 200
    old = legacy.get_pool(OWNER)["matches"][0]
    assert old["position"] == 4 and old["note"] == fields["note"] and old["reflection"] == "partial"
    assert browser.put(f"/api/hero-pool/matches/{job}", json={"reflection": "done"}).status_code == 200
    old = legacy.get_pool(OWNER)["matches"][0]
    assert old["focus"] == "safe_return" and old["reflection"] == "done" and old["note"] == fields["note"]
    assert browser.put(f"/api/hero-pool/matches/{job}", json={"focus": None}).status_code == 400
    assert browser.put(f"/api/hero-pool/matches/{job}", json={"focus": None, "reflection": None, "note": ""}).status_code == 200
    for invalid in ({"focus": "fabricated"}, {"reflection": "verified_by_parser"}, {"note": "x"*501}, {"note": "bad\u0000text"}):
        assert browser.put(f"/api/hero-pool/matches/{job}", json=invalid).status_code == 400
    legacy.update_match(OWNER, "8963624400", position=None, focus="item_plan", reflection="not_done", note="Проверить предмет")
    current = browser.get("/api/hero-pool").json()["history"][0]
    assert current["position"] is None and current["reflection"] == "not_done"
    # Only owner reflections change; the stored replay facts never do.
    with database() as connection:
        assert connection.execute("SELECT result_payload FROM replay_jobs WHERE id=%s", (job,)).fetchone()["result_payload"] == report()


def test_progress_upgrade_preserves_already_deployed_notes(browser):
    from psycopg import sql
    migrations = Path(pool.__file__).parent.parent / "migrations"
    schema = sql.Identifier("pool_upgrade_" + uuid4().hex)
    with database() as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(schema))
        connection.execute(sql.SQL("SET LOCAL search_path TO {}").format(schema))
        for migration in sorted(migrations.glob("*.sql")):
            if migration.name[:3] <= "007":
                connection.execute(migration.read_text())
        connection.execute("INSERT INTO portal_accounts(owner_id,email,password_hash) VALUES (%s,'upgrade@example.test','unused')", (OWNER,))
        connection.execute("""INSERT INTO replay_jobs(id,owner_id,filename,size_bytes,requested_nickname,nickname,
            match_id,account_id,source_sha256,state,progress,result_payload)
            VALUES (%s,%s,'upgrade.dem',20,'Player','Player','8963624400',%s,%s,'ready',100,%s)""",
            (uuid4(), OWNER, ACCOUNT, "a"*64, Jsonb(report())))
        connection.execute("""INSERT INTO hero_pool_match_notes(owner_id,account_id,match_id,position,focus,reflection,note)
            VALUES (%s,%s,'8963624400',4,'safe_return','done','Уже сохранено')""", (OWNER, ACCOUNT))
        before = connection.execute("SELECT * FROM hero_pool_match_notes").fetchone()
        connection.execute((migrations / "010_hero_pool_progress.sql").read_text())
        assert connection.execute("SELECT * FROM hero_pool_match_notes").fetchone() == before
        assert connection.execute("SELECT position FROM hero_pool_matches").fetchone()["position"] == 4
        connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(schema))
