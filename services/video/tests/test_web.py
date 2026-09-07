import hashlib
import os
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from narma_video import api, web
from narma_video.db import database, migrate

ORIGIN = "https://portal.example.test"
INVITE = "synthetic-setup-secret-" + "A" * 32
PASSWORD = "Synthetic passphrase 2026"


@pytest.fixture
def portal(monkeypatch, tmp_path):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set isolated TEST_DATABASE_URL")
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("APP_ORIGIN", ORIGIN)
    monkeypatch.setenv("PORTAL_SETUP_TOKEN_SHA256", hashlib.sha256(INVITE.encode()).hexdigest())
    monkeypatch.setenv("PORTAL_SETUP_EXPIRES_AT", "2099-01-01T00:00:00Z")
    monkeypatch.setenv("VIDEO_STORAGE_PATH", str(tmp_path / "media"))
    monkeypatch.setenv("VIDEO_SERVICE_TOKEN", "synthetic-service-" + "x" * 40)
    migrate()
    with database() as connection:
        connection.execute("TRUNCATE portal_accounts CASCADE")
        connection.execute("TRUNCATE portal_auth_limits")
        connection.execute("UPDATE video_ai_budget SET enabled=true,spent_microusd=0,reserved_microusd=0,frozen_reason=NULL WHERE id=1")
    application = FastAPI()
    web.attach_web(application)
    client = TestClient(application, base_url=ORIGIN)
    client.headers["Origin"] = ORIGIN
    yield client
    with database() as connection:
        connection.execute("DELETE FROM video_provider_calls WHERE owner_id LIKE 'portal_%' OR owner_id='synthetic-other'")
        connection.execute("DELETE FROM video_jobs WHERE owner_id LIKE 'portal_%' OR owner_id='synthetic-other'")
        connection.execute("TRUNCATE portal_accounts CASCADE")
        connection.execute("TRUNCATE portal_auth_limits")


def setup(client):
    response = client.post("/api/auth/setup", json={"token": INVITE, "email": "Owner@example.test", "password": PASSWORD})
    assert response.status_code == 201, response.text
    return response


def profile_seed():
    with database() as connection:
        owner = connection.execute("SELECT owner_id FROM portal_accounts").fetchone()["owner_id"]
        connection.execute("""INSERT INTO portal_dota_profiles
            (owner_id,account_id,nickname,match_id,hero_name,side,source_sha256)
            VALUES (%s,123,'SyntheticPlayer','8963624400','npc_dota_hero_axe','radiant',%s)""", (owner, "a" * 64))
    return owner


def test_password_hash_is_salted_and_strict():
    first = web.password_hash(PASSWORD)
    assert first != web.password_hash(PASSWORD)
    assert web.password_matches(PASSWORD, first)
    assert not web.password_matches(PASSWORD + "x", first)
    assert not web.password_matches(PASSWORD, None)
    assert not web.password_matches(PASSWORD, "scrypt$999999999$8$1$bad$bad")


def test_password_kdf_has_global_memory_concurrency_bound(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    lock = threading.Lock()
    active = peak = 0
    def synthetic_scrypt(*args, **kwargs):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        threading.Event().wait(.02)
        with lock:
            active -= 1
        return bytes(32)
    monkeypatch.setattr(web.hashlib, "scrypt", synthetic_scrypt)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: web.password_hash(PASSWORD), range(12)))
    assert peak == 2 and active == 0


