"""Browser video boundaries using an isolated database and synthetic reports.

No model or source-analysis calls are permitted in this suite. The selected
video report is seeded as already processed to check API projection, ownership,
deletion and preserved billing independently from the worker.
"""
import hashlib
import os
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from narma_video import api, budget, chatgpt_auth, openai_budget, openai_provider, video_analysis, web
from narma_video.config import job_directory
from narma_video.db import database, migrate

ORIGIN = 'https://video-portal.example.test'
PASSWORD = 'Synthetic video test passphrase'
INVITE = 'synthetic-video-invite-' + 'A' * 32


@pytest.fixture
def portal(monkeypatch, tmp_path):
    url = os.environ.get('TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set an isolated TEST_DATABASE_URL')
    monkeypatch.setenv('DATABASE_URL', url)
    monkeypatch.setenv('APP_ORIGIN', ORIGIN)
    monkeypatch.setenv('PORTAL_SETUP_TOKEN_SHA256', hashlib.sha256(INVITE.encode()).hexdigest())
    monkeypatch.setenv('PORTAL_SETUP_EXPIRES_AT', '2099-01-01T00:00:00Z')
    monkeypatch.setenv('VIDEO_STORAGE_PATH', str(tmp_path / 'media'))
    monkeypatch.setenv('VIDEO_SERVICE_TOKEN', 'synthetic-service-token-' + 'x' * 40)
    monkeypatch.setenv('VIDEO_ANALYSIS_MODE', 'selective_v1')
    monkeypatch.setenv('REPLAY_COACH_PROVIDER', 'openai_api')
    monkeypatch.setenv('OPENAI_API_KEY', 'synthetic-api-key-never-used')
    monkeypatch.setenv('OPENAI_MODEL', openai_provider.MODEL)
    def forbidden(*args, **kwargs):
        pytest.fail('Browser API must not invoke a model or process a video source')
    monkeypatch.setattr(video_analysis, 'probe_native', forbidden)
    monkeypatch.setattr(video_analysis, 'GeminiVideo', forbidden)
    monkeypatch.setattr(openai_provider, 'perform_reserved', forbidden)
    migrate()
    with database() as connection:
        connection.execute('TRUNCATE portal_accounts CASCADE')
        connection.execute('TRUNCATE portal_auth_limits')
        connection.execute("""UPDATE video_ai_budget SET enabled=true,model=%s,price_policy=%s,
            expires_at='2027-01-01T00:00:00Z',limit_microusd=10000000,
            spent_microusd=0,reserved_microusd=0,frozen_reason=NULL WHERE id=1""", (budget.MODEL, budget.POLICY))
        connection.execute("""UPDATE openai_api_budget SET enabled=true,model=%s,price_policy=%s,
            expires_at=%s,limit_microusd=10000000,spent_microusd=0,reserved_microusd=0,
            frozen_reason=NULL WHERE id=1""", (openai_budget.MODEL, openai_budget.POLICY, openai_budget.PRICE_EXPIRES))
    application = FastAPI()
    web.attach_web(application)
    client = TestClient(application, base_url=ORIGIN, headers={'Origin': ORIGIN})
    response = client.post('/api/auth/setup', json={
        'token': INVITE, 'email': 'owner@example.test', 'password': PASSWORD})
    assert response.status_code == 201, response.text
    with database() as connection:
        owner = connection.execute('SELECT owner_id FROM portal_accounts').fetchone()['owner_id']
        connection.execute("""INSERT INTO portal_dota_profiles
            (owner_id,account_id,nickname,match_id,hero_name,side,source_sha256)
            VALUES (%s,123,'SyntheticPlayer','8984479726','npc_dota_hero_crystal_maiden','radiant',%s)""", (owner, 'a' * 64))
    yield client, owner
    with database() as connection:
        connection.execute("DELETE FROM openai_api_calls WHERE owner_id LIKE 'portal_%' OR owner_id='synthetic-video-other'")
        connection.execute("DELETE FROM video_analysis_steps WHERE job_id IN (SELECT id FROM video_jobs WHERE owner_id LIKE 'portal_%' OR owner_id='synthetic-video-other')")
        connection.execute("DELETE FROM video_provider_calls WHERE owner_id LIKE 'portal_%' OR owner_id='synthetic-video-other'")
        connection.execute("DELETE FROM video_jobs WHERE owner_id LIKE 'portal_%' OR owner_id='synthetic-video-other'")
        connection.execute('TRUNCATE portal_accounts CASCADE')
        connection.execute('TRUNCATE portal_auth_limits')


