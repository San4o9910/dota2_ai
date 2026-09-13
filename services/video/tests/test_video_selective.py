"""Synthetic selective-video persistence, billing and player-boundary checks.

No provider requests leave the process. PostgreSQL tests require a throwaway
TEST_DATABASE_URL; native PostgreSQL CI remains the concurrency release gate.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from uuid import uuid4

import pytest

from narma_video import budget, openai_budget, openai_provider
from narma_video import video_analysis as analysis
from narma_video.db import database, migrate
from narma_video.video_native import OverviewResult, EpisodeResult, VideoObservation


USAGE = {'total_input_tokens': 100, 'total_output_tokens': 20,
         'total_thought_tokens': 10, 'total_tokens': 130}


def overview():
    return OverviewResult(focus_nickname='synthetic-player', focus_player_confirmed=True,
        identity_evidence='Виден ник выбранного игрока.', hud_readable=True,
        candidates=[], uncertainty=['Просмотрены выбранные кадры.'])


def episode_result(episode_id='e01', *, nickname='synthetic-player', start=5.0,
                   confirmed=True, hud=True, confidence='high'):
    return EpisodeResult(episode_id=episode_id, focus_nickname=nickname,
        focus_player_confirmed=confirmed,
        identity_evidence='Видна подпись выбранного игрока.' if confirmed else '',
        hud_readable=hud, observations=[VideoObservation(
            observation_id=episode_id + '-o01', video_seconds=start, category='support',
            observation='Игрок находится рядом с союзником.', confidence=confidence)] if confirmed else [],
        uncertainty=[] if hud else ['Интерфейс неразборчив.'])


def valid_coaching(evidence_id='e01-o01'):
    return {'summary': 'Виден эпизод рядом с союзником.',
        'points': [{'title': 'Помощь союзнику',
            'observation': 'Игрок находится рядом с союзником.',
            'advice': 'Перед уходом проверь безопасность союзника.', 'evidence_ids': [evidence_id]}],
        'next_game': [{'title': 'Проверка перед уходом',
            'action': 'Перед уходом назови цель и проверь безопасность союзника.',
            'measure': 'После игры проверь условия выбранного перехода.', 'evidence_ids': [evidence_id]}]}


@contextmanager
def immediate_media_slot(heartbeat=None, timeout=600):
    # This suite verifies persistence/accounting; real media and advisory-lock
    # behavior are exercised separately. Keep the real heartbeat/source fence.
    if heartbeat:
        heartbeat()
    yield


@pytest.fixture
def job(monkeypatch, tmp_path):
    url = os.environ.get('TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set isolated TEST_DATABASE_URL for PostgreSQL integration')
    monkeypatch.setenv('DATABASE_URL', url)
    monkeypatch.setenv('VIDEO_STORAGE_PATH', str(tmp_path / 'video'))
    monkeypatch.setenv('OPENAI_API_KEY', 'synthetic-api-key-not-used')
    monkeypatch.setenv('OPENAI_MODEL', openai_provider.MODEL)
    monkeypatch.setattr(analysis, 'media_slot', immediate_media_slot)
    migrate()
    owner, job_id, lease = 'video-synthetic-' + uuid4().hex, uuid4(), uuid4()
    source = b'SYNTHETIC VIDEO SOURCE; never sent to any provider'
    source_hash = hashlib.sha256(source).hexdigest()
    directory = tmp_path / 'video' / str(job_id)
    directory.mkdir(parents=True)
    (directory / 'source').write_bytes(source)
    with database() as connection:
        connection.execute("""UPDATE video_ai_budget SET enabled=true,model=%s,price_policy=%s,
            expires_at='2027-01-01T00:00:00Z',limit_microusd=10000000,
            spent_microusd=0,reserved_microusd=0,frozen_reason=NULL WHERE id=1""", (budget.MODEL, budget.POLICY))
        connection.execute("""UPDATE openai_api_budget SET enabled=true,model=%s,price_policy=%s,
            expires_at=%s::timestamptz,limit_microusd=10000000,
            spent_microusd=0,reserved_microusd=0,frozen_reason=NULL WHERE id=1""",
            (openai_budget.MODEL, openai_budget.POLICY, openai_budget.PRICE_EXPIRES))
        row = connection.execute("""INSERT INTO video_jobs(id,owner_id,account_id,nickname,filename,size_bytes,
            source_sha256,state,lease_token,lease_expires_at,analysis_mode,hero,position,mmr,training_level)
            VALUES (%s,%s,1000,'synthetic-player','synthetic.mp4',%s,%s,'processing',%s,
                now()+interval '1 hour','selective_v1','Dazzle',5,1000,'foundations') RETURNING *""",
            (job_id, owner, len(source), source_hash, lease)).fetchone()
    row['context_sha256'] = 'b' * 64
    yield row
    with database() as connection:
        connection.execute('DELETE FROM openai_api_calls WHERE owner_id=%s', (owner,))
        connection.execute('DELETE FROM video_analysis_steps WHERE job_id=%s', (job_id,))
        connection.execute('DELETE FROM video_provider_calls WHERE owner_id=%s', (owner,))
        connection.execute('DELETE FROM video_jobs WHERE id=%s', (job_id,))


class FakeVision:
    model = budget.MODEL

    def __init__(self):
        self.last_usage = None
        self.request_started = False
        self.calls = []

    def good(self, key='overview', result=None):
        callback = getattr(self, 'before_request', None)
        if callback:
            callback()
        self.request_started = True
        self.calls.append(key)
        self.last_usage = dict(USAGE)
        return result or overview()

    def analyze_overview(self, source, nickname, hero, position, metadata):
        assert (nickname, hero, position) == ('synthetic-player', 'Dazzle', 5)
        return self.good()

    def analyze_episode(self, source, nickname, hero, position, metadata, episode):
        assert (nickname, hero, position) == ('synthetic-player', 'Dazzle', 5)
        return self.good(episode.episode_id,
            episode_result(episode.episode_id, start=episode.start_seconds))


def run_stage(job, vision, invoke=None, *, key='overview', request_hash='c' * 64):
    return analysis.stage(job, vision, key, 'overview', request_hash, 40.0,
                          invoke or vision.good)


def calls_for(job):
    with database() as connection:
        return connection.execute('SELECT * FROM video_provider_calls WHERE job_id=%s ORDER BY id',
                                  (job['id'],)).fetchall()


def test_ready_stage_is_reused_without_second_provider_attempt(job):
    vision = FakeVision()
    first = run_stage(job, vision)
    second = run_stage(job, vision)
    assert first == second == overview().model_dump(mode='json')
    assert vision.calls == ['overview']
    calls = calls_for(job)
    assert len(calls) == 1 and calls[0]['billing_status'] == 'settled'
    assert calls[0]['charged_microusd'] == 188
    with database() as connection:
        assert connection.execute('SELECT completed_stages FROM video_jobs WHERE id=%s',
                                  (job['id'],)).fetchone()['completed_stages'] == 1


def test_changed_request_cannot_reuse_existing_stage(job):
    vision = FakeVision()
    run_stage(job, vision)
    with pytest.raises(ValueError, match='VIDEO_SOURCE_OR_MODEL_CHANGED'):
        run_stage(job, vision, request_hash='d' * 64)
    assert len(calls_for(job)) == 1 and vision.calls == ['overview']


@pytest.mark.parametrize('unavailable', ['missing_api_key', 'disabled_allowance', 'depleted_allowance'])
def test_gemini_stage_does_not_start_without_funded_final_coach(job, monkeypatch, unavailable):
    if unavailable == 'missing_api_key':
        monkeypatch.delenv('OPENAI_API_KEY')
    else:
        with database() as connection:
            change = 'enabled=false' if unavailable == 'disabled_allowance' else 'spent_microusd=limit_microusd'
            connection.execute('UPDATE openai_api_budget SET ' + change + ' WHERE id=1')
    vision = FakeVision()
    with pytest.raises(ValueError, match='VIDEO_COACH_NOT_AVAILABLE'):
        run_stage(job, vision)
    assert vision.calls == [] and calls_for(job) == []


@pytest.mark.parametrize('withdrawal', ['gemini_budget', 'openai_budget', 'deleted_source'])
def test_funding_and_source_rechecked_after_local_render_before_dispatch(job, withdrawal):
    vision = FakeVision()
    def local_render_then_attempt():
        with database() as connection:
            if withdrawal == 'gemini_budget':
                connection.execute('UPDATE video_ai_budget SET enabled=false WHERE id=1')
            elif withdrawal == 'openai_budget':
                connection.execute('UPDATE openai_api_budget SET enabled=false WHERE id=1')
            else:
                connection.execute('UPDATE video_jobs SET storage_deleted_at=now() WHERE id=%s', (job['id'],))
        return vision.good()
    with pytest.raises(ValueError, match='VIDEO_(?:BUDGET_DISABLED|COACH_NOT_AVAILABLE|LEASE_LOST)'):
        run_stage(job, vision, local_render_then_attempt)
    assert vision.calls == []
    call, = calls_for(job)
    assert call['billing_status'] == 'settled' and call['charged_microusd'] == 0
    assert budget.status()['reserved_microusd'] == 0


@pytest.mark.parametrize('uncertain', [False, True])
def test_failed_attempt_is_never_reissued_and_uncertainty_keeps_reservation(job, uncertain):
    vision = FakeVision()
    def fail():
        vision.request_started = uncertain
        vision.calls.append('failed')
        raise TimeoutError('synthetic failure')
    with pytest.raises(TimeoutError):
        run_stage(job, vision, fail)
    with pytest.raises(ValueError, match='VIDEO_STAGE_RECONCILIATION_REQUIRED'):
        run_stage(job, vision)
    assert vision.calls == ['failed']
    call, = calls_for(job)
    state = budget.status()
    assert state['spent_microusd'] == 0
    if uncertain:
        assert call['billing_status'] == 'unknown'
        assert state['reserved_microusd'] == call['reserved_microusd']
    else:
        assert call['billing_status'] == 'settled' and call['charged_microusd'] == 0
        assert state['reserved_microusd'] == 0


def test_local_failure_before_media_slot_does_not_retain_previous_attempt_flag(job, monkeypatch):
    vision = FakeVision()
    run_stage(job, vision)
    assert vision.request_started is True
    @contextmanager
    def unavailable_slot(heartbeat=None, timeout=600):
        raise ValueError('VIDEO_MEDIA_SLOT_TIMEOUT')
        yield
    monkeypatch.setattr(analysis, 'media_slot', unavailable_slot)
    with pytest.raises(ValueError, match='VIDEO_MEDIA_SLOT_TIMEOUT'):
        run_stage(job, vision, key='another')
    assert vision.calls == ['overview']
    second = calls_for(job)[1]
    assert second['billing_status'] == 'settled' and second['charged_microusd'] == 0
    assert budget.status()['reserved_microusd'] == 0


def test_invalid_output_after_billed_attempt_keeps_actual_cost(job):
    vision = FakeVision()
    def invalid_output():
        vision.good()
        raise ValueError('VIDEO_FOCUS_MISMATCH')
    with pytest.raises(ValueError, match='VIDEO_FOCUS_MISMATCH'):
        run_stage(job, vision, invalid_output)
    call, = calls_for(job)
    assert call['billing_status'] == 'settled' and call['charged_microusd'] == 188
    assert budget.status()['reserved_microusd'] == 0


def test_missing_usage_cannot_publish_ready_stage_or_retry(job):
    vision = FakeVision()
    def missing_usage():
        result = vision.good()
        vision.last_usage = None
        return result
    with pytest.raises(ValueError, match='VIDEO_STAGE_RECONCILIATION_REQUIRED'):
        run_stage(job, vision, missing_usage)
    with pytest.raises(ValueError, match='VIDEO_STAGE_RECONCILIATION_REQUIRED'):
        run_stage(job, vision)
    call, = calls_for(job)
    assert vision.calls == ['overview'] and call['billing_status'] == 'unknown'
    with database() as connection:
        assert connection.execute('SELECT state FROM video_analysis_steps WHERE job_id=%s',
                                  (job['id'],)).fetchone()['state'] != 'ready'


@pytest.mark.parametrize('change', ['owner', 'source', 'lease', 'deleted_state', 'deleted_storage'])
def test_stage_rejects_cross_owner_stale_or_deleted_source_without_dispatch(job, change):
    candidate = dict(job)
    if change == 'owner':
        candidate['owner_id'] = 'another-synthetic-owner'
    elif change == 'source':
        candidate['source_sha256'] = 'f' * 64
    elif change == 'lease':
        candidate['lease_token'] = uuid4()
    else:
        with database() as connection:
            statement = "state='deleted'" if change == 'deleted_state' else 'storage_deleted_at=now()'
            connection.execute('UPDATE video_jobs SET ' + statement + ' WHERE id=%s', (job['id'],))
    vision = FakeVision()
    with pytest.raises(ValueError, match='VIDEO_LEASE_LOST'):
        run_stage(candidate, vision)
    assert vision.calls == [] and calls_for(job) == []


def test_lease_loss_after_billed_response_charges_but_does_not_publish(job):
    vision = FakeVision()
    def lose_lease():
        result = vision.good()
        with database() as connection:
            connection.execute('UPDATE video_jobs SET lease_token=%s WHERE id=%s', (uuid4(), job['id']))
        return result
    with pytest.raises(ValueError, match='VIDEO_LEASE_LOST'):
        run_stage(job, vision, lose_lease)
    call, = calls_for(job)
    assert call['charged_microusd'] == 188 and call['billing_status'] == 'settled'
    with database() as connection:
        step = connection.execute('SELECT * FROM video_analysis_steps WHERE job_id=%s', (job['id'],)).fetchone()
    assert step['state'] != 'ready' and step['result'] is None


def test_role_context_changes_for_all_positions_and_preserves_uncertainty():
    inputs = []
    for position in range(1, 6):
        encoded, ids = analysis.coaching_input({'nickname': 'synthetic-player', 'hero': 'Dazzle',
            'position': position, 'mmr': 1000, 'training_level': 'foundations'},
            [episode_result(hud=False, confidence='low')])
        value = json.loads(encoded)
        assert ids == {'e01-o01'}
        assert value['training_context']['position'] == position
        assert value['training_context']['source'] == 'player_declared'
        assert value['observations'][0]['confidence'] == 'low'
        assert value['observations'][0]['hud_readable'] is False
        assert value['uncertainty'] == ['Интерфейс неразборчив.']
        inputs.append(value['role_context'])
    assert len({json.dumps(value, ensure_ascii=False, sort_keys=True) for value in inputs}) == 5


def test_coaching_rejects_another_players_observations():
    with pytest.raises(ValueError, match='VIDEO_.*(?:FOCUS|EVIDENCE|IDENTITY).*'):
        analysis.coaching_input({'nickname': 'synthetic-player', 'position': 5},
                                [episode_result(nickname='another-player')])


def test_duplicate_evidence_is_rejected():
    with pytest.raises(ValueError, match='VIDEO_EVIDENCE_MISMATCH'):
        analysis.coaching_input({'nickname': 'synthetic-player', 'position': 5},
                                [episode_result(), episode_result()])


def test_unconfirmed_player_skips_paid_coach(monkeypatch):
    def unexpected_call(*args, **kwargs):
        pytest.fail('Unconfirmed player must not trigger OpenAI')
    monkeypatch.setattr(openai_provider, 'reserve_call', unexpected_call)
    result = analysis.coach({'nickname': 'synthetic-player', 'position': 5},
                            [episode_result(confirmed=False)])
    assert result['status'] == 'insufficient_evidence'


def test_coach_reuses_exact_paid_response_without_second_dispatch(job, monkeypatch):
    seen = []
    def generate(payload):
        seen.append(payload)
        return {'status': 'completed', 'model': openai_provider.MODEL, 'service_tier': 'default',
            'output': [{'type': 'message', 'role': 'assistant', 'status': 'completed',
                        'content': [{'type': 'output_text', 'text': json.dumps(valid_coaching())}]}],
            'usage': {'input_tokens': 100, 'output_tokens': 30, 'total_tokens': 130,
                      'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 0}}}
    monkeypatch.setattr(openai_provider, '_generate', generate)
    first = analysis.coach(job, [episode_result()])
    second = analysis.coach(job, [episode_result()])
    assert first == second and first['status'] == 'ready' and len(seen) == 1
    evidence_message, = [item for item in seen[0]['input'] if item['role'] == 'user']
    value = json.loads(evidence_message['content'][0]['text'])
    assert value['training_context']['position'] == 5
    with database() as connection:
        calls = connection.execute('SELECT * FROM openai_api_calls WHERE owner_id=%s', (job['owner_id'],)).fetchall()
    assert len(calls) == 1 and calls[0]['charged_microusd'] == 1000


def test_run_selective_persists_plan_observations_and_coaching(job, monkeypatch):
    vision = FakeVision()
    monkeypatch.setattr(analysis, 'probe_native', lambda source:
                        {'duration_seconds': 120.0, 'first_pts_seconds': 0.0, 'width': 1280, 'height': 720})
    received = []
    def coach(given_job, results):
        received.append((given_job, results))
        return {'status': 'ready', **valid_coaching(results[0].observations[0].observation_id)}
    monkeypatch.setattr(analysis, 'coach', coach)
    analysis.run_selective(job, vision)
    with database() as connection:
        current = connection.execute('SELECT * FROM video_jobs WHERE id=%s', (job['id'],)).fetchone()
        public = analysis.public_analysis(connection, current)
    assert current['state'] == 'ready' and current['analysis_phase'] == 'complete'
    assert current['lease_token'] is None and current['lease_expires_at'] is None
    assert current['completed_stages'] == current['total_stages'] == len(current['video_plan']) + 2
    assert len(vision.calls) == len(current['video_plan']) + 1 and len(received) == 1
    assert public['coverage']['complete'] is False and public['coverage']['kind'] == 'selected_episodes'
    assert all(item['result'] is not None for item in public['episodes'])
    assert public['coaching']['status'] == 'ready'


def test_full_pipeline_resumes_saved_stages_without_recalling_vision(job, monkeypatch):
    vision = FakeVision()
    monkeypatch.setattr(analysis, 'probe_native', lambda source:
                        {'duration_seconds': 120.0, 'first_pts_seconds': 0.0})
    def crash_before_coach(*args, **kwargs):
        raise KeyboardInterrupt('synthetic worker crash')
    monkeypatch.setattr(analysis, 'coach', crash_before_coach)
    with pytest.raises(KeyboardInterrupt):
        analysis.run_selective(job, vision)
    attempts = list(vision.calls)
    monkeypatch.setattr(analysis, 'coach', lambda *args: {'status': 'insufficient_evidence'})
    analysis.run_selective(job, vision)
    assert vision.calls == attempts
    with database() as connection:
        assert connection.execute('SELECT state FROM video_jobs WHERE id=%s', (job['id'],)).fetchone()['state'] == 'ready'


def test_coach_failure_preserves_visual_evidence_without_provider_retry(job, monkeypatch):
    vision = FakeVision()
    monkeypatch.setattr(analysis, 'probe_native', lambda source:
                        {'duration_seconds': 120.0, 'first_pts_seconds': 0.0})
    def unavailable(*args):
        raise ValueError('OPENAI_NOT_CONFIGURED')
    monkeypatch.setattr(analysis, 'coach', unavailable)
    analysis.run_selective(job, vision)
    with database() as connection:
        row = connection.execute('SELECT * FROM video_jobs WHERE id=%s', (job['id'],)).fetchone()
        public = analysis.public_analysis(connection, row)
    assert row['state'] == 'ready'
    assert public['coaching'] == {'status': 'unavailable', 'failure_code': 'OPENAI_NOT_CONFIGURED'}
    assert public['episodes'] and all(item['result'] for item in public['episodes'])


def test_modified_local_source_never_reaches_vision(job):
    from narma_video.config import job_directory
    path = job_directory(job['id']) / 'source'
    original = path.read_bytes()
    path.write_bytes(b'x' * len(original))
    vision = FakeVision()
    with pytest.raises(ValueError, match='VIDEO_SOURCE_CHANGED'):
        analysis.run_selective(job, vision)
    assert vision.calls == [] and calls_for(job) == []
