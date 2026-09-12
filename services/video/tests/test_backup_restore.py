"""Restore verification against real historical PostgreSQL schemas, without providers."""
from dataclasses import dataclass
import hashlib
import importlib
import os
from pathlib import Path
from uuid import uuid4

import pytest


ROOT = Path(__file__).resolve().parents[3]
OWNER = 'synthetic-restore-owner'
SOURCE_HASH = 'a' * 64
FINISHED = '2026-09-12T00:00:00Z'


@dataclass
class RestoredDatabase:
    connection: object
    version: int
    backup: object

    def query(self, statement):
        return self.connection.execute(statement).fetchone()[0]

    def verify(self):
        return self.backup.verify_restored_database(self.query)

    def insert(self, table, **values):
        from psycopg import sql

        self.connection.execute(
            sql.SQL('INSERT INTO {} ({}) VALUES ({})').format(
                sql.Identifier(table),
                sql.SQL(',').join(map(sql.Identifier, values)),
                sql.SQL(',').join(sql.Placeholder() for _ in values),
            ), tuple(values.values()),
        )

    def rows(self, table):
        from psycopg import sql

        return self.connection.execute(sql.SQL('SELECT to_jsonb(t) FROM {} t ORDER BY id').format(
            sql.Identifier(table))).fetchall()

    def source(self, kind, *, provider='gemini'):
        identifier = uuid4()
        if kind == 'video':
            self.insert('video_jobs', id=identifier, owner_id=OWNER, account_id=123,
                        nickname='Player', filename='restore.mp4', size_bytes=100,
                        source_sha256=SOURCE_HASH)
        elif kind == 'replay':
            self.insert('replay_jobs', id=identifier, owner_id=OWNER, filename='restore.dem',
                        size_bytes=100, requested_nickname='Player', nickname='Player',
                        source_sha256=SOURCE_HASH)
        else:
            identity = ({'provider': provider, 'model': 'gpt-5.6-sol' if provider == 'openai_api'
                         else 'gemini-3.8-flash'} if self.version >= 15 else {})
            self.insert('hermes_tasks', id=identifier, owner_id=OWNER, account_id=123,
                        snapshot_sha256=SOURCE_HASH, snapshot='{}', source_jobs='{}', **identity)
        return identifier

    def gemini_call(self, kind):
        target = {'video': 'job_id', 'replay': 'replay_job_id', 'hermes': 'hermes_task_id'}[kind]
        self.insert('video_provider_calls', owner_id=OWNER, call_kind=kind,
                    **{target: self.source(kind)}, first_frame=0, last_frame=0,
                    budget_id=1, model='gemini-3.8-flash',
                    price_policy='gemini-3.8-flash-standard-2026-09-07',
                    reserved_microusd=10000, billing_status='unknown')
        self.connection.execute('''UPDATE video_ai_budget SET reserved_microusd=
            (SELECT sum(reserved_microusd) FROM video_provider_calls) WHERE id=1''')

    def openai_call(self, kind, *, billing='unknown'):
        identifier = uuid4()
        target = {'video': 'video_job_id', 'replay': 'job_id', 'hermes': 'task_id'}[kind]
        policy = self.connection.execute('SELECT price_policy FROM openai_api_budget').fetchone()[0]
        settled = billing == 'settled'
        values = dict(id=identifier, owner_id=OWNER, request_key=str(identifier),
                      request_sha256='b' * 64, kind=kind,
                      **{target: self.source(kind, provider='openai_api')},
                      lease_token=uuid4(), source_sha256=SOURCE_HASH, budget_id=1,
                      model='gpt-5.6-sol', price_policy=policy, input_token_bound=256,
                      max_output_tokens=256, reserved_microusd=10000,
                      charged_microusd=600 if settled else None,
                      state='succeeded' if settled else billing, billing_status=billing)
        if billing != 'reserved':
            values['finished_at'] = FINISHED
        if settled:
            values.update(output_text='{}', output_sha256=hashlib.sha256(b'{}').hexdigest())
        self.insert('openai_api_calls', **values)
        self.connection.execute('''UPDATE openai_api_budget SET enabled=true,limit_microusd=10000000,
            spent_microusd=(SELECT coalesce(sum(charged_microusd),0) FROM openai_api_calls),
            reserved_microusd=(SELECT coalesce(sum(reserved_microusd),0) FROM openai_api_calls
                WHERE billing_status IN ('reserved','unknown')) WHERE id=1''')
        return identifier


