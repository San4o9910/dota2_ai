"""Prove the legacy cutover fence using PostgreSQL, with no model requests."""
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import quote
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'ops/timeweb'))
from quiesce_workers import PROBE, receive

TABLES = ('replay_jobs', 'video_jobs', 'hermes_tasks', 'openai_api_calls', 'chatgpt_calls', 'video_provider_calls')


@pytest.fixture
def isolated_database():
    base = os.environ.get('TEST_DATABASE_URL')
    if not base:
        pytest.skip('Set an isolated TEST_DATABASE_URL')
    schema = 'quiesce_' + uuid4().hex
    url = base + ('&' if '?' in base else '?') + 'options=' + quote('-csearch_path=' + schema)
    with psycopg.connect(base, autocommit=True) as connection:
        connection.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    try:
        with psycopg.connect(url) as connection:
            for table in TABLES:
                connection.execute(sql.SQL('CREATE TABLE {} (state text,billing_status text)').format(sql.Identifier(table)))
        yield url
    finally:
        with psycopg.connect(base, autocommit=True) as connection:
            connection.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


def probe(url):
    # The old deployed modules are imported in the child. API/model credentials
    # are deliberately absent from this synthetic integration environment.
    return subprocess.Popen([sys.executable, '-u', '-c', PROBE, 'synthetic-challenge'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
        env={'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'DATABASE_URL': url,
             'PYTHONPATH': os.pathsep.join(str(path) for path in sys.path if path)})


def close_probe(process):
    if process.poll() is None:
        try:
            process.stdin.write(b'release\n')
            process.stdin.flush()
        except BrokenPipeError:
            pass
    process.stdin.close()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    process.stdout.close()


def test_idle_guard_blocks_claim_and_dispatch_until_explicit_release(isolated_database):
    with psycopg.connect(isolated_database) as connection:
        connection.execute("INSERT INTO replay_jobs(state) VALUES ('queued')")
    process = probe(isolated_database)
    try:
        assert receive(process, 15)['status'] == 'locked'
        for table in TABLES:
            with psycopg.connect(isolated_database) as connection:
                connection.execute("SET LOCAL lock_timeout='150ms'")
                with pytest.raises(psycopg.errors.LockNotAvailable):
                    connection.execute(sql.SQL("INSERT INTO {}(state) VALUES ('calling')").format(sql.Identifier(table)))
                connection.rollback()
        process.stdin.write(b'ping\n')
        process.stdin.flush()
        assert receive(process, 6)['status'] == 'locked'
    finally:
        close_probe(process)
    assert process.returncode == 0
    with psycopg.connect(isolated_database) as connection:
        assert connection.execute("UPDATE replay_jobs SET state='processing' WHERE state='queued' RETURNING state").fetchone() == ('processing',)


@pytest.mark.parametrize('table,state,billing', [
    ('replay_jobs', 'processing', None), ('video_jobs', 'processing', None),
    ('hermes_tasks', 'running', None), ('openai_api_calls', 'calling', 'reserved'),
    ('chatgpt_calls', 'reserved', None), ('video_provider_calls', None, 'reserved'),
])
def test_active_or_unfinished_attempt_refuses_without_changing_state(isolated_database, table, state, billing):
    with psycopg.connect(isolated_database) as connection:
        connection.execute(sql.SQL('INSERT INTO {}(state,billing_status) VALUES (%s,%s)').format(sql.Identifier(table)),
                           (state, billing))
    process = probe(isolated_database)
    try:
        assert receive(process, 15) == {'status': 'busy'}
    finally:
        close_probe(process)
    assert process.returncode == 2
    with psycopg.connect(isolated_database) as connection:
        assert connection.execute(sql.SQL('SELECT state,billing_status FROM {}').format(sql.Identifier(table))).fetchall() == [(state, billing)]


def test_historical_unknown_charges_stay_reserved_and_do_not_block_idle_cutover(isolated_database):
    with psycopg.connect(isolated_database) as connection:
        for table in ('openai_api_calls', 'chatgpt_calls', 'video_provider_calls'):
            connection.execute(sql.SQL("INSERT INTO {}(state,billing_status) VALUES ('unknown','unknown')").format(sql.Identifier(table)))
    process = probe(isolated_database)
    try:
        assert receive(process, 15)['status'] == 'locked'
    finally:
        close_probe(process)
    with psycopg.connect(isolated_database) as connection:
        for table in ('openai_api_calls', 'chatgpt_calls', 'video_provider_calls'):
            assert connection.execute(sql.SQL('SELECT state,billing_status FROM {}').format(sql.Identifier(table))).fetchall() == [('unknown', 'unknown')]