def command(**overrides):
    return {'id': str(uuid4()), 'filename': 'synthetic.mp4', 'size_bytes': 24,
            'hero': 'Crystal Maiden', 'position': 5, 'mmr': 1500,
            'training_level': 'foundations', **overrides}


def create(portal, **overrides):
    client, _ = portal
    body = command(**overrides)
    response = client.post('/api/videos', json=body)
    assert response.status_code == 201, response.text
    return body


def seed_report(job_id, owner):
    overview = {'focus_nickname': 'SyntheticPlayer', 'focus_player_confirmed': True,
                'identity_evidence': 'Виден ник игрока.', 'hud_readable': True,
                'candidates': [], 'uncertainty': ['Обзор использует редкие кадры.']}
    plan = [{'episode_id': 'e01', 'start_seconds': 30, 'end_seconds': 60,
             'categories': ['support'], 'selection': 'regular', 'question': 'Как помочь союзнику?'},
            {'episode_id': 'e02', 'start_seconds': 100, 'end_seconds': 130,
             'categories': ['map'], 'selection': 'regular', 'question': 'Куда переместиться?'}]
    episode = {'episode_id': 'e01', 'focus_nickname': 'SyntheticPlayer',
               'focus_player_confirmed': True, 'identity_evidence': 'Ник виден.', 'hud_readable': True,
               'observations': [{'observation_id': 'e01-o01', 'video_seconds': 40, 'category': 'support',
                                 'observation': 'Игрок находится рядом с союзником.', 'confidence': 'high'}],
               'uncertainty': []}
    coaching = {'status': 'ready', 'summary': 'Проверь момент помощи союзнику.',
                'points': [{'title': 'Помощь на линии', 'observation': 'Игрок рядом с союзником.',
                            'advice': 'Перед уходом проверь безопасность союзника.', 'evidence_ids': ['e01-o01']}],
                'next_game': [{'title': 'Один фокус', 'action': 'Назови цель своего перемещения.',
                               'measure': 'Проверь похожий момент после игры.', 'evidence_ids': ['e01-o01']}]}
    with database() as connection:
        connection.execute("""UPDATE video_jobs SET state='ready',source_sha256=%s,duration_seconds=600,
            video_plan=%s,video_coaching=%s,analysis_phase='complete',completed_stages=3,total_stages=4
            WHERE id=%s""", ('b' * 64, Jsonb(plan), Jsonb(coaching), job_id))
        for key, phase, result in [('overview', 'overview', overview), ('e01', 'episode', episode)]:
            call = connection.execute("""INSERT INTO video_provider_calls
                (job_id,owner_id,first_frame,last_frame,budget_id,model,price_policy,reserved_microusd,
                 charged_microusd,billing_status,finished_at) VALUES (%s,%s,0,0,1,%s,%s,1000,80,'settled',now())
                RETURNING id""", (job_id, owner, budget.MODEL, budget.POLICY)).fetchone()['id']
            connection.execute("""INSERT INTO video_analysis_steps
                (job_id,step_key,request_sha256,call_id,phase,state,result,finished_at)
                VALUES (%s,%s,%s,%s,%s,'ready',%s,now())""", (job_id, key, 'c' * 64, call, phase, Jsonb(result)))
        connection.execute('UPDATE video_ai_budget SET spent_microusd=160 WHERE id=1')
    (job_directory(job_id) / 'source').write_bytes(b'Synthetic source is never decoded')
    return overview, plan, episode, coaching


def test_browser_preserves_declared_context_and_server_locked_player(portal):
    client, owner = portal
    body = create(portal)
    with database() as connection:
        row = connection.execute('SELECT owner_id,account_id,nickname,hero,position,mmr,training_level,analysis_mode FROM video_jobs WHERE id=%s', (body['id'],)).fetchone()
    assert row == {'owner_id': owner, 'account_id': 123, 'nickname': 'SyntheticPlayer',
                   'hero': 'Crystal Maiden', 'position': 5, 'mmr': 1500,
                   'training_level': 'foundations', 'analysis_mode': 'selective_v1'}
    for spoof in ({'account_id': 999}, {'nickname': 'Other'}, {'owner_id': 'admin'}):
        response = client.post('/api/videos', json={**command(), **spoof})
        assert response.status_code == 400, response.text
    assert client.post('/api/videos', json=command(), headers={'Origin': 'https://evil.example'}).status_code == 403
    assert client.get('/api/videos').json()['videos'][0]['identity_status'] == 'nickname_only'


