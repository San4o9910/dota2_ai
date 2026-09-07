"""Browser boundary checks; database ownership is covered by hero-pool tests."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from narma_video import web, hero_pool, hero_pool_legacy

ORIGIN = "https://pool.example.test"


@pytest.fixture
def boundary(monkeypatch):
    monkeypatch.setenv("APP_ORIGIN", ORIGIN)
    monkeypatch.setattr(web, "session_account", lambda request: None)
    application = FastAPI()
    web.attach_web(application)
    hero_pool.attach_hero_pool(application)
    with TestClient(application, base_url=ORIGIN) as client:
        client.headers["Origin"] = ORIGIN
        yield client, application


def test_pool_cannot_use_caller_owner_without_browser_session(boundary):
    client, _ = boundary
    assert client.get("/api/hero-pool", headers={"X-Narma-Owner": "victim"}).status_code == 401
    assert client.get("/api/hero-pool/coach-context?hero=npc_dota_hero_axe&position=3").status_code == 401
    assert client.put("/api/hero-pool/matches/8984479726", json={"position": 2}).status_code == 401


def test_pool_routes_use_only_session_owner_and_validate_notes(boundary, monkeypatch):
    client, application = boundary
    application.dependency_overrides[web.account_required] = lambda: {"owner_id": "session-owner"}
    calls = []
    def get(owner, **filters):
        calls.append((owner, filters))
        return {"summary": {"matches": 0}}
    def update(owner, match_id, **fields):
        calls.append((owner, match_id, fields))
        return {"saved": True}
    monkeypatch.setattr(hero_pool, "get_pool", get)
    monkeypatch.setattr(hero_pool_legacy, "update_match", update)
    response = client.get("/api/hero-pool?hero=npc_dota_hero_axe&position=3&owner_id=victim")
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert calls == [("session-owner", {"window": "all", "hero": "npc_dota_hero_axe", "position": "3", "favorites_only": False})]
    data = {"position": 3, "focus": "safe_return", "reflection": "partial", "note": "Проверить эпизод"}
    response = client.put("/api/hero-pool/matches/8984479726", json=data)
    assert response.status_code == 200
    assert calls[-1] == ("session-owner", "8984479726", data)
    previous_count = len(calls)
    assert client.put("/api/hero-pool/matches/8984479726", json=data, headers={"Origin": "https://other.example"}).status_code == 403
    for invalid in ({**data, "owner_id": "victim"}, {**data, "account_id": 999},
                    {**data, "position": True}, {**data, "position": "3"},
                    {**data, "position": 6}, {**data, "note": "x" * 501},
                    {**data, "reflection": "verified_by_parser"}):
        assert client.put("/api/hero-pool/matches/8984479726", json=invalid).status_code == 400
    assert len(calls) == previous_count


def test_coach_context_uses_owned_filtered_history_and_never_generates(boundary, monkeypatch):
    from narma_video import hero_coach_context
    client, application = boundary
    application.dependency_overrides[web.account_required] = lambda: {"owner_id": "session-owner"}
    calls = []
    def get(owner, **filters):
        calls.append((owner, filters))
        return {"private_pool": True}
    def prepare(pool, **filters):
        assert pool == {"private_pool": True}
        assert filters == {"hero": "npc_dota_hero_axe", "position": 3}
        return {"integration_status": "prepared_not_running"}
    monkeypatch.setattr(hero_pool_legacy, "get_pool", get)
    monkeypatch.setattr(hero_coach_context, "build_hero_coach_context", prepare)
    response = client.get("/api/hero-pool/coach-context?hero=npc_dota_hero_axe&position=3&owner_id=other")
    assert response.status_code == 200 and response.json()["integration_status"] == "prepared_not_running"
    assert calls == [("session-owner", {"hero": "npc_dota_hero_axe", "position": 3})]
    assert client.get("/api/hero-pool/coach-context?hero=npc_dota_hero_axe&position=0").status_code == 422
    assert len(calls) == 1
