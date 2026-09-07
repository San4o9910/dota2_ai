"""Replay upload/auth/identity/lease regressions; no network or paid calls."""
import hashlib
import importlib.util
import os
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from narma_video.db import database, migrate
from narma_video.web import COOKIE

try:
    from narma_video import replay_jobs as replay
except ImportError:
    spec = importlib.util.spec_from_file_location("narma_video.replay_jobs", Path(__file__).with_name("replay_jobs.py"))
    replay = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = replay
    spec.loader.exec_module(replay)

# Existing protobuf fixtures contain metadata only. They may be queued but a
# real worker MUST reject them as full gameplay reports; tests never call them
# a parsed match.
from test_replay_metadata import metadata_fixture

ORIGIN = "https://replay.example.test"
OWNER = "portal_synthetic_replay_owner"
TOKEN = "Z" * 43


@pytest.fixture
def browser(monkeypatch, tmp_path):
    url = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("Set isolated TEST_DATABASE_URL")
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("APP_ORIGIN", ORIGIN)
    monkeypatch.setenv("VIDEO_STORAGE_PATH", str(tmp_path / "media"))
    migrate()
    with database() as connection:
        if not connection.execute("SELECT to_regclass('replay_jobs') AS name").fetchone()["name"]:
            connection.execute(Path(__file__).with_name("005_replay_analysis.sql").read_text())
        connection.execute("TRUNCATE portal_accounts CASCADE")
        connection.execute("TRUNCATE replay_workers")
        connection.execute("INSERT INTO portal_accounts(owner_id,email,password_hash) VALUES (%s,'synthetic@example.test','unused')", (OWNER,))
        connection.execute("INSERT INTO portal_sessions(token_hash,owner_id,expires_at) VALUES (%s,%s,now()+interval '1 hour')", (hashlib.sha256(TOKEN.encode()).hexdigest(), OWNER))
    app = FastAPI()
    replay.attach_replays(app)
    client = TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN})
    client.cookies.set(COOKIE, TOKEN)
    yield client
    with database() as connection:
        connection.execute("TRUNCATE portal_accounts CASCADE")


def start(browser, content=None, **fields):
    content = content or metadata_fixture()[0]
    command = {"id": str(uuid4()), "filename": "synthetic.dem", "size_bytes": len(content), "nickname": "Player_0", **fields}
    response = browser.post("/api/replays", json=command)
    assert response.status_code == 201, response.text
    return command, content


def upload(browser, content=None, **fields):
    command, content = start(browser, content, **fields)
    job = command["id"]
    response = browser.put(f"/api/replays/{job}/parts/1", content=content)
    assert response.status_code == 200, response.text
    return command, content


def queued(browser, content=None, **fields):
    command, content = upload(browser, content, **fields)
    response = browser.post(f"/api/replays/{command['id']}/complete")
    assert response.status_code == 200, response.text
    return command, content


