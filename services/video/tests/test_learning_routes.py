"""Browser security boundaries for practice mutations, without providers."""
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from narma_video import learning, web

ORIGIN = "https://learning.example.test"


@pytest.fixture
def boundary(monkeypatch):
    monkeypatch.setenv("APP_ORIGIN", ORIGIN)
    monkeypatch.setattr(web, "session_account", lambda request: None)
    app = FastAPI()
    web.attach_web(app)
    learning.attach_learning(app)
    with TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN}) as client:
        yield client, app


def test_session_owner_required_on_every_learning_route(boundary):
    client, _ = boundary
    job = str(uuid4())
    for method, path, body in (
        ("get", "/api/learning", None), ("get", f"/api/learning/reports/{job}", None),
        ("post", "/api/learning/plans", {"job_id": job, "exercise_id": "r1"}),
        ("patch", f"/api/learning/plans/{job}", {"status": "active"}),
        ("put", f"/api/learning/plans/{job}/checks", {"job_id": job, "answer": "Ответ", "self_assessment": "uncertain"})):
        response = client.request(method, path, json=body, headers={"X-Narma-Owner": "other"})
        assert response.status_code == 401


def test_mutations_validate_origin_and_never_accept_owner_or_verified_assessment(boundary, monkeypatch):
    client, app = boundary
    app.dependency_overrides[web.account_required] = lambda: {"owner_id": "session-owner"}
    calls = []
    monkeypatch.setattr(learning, "create_plan", lambda owner, body: calls.append((owner, body)) or {"saved": True})
    job = str(uuid4())
    data = {"job_id": job, "exercise_id": "r1"}
    response = client.post("/api/learning/plans", json=data)
    assert response.status_code == 201 and calls[0][0] == "session-owner"
    assert response.headers["cache-control"] == "no-store"
    assert client.post("/api/learning/plans", json=data, headers={"Origin": "https://foreign.test"}).status_code == 403
    client.headers.pop("Origin")
    assert client.post("/api/learning/plans", json=data).status_code == 403
    client.headers["Origin"] = ORIGIN
    for bad in ({**data, "owner_id": "victim"}, {**data, "account_id": 123}, {**data, "exercise_id": True}):
        assert client.post("/api/learning/plans", json=bad).status_code == 400
    for bad in (
        {"job_id": job, "answer": "Ответ", "self_assessment": "verified_by_parser"},
        {"job_id": job, "answer": " ", "self_assessment": "applied"},
        {"job_id": job, "answer": "a" * 1501, "self_assessment": "applied"},
        {"job_id": job, "answer": "Ответ", "self_assessment": "applied", "position": 3}):
        assert client.put(f"/api/learning/plans/{job}/checks", json=bad).status_code == 400
    assert len(calls) == 1


def test_read_scope_is_session_owned(boundary, monkeypatch):
    client, app = boundary
    app.dependency_overrides[web.account_required] = lambda: {"owner_id": "session-owner"}
    calls = []
    monkeypatch.setattr(learning, "get_learning", lambda *args: calls.append(args) or {"schema_version": learning.SCHEMA})
    response = client.get("/api/learning?hero=npc_dota_hero_axe&position=3&owner_id=victim")
    assert response.status_code == 200
    assert calls == [("session-owner", "npc_dota_hero_axe", "3")]
