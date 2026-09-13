"""Evidence accounting and isolated rehearsal: no provider requests or user data."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb
import pytest

from narma_video.db import database
from narma_video.pilot_evidence import collect, _code, _jsonable
spec = importlib.util.spec_from_file_location('pilot_loadcheck',
    Path(__file__).resolve().parents[1] / 'scripts/pilot_loadcheck.py')
loadcheck = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loadcheck)
distribution = loadcheck.distribution
isolated_database = loadcheck.isolated_database
metadata_fixture = loadcheck.metadata_fixture
offline_environment = loadcheck.offline_environment
rehearse = loadcheck.rehearse
validate_target = loadcheck.validate_target


@pytest.mark.parametrize('dsn', [
    '', 'postgresql://user:pass@production.example/narma',
    'postgresql://user:pass@127.0.0.1/narma?hostaddr=72.56.98.68',
    'postgresql://user:pass@127.0.0.1/narma?options=-csearch_path=public',
    'postgresql://user:pass@127.0.0.1/narma?service=production',
    'postgresql://user:pass@db/narma', 'host=localhost dbname=narma',
    'postgresql://user:pass@localhost:invalid/narma',
    'postgresql://user:pass@localhost/',
])
def test_rehearsal_rejects_unsafe_targets_without_connecting(dsn, monkeypatch):
    monkeypatch.delenv('NARMA_PILOT_CI_ISOLATED', raising=False)
    monkeypatch.setattr(psycopg, 'connect', lambda *a, **k: pytest.fail('Must reject before database access'))
    with pytest.raises(ValueError, match='PILOT_LOCAL_TEST_DATABASE_REQUIRED'):
        with isolated_database(dsn):
            pytest.fail('Unsafe target accepted')


def test_container_requires_both_explicit_flags(monkeypatch):
    dsn = 'postgresql://synthetic:unused@db/narma'
    monkeypatch.delenv('NARMA_PILOT_CI_ISOLATED', raising=False)
    with pytest.raises(ValueError):
        validate_target(dsn, ci_container=True)
    monkeypatch.setenv('NARMA_PILOT_CI_ISOLATED', '1')
    with pytest.raises(ValueError):
        validate_target(dsn, ci_container=False)
    assert validate_target(dsn, ci_container=True).hostname == 'db'
    assert validate_target('postgresql://test@127.0.0.1/isolated').hostname == '127.0.0.1'


def test_inherited_libpq_routing_is_removed_before_connection_and_restored(monkeypatch):
    inherited = {'PGHOSTADDR': '203.0.113.10', 'PGSERVICE': 'production',
                 'PGSERVICEFILE': '/private/service', 'PGOPTIONS': '-csearch_path=public'}
    for name, value in inherited.items():
        monkeypatch.setenv(name, value)
    def connect(*args, **kwargs):
        assert not any(name.startswith('PG') for name in os.environ)
        raise RuntimeError('synthetic connection failure')
    monkeypatch.setattr(psycopg, 'connect', connect)
    with pytest.raises(RuntimeError, match='synthetic connection failure'):
        with isolated_database('postgresql://test@127.0.0.1/isolated'):
            pytest.fail('Connection should not open')
    assert {name: os.environ[name] for name in inherited} == inherited


def test_generated_schema_uri_options_round_trip_through_libpq(monkeypatch):
    from psycopg.conninfo import conninfo_to_dict
    from narma_video import db
    import re

    class Admin:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def execute(self, *args):
            pass

    monkeypatch.setattr(psycopg, 'connect', lambda *args, **kwargs: Admin())
    def inspect_generated_connection():
        values = conninfo_to_dict(os.environ['DATABASE_URL'])
        assert re.fullmatch(r'-csearch_path=pilot_rehearsal_[a-f0-9]{32} '
                           r'-cstatement_timeout=8000 -clock_timeout=4000', values['options'])
        assert values['host'] == '127.0.0.1'
        assert values['dbname'] == 'isolated'
        assert values['sslmode'] == 'disable'
        assert values['application_name'] == 'narma-pilot-rehearsal'
        raise RuntimeError('synthetic stop before migrations')
    monkeypatch.setattr(db, 'migrate', inspect_generated_connection)
    with pytest.raises(RuntimeError, match='synthetic stop before migrations'):
        with isolated_database('postgresql://test@127.0.0.1/isolated?sslmode=disable'):
            pytest.fail('Should stop before real PostgreSQL')


def test_minimal_metadata_is_real_queue_input_not_gameplay_report():
    from narma_video.replay_metadata import read_demo_metadata_ranges
    value = metadata_fixture()
    result = read_demo_metadata_ranges(len(value), lambda offset, length: value[offset:offset+length])
    assert result['players'][0]['account_id'] == 1000
    assert result['players'][0]['nickname'] == 'Player_0'
    assert len(value) < 1024


def test_report_json_types_and_safe_diagnostics():
    value = _jsonable({'n': Decimal('5'), 'mean': Decimal('5.5'),
                      'at': datetime(2026, 9, 13, tzinfo=timezone.utc)})
    assert value == {'n': 5, 'mean': 5.5, 'at': '2026-09-13T00:00:00Z'}
    assert _code('OPENAI_TIMEOUT') == 'OPENAI_TIMEOUT'
    assert _code('owner@example.test secret-provider-body') == 'OTHER'
    assert _code('OPENAI_' + 'X'*61) == 'OTHER'
    assert distribution([])['p95_ms'] is None
    assert distribution([0, 10, 20]) == {'samples': 3, 'p50_ms': 10.0, 'p95_ms': 19.0}


def test_evidence_window_rejects_before_query():
    class Forbidden:
        def execute(self, *args):
            pytest.fail('Invalid window must not reach SQL')
    now = datetime.now(timezone.utc)
    for since, until in [(now, now), (now, now-timedelta(days=1)),
                         (now-timedelta(days=367), now), (now.replace(tzinfo=None), now)]:
        with pytest.raises(ValueError, match='PILOT_EVIDENCE_WINDOW_INVALID'):
            collect(Forbidden(), since=since, until=until)


@pytest.fixture
def isolated(monkeypatch):
    dsn = os.environ.get('TEST_DATABASE_URL')
    if not dsn:
        pytest.skip('Requires isolated local/CI TEST_DATABASE_URL')
    # CI's test database is not an application database. The context still
    # creates its own random schema and never migrates or truncates public.
    from urllib.parse import urlsplit
    ci = urlsplit(dsn).hostname == 'db'
    if ci:
        monkeypatch.setenv('NARMA_PILOT_CI_ISOLATED', '1')
    with isolated_database(dsn, ci_container=ci):
        yield


def seed_job(connection, kind, *, coaching=None, state='ready'):
    owner = 'pilot_' + uuid4().hex
    job = uuid4()
    connection.execute("INSERT INTO portal_accounts(owner_id,email,password_hash) VALUES (%s,%s,'unused')",
                       (owner, owner+'@private.example.test'))
    if kind == 'video':
        connection.execute("""INSERT INTO video_jobs(id,owner_id,account_id,nickname,filename,size_bytes,
            source_sha256,state,video_coaching,created_at,updated_at)
            VALUES (%s,%s,123,'private_nickname','private_filename.mp4',100,%s,%s,%s,
                now()-interval '10 minutes',now()-interval '5 minutes')""",
            (job, owner, 'a'*64, state, Jsonb(coaching)))
    else:
        payload = {'match_id': '8984479726', 'player': {'account_id': 123},
                   'coaching': coaching, 'private': 'secret_gameplay_text'}
        connection.execute("""INSERT INTO replay_jobs(id,owner_id,filename,size_bytes,requested_nickname,
            nickname,source_sha256,match_id,account_id,state,progress,result_payload,created_at,updated_at)
            VALUES (%s,%s,'private.dem',100,'private_nickname','private_nickname',%s,'8984479726',123,%s,%s,%s,
                now()-interval '10 minutes',now()-interval '5 minutes')""",
            (job, owner, 'a'*64, state, 100 if state == 'ready' else 0, Jsonb(payload)))
    return job, owner


def seed_openai(connection, kind, job, owner, *, charge=None, state='unknown', source='a'*64):
    call = uuid4()
    column = 'job_id' if kind == 'replay' else 'video_job_id'
    billing = 'unknown' if charge is None else 'settled'
    connection.execute(f"""INSERT INTO openai_api_calls(id,owner_id,request_key,request_sha256,kind,{column},
        lease_token,source_sha256,budget_id,model,price_policy,input_token_bound,max_output_tokens,
        reserved_microusd,charged_microusd,state,billing_status,output_text,output_sha256,
        created_at,started_at,finished_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,1,'synthetic','synthetic',1000,256,400,%s,%s,%s,%s,%s,
            now()-interval '9 minutes',now()-interval '8 minutes',now()-interval '7 minutes')""",
        (call, owner, str(call), 'b'*64, kind, job, uuid4(), source, charge, state, billing,
         'private_model_text' if state == 'succeeded' else None, 'c'*64 if state == 'succeeded' else None))


def seed_gemini(connection, job, owner, charge, frame):
    connection.execute("""INSERT INTO video_provider_calls(job_id,owner_id,first_frame,last_frame,
        budget_id,model,price_policy,reserved_microusd,charged_microusd,billing_status,finished_at,
        created_at) VALUES (%s,%s,%s,%s,1,'synthetic','synthetic',100,%s,'settled',now(),
            now()-interval '9 minutes')""", (job, owner, frame, frame, charge))


def test_evidence_separates_ready_from_openai_success_and_no_join_fanout(isolated):
    with database() as connection:
        video, owner = seed_job(connection, 'video', coaching={'status': 'ready'})
        seed_openai(connection, 'video', video, owner, charge=30, state='succeeded')
        seed_gemini(connection, video, owner, 10, 0)
        seed_gemini(connection, video, owner, 20, 1)
        failed, owner = seed_job(connection, 'video', state='failed')
        seed_openai(connection, 'video', failed, owner)
        seed_job(connection, 'replay', coaching={'status': 'unavailable'})
        replay, owner = seed_job(connection, 'replay', coaching={'status': 'ready'})
        seed_openai(connection, 'replay', replay, owner, charge=7, state='failed')
        replay, owner = seed_job(connection, 'replay', coaching={'status': 'ready'})
        seed_openai(connection, 'replay', replay, owner, charge=11, state='succeeded')
        replay, owner = seed_job(connection, 'replay', coaching={'status': 'ready'})
        seed_openai(connection, 'replay', replay, owner, charge=13, state='succeeded', source='d'*64)
        before = connection.execute('SELECT * FROM openai_api_budget').fetchall()
    now = datetime.now(timezone.utc)
    with database() as connection:
        report = collect(connection, since=now-timedelta(days=1), until=now)
        assert connection.execute('SHOW transaction_read_only').fetchone()['transaction_read_only'] == 'on'
    summaries = {row['kind']: row for row in report['ready_reports']}
    assert summaries['video']['ready_with_confirmed_openai_call'] == 1
    assert summaries['replay']['ready_reports'] == 4
    assert summaries['replay']['ready_with_confirmed_openai_call'] == 1
    costs = {row['kind']: row for row in report['job_cohort_recorded_costs']}
    assert costs['video']['recorded_charge_microusd'] == 60  # 30+10+20, never 30 twice.
    assert costs['video']['ready_mean_recorded_microusd'] == 60
    assert costs['video']['jobs_with_unresolved_cost'] == 1
    assert costs['video']['retained_reservation_microusd'] == 400
    assert costs['replay']['jobs_without_provider_calls'] == 1
    assert report['ledger_link_integrity']['openai_source_mismatches'] == 1
    assert {row['kind']: row for row in report['ready_upload_to_last_update_proxy']}['video']['p50_seconds'] == 300
    encoded = json.dumps(report)
    for private in ('private_nickname', 'private_filename', 'secret_gameplay_text', 'private_model_text', '@private', str(video)):
        assert private not in encoded
    with database() as connection:
        assert connection.execute('SELECT * FROM openai_api_budget').fetchall() == before


def test_evidence_transaction_prevents_writes(isolated):
    now = datetime.now(timezone.utc)
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        with database() as connection:
            collect(connection, since=now-timedelta(days=1), until=now)
            connection.execute('UPDATE openai_api_budget SET limit_microusd=1')


def test_bounded_real_cookie_upload_admission_queue_rehearsal(isolated, tmp_path):
    with offline_environment(str(tmp_path)):
        result = rehearse(users=2, concurrency=4)
    assert result['queued_jobs'] == result['distinct_fenced_claims'] == 4
    assert result['owner_quota_rejections'] == 2
    assert result['provider_calls_created'] == result['gameplay_reports_created'] == 0
    assert result['anonymous_read_rejected'] and result['cross_owner_read_rejected']
    assert result['http_timings']['complete']['samples'] == 4