def test_cookie_auth_csrf_and_no_identity_from_headers(browser):
    anonymous = TestClient(browser.app, base_url=ORIGIN)
    assert anonymous.get("/api/replays", headers={"X-Narma-Owner": OWNER, "Authorization": "Bearer synthetic"}).status_code == 401
    assert browser.get("/api/replays").status_code == 200
    assert browser.post("/api/replays", json={}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert browser.post("/api/replays", json={"id": str(uuid4()), "filename": "x.dem", "size_bytes": 20, "nickname": "Player_0", "account_id": 999}).status_code == 400


def test_upload_queued_identity_bound_parts_immutable_and_completion_idempotent(browser):
    command, content = upload(browser)
    job = command["id"]
    assert browser.post("/api/replays", json=command).status_code == 201
    assert browser.post("/api/replays", json={**command, "nickname": "Player_1"}).status_code == 409
    assert browser.put(f"/api/replays/{job}/parts/1", content=content).status_code == 200
    assert browser.put(f"/api/replays/{job}/parts/1", content=content[:-1] + bytes([content[-1] ^ 1])).status_code == 409
    assert browser.post(f"/api/replays/{job}/complete").status_code == 200
    assert browser.post(f"/api/replays/{job}/complete").status_code == 200
    result = browser.get(f"/api/replays/{job}").json()
    assert result["replay"]["state"] == "queued" and result["report"] is None
    assert "players" not in str(result)
    with database() as connection:
        row = connection.execute("SELECT * FROM replay_jobs WHERE id=%s", (job,)).fetchone()
        profile = connection.execute("SELECT * FROM portal_dota_profiles WHERE owner_id=%s", (OWNER,)).fetchone()
    assert row["account_id"] == profile["account_id"] == 1000
    assert row["match_id"] == "8963624400"
    assert row["source_sha256"] == hashlib.sha256(content).hexdigest()
    assert (replay.replay_directory(job) / "source.dem").read_bytes() == content
    assert not list(replay.replay_directory(job).glob("part-*"))
    assert browser.put(f"/api/replays/{job}/parts/1", content=content).status_code == 409
    with pytest.raises(HTTPException) as rejected:
        replay.get_replay(job, "forged-other-owner")
    assert rejected.value.status_code == 404


def test_incomplete_corrupt_parts_and_wrong_match_never_queue(browser):
    command, content = start(browser)
    job = command["id"]
    assert browser.post(f"/api/replays/{job}/complete").status_code == 409
    assert browser.put(f"/api/replays/{job}/parts/1", content=content[:10]).status_code == 400
    assert browser.put(f"/api/replays/{job}/parts/1", content=b"notdemo!" + content[8:]).status_code == 415
    assert browser.put(f"/api/replays/{job}/parts/1", content=content).status_code == 200
    path = replay.replay_directory(job) / "part-1"
    path.write_bytes(content[:-1] + bytes([content[-1] ^ 1]))
    assert browser.post(f"/api/replays/{job}/complete").status_code == 409
    assert browser.delete(f"/api/replays/{job}").status_code == 200
    wrong, _ = upload(browser, match_id="8984479726")
    assert browser.post(f"/api/replays/{wrong['id']}/complete").status_code == 409
    assert browser.get(f"/api/replays/{wrong['id']}").json()["replay"]["state"] == "uploading"
    with database() as connection:
        assert connection.execute("SELECT count(*) AS n FROM portal_dota_profiles").fetchone()["n"] == 0


def test_bound_steam_identity_survives_nickname_change_and_cannot_switch(browser):
    first, _ = queued(browser)
    # Free active quota while preserving the bound player.
    assert browser.delete(f"/api/replays/{first['id']}").status_code == 200
    renamed = metadata_fixture(mutate=lambda players: players[0].update(nickname="NewNick"))[0]
    second, _ = queued(browser, renamed, nickname="Player_1")
    with database() as connection:
        row = connection.execute("SELECT account_id,nickname FROM replay_jobs WHERE id=%s", (second["id"],)).fetchone()
    assert row == {"account_id": 1000, "nickname": "NewNick"}
    assert browser.delete(f"/api/replays/{second['id']}").status_code == 200
    absent = metadata_fixture(mutate=lambda players: players[0].update(account_id=2000))[0]
    third, _ = upload(browser, absent)
    assert browser.post(f"/api/replays/{third['id']}/complete").status_code == 409
    with database() as connection:
        assert connection.execute("SELECT account_id FROM portal_dota_profiles").fetchone()["account_id"] == 1000


def test_worker_lease_identity_result_and_delete_fencing(browser):
    command, _ = queued(browser)
    job = command["id"]
    claimed = replay.claim_replay("synthetic-worker", job)
    lease = claimed["lease_token"]
    assert claimed["state"] == "processing" and claimed["attempt"] == 1
    assert replay.claim_replay("synthetic-worker", job) is None
    assert replay.replay_progress(job, lease, 20)
    assert not replay.replay_progress(job, uuid4(), 90)
    with pytest.raises(ValueError, match="REPLAY_RESULT_IDENTITY"):
        replay.finish_replay(job, lease, {"match_id": "8963624400", "player": {"account_id": 999}})
    report = {"match_id": "8963624400", "player": {"account_id": 1000}, "synthetic_test_only": True}
    assert replay.finish_replay(job, lease, report)
    assert not replay.finish_replay(job, lease, report)
    result = browser.get(f"/api/replays/{job}").json()
    assert result["replay"]["state"] == "ready" and result["report"] == report
    assert browser.delete(f"/api/replays/{job}").status_code == 200
    assert browser.get(f"/api/replays/{job}").status_code == 404
    assert not replay.replay_directory(job).exists()
    assert not replay.finish_replay(job, lease, report)


def test_expired_worker_cannot_finish_and_attempts_are_bounded(browser):
    command, _ = queued(browser)
    job = command["id"]
    first = replay.claim_replay("synthetic-worker", job)
    with database() as connection:
        connection.execute("UPDATE replay_jobs SET lease_expires_at=now()-interval '1 second' WHERE id=%s", (job,))
    assert not replay.finish_replay(job, first["lease_token"], {"match_id": "8963624400", "player": {"account_id": 1000}})
    second = replay.claim_replay("synthetic-worker", job)
    assert second["attempt"] == 2 and second["lease_token"] != first["lease_token"]
    assert not replay.fail_replay(job, first["lease_token"], "REPLAY_PARSE_FAILED")
    with database() as connection:
        connection.execute("UPDATE replay_jobs SET lease_expires_at=now()-interval '1 second',attempt=3 WHERE id=%s", (job,))
    assert replay.claim_replay("synthetic-worker", job) is None
    result = browser.get(f"/api/replays/{job}").json()
    assert result["replay"]["state"] == "failed"
    assert result["report"] is None


def test_active_and_storage_quota_precedes_reservation(browser, monkeypatch):
    first, _ = start(browser)
    second, _ = start(browser)
    response = browser.post("/api/replays", json={**first, "id": str(uuid4())})
    assert response.status_code == 429
    assert browser.delete(f"/api/replays/{first['id']}").status_code == 200
    monkeypatch.setattr(replay, "OWNER_STORAGE_BYTES", second["size_bytes"])
    assert browser.post("/api/replays", json={**first, "id": str(uuid4())}).status_code == 429
    with database() as connection:
        assert connection.execute("SELECT count(*) AS n FROM replay_jobs").fetchone()["n"] == 2


def test_database_rejects_mutation_of_bound_identity(browser):
    import psycopg
    command, _ = queued(browser)
    for column, value in (("account_id", 2000), ("match_id", "8984479726"), ("source_sha256", "b" * 64)):
        with pytest.raises(psycopg.Error):
            with database() as connection:
                connection.execute(f"UPDATE replay_jobs SET {column}=%s WHERE id=%s", (value, command["id"]))