@pytest.mark.parametrize('change', [
    {'hero': ''}, {'hero': 'x' * 81}, {'position': 0}, {'position': 6},
    {'mmr': -1}, {'mmr': 20001}, {'training_level': 'invented'},
])
def test_invalid_context_is_rejected_before_job_creation(portal, change):
    client, owner = portal
    body = command(**change)
    assert client.post('/api/videos', json=body).status_code == 400
    with database() as connection:
        assert connection.execute('SELECT count(*) AS n FROM video_jobs WHERE owner_id=%s', (owner,)).fetchone()['n'] == 0
    assert not job_directory(body['id']).exists()


def test_idempotent_resume_retains_context_and_rejects_context_changes(portal):
    client, owner = portal
    body = create(portal)
    content = b'\x00\x00\x00\x18ftyp' + bytes(16)
    assert client.put(f"/api/videos/{body['id']}/parts/1", content=content).status_code == 200
    assert client.post('/api/videos', json=body).status_code == 201
    assert client.get(f"/api/videos/{body['id']}").json()['parts'] == [1]
    for change in ({'hero': 'Juggernaut'}, {'position': 1}, {'mmr': 8000}, {'training_level': 'advanced'}):
        assert client.post('/api/videos', json={**body, **change}).status_code == 409
    with database() as connection:
        assert connection.execute('SELECT count(*) AS n FROM video_jobs WHERE owner_id=%s', (owner,)).fetchone()['n'] == 1
        connection.execute('UPDATE openai_api_budget SET enabled=false WHERE id=1')
    # A disabled new-admission gate does not destroy existing upload metadata.
    assert client.post('/api/videos', json=body).status_code == 201
    assert client.get(f"/api/videos/{body['id']}").json()['parts'] == [1]


def test_selective_detail_has_partial_coverage_and_no_foreign_access(portal):
    client, owner = portal
    body = create(portal)
    overview, plan, episode, coaching = seed_report(body['id'], owner)
    result = client.get(f"/api/videos/{body['id']}").json()
    assert result['analysis'] == {'mode': 'selective_v1', 'overview': overview,
        'episodes': [{**plan[0], 'result': episode}, {**plan[1], 'result': None}], 'coaching': coaching,
        'coverage': {'kind': 'selected_episodes', 'complete': False, 'overview_fps': .2, 'detail_fps': 2, 'reviewed_seconds': 30}}
    assert not ({'owner_id', 'source_sha256', 'context_sha256', 'lease_token', 'video_coaching'} & result['video'].keys())
    foreign = command()
    api.create_video(api.CreateVideo(**foreign, account_id=999, nickname='Other'), 'synthetic-video-other')
    spoof = {'X-Narma-Owner': 'synthetic-video-other', 'Authorization': 'Bearer ' + os.environ['VIDEO_SERVICE_TOKEN']}
    for suffix in ('', '/source'):
        assert client.get(f"/api/videos/{foreign['id']}{suffix}", headers=spoof).status_code == 404
    assert client.delete(f"/api/videos/{foreign['id']}", headers=spoof).status_code == 404
    assert {row['id'] for row in client.get('/api/videos').json()['videos']} == {body['id']}


