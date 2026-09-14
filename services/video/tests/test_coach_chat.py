"""Conversation isolation and accounting, using an offline provider only."""
from copy import deepcopy
import json
from uuid import uuid4

import pytest
from fastapi import HTTPException, FastAPI
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from narma_video import coach_chat as chat, openai_provider as provider, openai_budget as budget
from narma_video.db import database
from narma_video.web import account_required
from test_replay_openai_api import paid, owned  # noqa: F401 — isolated native PostgreSQL fixtures

ANSWER = {'answer': 'В журнале после смерти записан выкуп. Проверь, какую задачу можно было выполнить.',
          'next_step': 'Перед возвращением назови достижимую цель.', 'evidence_ids': ['buyback.1']}


@pytest.fixture
def replay(owned):
    job, facts = owned
    with database() as connection:
        connection.execute("UPDATE replay_jobs SET state='ready',result_payload=%s WHERE id=%s", (Jsonb(facts), job['id']))
        current = chat._current(connection, job['owner_id'], job['id'])
    return job, current


def command(current, **changes):
    return chat.Question(id=uuid4(), report_sha256=current['report_sha256'], question='Как проверить решение о выкупе?', **changes)


def fake_provider(monkeypatch, output=None, before=None, usage=True):
    calls = []
    def generate(payload):
        calls.append(payload)
        if before:
            before()
        result = {'model': provider.MODEL, 'status': 'completed', 'output': [{'type': 'message', 'role': 'assistant',
            'content': [{'type': 'output_text', 'text': json.dumps(output or ANSWER)}]}]}
        if usage:
            result['usage'] = {'input_tokens': 100, 'output_tokens': 100, 'total_tokens': 200}
        return result
    monkeypatch.setattr(provider, '_generate', generate)
    return calls


def test_question_and_answer_reject_invented_references_and_markup():
    for question in (' ', '\x00'):
        with pytest.raises(ValueError):
            chat.Question(id=uuid4(), report_sha256='a'*64, question=question)
    for changes in ({'evidence_ids': ['foreign']}, {'evidence_ids': ['buyback.1']*2}, {'answer': '<script>bad</script>'}):
        with pytest.raises(ValueError):
            chat.validate_answer({**ANSWER, **changes}, {'buyback.1'})
    assert chat.validate_answer(ANSWER, {'buyback.1'}) == ANSWER


def test_chat_routes_require_session_and_same_origin(monkeypatch):
    app = FastAPI();chat.attach_coach_chat(app)
    client = TestClient(app)
    assert client.get(f'/api/replays/{uuid4()}/chat').status_code == 401
    app.dependency_overrides[account_required] = lambda: {'owner_id': 'synthetic'}
    monkeypatch.setenv('APP_ORIGIN', 'https://narma.example.test')
    response = client.post(f'/api/replays/{uuid4()}/chat', json={})
    assert response.status_code == 403


def test_chat_is_metered_idempotent_and_history_is_read_only(replay, monkeypatch):
    job, current = replay;calls = fake_provider(monkeypatch)
    body = command(current, evidence_id='buyback.1')
    assert chat.history(job['owner_id'], job['id'])['turns'] == []
    assert not calls
    first = chat.ask(job['owner_id'], job['id'], body)
    assert first['turn']['state'] == 'succeeded', first
    assert chat.ask(job['owner_id'], job['id'], body) == first
    assert len(calls) == 1
    data = json.loads(calls[0]['input'][1]['content'][0]['text'])
    assert data['selected_evidence_id'] == 'buyback.1'
    assert 'account_id' not in data['replay']['player']
    history = chat.history(job['owner_id'], job['id'])
    assert history['turns'] == [first['turn']]
    assert 'input_data' not in history['turns'][0]
    with database() as connection:
        row = connection.execute('SELECT * FROM openai_api_calls WHERE task_id=%s', (body.id,)).fetchone()
        assert row['kind'] == 'chat' and row['billing_status'] == 'settled'
        assert budget.status(connection)['spent_microusd'] > 0
    second = command(current)
    assert chat.ask(job['owner_id'], job['id'], second)['turn']['state'] == 'succeeded'
    assert json.loads(calls[1]['input'][1]['content'][0]['text'])['history'][0]['answer'] == ANSWER


def test_chat_rejects_foreign_owner_stale_report_and_evidence_before_spending(replay, monkeypatch):
    job, current = replay;calls = fake_provider(monkeypatch)
    with pytest.raises(HTTPException) as caught:
        chat.ask('another-owner', job['id'], command(current))
    assert caught.value.status_code == 404
    with pytest.raises(HTTPException):
        chat.ask(job['owner_id'], job['id'], command({**current, 'report_sha256': 'b'*64}))
    with pytest.raises(HTTPException):
        chat.ask(job['owner_id'], job['id'], command(current, evidence_id='foreign'))
    assert not calls


def test_disabled_allowance_cannot_create_chat_call(replay, monkeypatch):
    job, current = replay;calls = fake_provider(monkeypatch)
    with database() as connection:
        connection.execute('UPDATE openai_api_budget SET enabled=false WHERE id=1')
    with pytest.raises(HTTPException) as caught:
        chat.ask(job['owner_id'], job['id'], command(current))
    assert caught.value.status_code == 429 and not calls
    assert chat.history(job['owner_id'], job['id'])['turns'] == []


@pytest.mark.parametrize('failure', ['unknown_usage', 'invalid_evidence'])
def test_failed_paid_response_never_retries_or_releases_unknown_cost(replay, monkeypatch, failure):
    job, current = replay
    calls = fake_provider(monkeypatch, output={**ANSWER, 'evidence_ids': ['foreign']} if failure == 'invalid_evidence' else None,
                          usage=failure != 'unknown_usage')
    body = command(current)
    first = chat.ask(job['owner_id'], job['id'], body)
    assert first['turn']['state'] == 'failed' and first['turn']['answer'] is None
    assert chat.ask(job['owner_id'], job['id'], body) == first and len(calls) == 1
    with database() as connection:
        allowance = budget.status(connection)
        assert allowance['reserved_microusd'] > 0 if failure == 'unknown_usage' else allowance['spent_microusd'] > 0


def test_deletion_during_answer_hides_text_but_settles_cost(replay, monkeypatch):
    job, current = replay
    def remove():
        with database() as connection:
            connection.execute("UPDATE replay_jobs SET state='deleted',result_payload=NULL WHERE id=%s", (job['id'],))
            provider.forget_output(connection, owner_id=job['owner_id'], job_id=job['id'])
    calls = fake_provider(monkeypatch, before=remove)
    body = command(current)
    with pytest.raises(HTTPException):
        chat.ask(job['owner_id'], job['id'], body)
    assert len(calls) == 1
    with database() as connection:
        turn = connection.execute('SELECT * FROM coach_chat_turns WHERE id=%s', (body.id,)).fetchone()
        call = connection.execute('SELECT * FROM openai_api_calls WHERE task_id=%s', (body.id,)).fetchone()
        assert turn['question'] == '' and turn['answer'] is None and turn['input_data'] is None
        assert call['output_text'] is None and call['charged_microusd'] > 0
