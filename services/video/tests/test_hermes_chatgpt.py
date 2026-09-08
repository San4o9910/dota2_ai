"""Subscription routing keeps native Hermes isolated and never spends Gemini budget."""
import hashlib
import json
from contextlib import contextmanager
from uuid import uuid4

import pytest

from narma_video import budget, hermes_broker as broker, hermes_tasks as tasks
from narma_video.db import database
from test_hermes_bridge import OWNER, browser, review_fixture
from test_hermes_tasks import queue, billed


@pytest.fixture
def subscription(queue, monkeypatch):
    from narma_video import chatgpt_auth as auth, chatgpt_provider as provider
    state = {"generation": str(uuid4()), "connected": True, "available": True, "paused_until": None}
    monkeypatch.setenv("HERMES_PROVIDER", tasks.CHATGPT_PROVIDER)
    monkeypatch.setattr(auth, "current_connection", lambda connection, owner_id: dict(state) if owner_id == OWNER else None)
    monkeypatch.setattr(auth, "get_access_credentials", lambda owner_id: {
        "access_token": "synthetic-offline-only", "account_id": "synthetic-account",
        "generation": state["generation"]})
    monkeypatch.setattr(auth, "credentials_current", lambda owner_id, generation:
        owner_id == OWNER and state["connected"] and generation == state["generation"])
    monkeypatch.setattr(provider, "_generate", lambda *args, **kwargs: pytest.fail("Unexpected provider dispatch"))
    with database() as connection:
        connection.execute("TRUNCATE chatgpt_calls")
        connection.execute("UPDATE video_ai_budget SET enabled=false WHERE id=1")
    yield state, queue
    with database() as connection:
        connection.execute("TRUNCATE chatgpt_calls")


def request(task):
    return broker.validate_request({"model": tasks.CHATGPT_MODEL, "messages": [
        {"role": "system", "content": "Return evidence-bound JSON."},
        {"role": "user", "content": json.dumps(task["snapshot"], ensure_ascii=False)}]})


def result_text(task):
    result = review_fixture(task["snapshot"], task["snapshot_sha256"])
    result["producer"] = {"name": "NousResearch/hermes-agent", "version": tasks.RUNTIME_REVISION,
        "model": tasks.CHATGPT_MODEL}
    return json.dumps(result, ensure_ascii=False)


def dispatch(task, monkeypatch):
    from narma_video import chatgpt_provider as provider
    text = result_text(task)
    calls = []
    def generate(credentials, instructions, input_data, model):
        calls.append(model)
        assert credentials["generation"] == str(task["connection_generation"])
        assert model == tasks.CHATGPT_MODEL
        assert instructions and json.loads(input_data)[0]["role"] == "user"
        return {"text": text, "model": model, "usage": None}
    monkeypatch.setattr(provider, "_generate", generate)
    result = broker.complete(task["token"], request(task), lambda: pytest.fail("Gemini must not initialize"))
    assert result["choices"][0]["message"]["content"] == text
    assert result["model"] == tasks.CHATGPT_MODEL and "usage" not in result
    return text, calls


def test_waiting_login_does_not_enqueue_claim_or_touch_legacy_budget(subscription):
    state, _ = subscription
    state.update(connected=False, available=False)
    before = budget.status()
    assert tasks.enqueue_eligible() == 0
    assert tasks.claim_task() is None
    assert budget.status() == before
    with database() as connection:
        assert connection.execute("SELECT count(*) AS n FROM chatgpt_calls").fetchone()["n"] == 0
        assert connection.execute("SELECT count(*) AS n FROM video_provider_calls").fetchone()["n"] == 0
        connection.execute("INSERT INTO hermes_workers(id,runtime_revision,automatic_tracking) VALUES ('scheduler',%s,true)",
            (tasks.RUNTIME_REVISION,))
    status = tasks.get_runtime_status(OWNER)
    assert status["services_ready"] and status["readiness"] == "waiting_auth"
    assert not status["runtime_verified"] and not status["runtime_connected"]


