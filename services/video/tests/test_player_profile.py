"""Private progressive onboarding; all data synthetic, providers offline."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from narma_video import player_profile as profiles, player_program
from narma_video.db import database
from test_web import portal, setup, profile_seed
from test_portal_access import guest
from test_portal_registration import register
from test_learning import client, positioned, plan
from test_hero_pool import browser, OWNER

BASE = {'goal': 'consistency', 'position': 3, 'rank_band': 'unknown',
        'experience': 'returning', 'matches_per_week': 'rare', 'practice_minutes': 0,
        'explanation': 'short', 'tone': 'calm'}


@pytest.fixture
def profile_client(portal):
    profiles.attach_player_profile(portal.app)
    setup(portal)
    return portal


def put(client, answers, revision=0, action='save', step=1):
    return client.put('/api/player-profile', json={'expected_revision': revision,
                      'answers': answers, 'action': action, 'last_step': step})


def test_session_origin_and_strict_fields(profile_client):
    visitor = guest(profile_client)
    assert visitor.get('/api/player-profile').status_code == 401
    for method in ('put', 'delete'):
        response = getattr(profile_client, method)('/api/player-profile', headers={'Origin': 'https://foreign.example'})
        assert response.status_code == 403
    for patch in ({'owner_id': 'someone-else'}, {'position': True}, {'practice_minutes': False}, {'heroes': ['x']*4},
                  {'goal_note': 'x'*161}, {'scenarios': {'bogus': {'choice': 'act'}}},
                  {'rank_band': 'secret'}, {'experience': 'diagnosis'}):
        assert put(profile_client, patch).status_code == 400
    assert put(profile_client, {}, action='finish').status_code == 400
    assert profile_client.put('/api/player-profile', content='x'*9000, headers={'Content-Type':'application/json'}).status_code == 413
    assert profile_client.put('/api/player-profile', content='plain', headers={'Content-Type':'text/plain'}).status_code == 415


def test_steps_resume_without_cloning_owner_and_do_not_spend(profile_client):
    c = profile_client
    with database() as con:
        before = con.execute('SELECT count(*) AS n FROM openai_api_calls').fetchone()['n']
    assert c.get('/api/player-profile').json()['profile']['state'] == 'not_started'
    first = put(c, {'goal': 'decisions'});assert first.status_code == 200
    assert first.json()['profile']['state'] == 'partial'
    assert c.get('/api/player-profile').json()['profile']['answers'] == {'goal':'decisions'}
    # Lost response retries are idempotent, and older tabs cannot overwrite changes.
    assert put(c, {'goal':'decisions'}).json()['profile']['revision'] == 1
    assert put(c, {'goal':'ranked'}).status_code == 409
    saved = put(c, BASE, 1, 'finish', 7);assert saved.status_code == 200, saved.text
    assert saved.json()['profile']['state'] == 'ready'
    assert 'Отдельная тренировка не нужна' in saved.json()['guidance']['dose']
    assert c.get('/api/player-profile').headers['cache-control'] == 'no-store'
    other = guest(c)
    assert register(other,'different@example.test').status_code == 201
    assert other.get('/api/player-profile').json()['profile']['answers'] == {}
    assert put(other, {**BASE,'practice_minutes':20}, action='finish', step=7).status_code == 200
    assert c.get('/api/player-profile').json()['profile']['answers']['practice_minutes'] == 0
    assert other.get('/api/player-profile?owner_id=owner').json()['profile']['answers']['practice_minutes'] == 20
    c.delete('/api/player-profile')
    assert other.get('/api/player-profile').json()['profile']['state'] == 'ready'
    assert c.get('/api/player-profile').json()['profile']['answers'] == {}
    assert put(c, BASE, 2, 'finish', 7).status_code == 409
    with database() as con:
        assert con.execute('SELECT count(*) AS n FROM openai_api_calls').fetchone()['n'] == before


def test_same_owner_concurrent_answers_never_silently_overwrite(profile_client):
    owner = profile_seed()
    barrier = Barrier(2)
    def write(goal):
        barrier.wait(timeout=10)
        try:
            return profiles.save(owner, profiles.Update(expected_revision=0, answers={'goal':goal}))['profile']['revision']
        except HTTPException as error:
            return error.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(write, ('consistency','decisions'))) == [1,409]


def test_profile_snapshot_keeps_existing_plan_and_match_facts(client):
    profiles.attach_player_profile(client.app);player_program.attach_program(client.app)
    saved=put(client, BASE, action='finish', step=7);assert saved.status_code == 200, saved.text
    job=positioned(client);active=plan(client, job)
    assert active['exercise']['personalization']['revision'] == 1
    with database() as con:
        before=con.execute('SELECT result_payload FROM replay_jobs WHERE id=%s',(job,)).fetchone()['result_payload']
    assert put(client,{**BASE,'practice_minutes':20,'explanation':'detailed'},1,'finish',7).status_code == 200
    data=client.get('/api/program').json()
    assert data['guidance']['revision'] == 2
    assert data['focus']['exercise']['personalization']['revision'] == 1
    assert '20 минут' in data['guidance']['dose']
    assert client.delete('/api/player-profile').status_code == 200
    data=client.get('/api/program').json()
    assert data['guidance'] is None
    assert 'personalization' not in data['focus']['exercise']
    with database() as con:
        assert con.execute('SELECT result_payload FROM replay_jobs WHERE id=%s',(job,)).fetchone()['result_payload'] == before
        assert con.execute('SELECT coaching_profile FROM learning_plans WHERE id=%s',(active['id'],)).fetchone()['coaching_profile'] == {}


def test_same_evidence_different_practice_and_safe_scoped_snapshot():
    first={'revision':1,'answers':BASE}
    second={'revision':2,'answers':{**BASE,'practice_minutes':10,'experience':'regular','explanation':'detailed','focus_skill':'items'}}
    assert profiles.guidance(first)['dose'] != profiles.guidance(second)['dose']
    assert profiles.guidance(first)['action'] != profiles.guidance(second)['action']
    a=profiles.Answers.model_validate({'goal':'custom','goal_note':'<script>synthetic</script>',
        'scenarios':{'map':{'choice':'unknown','reason':'Нужно увидеть больше информации.'}}})
    snapshot=profiles.snapshot({'revision':2,'answers':a.model_dump(exclude_unset=True)|{'email':'secret@example.test','account_id':123}})
    assert snapshot['classification']=='self_report_not_match_evidence'
    assert 'email' not in snapshot['preferences'] and 'account_id' not in snapshot['preferences']
    assert snapshot['preferences']['scenarios']['map']['choice']=='unknown'
