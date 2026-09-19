"""Operational receipts reveal aggregates, preserve ledgers, and never call AI."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from narma_video import operations_health as health


def budget(**changes):
    value = dict(enabled=True, frozen=False, limit_microusd=5_000_000,
                spent_microusd=100_000, reserved_microusd=200_000,
                expiry_seconds=7 * 86400,
                expires_at=datetime(2026, 9, 19, tzinfo=timezone.utc))
    value.update(changes)
    return value


def calls(**changes):
    value = dict(unknown_calls=0, unknown_reserved_microusd=0, stale_reserved_calls=0,
                 charged_microusd=100_000, held_microusd=200_000)
    value.update(changes)
    return value


def test_idle_or_busy_workers_use_bounded_heartbeat_and_mode():
    assert health.worker_check("video", {"age_seconds": None}, False)["severity"] == "ok"
    assert health.worker_check("video", {"age_seconds": None}, True)["severity"] == "critical"
    assert health.worker_check("replay", {"age_seconds": 600}, True)["severity"] == "ok"
    assert health.worker_check("replay", {"age_seconds": 901}, True)["severity"] == "critical"


@pytest.mark.parametrize("age,expired,severity", [(None, 0, "ok"), (1799, 0, "ok"),
    (1800, 0, "warning"), (7200, 0, "critical"), (1, 1, "critical")])
def test_queue_wait_or_expired_lease_exposes_stuck_processing(age, expired, severity):
    result = health.queue_check("replay", dict(oldest_queued_seconds=age, queued=1,
        processing=1, expired_leases=expired, failed_last_day=0))
    assert result["severity"] == severity


@pytest.mark.parametrize("total,free,severity", [(80, 20, "ok"), (80, 3, "critical"),
    (80, 6, "warning"), (10, 3, "warning"), (10, 1, "critical")])
def test_disk_absolute_and_relative_headroom(total, free, severity):
    assert health.disk_check(total * health.GIB, free * health.GIB)["severity"] == severity


@pytest.mark.parametrize("change,severity", [({"expiry_seconds": 172800}, "warning"),
    ({"expiry_seconds": 0}, "critical"), ({"enabled": False}, "critical"),
    ({"frozen": True}, "critical"), ({"limit_microusd": 300000}, "critical"),
    ({"limit_microusd": 350000}, "warning")])
def test_allowance_warnings_do_not_change_money_or_deadline(change, severity):
    row = budget()
    row.update(change)
    before = dict(row)
    result = health.openai_checks(row, calls(), True)
    assert result[0]["severity"] == severity
    assert row == before


def test_unknown_holds_remain_in_reserved_and_do_not_become_spend_or_credit():
    result = health.openai_checks(budget(), calls(unknown_calls=1,
        unknown_reserved_microusd=150000), True)
    assert result[0]["metrics"]["available_microusd"] == 4_700_000
    assert result[1]["severity"] == "warning"
    assert result[1]["metrics"]["unknown_reserved_microusd"] == 150000
    assert health.openai_checks(budget(), calls(held_microusd=0), True)[1]["severity"] == "critical"


@pytest.fixture
def operational_db():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set isolated TEST_DATABASE_URL; PostgreSQL coverage runs in native CI")
    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row
    schema = "synthetic_monitor_" + uuid4().hex
    with psycopg.connect(url, row_factory=dict_row) as connection:
        try:
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            connection.execute(sql.SQL("SET search_path TO {}, pg_catalog").format(sql.Identifier(schema)))
            for path in sorted((Path(__file__).resolve().parents[1] / "migrations").glob("*.sql")):
                connection.execute(path.read_text())
            connection.execute("INSERT INTO replay_workers(id) VALUES ('replay')")
            connection.execute("INSERT INTO video_workers(id,model) VALUES ('vision','synthetic-model')")
            connection.execute("""INSERT INTO hermes_workers(id,runtime_revision,automatic_tracking)
                VALUES ('scheduler',%s,true)""", ("a" * 40,))
            connection.execute("""UPDATE openai_api_budget SET enabled=true,limit_microusd=5000000,
                expires_at=now()+interval '7 days' WHERE id=1""")
            connection.execute("""UPDATE video_ai_budget SET enabled=true,frozen_reason=NULL,
                expires_at=now()+interval '7 days' WHERE id=1""")
            connection.commit()
            yield connection
        finally:
            connection.rollback()
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
            connection.commit()


def readonly_snapshot(connection):
    connection.commit()
    connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
    result = health.collect(connection, environment={"VIDEO_ANALYSIS_MODE": "selective_v1",
        "REPLAY_COACH_PROVIDER": "openai_api", "HERMES_PROVIDER": "openai_api"},
        disk_usage=lambda _: SimpleNamespace(total=80 * health.GIB, free=40 * health.GIB))
    connection.rollback()
    return result


def test_native_readonly_snapshot_reports_modes_without_identifiers(operational_db):
    result = readonly_snapshot(operational_db)
    assert result["status"] == "ok"
    assert len(result["checks"]) == 10
    assert all(row["metrics"]["expected"] for row in result["checks"] if row["name"].endswith("_worker"))
    assert "synthetic-model" not in json.dumps(result)


def test_native_queue_expired_leases_and_unknown_accounting(operational_db):
    connection = operational_db
    job, call = uuid4(), uuid4()
    connection.execute("""INSERT INTO video_jobs(id,owner_id,account_id,nickname,filename,size_bytes,
        state,lease_expires_at) VALUES (%s,'private-owner',123,'private-player','private.mp4',100,
        'processing',now()-interval '10 minutes')""", (job,))
    connection.execute("""INSERT INTO openai_api_calls(id,owner_id,request_key,request_sha256,kind,
        video_job_id,lease_token,source_sha256,budget_id,model,price_policy,input_token_bound,
        max_output_tokens,reserved_microusd,state,billing_status,finished_at)
        SELECT %s,'private-owner','private-request',%s,'video',%s,%s,%s,1,model,price_policy,
            1000,256,200000,'unknown','unknown',now() FROM openai_api_budget WHERE id=1""",
        (call, "a" * 64, job, uuid4(), "b" * 64))
    connection.execute("UPDATE openai_api_budget SET reserved_microusd=200000 WHERE id=1")
    before = connection.execute("SELECT spent_microusd,reserved_microusd,expires_at FROM openai_api_budget").fetchone()
    result = readonly_snapshot(connection)
    rows = {r["name"]: r for r in result["checks"]}
    assert rows["video_queue"]["metrics"]["expired_leases"] == 1
    assert rows["video_queue"]["severity"] == "critical"
    assert rows["openai_accounting"]["metrics"]["unknown_reserved_microusd"] == 200000
    assert "private" not in json.dumps(result)
    after = connection.execute("SELECT spent_microusd,reserved_microusd,expires_at FROM openai_api_budget").fetchone()
    assert before == after