def test_subscription_has_immutable_generation_and_ignores_disabled_gemini_budget(subscription):
    state, _ = subscription
    assert tasks.enqueue_eligible() == 1
    task = tasks.claim_task()
    assert task["provider"] == tasks.CHATGPT_PROVIDER and task["model"] == tasks.CHATGPT_MODEL
    assert str(task["connection_generation"]) == state["generation"]
    assert task["snapshot"]["provider_context"] == {"provider": tasks.CHATGPT_PROVIDER,
        "model": tasks.CHATGPT_MODEL, "connection_generation": state["generation"]}
    state["generation"] = str(uuid4())
    with database() as connection:
        with pytest.raises(ValueError, match="CONNECTION_CHANGED"):
            tasks.authorize_call(connection, task["token"])


def test_one_native_review_requires_settled_matching_text_and_correct_producer(subscription, monkeypatch):
    tasks.enqueue_eligible()
    task = tasks.claim_task()
    before = budget.status()
    text, calls = dispatch(task, monkeypatch)
    with pytest.raises(ValueError, match="ALREADY_ATTEMPTED"):
        broker.complete(task["token"], request(task))
    forged = json.loads(text)
    forged["goals"] = []
    with pytest.raises(ValueError, match="CALL_NOT_SETTLED"):
        tasks.complete_task(task["id"], task["lease_token"], json.dumps(forged), tasks.RUNTIME_REVISION)
    tasks.complete_task(task["id"], task["lease_token"], text, tasks.RUNTIME_REVISION)
    assert calls == [tasks.CHATGPT_MODEL]
    assert tasks.latest_valid_review(OWNER)["runtime_verified"]
    assert tasks.latest_valid_review("someone-else") is None
    assert budget.status() == before
    with database() as connection:
        assert connection.execute("SELECT count(*) AS n FROM video_provider_calls").fetchone()["n"] == 0
        row = connection.execute("SELECT state,api_cost_microusd,output_sha256 FROM chatgpt_calls").fetchone()
    assert row == {"state": "succeeded", "api_cost_microusd": None,
        "output_sha256": hashlib.sha256(text.encode()).hexdigest()}


def test_wrong_model_is_rejected_before_either_provider_initializes(subscription):
    tasks.enqueue_eligible()
    task = tasks.claim_task()
    value = request(task)
    value["model"] = budget.MODEL
    with pytest.raises(ValueError, match="MODEL_UNSUPPORTED"):
        broker.complete(task["token"], value, lambda: pytest.fail("Wrong provider initialized"))
    with database() as connection:
        assert connection.execute("SELECT count(*) AS n FROM chatgpt_calls").fetchone()["n"] == 0


def test_unknown_subscription_attempt_is_not_retried_after_reconnect(subscription, monkeypatch):
    from narma_video import chatgpt_provider as provider
    state, _ = subscription
    tasks.enqueue_eligible()
    task = tasks.claim_task()
    def unknown(*args):
        raise provider.ProviderError("CHATGPT_TIMEOUT", unknown=True)
    monkeypatch.setattr(provider, "_generate", unknown)
    with pytest.raises(ValueError, match="CHATGPT_TIMEOUT"):
        broker.complete(task["token"], request(task))
    tasks.fail_task(task["id"], task["lease_token"], "HERMES_UPSTREAM_CALL_FAILED")
    state["generation"] = str(uuid4())
    assert tasks.enqueue_eligible() == 0 and tasks.claim_task() is None
    with database() as connection:
        assert connection.execute("SELECT state FROM chatgpt_calls").fetchone()["state"] == "unknown"
        assert connection.execute("SELECT count(*) AS n FROM hermes_tasks").fetchone()["n"] == 1
        connection.execute("INSERT INTO hermes_workers(id,runtime_revision,automatic_tracking) VALUES ('scheduler',%s,true)",
            (tasks.RUNTIME_REVISION,))
    assert tasks.get_runtime_status(OWNER)["readiness"] == "requires_review"


