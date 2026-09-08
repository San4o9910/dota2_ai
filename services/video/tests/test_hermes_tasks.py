"""Runtime jobs keep identity, evidence, attempt limits and billing durable."""
import json
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from narma_video import budget, hermes_tasks as tasks
from narma_video.db import database
from test_hermes_bridge import OWNER, browser, review_fixture


@pytest.fixture
def queue(browser, monkeypatch):
    _, pool = browser
    from narma_video import hero_pool
    monkeypatch.setattr(hero_pool, "get_pool", lambda owner, **kwargs: pool)
    with database() as connection:
        connection.execute("TRUNCATE hermes_tasks CASCADE")
        connection.execute("DELETE FROM hermes_workers")
        connection.execute("""UPDATE video_ai_budget SET enabled=true,model=%s,price_policy=%s,
            limit_microusd=10000000,spent_microusd=0,reserved_microusd=0,
            frozen_reason=NULL,expires_at='2027-01-01T00:00:00Z' WHERE id=1""", (budget.MODEL, budget.POLICY))
    yield pool
    with database() as connection:
        connection.execute("TRUNCATE hermes_tasks CASCADE")
        connection.execute("DELETE FROM hermes_workers")


def billed(task, *, known=True):
    with database() as connection:
        checked = tasks.authorize_call(connection, task["token"])
        call_id = budget.reserve_hermes(connection, checked, budget.MODEL)
    budget.settle(call_id, {"total_input_tokens": 100, "total_output_tokens": 20,
        "total_thought_tokens": 0, "total_tokens": 120} if known else None)
    return call_id


def response(task):
    return json.dumps(review_fixture(task["snapshot"], task["snapshot_sha256"]))


def legacy_task(pool):
    """The deployed v1 contract had no runtime_contract field in its snapshot."""
    snapshot, digest, sources = tasks.build_snapshot(pool)
    with database() as connection:
        connection.execute("""INSERT INTO hermes_tasks
            (id,owner_id,account_id,snapshot_sha256,snapshot,source_jobs)
            VALUES (%s,%s,1000,%s,%s,%s)""", (uuid4(), OWNER, digest,
                tasks.Jsonb(snapshot), tasks.Jsonb(sources)))
    return tasks.claim_task()


def test_snapshot_enqueues_once_and_concurrent_claims_have_one_lease(queue):
    assert tasks.enqueue_eligible() == 1
    assert tasks.enqueue_eligible() == 0
    with ThreadPoolExecutor(max_workers=2) as workers:
        claimed = list(workers.map(lambda _: tasks.claim_task(), range(2)))
    assert sum(task is not None for task in claimed) == 1
    task = next(task for task in claimed if task)
    with database() as connection:
        assert tasks.authorize_call(connection, task["token"])["owner_id"] == OWNER
        with pytest.raises(ValueError, match="TOKEN_INVALID"):
            tasks.authorize_call(connection, "x" * 43)
    assert tasks.latest_valid_review("different-owner") is None


def test_insufficient_evidence_does_not_enqueue(queue):
    queue["history"][0]["evidence"] = []
    assert tasks.enqueue_eligible() == 0
    assert tasks.claim_task() is None


def test_stale_source_is_rejected_before_spend_and_new_snapshot_can_enqueue(queue):
    tasks.enqueue_eligible()
    task = tasks.claim_task()
    match = queue["history"][0]
    with database() as connection:
        connection.execute("UPDATE hero_pool_matches SET position=2 WHERE owner_id=%s AND match_id=%s", (OWNER, match["match_id"]))
    with database() as connection:
        with pytest.raises(ValueError, match="SOURCE_CHANGED"):
            tasks.authorize_call(connection, task["token"])
    tasks.fail_task(task["id"], task["lease_token"], "HERMES_SOURCE_CHANGED")
    match["position"] = match["pool_metadata"]["position"] = 2
    assert tasks.enqueue_eligible() == 1
    fresh = tasks.claim_task()
    assert fresh["snapshot_sha256"] != task["snapshot_sha256"]
    assert budget.status()["reserved_microusd"] == 0


def test_expired_lease_is_terminal_and_does_not_reissue_credential(queue):
    tasks.enqueue_eligible()
    task = tasks.claim_task()
    with database() as connection:
        connection.execute("UPDATE hermes_tasks SET lease_until=now()-interval '1 second' WHERE id=%s", (task["id"],))
    with database() as connection:
        with pytest.raises(ValueError, match="LEASE_EXPIRED"):
            tasks.authorize_call(connection, task["token"])
    assert tasks.claim_task() is None
    assert tasks.enqueue_eligible() == 0
    with database() as connection:
        row = connection.execute("SELECT state,credential_sha256,attempts FROM hermes_tasks WHERE id=%s", (task["id"],)).fetchone()
    assert row == {"state": "failed", "credential_sha256": None, "attempts": 1}