def test_setup_csrf_expiry_single_owner_and_cookie(portal, monkeypatch):
    body = {"token": INVITE, "email": "Owner@example.test", "password": PASSWORD}
    assert portal.get("/api/session").json()["setup_required"] is True
    for bad in ("https://evil.example", "null", ""):
        assert portal.post("/api/auth/setup", json=body, headers={"Origin": bad}).status_code == 403
    monkeypatch.setenv("PORTAL_SETUP_EXPIRES_AT", "2020-01-01T00:00:00Z")
    assert portal.post("/api/auth/setup", json=body).status_code == 403
    monkeypatch.setenv("PORTAL_SETUP_EXPIRES_AT", "2099-01-01T00:00:00Z")
    assert portal.post("/api/auth/setup", json={**body, "token": "wrong" * 10}).status_code == 403
    response = setup(portal)
    cookie = response.headers["set-cookie"]
    assert "__Host-narma_session=" in cookie
    assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/" in cookie
    assert "Domain=" not in cookie
    assert portal.post("/api/auth/setup", json=body).status_code == 409
    state = portal.get("/api/session")
    assert state.json()["user"]["email"] == "owner@example.test"
    assert state.headers["cache-control"] == "no-store"
    with database() as connection:
        assert connection.execute("SELECT count(*) AS n FROM portal_accounts").fetchone()["n"] == 1
        stored = connection.execute("SELECT token_hash FROM portal_sessions").fetchone()["token_hash"]
    assert stored == hashlib.sha256(portal.cookies.get(web.COOKIE).encode()).hexdigest()