def test_daily_limit_keeps_task_queued_without_consuming_its_attempt(subscription):
    state, _ = subscription
    tasks.enqueue_eligible()
    with database() as connection:
        for number in range(6):
            connection.execute("""INSERT INTO chatgpt_calls(id,owner_id,request_key,request_sha256,
                job_id,model,connection_generation,lease_token,source_sha256) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (uuid4(), OWNER, f"synthetic:{number}", "a" * 64, uuid4(), tasks.CHATGPT_MODEL,
                    state["generation"], uuid4(), "b" * 64))
    assert tasks.claim_task() is None
    with database() as connection:
        assert connection.execute("SELECT state,attempts FROM hermes_tasks").fetchone() == {"state": "queued", "attempts": 0}
        connection.execute("UPDATE chatgpt_calls SET created_at=now()-interval '1 day'")
    assert tasks.claim_task()["attempts"] == 1


def test_auth_failure_before_inference_can_use_new_generation_without_reset(subscription):
    state, _ = subscription
    tasks.enqueue_eligible()
    first = tasks.claim_task()
    tasks.fail_task(first["id"], first["lease_token"], "HERMES_UPSTREAM_CALL_FAILED")
    state["generation"] = str(uuid4())
    assert tasks.enqueue_eligible() == 1
    fresh = tasks.claim_task()
    assert fresh["id"] != first["id"]
    with database() as connection:
        assert connection.execute("SELECT state,attempts FROM hermes_tasks WHERE id=%s", (first["id"],)).fetchone() == {
            "state": "failed", "attempts": 1}


def test_completed_facts_are_not_bought_again_on_new_auth_generation(subscription, monkeypatch):
    state, _ = subscription
    tasks.enqueue_eligible()
    task = tasks.claim_task()
    text, _ = dispatch(task, monkeypatch)
    tasks.complete_task(task["id"], task["lease_token"], text, tasks.RUNTIME_REVISION)
    state["generation"] = str(uuid4())
    assert tasks.enqueue_eligible() == 0


def test_changed_source_prevents_runtime_attestation(subscription, monkeypatch):
    _, pool = subscription
    tasks.enqueue_eligible()
    task = tasks.claim_task()
    text, _ = dispatch(task, monkeypatch)
    with database() as connection:
        connection.execute("UPDATE hero_pool_matches SET position=2 WHERE owner_id=%s AND match_id=%s",
            (OWNER, pool["history"][0]["match_id"]))
    with pytest.raises(ValueError, match="SOURCE_CHANGED"):
        tasks.complete_task(task["id"], task["lease_token"], text, tasks.RUNTIME_REVISION)
    assert tasks.latest_valid_review(OWNER) is None


def test_runtime_status_with_saved_review_works_in_read_only_transaction(subscription, monkeypatch):
    tasks.enqueue_eligible()
    task = tasks.claim_task()
    text, _ = dispatch(task, monkeypatch)
    tasks.complete_task(task["id"], task["lease_token"], text, tasks.RUNTIME_REVISION)
    @contextmanager
    def read_only():
        with database() as connection:
            connection.execute("SET TRANSACTION READ ONLY")
            yield connection
    monkeypatch.setattr(tasks, "database", read_only)
    assert tasks.get_runtime_status(OWNER)["runtime_verified"]


def test_subscription_start_keeps_failed_gemini_task_and_reservation(subscription, monkeypatch):
    _, _ = subscription
    monkeypatch.setenv("HERMES_PROVIDER", "gemini")
    with database() as connection:
        connection.execute("UPDATE video_ai_budget SET enabled=true WHERE id=1")
    tasks.enqueue_eligible()
    legacy = tasks.claim_task()
    billed(legacy, known=False)
    tasks.fail_task(legacy["id"], legacy["lease_token"], "HERMES_CALL_NOT_SETTLED")
    before = budget.status()
    monkeypatch.setenv("HERMES_PROVIDER", tasks.CHATGPT_PROVIDER)
    assert tasks.enqueue_eligible() == 1
    assert tasks.claim_task()["provider"] == tasks.CHATGPT_PROVIDER
    assert budget.status() == before
    with database() as connection:
        assert connection.execute("SELECT state,attempts FROM hermes_tasks WHERE id=%s", (legacy["id"],)).fetchone() == {
            "state": "failed", "attempts": 1}
