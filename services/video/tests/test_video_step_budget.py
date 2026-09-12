"""Selective-video reservations respect existing per-owner spend controls."""
from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier, Event
import time
from uuid import uuid4

import pytest

from narma_video import budget
from narma_video.db import database, migrate


@pytest.fixture
def sql(monkeypatch):
    url = os.environ.get('TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set isolated TEST_DATABASE_URL')
    monkeypatch.setenv('DATABASE_URL', url)
    monkeypatch.setenv('VIDEO_REQUEST_BUDGET', '250')
    monkeypatch.setenv('VIDEO_OWNER_DAILY_REQUEST_BUDGET', '1000')
    migrate()
    with database() as connection:
        connection.execute("""UPDATE video_ai_budget SET enabled=true,model=%s,price_policy=%s,
            expires_at='2027-01-01T00:00:00Z',limit_microusd=10000000,
            spent_microusd=0,reserved_microusd=0,frozen_reason=NULL WHERE id=1""", (budget.MODEL, budget.POLICY))
    yield monkeypatch
    with database() as connection:
        connection.execute("DELETE FROM video_provider_calls WHERE owner_id LIKE 'synthetic-native-budget-%%'")
        connection.execute("DELETE FROM video_jobs WHERE owner_id LIKE 'synthetic-native-budget-%%'")


def job(owner=None):
    with database() as connection:
        return connection.execute("""INSERT INTO video_jobs(id,owner_id,account_id,nickname,filename,
            size_bytes,source_sha256,state,lease_token,lease_expires_at,analysis_mode)
            VALUES (%s,%s,123,'Player','synthetic.mp4',100,%s,'processing',%s,
                now()+interval '10 minutes','selective_v1') RETURNING *""",
            (uuid4(), owner or 'synthetic-native-budget-' + uuid4().hex, 'a' * 64, uuid4())).fetchone()


def reserve(row):
    with database() as connection:
        return budget.reserve_video_step(connection, row, budget.MODEL, 40000)


def known(call):
    budget.settle(call, {'total_input_tokens': 100, 'total_output_tokens': 20,
        'total_thought_tokens': 0, 'total_tokens': 120})


@pytest.mark.parametrize('change', ['owner', 'lease', 'source', 'deleted_storage', 'deleted_state'])
def test_source_identity_and_deleted_storage_fail_without_reservation(sql, change):
    row = job()
    if change == 'owner':
        row['owner_id'] += '-other'
    elif change == 'lease':
        row['lease_token'] = uuid4()
    elif change == 'source':
        row['source_sha256'] = 'b' * 64
    else:
        with database() as connection:
            if change == 'deleted_storage':
                connection.execute('UPDATE video_jobs SET storage_deleted_at=now() WHERE id=%s', (row['id'],))
            else:
                connection.execute("UPDATE video_jobs SET state='deleted' WHERE id=%s", (row['id'],))
    with pytest.raises(ValueError, match='VIDEO_LEASE_LOST'):
        reserve(row)
    assert budget.status()['reserved_microusd'] == 0


def test_native_calls_use_configured_per_job_limit(sql):
    sql.setenv('VIDEO_REQUEST_BUDGET', '1')
    row = job()
    known(reserve(row))
    with pytest.raises(ValueError, match='VIDEO_REQUEST_BUDGET_EXCEEDED'):
        reserve(row)
    assert budget.status()['spent_microusd'] == 150


def test_daily_limit_combines_jobs_of_one_owner_and_isolates_other_clients(sql):
    sql.setenv('VIDEO_OWNER_DAILY_REQUEST_BUDGET', '1')
    first = job()
    known(reserve(first))
    with pytest.raises(ValueError, match='VIDEO_REQUEST_BUDGET_EXCEEDED'):
        reserve(job(first['owner_id']))
    known(reserve(job()))
    assert budget.status()['spent_microusd'] == 300


def test_lease_expiring_during_reservation_rolls_back_the_uncommitted_hold(sql):
    row = job()
    original = budget._reserve
    def expire_after_reservation(connection, *args, **kwargs):
        call = original(connection, *args, **kwargs)
        connection.execute("UPDATE video_jobs SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE id=%s", (row['id'],))
        return call
    sql.setattr(budget, '_reserve', expire_after_reservation)
    with pytest.raises(ValueError, match='VIDEO_LEASE_LOST'):
        reserve(row)
    assert budget.status()['reserved_microusd'] == 0
    with database() as connection:
        assert connection.execute('SELECT count(*) AS n FROM video_provider_calls WHERE job_id=%s', (row['id'],)).fetchone()['n'] == 0


@pytest.mark.skipif(os.environ.get('NARMA_SYNTHETIC_PGLITE') == '1', reason='Requires native PostgreSQL row/advisory locks')
def test_concurrent_jobs_cannot_bypass_owner_daily_limit(sql):
    sql.setenv('VIDEO_OWNER_DAILY_REQUEST_BUDGET', '1')
    first = job()
    second = job(first['owner_id'])
    barrier = Barrier(2)
    def attempt(row):
        barrier.wait(timeout=5)
        try:
            reserve(row)
            return 'reserved'
        except ValueError as error:
            return str(error)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, (first, second)))
    assert sorted(results) == ['VIDEO_REQUEST_BUDGET_EXCEEDED', 'reserved']


@pytest.mark.skipif(os.environ.get('NARMA_SYNTHETIC_PGLITE') == '1', reason='Requires native PostgreSQL row/advisory locks')
def test_budget_lock_wait_past_lease_never_commits_reservation(sql):
    row = job()
    reached = Event()
    original = budget._reserve
    def entered(*args, **kwargs):
        reached.set()
        return original(*args, **kwargs)
    sql.setattr(budget, '_reserve', entered)
    with database() as connection:
        connection.execute("UPDATE video_jobs SET lease_expires_at=clock_timestamp()+interval '2 seconds' WHERE id=%s", (row['id'],))
    with ThreadPoolExecutor(max_workers=1) as pool:
        with database() as blocker:
            blocker.execute('SELECT id FROM video_ai_budget WHERE id=1 FOR UPDATE')
            result = pool.submit(reserve, row)
            assert reached.wait(timeout=5)
            time.sleep(2.1)
            assert not result.done()
        with pytest.raises(ValueError, match='VIDEO_LEASE_LOST'):
            result.result(timeout=10)
    assert budget.status()['reserved_microusd'] == 0