def test_completion_requires_lease_settled_call_revision_and_real_references(queue):
    tasks.enqueue_eligible()
    task = tasks.claim_task()
    with pytest.raises(ValueError, match="CALL_NOT_SETTLED"):
        tasks.complete_task(task["id"], task["lease_token"], response(task), tasks.RUNTIME_REVISION)
    billed(task)
    with pytest.raises(ValueError, match="LEASE_EXPIRED"):
        tasks.complete_task(task["id"], uuid4(), response(task), tasks.RUNTIME_REVISION)
    with pytest.raises(ValueError, match="RUNTIME_REVISION"):
        tasks.complete_task(task["id"], task["lease_token"], response(task), "f" * 40)
    forged = json.loads(response(task))
    forged["patterns"][0]["evidence"][0]["evidence_id"] = "fabricated-event"
    with pytest.raises(ValueError, match="REVIEW_INVALID"):
        tasks.complete_task(task["id"], task["lease_token"], json.dumps(forged), tasks.RUNTIME_REVISION)
    identity = tasks.complete_task(task["id"], task["lease_token"], response(task), tasks.RUNTIME_REVISION)
    assert tasks.complete_task(task["id"], task["lease_token"], response(task), tasks.RUNTIME_REVISION) == identity
    saved = tasks.latest_valid_review(OWNER)
    assert saved["id"] == identity and saved["runtime_verified"] and not saved["interpretation_verified"]
    assert saved["review"]["producer"] == {"name": "NousResearch/hermes-agent", "version": tasks.RUNTIME_REVISION, "model": budget.MODEL}
    assert tasks.latest_valid_review("other-owner") is None
    assert tasks.enqueue_eligible() == 0


def test_unknown_usage_keeps_reservation_and_cannot_attest_runtime(queue):
    tasks.enqueue_eligible()
    task = tasks.claim_task()
    billed(task, known=False)
    with pytest.raises(ValueError, match="CALL_NOT_SETTLED"):
        tasks.complete_task(task["id"], task["lease_token"], response(task), tasks.RUNTIME_REVISION)
    tasks.fail_task(task["id"], task["lease_token"], "HERMES_CALL_NOT_SETTLED")
    assert budget.status()["reserved_microusd"] == budget.RESERVATION
    assert tasks.enqueue_eligible() == 0 and tasks.claim_task() is None
    assert not tasks.get_runtime_status(OWNER)["runtime_connected"]


def test_deleted_binding_hides_review_but_preserves_provider_ledger(queue):
    tasks.enqueue_eligible()
    task = tasks.claim_task()
    call_id = billed(task)
    tasks.complete_task(task["id"], task["lease_token"], response(task), tasks.RUNTIME_REVISION)
    with database() as connection:
        connection.execute("DELETE FROM portal_dota_profiles WHERE owner_id=%s", (OWNER,))
    assert tasks.latest_valid_review(OWNER) is None
    with database() as connection:
        call = connection.execute("SELECT hermes_task_id,billing_status FROM video_provider_calls WHERE id=%s", (call_id,)).fetchone()
    assert call == {"hermes_task_id": task["id"], "billing_status": "settled"}


def test_scheduler_saves_one_review_and_heartbeat_requires_actual_completion(queue, monkeypatch):
    monkeypatch.setenv("HERMES_RUNTIME_ENABLED", "1")
    calls = []
    def runner(path, body=None, timeout=10):
        if path == "/healthz":
            return {"status": "ready", "runtime_revision": tasks.RUNTIME_REVISION}
        calls.append(body["task_id"])
        with database() as connection:
            task = tasks.authorize_call(connection, body["token"])
        billed({**task, "token": body["token"]})
        return {"final_response": response(task), "runtime_revision": tasks.RUNTIME_REVISION}
    monkeypatch.setattr(tasks, "_runner_json", runner)
    tasks.refresh_heartbeat()
    assert not tasks.get_runtime_status(OWNER)["runtime_connected"]
    result = tasks.process_once()
    assert result["status"] == "succeeded" and result["review_id"] == result["task_id"]
    assert tasks.get_runtime_status(OWNER)["automatic_tracking"]
    assert tasks.process_once() == {"status": "idle"} and len(calls) == 1


def test_invalid_runtime_output_fails_once_without_refunding_charge(queue, monkeypatch):
    def runner(path, body=None, timeout=10):
        if path == "/healthz":
            return {"status": "ready", "runtime_revision": tasks.RUNTIME_REVISION}
        with database() as connection:
            task = tasks.authorize_call(connection, body["token"])
        billed({**task, "token": body["token"]})
        return {"final_response": "```invalid```", "runtime_revision": tasks.RUNTIME_REVISION}
    monkeypatch.setattr(tasks, "_runner_json", runner)
    result = tasks.process_once()
    assert result["status"] == "failed" and result["error_code"] == "HERMES_REVIEW_INVALID"
    assert budget.status()["spent_microusd"] > 0 and budget.status()["reserved_microusd"] == 0
    assert tasks.process_once() == {"status": "idle"}


