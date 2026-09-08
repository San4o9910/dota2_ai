"""Persistent, canonical and owner-scoped self reports; synthetic replays."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb
import pytest

from narma_video import learning
from narma_video.db import database
from test_hero_pool import browser, seed, report, OWNER, ACCOUNT, HERO

UTC = timezone.utc


@pytest.fixture
def client(browser):
    learning.attach_learning(browser.app)
    return browser


def positioned(client, match_id="8963624400", *, payload=None, played_at=None, position=3):
    job = seed(payload=payload, match_id=match_id)
    body = {"position": position}
    if played_at is not None:
        body["played_at"] = played_at.isoformat()
    assert client.patch(f"/api/hero-pool/matches/{job}", json=body).status_code == 200
    return job


def plan(client, job, exercise="r1"):
    response = client.post("/api/learning/plans", json={"job_id": job, "exercise_id": exercise})
    assert response.status_code == 201, response.text
    return response.json()["plan"]


def check(client, active, job, *, evidence="e10", assessment="applied", answer="Я проверил доступную информацию до решения."):
    return client.put(f"/api/learning/plans/{active['id']}/checks", json={
        "job_id": job, "evidence_id": evidence, "answer": answer, "self_assessment": assessment})


def test_existing_report_role_required_and_deduplicated_active_scope(client):
    job = seed()
    snapshot = client.get(f"/api/learning/reports/{job}").json()
    assert snapshot["position_required"] is True and snapshot["hero"] == HERO
    assert snapshot["review_candidates"][0]["evidence_id"] == "e10"
    assert client.post("/api/learning/plans", json={"job_id": job, "exercise_id": "r1"}).status_code == 409
    assert client.patch(f"/api/hero-pool/matches/{job}", json={"position": 3}).status_code == 200
    first = plan(client, job)
    second = plan(client, job)
    assert first["id"] == second["id"]
    assert client.post("/api/learning/plans", json={"job_id": job, "exercise_id": "m1"}).status_code == 409
    assert client.post("/api/learning/plans", json={"job_id": job, "exercise_id": "l2"}).status_code == 400
    assert client.patch(f"/api/learning/plans/{first['id']}", json={"status": "paused"}).status_code == 200
    other = plan(client, job, "m1")
    assert other["id"] != first["id"]
    assert client.patch(f"/api/learning/plans/{first['id']}", json={"status": "active"}).status_code == 409


def test_repeated_checks_do_not_multiply_and_baseline_is_not_new_training(client):
    job = positioned(client)
    active = plan(client, job)
    first = check(client, active, job)
    assert first.status_code == 200
    saved = first.json()["plan"]
    assert saved["training_matches"] == 0 and saved["reviewed_matches"] == 1
    assert saved["checks"][0]["chronology_status"] == "baseline"
    assert saved["checks"][0]["source"] == "player_self_report"
    second = check(client, active, job).json()["plan"]
    assert saved["checks"][0]["checked_at"] == second["checks"][0]["checked_at"]
    duplicate = seed()
    current = client.get(f"/api/learning/reports/{duplicate}").json()
    # An identical duplicate report retains the binding, but one match remains
    # one response and one factual match irrespective of number of uploads.
    assert current["match_id"] == "8963624400"
    revised = check(client, active, duplicate, assessment="partial").json()["plan"]
    assert len(revised["checks"]) == 1 and revised["checks"][0]["self_assessment"] == "partial"


def test_new_old_and_undated_uploads_are_separate_from_training(client):
    job = positioned(client)
    active = plan(client, job)
    # Simulate a plan created before subsequent actual matches without sleeps.
    with database() as connection:
        connection.execute("UPDATE learning_plans SET created_at=now()-interval '2 days' WHERE id=%s", (active["id"],))
    new_job = positioned(client, "8963624401", played_at=datetime.now(UTC) - timedelta(days=1))
    old_job = positioned(client, "8963624402", played_at=datetime.now(UTC) - timedelta(days=3))
    unknown_job = positioned(client, "8963624403")
    for other in (new_job, old_job, unknown_job):
        response = check(client, active, other)
        assert response.status_code == 200, response.text
    current = response.json()["plan"]
    assert current["training_matches"] == 1 and current["self_report_counts"]["applied"] == 1
    assert {r["chronology_status"] for r in current["checks"]} == {"after_plan", "predates_plan", "date_unknown"}
    assert sum(r["is_training"] for r in current["checks"]) == 1


def test_known_different_build_is_not_added_to_practice_series(client):
    original = report()
    original["coverage"]["engine_build"] = 100
    job = positioned(client, payload=original)
    active = plan(client, job)
    with database() as connection:
        connection.execute("UPDATE learning_plans SET created_at=now()-interval '2 days' WHERE id=%s", (active["id"],))
    changed_build = report(match_id="8963624401")
    changed_build["coverage"]["engine_build"] = 101
    later = positioned(client, "8963624401", payload=changed_build, played_at=datetime.now(UTC) - timedelta(days=1))
    result = check(client, active, later).json()["plan"]
    assert result["post_plan_self_reports"] == 1 and result["training_matches"] == 0
    assert result["checks"][0]["build_status"] == "different_build"
    assert result["checks"][0]["mode_status"] == "unknown_mode"
    assert result["checks"][0]["chronology_status"] == "after_plan"


def test_future_or_untrusted_dates_do_not_establish_training():
    now = datetime.now(UTC)
    baseline = {"baseline_match_ids": ["baseline"], "created_at": now - timedelta(days=2)}
    future = {"match_id": "later", "played_at": (now + timedelta(hours=1)).isoformat(), "date_source": "user"}
    assert learning.chronology(baseline, future) == "date_unknown"
    untrusted = {**future, "played_at": (now - timedelta(days=1)).isoformat(), "date_source": "analysis"}
    assert learning.chronology(baseline, untrusted) == "date_unknown"
    assert learning.chronology(baseline, {**untrusted, "match_id": "baseline"}) == "baseline"


def test_role_change_and_report_change_invalidate_dynamic_bindings(client):
    job = positioned(client)
    active = plan(client, job)
    assert check(client, active, job).status_code == 200
    assert client.patch(f"/api/hero-pool/matches/{job}", json={"position": 2}).status_code == 200
    stale = client.get("/api/learning").json()["plans"][0]
    assert stale["validity"] == "scope_changed" and stale["can_check"] is False
    assert stale["checks"][0]["validity"] == "scope_changed"
    assert check(client, active, job).status_code == 409
    assert client.patch(f"/api/hero-pool/matches/{job}", json={"position": 3}).status_code == 200
    changed = report()
    changed["metrics"]["kills"] += 1
    with database() as connection:
        connection.execute("UPDATE replay_jobs SET result_payload=%s WHERE id=%s", (Jsonb(changed), job))
    stale = client.get("/api/learning").json()["plans"][0]
    assert stale["validity"] == "source_changed" and stale["checks"][0]["validity"] == "report_changed"
    assert stale["training_matches"] == 0
    retry = client.post("/api/learning/plans", json={"job_id": job, "exercise_id": "r1"})
    assert retry.status_code == 409 and retry.headers["X-Narma-Error"] == "LEARNING_PLAN_STALE"


def test_model_context_uses_canonical_duplicate_and_rejects_stale_source(client):
    job = positioned(client)
    plan(client, job)
    def current_exercise():
        with database() as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            return learning.resolve_active_exercise(connection, OWNER, ACCOUNT, HERO, 3)
    assert current_exercise() == "r1"
    replacement = report()
    replacement["metrics"]["kills"] += 1
    seed(payload=replacement, when=datetime.now(UTC))
    assert current_exercise() is None
    assert client.get("/api/learning").json()["plans"][0]["validity"] == "source_changed"


def test_worker_refresh_between_history_and_evidence_cannot_save_old_hash(client, monkeypatch):
    job = positioned(client)
    original = learning._load_history
    fired = False
    def refresh_after_history(connection, owner_id, **options):
        nonlocal fired
        result = original(connection, owner_id, **options)
        if not fired:
            fired = True
            replacement = report()
            replacement["evidence"][0]["id"] = "replacement-event"
            with database() as writer:
                writer.execute("UPDATE replay_jobs SET result_payload=%s WHERE id=%s", (Jsonb(replacement), job))
        return result
    monkeypatch.setattr(learning, "_load_history", refresh_after_history)
    response = client.post("/api/learning/plans", json={"job_id": job, "exercise_id": "r1"})
    assert response.status_code == 409 and response.headers["X-Narma-Error"] == "LEARNING_REPORT_CHANGED"
    with database() as connection:
        assert connection.execute("SELECT count(*) AS n FROM learning_plans").fetchone()["n"] == 0


def test_deleted_report_and_locked_account_are_not_resurrected(client):
    job = positioned(client)
    active = plan(client, job)
    assert check(client, active, job, answer="Удалённый личный ответ").status_code == 200
    with database() as connection:
        connection.execute("UPDATE replay_jobs SET state='deleted' WHERE id=%s", (job,))
    stale = client.get("/api/learning").json()["plans"][0]
    assert stale["validity"] == "source_unavailable" and stale["checks"] == []
    assert client.get(f"/api/learning/reports/{job}").status_code == 404
    with database() as connection:
        connection.execute("UPDATE portal_dota_profiles SET account_id=%s WHERE owner_id=%s", (ACCOUNT + 1, OWNER))
    assert client.get("/api/learning").json()["plans"] == []
    assert client.patch(f"/api/learning/plans/{active['id']}", json={"status": "completed"}).status_code == 404


def test_foreign_player_upload_with_same_public_match_id_is_not_authorized(client):
    own = positioned(client)
    active = plan(client, own)
    # The deployed portal deliberately has one owner. A replay of the other
    # player in the very same match must still not pass the bound-account gate.
    foreign = seed(account=ACCOUNT + 1)
    assert client.get(f"/api/learning/reports/{foreign}").status_code == 404
    assert client.post("/api/learning/plans", json={"job_id": foreign, "exercise_id": "r1"}).status_code == 404
    assert check(client, active, foreign).status_code == 404
    assert client.patch(f"/api/learning/plans/{uuid4()}", json={"status": "completed"}).status_code == 404
    # Authenticated scope is also enforced by the data layer independently of
    # browser headers: a foreign owner cannot address this owner's known UUIDs.
    client.app.dependency_overrides[learning.account_required] = lambda: {"owner_id": "foreign-owner"}
    assert client.get(f"/api/learning/reports/{own}").status_code == 404
    assert client.post("/api/learning/plans", json={"job_id": own, "exercise_id": "r1"}).status_code == 404
    assert check(client, active, own).status_code == 404


def test_episode_anchor_required_and_passive_item_never_implies_failed_activation(client):
    payload = report()
    payload["evidence"].append({"id": "purchase1", "type": "purchase", "time": 600, "data": {"item": "item_desolator"}})
    payload["insights"]["items"] = [{"item": "item_desolator", "event_id": "purchase1", "time": 600,
        "realization": {"status": "passive_item", "first_use_time": None, "first_use_event_id": None}}]
    job = positioned(client, payload=payload)
    active = plan(client, job, "i2")
    assert check(client, active, job, evidence="foreign-event").status_code == 400
    assert check(client, active, job, evidence="e10").status_code == 400
    assert check(client, active, job, evidence=None).status_code == 400
    assert check(client, active, job, evidence=None, assessment="uncertain").status_code == 200
    response = check(client, active, job, evidence="purchase1", assessment="partial")
    assert response.status_code == 200, response.text
    result = response.json()["plan"]
    assert result["checks"][0]["self_assessment"] == "partial"
    assert result["progress_source"] == "player_self_report"
    assert all(value == 0 for value in result["self_report_counts"].values())


def test_manual_context_can_be_reflected_without_invented_event(client):
    job = positioned(client)
    active = plan(client, job, "m1")
    response = check(client, active, job, evidence=None)
    assert response.status_code == 200
    assert response.json()["plan"]["checks"][0]["context_source"] == "player_context"


def test_concurrent_duplicate_creation_has_one_active_plan(client):
    job = positioned(client)
    body = learning.PlanCreate(job_id=UUID(job), exercise_id="r1")
    with ThreadPoolExecutor(max_workers=2) as workers:
        responses = list(workers.map(lambda _: learning.create_plan(OWNER, body), range(2)))
    assert responses[0]["plan"]["id"] == responses[1]["plan"]["id"]
    with database() as connection:
        assert connection.execute("SELECT count(*) AS n FROM learning_plans WHERE status='active'").fetchone()["n"] == 1


def test_read_endpoints_can_run_in_read_only_transactions(client, monkeypatch):
    from contextlib import contextmanager
    job = positioned(client)
    active = plan(client, job)
    assert check(client, active, job).status_code == 200
    @contextmanager
    def readonly():
        with database() as connection:
            connection.execute("SET TRANSACTION READ ONLY")
            yield connection
    monkeypatch.setattr(learning, "database", readonly)
    assert client.get("/api/learning").status_code == 200
    assert client.get(f"/api/learning/reports/{job}").status_code == 200