@pytest.fixture
def restored(request, monkeypatch):
    url = os.environ.get('TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set isolated TEST_DATABASE_URL; native PostgreSQL runs in service CI')
    import psycopg
    from psycopg import sql

    monkeypatch.syspath_prepend(str(ROOT / 'ops' / 'timeweb'))
    backup = importlib.import_module('backup')
    version = getattr(request, 'param', 22)
    schema = 'synthetic_restore_' + uuid4().hex
    with psycopg.connect(url) as connection:
        try:
            connection.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
            connection.execute(sql.SQL('SET LOCAL search_path TO {}, pg_catalog').format(sql.Identifier(schema)))
            connection.execute('''CREATE TABLE video_schema_migrations
                (name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())''')
            for migration in sorted((ROOT / 'services' / 'video' / 'migrations').glob('*.sql')):
                if int(migration.name[:3]) <= version:
                    connection.execute(migration.read_text())
                    connection.execute('INSERT INTO video_schema_migrations(name) VALUES (%s)', (migration.name,))
            database = RestoredDatabase(connection, version, backup)
            database.insert('portal_accounts', owner_id=OWNER, email='restore@example.invalid', password_hash='synthetic')
            yield database
        finally:
            # Every table, constraint change and test row belongs to this transaction.
            connection.rollback()


@pytest.mark.parametrize('restored', [6, 11, 17], indirect=True)
def test_historical_gemini_targets_and_unknown_holds_survive(restored):
    kinds = ['video', 'replay'] + (['hermes'] if restored.version >= 11 else [])
    for kind in kinds:
        restored.gemini_call(kind)
    restored.connection.execute("UPDATE video_ai_budget SET frozen_reason='INVALID_PROVIDER_USAGE'")
    before_budget = restored.rows('video_ai_budget')[0][0]
    before_calls = restored.rows('video_provider_calls')

    state = restored.verify()

    assert state['provider']['invalid_call_jobs'] == 0
    assert state['calls'] == len(kinds)
    assert restored.rows('video_provider_calls') == before_calls
    assert restored.rows('video_ai_budget')[0][0] == {**before_budget, 'enabled': False}


@pytest.mark.parametrize('restored,kind', [(6, 'video'), (6, 'replay'), (11, 'hermes'),
                                         (17, 'video'), (17, 'replay'), (17, 'hermes')],
                         indirect=['restored'])
def test_gemini_owner_mismatch_is_rejected(restored, kind):
    restored.gemini_call(kind)
    restored.connection.execute("UPDATE video_provider_calls SET owner_id='another-owner'")
    with pytest.raises(restored.backup.CheckError, match='backup_provider_restore_invariants_failed'):
        restored.verify()


@pytest.mark.parametrize('restored', [6, 17], indirect=True)
def test_invalid_video_frame_range_is_rejected(restored):
    restored.gemini_call('video')
    restored.connection.execute('UPDATE video_provider_calls SET first_frame=2,last_frame=1')
    with pytest.raises(restored.backup.CheckError, match='backup_provider_restore_invariants_failed'):
        restored.verify()


@pytest.mark.parametrize('corruption', ['target', 'frames'])
@pytest.mark.parametrize('restored', [11, 17], indirect=True)
def test_corrupt_hermes_target_and_frames_are_rejected(restored, corruption):
    restored.gemini_call('hermes')
    if corruption == 'target':
        restored.connection.execute('ALTER TABLE video_provider_calls DROP CONSTRAINT provider_call_exactly_one_job')
        restored.connection.execute('UPDATE video_provider_calls SET hermes_task_id=NULL')
    else:
        restored.connection.execute('ALTER TABLE video_provider_calls DROP CONSTRAINT hermes_call_has_no_frames')
        restored.connection.execute('UPDATE video_provider_calls SET last_frame=1')
    with pytest.raises(restored.backup.CheckError, match='backup_provider_restore_invariants_failed'):
        restored.verify()


@pytest.mark.parametrize('restored', [17, 20, 21, 22], indirect=True)
def test_multiple_accounts_require_the_explicit_migration(restored):
    if restored.version < 21:
        restored.connection.execute('ALTER TABLE portal_accounts DROP CONSTRAINT portal_accounts_singleton_key')
    restored.insert('portal_accounts', owner_id='second-owner', email='second@example.invalid', password_hash='synthetic')
    if restored.version < 21:
        with pytest.raises(restored.backup.CheckError, match='backup_portal_restore_invariants_failed'):
            restored.verify()
    else:
        assert restored.verify()['portal']['accounts'] == 2