def test_cookie_sessions_logout_expiry_and_spoofed_headers(portal):
    assert portal.get("/api/videos", headers={"X-Narma-Owner": "admin", "Authorization": "Bearer " + os.environ["VIDEO_SERVICE_TOKEN"]}).status_code == 401
    setup(portal)
    assert portal.get("/api/videos").status_code == 200
    token = portal.cookies.get(web.COOKIE)
    assert portal.post("/api/auth/logout", json={}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert portal.get("/api/session").json()["authenticated"] is True
    assert portal.post("/api/auth/logout", json={}).status_code == 200
    assert portal.get("/api/videos").status_code == 401
    portal.cookies.set(web.COOKIE, token)
    assert portal.get("/api/videos").status_code == 401
    portal.cookies.clear()
    assert portal.post("/api/auth/login", json={"email": "owner@example.test", "password": PASSWORD}).status_code == 200
    with database() as connection:
        connection.execute("UPDATE portal_sessions SET expires_at=now()-interval '1 second'")
    assert portal.get("/api/videos").status_code == 401


def test_database_rate_limits_survive_new_clients(portal):
    setup(portal)
    portal.cookies.clear()
    for _ in range(10):
        assert portal.post("/api/auth/login", json={"email": "owner@example.test", "password": PASSWORD + "wrong"}).status_code == 401
    separate = TestClient(portal.app, base_url=ORIGIN, headers={"Origin": ORIGIN})
    assert separate.post("/api/auth/login", json={"email": "owner@example.test", "password": PASSWORD}).status_code == 429


def test_password_change_revokes_other_sessions(portal):
    setup(portal)
    separate = TestClient(portal.app, base_url=ORIGIN, headers={"Origin": ORIGIN})
    assert separate.post("/api/auth/login", json={"email": "owner@example.test", "password": PASSWORD}).status_code == 200
    response = portal.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": PASSWORD + " updated"})
    assert response.status_code == 200, response.text
    assert response.json()["authenticated"] is False
    assert portal.cookies.get(web.COOKIE) is None
    assert separate.get("/api/videos").status_code == 401
    assert portal.get("/api/videos").status_code == 401
    assert separate.post("/api/auth/login", json={"email": "owner@example.test", "password": PASSWORD}).status_code == 401
    assert separate.post("/api/auth/login", json={"email": "owner@example.test", "password": PASSWORD + " updated"}).status_code == 200


def test_concurrent_old_password_login_cannot_survive_rotation(portal):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    setup(portal)
    challenger = TestClient(portal.app, base_url=ORIGIN, headers={"Origin": ORIGIN})
    barrier = Barrier(2)
    def login():
        barrier.wait(timeout=10)
        return challenger.post("/api/auth/login", json={"email": "owner@example.test", "password": PASSWORD})
    def rotate():
        barrier.wait(timeout=10)
        return portal.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": PASSWORD + " rotated"})
    with ThreadPoolExecutor(max_workers=2) as pool:
        entered = pool.submit(login)
        changed = pool.submit(rotate)
        assert changed.result(timeout=30).status_code == 200
        assert entered.result(timeout=30).status_code in (200, 401)
    assert challenger.get("/api/videos").status_code == 401
    with database() as connection:
        assert connection.execute("SELECT count(*) AS n FROM portal_sessions").fetchone()["n"] == 0


def test_browser_uses_bound_player_and_preserves_owner_range_and_delete(portal):
    setup(portal)
    job = str(uuid4())
    command = {"id": job, "filename": "synthetic.mp4", "size_bytes": 24}
    assert portal.post("/api/videos", json=command).status_code == 409
    owner = profile_seed()
    assert portal.post("/api/videos", json={**command, "account_id": 999}).status_code == 400
    assert portal.post("/api/videos", json=command).status_code == 201
    with database() as connection:
        row = connection.execute("SELECT owner_id,account_id,nickname FROM video_jobs WHERE id=%s", (job,)).fetchone()
    assert row == {"owner_id": owner, "account_id": 123, "nickname": "SyntheticPlayer"}
    foreign = uuid4()
    api.create_video(api.CreateVideo(id=foreign, filename="synthetic.mp4", size_bytes=24, account_id=999, nickname="Other"), "synthetic-other")
    spoof = {"X-Narma-Owner": "synthetic-other", "Authorization": "Bearer " + os.environ["VIDEO_SERVICE_TOKEN"]}
    assert portal.get(f"/api/videos/{foreign}", headers=spoof).status_code == 404
    content = b"\x00\x00\x00\x18ftyp" + bytes(16)
    assert portal.put(f"/api/videos/{job}/parts/1", content=content).status_code == 200
    assert portal.post(f"/api/videos/{job}/complete", json={}).status_code == 200
    response = portal.get(f"/api/videos/{job}/source", headers={"Range": "bytes=0-7"})
    assert response.status_code == 206 and response.content == content[:8]
    assert portal.delete(f"/api/videos/{job}").status_code == 200
    assert portal.get(f"/api/videos/{job}").status_code == 404


def test_bad_and_oversized_replay_cleanup_and_immutable_profile(portal, monkeypatch):
    setup(portal)
    response = portal.post("/api/profile/replay", content=b"invalid", headers={"X-Dota-Nickname": "Player_0"})
    assert response.status_code == 400
    root = Path(os.environ["VIDEO_STORAGE_PATH"]) / "profile-uploads"
    assert not list(root.iterdir())
    with database() as connection:
        assert connection.execute("SELECT count(*) AS n FROM portal_replay_uploads").fetchone()["n"] == 0
    assert portal.post("/api/profile/replay", content=b"x", headers={"X-Dota-Nickname": "Player_0", "Content-Length": str(web.MAX_REPLAY_BYTES + 1)}).status_code == 413
    metadata = {"match_id": "8963624400", "players": [
        {"account_id": 123, "nickname": "Player_0", "hero_name": "npc_dota_hero_axe", "side": "radiant"},
        {"account_id": 456, "nickname": "Player_1", "hero_name": "npc_dota_hero_lina", "side": "dire"}]}
    monkeypatch.setattr(web, "parse_demo_metadata", lambda path: metadata)
    response = portal.post("/api/profile/replay", content=b"synthetic-only", headers={"X-Dota-Nickname": "Player_0"})
    assert response.status_code == 200, response.text
    assert response.json()["profile"]["account_id"] == 123 and "players" not in response.json()
    assert portal.post("/api/profile/replay", content=b"synthetic-only", headers={"X-Dota-Nickname": "Player_1"}).status_code == 409
    assert portal.get("/api/profile").json()["profile"]["account_id"] == 123
    assert not list(root.iterdir())


def test_json_body_limit_and_cross_site_metadata(portal):
    assert portal.post("/api/auth/login", content=b"x" * 8193, headers={"Content-Type": "application/json"}).status_code == 413
    assert portal.post("/api/auth/login", content=b"{}").status_code == 415
    assert portal.post("/api/auth/login", json={"email": "owner@example.test", "password": PASSWORD}, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
