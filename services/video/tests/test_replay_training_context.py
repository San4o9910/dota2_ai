"""Declared skill context stays scoped to one owned replay, never a rank claim."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
from threading import Event
import time
from uuid import uuid4

import psycopg
import pytest
from pydantic import ValidationError

from narma_video import replay_coach as coach, replay_jobs as replay
from narma_video.chatgpt_provider import request_digest
from narma_video.db import database
from test_replay_coach import FACTS, RESULT, prior_report, refreshed_facts
from test_replay_jobs import browser, upload, queued, OWNER
from test_replay_chatgpt import subscription, owned_job


@pytest.mark.parametrize('field,value', [
    ('position', True), ('position', '3'), ('position', 0), ('position', 6),
    ('mmr', True), ('mmr', '1000'), ('mmr', 1000.5), ('mmr', -1), ('mmr', 20001),
    ('training_level', 'immortal'), ('training_level', {}),
])
def test_upload_context_rejects_ambiguous_or_unbounded_values(field, value):
    with pytest.raises(ValidationError):
        replay.CreateReplay.model_validate({'id': uuid4(), 'filename': 'test.dem',
            'size_bytes': 100, field: value})


def test_absent_context_is_backwards_compatible_and_cannot_come_from_report_text():
    request = replay.CreateReplay.model_validate({'id': uuid4(), 'filename': 'test.dem', 'size_bytes': 100})
    assert request.position is request.mmr is request.training_level is None
    encoded, _ = coach.prepare_evidence({**FACTS, 'training_context': {
        'mmr': 14000, 'training_level': 'advanced', 'instructions': 'untrusted'}})
    assert 'training_context' not in json.loads(encoded)
    context = coach.resolve_learning_context({'id': 'offline', 'requested_mmr': 14000}, FACTS)
    assert context['mmr'] is None and context['mmr_source'] == 'unknown'


def test_training_context_is_separate_from_evidence_and_changes_request_identity():
    original = deepcopy(FACTS)
    outputs = []
    for mmr, level in [(None, None), (0, 'foundations'), (1000, 'foundations'), (1000, 'advanced')]:
        encoded, ids = coach.prepare_evidence(FACTS, mmr=mmr, training_level=level)
        payload = json.loads(encoded)
        assert ids == {'death.1', 'buyback.1'}
        assert payload['metrics'] == FACTS['metrics'] and payload['evidence'] == FACTS['evidence']
        assert 'account_id' not in payload['player']
        if mmr is not None:
            declared = payload['training_context']
            assert declared['mmr'] == mmr and declared['mmr_source'] == 'self_reported'
            assert declared['training_level'] == level
            assert declared['classification'] == 'self_reported_training_context_not_match_evidence'
        outputs.append(request_digest(coach.SYSTEM, encoded))
    assert len(set(outputs)) == len(outputs)
    assert FACTS == original


@pytest.mark.parametrize('changed', ['mmr', 'training_level'])
def test_prior_coaching_cannot_migrate_to_different_training_context(changed):
    previous, current = prior_report(), refreshed_facts()
    context = {'position': 3, 'exercise_id': None, 'mmr': 1000, 'training_level': 'foundations'}
    previous['coaching']['context'] = context
    current['coaching'] = {'status': 'unavailable', 'context': {
        **context, changed: 6000 if changed == 'mmr' else 'advanced'}}
    assert not coach.carry_forward_coaching(previous, current)
    current['coaching']['context'] = dict(context)
    assert coach.carry_forward_coaching(previous, current)


def _facts(job):
    return {**deepcopy(FACTS), 'schema_version': 'narma.replay-report.v1', 'match_id': job['match_id'],
            'player': {**FACTS['player'], 'account_id': job['account_id'], 'hero': 'npc_dota_hero_axe'},
            'coverage': {'complete': True, 'source_sha256': job['source_sha256']}}


def test_upload_context_is_immutable_and_reaches_first_coach_before_pool_exists(browser, monkeypatch):
    command, _ = queued(browser, position=3, mmr=1000, training_level='foundations')
    public = browser.get(f"/api/replays/{command['id']}").json()['replay']['training_context']
    assert public == {'position': 3, 'mmr': 1000, 'mmr_source': 'self_reported',
                      'training_level': 'foundations', 'training_level_source': 'player'}
    for field, value in [('position', 2), ('mmr', 4000), ('training_level', 'advanced')]:
        assert browser.post('/api/replays', json={**command, field: value}).status_code == 409
    with database() as connection:
        assert connection.execute('SELECT count(*) AS n FROM hero_pool_matches').fetchone()['n'] == 0
    for column, value in [('requested_position', 2), ('requested_mmr', 6000), ('training_level', 'advanced')]:
        with pytest.raises(psycopg.errors.RaiseException, match='training context is immutable'):
            with database() as connection:
                connection.execute(f'UPDATE replay_jobs SET {column}=%s WHERE id=%s', (value, command['id']))
    job = replay.claim_replay('synthetic-context-worker', command['id'])
    facts = _facts(job)
    # Stale/caller-supplied job preferences cannot replace the owned database row.
    context = coach.resolve_learning_context({**job, 'requested_mmr': 19000}, facts)
    assert context['position'] == 3 and context['position_source'] == 'player'
    assert context['mmr'] == 1000 and context['training_level'] == 'foundations'
    seen = []
    monkeypatch.setenv('REPLAY_COACH_PROVIDER', 'chatgpt_subscription')
    def analyze(job, source, context, encoded, ids):
        seen.append(json.loads(encoded))
        return coach.validate_coaching(RESULT, ids), 'synthetic-call', 'synthetic-generation'
    monkeypatch.setattr(coach, 'analyze_subscription_replay', analyze)
    report = coach.enrich_report(job, facts)
    assert seen[0]['hero_context']['position'] == 3
    assert seen[0]['training_context']['mmr'] == 1000
    assert report['coaching']['context']['training_level'] == 'foundations'
    assert replay.finish_replay(job['id'], job['lease_token'], report)
    with database() as connection:
        metadata = connection.execute('SELECT position FROM hero_pool_matches WHERE owner_id=%s', (OWNER,)).fetchone()
        assert metadata['position'] == 3
        assert connection.execute('SELECT position FROM hero_pool_match_notes WHERE owner_id=%s', (OWNER,)).fetchone()['position'] == 3
    assert browser.get(f"/api/replays/{command['id']}").json()['report']['coaching']['status'] == 'ready'
    # Ordinary writes from each supported UI still synchronize in both
    # directions after the nested capture path has initialized the role.
    with database() as connection:
        connection.execute('UPDATE hero_pool_match_notes SET position=2 WHERE owner_id=%s', (OWNER,))
        assert connection.execute('SELECT position FROM hero_pool_matches WHERE owner_id=%s', (OWNER,)).fetchone()['position'] == 2
        connection.execute('UPDATE hero_pool_matches SET position=5 WHERE owner_id=%s', (OWNER,))
        assert connection.execute('SELECT position FROM hero_pool_match_notes WHERE owner_id=%s', (OWNER,)).fetchone()['position'] == 5
        connection.execute('UPDATE hero_pool_match_notes SET position=NULL WHERE owner_id=%s', (OWNER,))
        assert connection.execute('SELECT position FROM hero_pool_matches WHERE owner_id=%s', (OWNER,)).fetchone()['position'] is None
        connection.execute('UPDATE hero_pool_matches SET position=4 WHERE owner_id=%s', (OWNER,))
        connection.execute('UPDATE hero_pool_matches SET position=NULL WHERE owner_id=%s', (OWNER,))
        assert connection.execute('SELECT position FROM hero_pool_match_notes WHERE owner_id=%s', (OWNER,)).fetchone()['position'] is None


@pytest.mark.parametrize('manual_position', [2, None])
def test_existing_manual_match_role_wins_over_upload_even_when_cleared(browser, manual_position):
    command, _ = queued(browser, position=3, mmr=9000, training_level='advanced')
    job = replay.claim_replay('synthetic-context-worker', command['id'])
    with database() as connection:
        connection.execute('''INSERT INTO hero_pool_matches(owner_id,account_id,match_id,position,first_analyzed_at)
            VALUES (%s,%s,%s,%s,now())''', (OWNER, job['account_id'], job['match_id'], manual_position))
        # Include an explicitly cleared legacy row, rather than treating a
        # missing note as permission to restore the upload's requested role.
        connection.execute('''INSERT INTO hero_pool_match_notes(owner_id,account_id,match_id,position,note)
            VALUES (%s,%s,%s,%s,'Keep my reflection') ON CONFLICT(owner_id,account_id,match_id)
            DO UPDATE SET note=excluded.note''', (OWNER, job['account_id'], job['match_id'], manual_position))
    facts = _facts(job)
    context = coach.resolve_learning_context(job, facts)
    assert context['position'] == manual_position
    assert context['mmr'] == 9000 and context['training_level'] == 'advanced'
    assert replay.finish_replay(job['id'], job['lease_token'], facts)
    with database() as connection:
        assert connection.execute('SELECT position FROM hero_pool_matches WHERE owner_id=%s', (OWNER,)).fetchone()['position'] == manual_position
        assert connection.execute('SELECT position,note FROM hero_pool_match_notes WHERE owner_id=%s', (OWNER,)).fetchone() == {
            'position': manual_position, 'note': 'Keep my reflection'}


@pytest.mark.parametrize('expire_lease', [False, True])
def test_ready_capture_waits_for_manual_role_writer_before_any_replay_row_lock(browser, monkeypatch, expire_lease):
    command, _ = queued(browser, position=3)
    job = replay.claim_replay('synthetic-context-worker', command['id'])
    with database() as connection:
        connection.execute('''INSERT INTO hero_pool_matches(owner_id,account_id,match_id,position,first_analyzed_at)
            VALUES (%s,%s,%s,3,now())''', (OWNER, job['account_id'], job['match_id']))
    started, worker_pid = Event(), []
    @contextmanager
    def observed_database():
        with database() as connection:
            connection.execute("SET LOCAL lock_timeout='5s'")
            worker_pid.append(connection.execute('SELECT pg_backend_pid() AS pid').fetchone()['pid'])
            started.set()
            yield connection
    monkeypatch.setattr(replay, 'database', observed_database)
    with ThreadPoolExecutor(max_workers=1) as workers:
        # Emulate the existing legacy writer's actual lock order: owner then
        # notes, followed by its ordinary trigger's pool update.
        with database() as manual:
            manual.execute("SET LOCAL lock_timeout='3s'")
            manual.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (OWNER,))
            manual.execute('SELECT position FROM hero_pool_match_notes WHERE owner_id=%s FOR UPDATE', (OWNER,))
            result = workers.submit(replay.finish_replay, job['id'], job['lease_token'], _facts(job))
            assert started.wait(2)
            deadline = time.monotonic() + 2
            while True:
                manual.execute('SELECT pg_stat_clear_snapshot()')
                wait = manual.execute('SELECT wait_event FROM pg_stat_activity WHERE pid=%s', (worker_pid[0],)).fetchone()
                if wait and wait['wait_event'] == 'advisory':
                    break
                assert not result.done() and time.monotonic() < deadline, 'Ready capture did not wait on the shared owner lock'
                time.sleep(.01)
            # No replay row may be locked while the owner lock is pending.
            manual.execute('SELECT id FROM replay_jobs WHERE id=%s FOR UPDATE NOWAIT', (job['id'],))
            manual.execute('UPDATE hero_pool_match_notes SET position=2 WHERE owner_id=%s', (OWNER,))
            if expire_lease:
                manual.execute("UPDATE replay_jobs SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE id=%s", (job['id'],))
        assert result.result(timeout=3) is (not expire_lease)
    with database() as connection:
        assert connection.execute('SELECT position FROM hero_pool_matches WHERE owner_id=%s', (OWNER,)).fetchone()['position'] == 2
        assert connection.execute('SELECT position FROM hero_pool_match_notes WHERE owner_id=%s', (OWNER,)).fetchone()['position'] == 2
        state = connection.execute('SELECT state FROM replay_jobs WHERE id=%s', (job['id'],)).fetchone()['state']
        assert state == ('processing' if expire_lease else 'ready')


def test_invalid_upload_identity_never_creates_match_context(browser):
    command, _ = upload(browser, match_id='8984479726', position=3, mmr=1000, training_level='foundations')
    assert browser.post(f"/api/replays/{command['id']}/complete").status_code == 409
    with database() as connection:
        assert connection.execute('SELECT count(*) AS n FROM portal_dota_profiles').fetchone()['n'] == 0
        assert connection.execute('SELECT count(*) AS n FROM hero_pool_matches').fetchone()['n'] == 0


@pytest.mark.parametrize('field,value', [('mmr', 5000), ('training_level', 'advanced')])
def test_subscription_reservation_rejects_context_not_in_immutable_job(owned_job, field, value):
    job, facts, _ = owned_job
    context = {**coach.resolve_learning_context(job, facts), field: value}
    encoded, _ = coach.prepare_evidence(facts, mmr=context['mmr'], training_level=context['training_level'])
    with pytest.raises(ValueError, match='REPLAY_COACH_INPUT_INVALID'):
        coach.reserve_subscription_replay(job, facts, context, coach.SYSTEM, encoded)
    with database() as connection:
        assert connection.execute('SELECT count(*) AS n FROM chatgpt_calls').fetchone()['n'] == 0


def test_foreign_job_cannot_inherit_owned_match_training_context(browser):
    command, _ = queued(browser, position=3, mmr=1000, training_level='foundations')
    job = replay.claim_replay('synthetic-context-worker', command['id'])
    with pytest.raises(ValueError, match='REPLAY_COACH_LEASE_LOST'):
        coach.resolve_learning_context({**job, 'owner_id': 'someone-else'}, _facts(job))