@pytest.mark.parametrize('restored', [18, 20, 22], indirect=True)
@pytest.mark.parametrize('frozen_reason', [None, 'PROVIDER_ACCOUNTING_UNCERTAIN'])
def test_openai_ledger_and_both_budget_snapshots_survive_restore(restored, frozen_reason):
    restored.gemini_call('video')
    restored.openai_call('video', billing='reserved')
    restored.openai_call('replay', billing='settled')
    if restored.version >= 20:
        restored.openai_call('hermes', billing='unknown')
    for table in ('video_ai_budget', 'openai_api_budget'):
        from psycopg import sql
        restored.connection.execute(sql.SQL('UPDATE {} SET frozen_reason=%s').format(sql.Identifier(table)),
                                    (frozen_reason,))
    budgets = {table: restored.rows(table)[0][0] for table in ('video_ai_budget', 'openai_api_budget')}
    calls = {table: restored.rows(table) for table in ('video_provider_calls', 'openai_api_calls')}

    assert restored.verify()['openai']['invalid_call_jobs'] == 0

    for table, before in budgets.items():
        assert restored.rows(table)[0][0] == {
            **before, 'enabled': False,
            'frozen_reason': frozen_reason or 'RESTORE_REQUIRES_SPEND_RECONCILIATION',
        }
    for table, before in calls.items():
        assert restored.rows(table) == before


@pytest.mark.parametrize('kind', ['video', 'replay', 'hermes'])
@pytest.mark.parametrize('corruption', ['owner', 'target', 'hash'])
def test_invalid_openai_source_identity_is_rejected(restored, kind, corruption):
    call = restored.openai_call(kind)
    if corruption == 'owner':
        restored.connection.execute("UPDATE openai_api_calls SET owner_id='another-owner' WHERE id=%s", (call,))
    elif corruption == 'hash':
        restored.connection.execute('UPDATE openai_api_calls SET source_sha256=%s WHERE id=%s', ('c' * 64, call))
    else:
        from psycopg import sql
        target = {'video': 'video_job_id', 'replay': 'job_id', 'hermes': 'task_id'}[kind]
        restored.connection.execute(sql.SQL('UPDATE openai_api_calls SET {}=%s WHERE id=%s').format(
            sql.Identifier(target)), (uuid4(), call))
    with pytest.raises(restored.backup.CheckError, match='backup_openai_restore_invariants_failed'):
        restored.verify()


@pytest.mark.parametrize('field', ['spent_microusd', 'reserved_microusd'])
def test_openai_budget_amount_mismatch_is_rejected(restored, field):
    from psycopg import sql

    restored.openai_call('video', billing='unknown')
    restored.openai_call('replay', billing='settled')
    restored.connection.execute(sql.SQL('UPDATE openai_api_budget SET {}={}+1').format(
        sql.Identifier(field), sql.Identifier(field)))
    with pytest.raises(restored.backup.CheckError, match='backup_openai_restore_invariants_failed'):
        restored.verify()


@pytest.mark.parametrize('kind', ['video', 'replay', 'hermes'])
@pytest.mark.parametrize('billing', ['unknown', 'settled'])
def test_soft_deleted_openai_sources_keep_their_ledger(restored, kind, billing):
    call = restored.openai_call(kind, billing=billing)
    if kind == 'hermes':
        restored.connection.execute("UPDATE hermes_tasks SET state='stale',snapshot='{}',source_jobs='{}',review=NULL")
    else:
        from psycopg import sql
        restored.connection.execute(sql.SQL("UPDATE {} SET state='deleted',storage_deleted_at=now()").format(
            sql.Identifier(kind + '_jobs')))
    restored.connection.execute('''UPDATE openai_api_calls SET state=%s,
        error_code='OPENAI_SOURCE_DELETED',output_text=NULL,output_sha256=NULL WHERE id=%s''',
        ('failed' if billing == 'settled' else 'unknown', call))
    before_calls = restored.rows('openai_api_calls')
    before_budget = restored.rows('openai_api_budget')[0][0]

    assert restored.verify()['openai']['invalid_call_jobs'] == 0

    assert restored.rows('openai_api_calls') == before_calls
    assert restored.rows('openai_api_budget')[0][0] == {
        **before_budget, 'enabled': False, 'frozen_reason': 'RESTORE_REQUIRES_SPEND_RECONCILIATION',
    }
