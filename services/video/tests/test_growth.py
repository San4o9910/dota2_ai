"""Observed practice, owner-only controls and metered multi-match conversation."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import json

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from narma_video import growth, coach_chat as chat, owner_dashboard as owner, openai_provider as provider
from narma_video.db import database
from narma_video.web import account_required
from test_coach_chat import replay, owned, paid, fake_provider, ANSWER  # noqa: F401
from test_replay_coach import RESULT


def test_progress_compares_only_new_same_scope_and_build_with_known_dates():
    now = datetime.now(timezone.utc)
    plan = {'source_match_id': '1', 'hero': 'hero', 'position': 2, 'exercise_id': 'r2',
        'validity': 'current', 'created_at': now-timedelta(days=2), 'baseline_match_ids': ['1', '8']}
    def fact(match, days, value, **changes):
        return dict(match_id=match, job_id=match, report_sha256='a'*64, hero='hero', position=2,
            engine_build=100, played_at=(now-timedelta(days=days)).isoformat(), date_source='replay',
            chronology_at=(now-timedelta(days=days)).isoformat(), metrics={'repeated_deaths': value}, evidence=[], **changes)
    base = fact('1', 3, 3)
    history = [base, fact('2', 1, 1), {**fact('3', 1, 0), 'position': 5},
        {**fact('4', 1, 0), 'engine_build': 200}, {**fact('5', 1, 0), 'date_source': 'analysis', 'played_at': None},
        fact('6', 4, 0), fact('8', 1, 0), fact('9', -1, 0)]
    result = growth.assess(plan, history)
    assert result['status'] == 'measured' and result['delta'] == -2
    assert [r['match_id'] for r in result['matches']] == ['2']
    assert 'правильность' not in result and 'mastery' not in result
    assert growth.assess({**plan, 'validity': 'scope_changed'}, history)['status'] == 'needs_review'
    assert growth.assess({**plan, 'exercise_id': 'l1', 'position': 5}, history)['metric'] is None


@pytest.fixture
def full(replay):
    job, current = replay
    facts = deepcopy(current['result_payload'])
    facts.update(schema_version='narma.replay-report.v1', coaching={'status': 'ready', **deepcopy(RESULT)})
    facts['player']['team'] = 'radiant'
    with database() as connection:
        connection.execute('UPDATE replay_jobs SET result_payload=%s WHERE id=%s', (Jsonb(facts), job['id']))
        connection.execute('''INSERT INTO hero_pool_matches(owner_id,account_id,match_id,position,first_analyzed_at)
            VALUES (%s,123,%s,5,now()) ON CONFLICT DO NOTHING''', (job['owner_id'], job['match_id']))
        current = chat._current(connection, job['owner_id'], job['id'])
    return job, current


def add_match(job, current, match_id='8984479700'):
    facts = deepcopy(current['result_payload']);facts['match_id'] = match_id;ident = uuid4()
    with database() as connection:
        connection.execute('''INSERT INTO replay_jobs(id,owner_id,filename,size_bytes,requested_nickname,nickname,
            match_id,account_id,source_sha256,state,progress,requested_position,result_payload)
            VALUES (%s,%s,'synthetic.dem',100,'Player','Player',%s,123,%s,'ready',100,5,%s)''',
            (ident, job['owner_id'], match_id, job['source_sha256'], Jsonb(facts)))
        connection.execute('''INSERT INTO hero_pool_matches(owner_id,account_id,match_id,position,first_analyzed_at)
            VALUES (%s,123,%s,5,now()) ON CONFLICT(owner_id,account_id,match_id)
            DO UPDATE SET position=5''', (job['owner_id'], match_id))
    return ident


def test_growth_routes_reject_unauthenticated_or_cross_origin_requests(monkeypatch):
    monkeypatch.setenv('APP_ORIGIN', 'https://narma.example.test')
    app = FastAPI();growth.attach_growth(app);owner.attach_owner_dashboard(app);client = TestClient(app)
    assert client.get('/api/owner/dashboard').status_code == 401
    assert client.get('/api/learning/progress').status_code == 401
    assert client.get(f'/api/replays/{uuid4()}/practice').status_code == 401
    app.dependency_overrides[account_required] = lambda: {'owner_id': 'other'}
    assert client.post(f'/api/replays/{uuid4()}/feedback', json={}).status_code == 403


def test_personal_exercise_persists_answer_and_rejects_other_source(full):
    job, current = full
    data = growth.practice(job['owner_id'], job['id']);assert data['scenarios']
    assert all('reflection' not in scenario for scenario in data['scenarios'])
    scenario = data['scenarios'][0]
    body = growth.Attempt(id=uuid4(), report_sha256=current['report_sha256'], exercise_id=scenario['exercise_id'],
        evidence_id=scenario['episode']['evidence_id'], answer='Сначала проверю доступную цель и союзников.')
    assert growth.submit_attempt(job['owner_id'], job['id'], body)['saved']
    assert growth.submit_attempt(job['owner_id'], job['id'], body)['reflection']['action']
    assert len(growth.practice(job['owner_id'], job['id'])['attempts']) == 1
    with pytest.raises(HTTPException): growth.submit_attempt('foreign', job['id'], body)
    with pytest.raises(HTTPException): growth.submit_attempt(job['owner_id'], job['id'], body.model_copy(update={'evidence_id': 'foreign'}))


def test_feedback_owner_dashboard_and_source_deletion(full):
    job, current = full
    body = growth.Feedback(id=uuid4(), report_sha256=current['report_sha256'], reason='context', comment='Срочная защита базы')
    assert growth.save_feedback(job['owner_id'], job['id'], body) == {'saved': True}
    growth.save_feedback(job['owner_id'], job['id'], body)
    with pytest.raises(HTTPException): owner.dashboard(job['owner_id'])
    with database() as connection:
        connection.execute('UPDATE portal_accounts SET is_platform_owner=true WHERE owner_id=%s', (job['owner_id'],))
    view = owner.dashboard(job['owner_id'])
    assert len(view['feedback']) == 1 and view['feedback'][0]['comment'] == body.comment
    with database() as connection:
        provider.forget_output(connection, owner_id=job['owner_id'], job_id=job['id'])
        assert connection.execute('SELECT count(*) AS n FROM coaching_feedback').fetchone()['n'] == 0


def test_owner_cap_blocks_before_a_paid_attempt_and_preserves_reading(full, monkeypatch):
    job, current = full;calls = fake_provider(monkeypatch)
    with database() as connection:
        connection.execute('INSERT INTO owner_ai_limits(owner_id,limit_microusd) VALUES (%s,0)', (job['owner_id'],))
    body = chat.Question(id=uuid4(), report_sha256=current['report_sha256'], question='Как проверить решение?')
    with pytest.raises(HTTPException) as caught: chat.ask(job['owner_id'], job['id'], body)
    assert caught.value.status_code == 429 and not calls
    assert chat.history(job['owner_id'], job['id'])['turns'] == []
    assert growth.progress(job['owner_id']) == {'plans': []}


def test_series_chat_namespaces_evidence_and_reads_across_matches(full, monkeypatch):
    job, current = full;other = add_match(job, current)
    ref = 'match.8984479700:buyback.1'
    calls = fake_provider(monkeypatch, output={**ANSWER, 'evidence_ids': [ref]})
    body = chat.Question(id=uuid4(), report_sha256=current['report_sha256'], question='Что повторилось в моих играх?', scope='series')
    result = chat.ask(job['owner_id'], job['id'], body)
    assert result['turn']['state'] == 'succeeded', result
    data = json.loads(calls[0]['input'][1]['content'][0]['text'])
    assert len(data['related_replays']) == 1 and data['related_replays'][0]['position'] == 5
    assert ref in {e['id'] for e in data['related_replays'][0]['evidence']}
    assert 'account_id' not in json.dumps(data)
    history = chat.history(job['owner_id'], other, 'series')
    assert len(history['turns']) == 1 and any(r['id'] == ref for r in history['turns'][0]['references'])
    assert chat.history(job['owner_id'], other)['turns'] == []
    with database() as connection:
        connection.execute("UPDATE replay_jobs SET state='deleted',result_payload=NULL WHERE id=%s", (other,))
        provider.forget_output(connection, owner_id=job['owner_id'], job_id=other)
    assert chat.history(job['owner_id'], job['id'], 'series')['turns'] == []
    with database() as connection:
        turn = connection.execute('SELECT * FROM coach_chat_turns WHERE id=%s', (body.id,)).fetchone()
        call = connection.execute('SELECT * FROM openai_api_calls WHERE task_id=%s', (body.id,)).fetchone()
        assert turn['question'] == '' and turn['answer'] is None
        assert call['output_text'] is None and call['charged_microusd'] > 0


def test_changed_related_role_during_response_fences_publication(full, monkeypatch):
    job, current = full;other = add_match(job, current)
    def change():
        with database() as connection:
            connection.execute('UPDATE hero_pool_matches SET position=4 WHERE owner_id=%s AND match_id=%s', (job['owner_id'], '8984479700'))
    calls = fake_provider(monkeypatch, before=change)
    body = chat.Question(id=uuid4(), report_sha256=current['report_sha256'], question='Какие ошибки повторяются?', scope='series')
    assert chat.ask(job['owner_id'], job['id'], body)['context_changed'] is True
    assert len(calls) == 1