def test_queue_defers_when_replay_processing(queue):
    tasks.enqueue_eligible()
    # Ready source becoming active is also invalidated, but the scheduler should
    # defer globally before taking a lease or consuming a task attempt.
    with database() as connection:
        connection.execute("UPDATE replay_jobs SET state='processing' WHERE id=%s", (queue["history"][0]["job_id"],))
    assert tasks.claim_task() is None
    with database() as connection:
        assert connection.execute("SELECT state,attempts FROM hermes_tasks").fetchone() == {"state": "queued", "attempts": 0}


@pytest.mark.parametrize("disabled", [True, False])
def test_budget_unavailable_preserves_unclaimed_snapshot_until_budget_restored(queue, disabled):
    tasks.enqueue_eligible()
    with database() as connection:
        connection.execute("UPDATE video_ai_budget SET enabled=%s,reserved_microusd=%s WHERE id=1",
            (not disabled, 0 if disabled else 10000000))
    assert tasks.claim_task() is None
    with database() as connection:
        assert connection.execute("SELECT state,attempts FROM hermes_tasks").fetchone() == {"state": "queued", "attempts": 0}
        connection.execute("UPDATE video_ai_budget SET enabled=true,reserved_microusd=0 WHERE id=1")
    assert tasks.claim_task()["attempts"] == 1


@pytest.mark.parametrize("completion", [False, True])
def test_lease_expiring_while_sources_are_locked_is_rechecked(queue, monkeypatch, completion):
    tasks.enqueue_eligible()
    task = tasks.claim_task()
    if completion:
        billed(task)
    original = tasks._sources_available
    def expire_while_checking(connection, owner_id, sources):
        valid = original(connection, owner_id, sources)
        connection.execute("UPDATE hermes_tasks SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s", (task["id"],))
        return valid
    monkeypatch.setattr(tasks, "_sources_available", expire_while_checking)
    with pytest.raises(ValueError, match="LEASE_EXPIRED"):
        if completion:
            tasks.complete_task(task["id"], task["lease_token"], response(task), tasks.RUNTIME_REVISION)
        else:
            with database() as connection:
                tasks.authorize_call(connection, task["token"])


def test_corrected_contract_preserves_failed_v1_and_unknown_reservation(queue):
    old = legacy_task(queue)
    call_id = billed(old, known=False)
    tasks.fail_task(old["id"], old["lease_token"], "HERMES_RUNNER_FAILED")
    with database() as connection:
        before = connection.execute("SELECT * FROM hermes_tasks WHERE id=%s", (old["id"],)).fetchone()
        call_before = connection.execute("SELECT * FROM video_provider_calls WHERE id=%s", (call_id,)).fetchone()
    allowance = budget.status()
    assert tasks.enqueue_eligible() == 1
    assert tasks.enqueue_eligible() == 0
    new = tasks.claim_task()
    assert new["id"] != old["id"] and new["snapshot_sha256"] != old["snapshot_sha256"]
    assert new["snapshot"]["runtime_contract"] == "narma.hermes.review.v2"
    assert {key: value for key, value in new["snapshot"].items() if key != "runtime_contract"} == old["snapshot"]
    assert budget.status() == allowance
    with database() as connection:
        assert connection.execute("SELECT * FROM hermes_tasks WHERE id=%s", (old["id"],)).fetchone() == before
        assert connection.execute("SELECT * FROM video_provider_calls WHERE id=%s", (call_id,)).fetchone() == call_before
        assert connection.execute("SELECT count(*) AS n FROM hermes_tasks").fetchone()["n"] == 2


def test_corrected_contract_skips_identical_successfully_reviewed_v1_facts(queue):
    old = legacy_task(queue)
    billed(old)
    tasks.complete_task(old["id"], old["lease_token"], response(old), tasks.RUNTIME_REVISION)
    allowance = budget.status()
    assert tasks.enqueue_eligible() == 0
    assert tasks.claim_task() is None
    assert budget.status() == allowance
    with database() as connection:
        assert connection.execute("SELECT count(*) AS n FROM hermes_tasks").fetchone()["n"] == 1
        assert connection.execute("SELECT count(*) AS n FROM video_provider_calls WHERE call_kind='hermes'").fetchone()["n"] == 1


@pytest.mark.parametrize("value,expected", [
    ({"error": "HERMES_UPSTREAM_CALL_FAILED"}, "HERMES_UPSTREAM_CALL_FAILED"),
    ({"error": "private provider body"}, "HERMES_RUNNER_FAILED"),
    ({"error": ["private"]}, "HERMES_RUNNER_FAILED"),
])
def test_runner_http_failures_propagate_only_fixed_categories(monkeypatch, value, expected):
    import io
    import urllib.error
    def failed(*args, **kwargs):
        raise urllib.error.HTTPError("http://hermes-runner/run", 502, "private detail", {},
                                     io.BytesIO(json.dumps(value).encode()))
    monkeypatch.setattr(tasks.urllib.request, "urlopen", failed)
    with pytest.raises(ValueError, match=expected):
        tasks._runner_json("/run", {})