@pytest.mark.parametrize('call_state', ['succeeded', 'unknown'])
def test_delete_clears_private_results_and_preserves_cost_and_unknown_reservations(portal, call_state):
    client, owner = portal
    body = create(portal)
    seed_report(body['id'], owner)
    call_id = uuid4()
    output = '{"summary":"Synthetic private coaching"}' if call_state == 'succeeded' else None
    with database() as connection:
        connection.execute("""INSERT INTO openai_api_calls
            (id,owner_id,request_key,request_sha256,kind,video_job_id,lease_token,source_sha256,
             budget_id,model,price_policy,input_token_bound,max_output_tokens,reserved_microusd,
             charged_microusd,state,billing_status,output_text,output_sha256,started_at,finished_at)
            VALUES (%s,%s,%s,%s,'video',%s,%s,%s,1,%s,%s,100,256,5520,%s,%s,%s,%s,%s,now(),now())""",
            (call_id, owner, 'video:' + body['id'], 'd' * 64, body['id'], uuid4(), 'b' * 64,
             openai_budget.MODEL, openai_budget.POLICY, 600 if output else None, call_state,
             'settled' if output else 'unknown', output,
             hashlib.sha256(output.encode()).hexdigest() if output else None))
        connection.execute('UPDATE openai_api_budget SET spent_microusd=%s,reserved_microusd=%s WHERE id=1',
                           (600 if output else 0, 0 if output else 5520))
        money_before = [connection.execute(f'SELECT spent_microusd,reserved_microusd FROM {table} WHERE id=1').fetchone()
                        for table in ('video_ai_budget', 'openai_api_budget')]
    assert client.delete(f"/api/videos/{body['id']}").status_code == 200
    assert client.get(f"/api/videos/{body['id']}").status_code == 404
    assert client.get(f"/api/videos/{body['id']}/source").status_code == 404
    assert not job_directory(body['id']).exists()
    with database() as connection:
        row = connection.execute('SELECT state,video_plan,video_coaching FROM video_jobs WHERE id=%s', (body['id'],)).fetchone()
        assert row == {'state': 'deleted', 'video_plan': None, 'video_coaching': None}
        assert connection.execute('SELECT count(*) AS n FROM video_analysis_steps WHERE job_id=%s', (body['id'],)).fetchone()['n'] == 0
        assert connection.execute('SELECT count(*) AS n FROM video_provider_calls WHERE job_id=%s', (body['id'],)).fetchone()['n'] == 2
        call = connection.execute('SELECT * FROM openai_api_calls WHERE id=%s', (call_id,)).fetchone()
        assert call['output_text'] is None and call['output_sha256'] is None
        assert call['error_code'] == 'OPENAI_SOURCE_DELETED'
        assert call['billing_status'] == ('settled' if output else 'unknown')
        assert call['charged_microusd'] == (600 if output else None)
        money_after = [connection.execute(f'SELECT spent_microusd,reserved_microusd FROM {table} WHERE id=1').fetchone()
                       for table in ('video_ai_budget', 'openai_api_budget')]
    assert money_after == money_before
    assert client.delete(f"/api/videos/{body['id']}").status_code == 200


def test_platform_capability_never_uses_personal_subscription_for_owner_or_client(portal, monkeypatch):
    client, _ = portal
    def forbidden(*args, **kwargs):
        pytest.fail('Platform capability must not consult personal OAuth')
    monkeypatch.setattr(chatgpt_auth, 'current_connection', forbidden)
    monkeypatch.setattr(chatgpt_auth, '_owner_allowed', forbidden)
    assert client.get('/api/session').json()['coaching'] == {'mode': 'platform', 'available': True, 'personal_connect': False}
    with database() as connection:
        connection.execute('INSERT INTO portal_accounts(owner_id,email,password_hash) VALUES (%s,%s,%s)',
                           ('synthetic-video-other', 'client@example.test', web.password_hash(PASSWORD)))
    customer = TestClient(client.app, base_url=ORIGIN, headers={'Origin': ORIGIN})
    assert customer.post('/api/auth/login', json={'email': 'client@example.test', 'password': PASSWORD}).status_code == 200
    assert customer.get('/api/session').json()['coaching'] == {'mode': 'platform', 'available': True, 'personal_connect': False}
    with database() as connection:
        connection.execute('UPDATE openai_api_budget SET enabled=false WHERE id=1')
    assert customer.get('/api/session').json()['coaching'] == {'mode': 'platform', 'available': False, 'personal_connect': False}
    anonymous = TestClient(client.app, base_url=ORIGIN)
    assert anonymous.get('/api/session').json()['coaching'] == {'mode': 'unavailable', 'available': False, 'personal_connect': False}


@pytest.mark.parametrize('unavailable', ['gemini_budget', 'openai_budget', 'openai_key'])
def test_new_video_requires_funding_before_source_or_provider_work(portal, monkeypatch, unavailable):
    client, owner = portal
    if unavailable == 'openai_key':
        monkeypatch.delenv('OPENAI_API_KEY')
    else:
        table = 'video_ai_budget' if unavailable == 'gemini_budget' else 'openai_api_budget'
        with database() as connection:
            connection.execute(f'UPDATE {table} SET enabled=false WHERE id=1')
    body = command()
    response = client.post('/api/videos', json=body)
    assert response.status_code == 503, response.text
    assert client.get('/api/videos').json()['budget_available'] is False
    assert not job_directory(body['id']).exists()
    with database() as connection:
        assert connection.execute('SELECT count(*) AS n FROM video_jobs WHERE owner_id=%s', (owner,)).fetchone()['n'] == 0
        assert connection.execute('SELECT count(*) AS n FROM video_provider_calls WHERE owner_id=%s', (owner,)).fetchone()['n'] == 0
        assert connection.execute('SELECT count(*) AS n FROM openai_api_calls WHERE owner_id=%s', (owner,)).fetchone()['n'] == 0
