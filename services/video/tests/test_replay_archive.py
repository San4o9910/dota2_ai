"""Retaining evidence must not require retaining hundreds of MB of replay media."""
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from narma_video import replay_archive as archive
from narma_video.db import database
from test_replay_jobs import browser, queued, OWNER, ORIGIN, replay


def prepared(browser):
    command, _ = queued(browser)
    job_id = command["id"]
    claim = replay.claim_replay("synthetic-archive-worker", job_id)
    report = {"match_id": "8963624400", "player": {"account_id": 1000},
              "synthetic_test_only": True}
    assert replay.finish_replay(job_id, claim["lease_token"], report)
    return job_id, report


def test_source_cleanup_keeps_report_identity_and_budget_and_is_idempotent(browser):
    archive.attach_replay_archive(browser.app)
    job_id, report = prepared(browser)
    with database() as connection:
        before = connection.execute("SELECT * FROM video_ai_budget WHERE id=1").fetchone()
    endpoint = f"/api/replays/{job_id}/source"
    assert browser.delete(endpoint).json() == {"source_deleted": True, "report_retained": True}
    assert browser.delete(endpoint).status_code == 200
    assert not replay.replay_directory(job_id).exists()
    detail = browser.get(f"/api/replays/{job_id}").json()
    assert detail["report"] == report and detail["replay"]["state"] == "ready"
    with database() as connection:
        row = connection.execute("SELECT * FROM replay_jobs WHERE id=%s", (job_id,)).fetchone()
        assert row["storage_deleted_at"] is not None and row["source_sha256"]
        assert row["attempt"] == 1
        assert connection.execute("SELECT * FROM video_ai_budget WHERE id=1").fetchone() == before


def test_source_cleanup_auth_csrf_and_processing_guard(browser):
    archive.attach_replay_archive(browser.app)
    command, _ = queued(browser)
    job_id = command["id"]
    endpoint = f"/api/replays/{job_id}/source"
    anonymous = TestClient(browser.app, base_url=ORIGIN, headers={"Origin": ORIGIN})
    assert anonymous.delete(endpoint).status_code == 401
    assert browser.delete(endpoint, headers={"Origin": "https://other.example"}).status_code == 403
    assert browser.delete(endpoint).status_code == 409
    with pytest.raises(HTTPException) as refused:
        archive.remove_source(job_id, "synthetic-other-owner")
    assert refused.value.status_code == 404
    assert (replay.replay_directory(job_id) / "source.dem").exists()


def test_cleanup_failure_retains_disk_reservation_and_report(browser, monkeypatch):
    job_id, report = prepared(browser)
    def unavailable(*args, **kwargs):
        raise PermissionError("synthetic failure")
    monkeypatch.setattr(archive.shutil, "rmtree", unavailable)
    with pytest.raises(HTTPException) as refused:
        archive.remove_source(job_id, OWNER)
    assert refused.value.status_code == 503
    with database() as connection:
        row = connection.execute("SELECT state,storage_deleted_at,result_payload FROM replay_jobs WHERE id=%s", (job_id,)).fetchone()
    assert row == {"state": "ready", "storage_deleted_at": None, "result_payload": report}
