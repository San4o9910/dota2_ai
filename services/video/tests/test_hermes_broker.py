"""The actual provider boundary: request bounds, durable accounting and isolation."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
from threading import Barrier, Event
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from narma_video import budget, hermes_bridge, hermes_broker as broker
from narma_video.db import database
from test_hermes_bridge import OWNER, browser

TOKEN = 'b' * 43
REQUEST = {'model': budget.MODEL, 'messages': [{'role': 'system', 'content': 'Return evidence-bound JSON.'},
    {'role': 'user', 'content': '{"synthetic":true}'}], 'max_tokens': 4096, 'stream': False}
USAGE = {'total_input_tokens': 100, 'total_output_tokens': 30, 'total_thought_tokens': 20, 'total_tokens': 150}
RAW_USAGE = {'promptTokenCount': 100, 'candidatesTokenCount': 30, 'thoughtsTokenCount': 20, 'totalTokenCount': 150}


@pytest.mark.parametrize('change', [
    {'model': 'unapproved'}, {'max_tokens': 4097}, {'max_tokens': True}, {'max_tokens': 0},
    {'max_completion_tokens': 1000000}, {'stream': True}, {'n': 2}, {'n': True},
    {'tools': [{'type': 'function'}]}, {'tool_choice': 'auto'}, {'functions': []},
    {'response_format': {'type': 'json_schema', 'json_schema': {}}}, {'temperature': float('nan')},
    {'top_p': -1}, {'reasoning_effort': 'high'}, {'stop': ['x' * 101]},
    {'messages': [{'role': 'tool', 'content': 'not allowed'}]},
    {'messages': [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'https://private'}}]}]},
    {'messages': [{'role': 'assistant', 'content': 'x', 'tool_calls': []}]},
    {'messages': [{'role': 'system', 'content': 'no user'}]},
    {'messages': [{'role': 'user', 'content': 'x'}] * 33},
    {'owner_id': 'somebody_else'}, {'api_key': 'never pass provider secrets'},
])
def test_unsupported_or_unbounded_input_never_reaches_accounting(change, monkeypatch):
    monkeypatch.setattr(broker, 'complete', lambda *_: pytest.fail('Invalid input reached dispatch'))
    client = TestClient(broker.app)
    response = client.post('/v1/chat/completions', content=json.dumps({**REQUEST, **change}),
        headers={'Authorization': f'Bearer {TOKEN}'})
    assert response.status_code in (400, 413), response.text


def test_text_blocks_and_requested_output_cap_are_preserved():
    request = deepcopy(REQUEST)
    request.update(max_tokens=2048, max_completion_tokens=1024)
    request['messages'][1]['content'] = [{'type': 'text', 'text': 'first'}, {'type': 'text', 'text': 'second'}]
    clean = broker.validate_request(request)
    assert clean['messages'][1]['content'] == 'first\nsecond'
    assert clean['max_tokens'] == 1024


def test_http_requires_task_credential_and_enforces_body_size(monkeypatch):
    monkeypatch.setattr(broker, 'complete', lambda *_: pytest.fail('Unauthenticated/oversized dispatch'))
    client = TestClient(broker.app)
    assert client.post('/v1/chat/completions', json=REQUEST).status_code == 401
    assert client.get('/v1/models').status_code == 401
    response = client.post('/v1/chat/completions', content=b'x' * (broker.MAX_REQUEST_BYTES + 1),
        headers={'Authorization': f'Bearer {TOKEN}'})
    assert response.status_code == 413
    assert client.get('/healthz').json() == {'ok': True, 'service': 'hermes-broker'}


def response_body(*, usage=None, finish='STOP', parts=None):
    return {'usageMetadata': RAW_USAGE if usage is None else usage,
        'candidates': [{'finishReason': finish, 'content': {'parts': [{'text': '{"synthetic":true}'}] if parts is None else parts}}]}


def provider_with_response(body):
    provider = broker.GeminiHermesProvider.__new__(broker.GeminiHermesProvider)
    observed = {}
    def generate_content(**kwargs):
        observed.update(kwargs)
        return SimpleNamespace(sdk_http_response=SimpleNamespace(body=json.dumps(body)))
    provider.client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    provider.last_usage = None
    return provider, observed


def test_adapter_uses_fixed_model_text_only_standard_low_thinking_and_raw_usage():
    provider, observed = provider_with_response(response_body())
    assert provider.analyze(broker.validate_request(REQUEST)) == '{"synthetic":true}'
    assert provider.last_usage == USAGE
    assert observed['model'] == budget.MODEL
    config = observed['config']
    assert config.max_output_tokens == 4096 and config.candidate_count == 1
    assert config.service_tier == 'standard' and config.thinking_config.thinking_level.value.lower() == 'low'
    assert config.automatic_function_calling.disable is True
    assert config.tools is None and config.response_mime_type == 'application/json'
    assert config.should_return_http_response is True
    assert observed['contents'][0].role == 'user'
    assert observed['contents'][0].parts[0].text == '{"synthetic":true}'


def test_adapter_has_one_sdk_attempt(monkeypatch):
    observed = {}
    def client(**kwargs):
        observed.update(kwargs)
        return SimpleNamespace()
    monkeypatch.setenv('GEMINI_MODEL', budget.MODEL)
    monkeypatch.setenv('GEMINI_API_KEY', 'synthetic-not-real')
    monkeypatch.setattr(broker.genai, 'Client', client)
    broker.GeminiHermesProvider()
    assert observed['http_options'].retry_options.attempts == 1
    assert observed['http_options'].timeout == 120000


@pytest.mark.parametrize('body', [response_body(finish='MAX_TOKENS'), response_body(parts=[{'functionCall': {'name': 'blocked'}}]),
    response_body(parts=[]), response_body(parts=[{'text': 'x' * (broker.MAX_RESPONSE_BYTES + 1)}])])
def test_bad_provider_output_preserves_known_usage(body):
    provider, _ = provider_with_response(body)
    with pytest.raises(ValueError, match='RESPONSE_INVALID'):
        provider.analyze(broker.validate_request(REQUEST))
    assert provider.last_usage == USAGE


@pytest.mark.parametrize('extra', [
    {'newBillableFeature': 1}, {'serviceTier': 'priority'}, {'toolUsePromptTokenCount': 2},
    {'promptTokensDetails': [{'modality': 'IMAGE', 'tokenCount': 100}]},
])
def test_unknown_or_non_text_usage_cannot_be_silently_dropped(extra):
    raw = {**RAW_USAGE, **extra}
    provider, _ = provider_with_response(response_body(usage=raw))
    with pytest.raises(ValueError, match='USAGE_UNSUPPORTED|USAGE_INVALID'):
        provider.analyze(broker.validate_request(REQUEST))
    assert provider.last_usage == {'unrecognized_generate_content_usage': raw}


@pytest.fixture
def active_task(browser):
    _, pool = browser
    snapshot, digest, sources = hermes_bridge.build_snapshot(pool)
    with database() as connection:
        connection.execute("""UPDATE video_ai_budget SET enabled=true,model=%s,price_policy=%s,
            expires_at='2027-01-01T00:00:00Z',limit_microusd=10000000,
            spent_microusd=0,reserved_microusd=0,frozen_reason=NULL WHERE id=1""", (budget.MODEL, budget.POLICY))
        task = connection.execute("""INSERT INTO hermes_tasks
            (id,owner_id,account_id,snapshot_sha256,snapshot,source_jobs,state,attempts,lease_token,credential_sha256,lease_until)
            VALUES (%s,%s,1000,%s,%s,%s,'running',1,%s,%s,now()+interval '5 minutes') RETURNING *""",
            (uuid4(), OWNER, digest, hermes_bridge.Jsonb(snapshot), hermes_bridge.Jsonb(sources), uuid4(),
                hashlib.sha256(TOKEN.encode()).hexdigest())).fetchone()
    yield task
    with database() as connection:
        connection.execute('DELETE FROM video_provider_calls WHERE hermes_task_id=%s', (task['id'],))
        connection.execute('DELETE FROM hermes_tasks WHERE id=%s', (task['id'],))


class SyntheticProvider:
    calls = 0
    def __init__(self):
        self.last_usage = None
    def analyze(self, request):
        type(self).calls += 1
        # A separate database connection must already observe the reservation;
        # a broker process dying during inference cannot lose the ledger entry.
        with database() as connection:
            call = connection.execute("SELECT * FROM video_provider_calls WHERE owner_id=%s AND call_kind='hermes'", (OWNER,)).fetchone()
            assert call and call['billing_status'] == 'reserved'
        self.last_usage = deepcopy(USAGE)
        return 'malformed output is validated by the task consumer'
    def close(self):
        pass


def test_provider_attempt_commits_before_call_and_settles_even_invalid_final_json(active_task):
    result = broker.complete(TOKEN, broker.validate_request(REQUEST), SyntheticProvider)
    assert result['choices'][0]['message']['content'].startswith('malformed output')
    assert result['usage'] == {'prompt_tokens': 100, 'completion_tokens': 50, 'total_tokens': 150}
    state = budget.status()
    assert state['spent_microusd'] == 263 and state['reserved_microusd'] == 0
    with database() as connection:
        call = connection.execute('SELECT * FROM video_provider_calls WHERE hermes_task_id=%s', (active_task['id'],)).fetchone()
        assert call['owner_id'] == OWNER and call['job_id'] is None and call['replay_job_id'] is None
        assert call['call_kind'] == 'hermes' and call['billing_status'] == 'settled'
    attempts = SyntheticProvider.calls
    with pytest.raises(ValueError, match='HERMES_REQUEST_BUDGET_EXCEEDED'):
        broker.complete(TOKEN, broker.validate_request(REQUEST), SyntheticProvider)
    assert SyntheticProvider.calls == attempts


@pytest.mark.parametrize('failure', ['timeout', 'invalid_output', 'invalid_usage'])
def test_failed_attempts_settle_and_unknown_usage_keeps_reservation(active_task, failure):
    class Failed(SyntheticProvider):
        def analyze(self, request):
            if failure == 'timeout':
                raise TimeoutError('Do not log secret provider request')
            self.last_usage = deepcopy(USAGE) if failure == 'invalid_output' else {'new_billable_counter': 1}
            raise ValueError('HERMES_PROVIDER_RESPONSE_INVALID')
    with pytest.raises((TimeoutError, ValueError)):
        broker.complete(TOKEN, broker.validate_request(REQUEST), Failed)
    state = budget.status()
    if failure == 'invalid_output':
        assert state['spent_microusd'] == 263 and state['reserved_microusd'] == 0
    else:
        assert state['spent_microusd'] == 0 and state['reserved_microusd'] == budget.RESERVATION
        assert state['enabled'] is (failure == 'timeout')
    with database() as connection:
        call = connection.execute('SELECT * FROM video_provider_calls WHERE hermes_task_id=%s', (active_task['id'],)).fetchone()
        assert call['billing_status'] == ('settled' if failure == 'invalid_output' else 'unknown')
    if failure != 'invalid_output':
        budget.settle(call['id'], USAGE)
        assert budget.status()['reserved_microusd'] == budget.RESERVATION


@pytest.mark.parametrize('change,expected', [
    ('token', 'HERMES_TOKEN_INVALID'), ('expiry', 'HERMES_LEASE_EXPIRED'),
    ('owner', 'HERMES_SOURCE_CHANGED'), ('binding', 'HERMES_SOURCE_CHANGED'),
    ('source', 'HERMES_SOURCE_CHANGED'), ('position', 'HERMES_SOURCE_CHANGED'),
    ('disabled', 'VIDEO_GLOBAL_BUDGET_DISABLED'), ('exhausted', 'VIDEO_GLOBAL_BUDGET_EXCEEDED'),
])
def test_credential_source_and_budget_denials_make_no_provider_attempt(active_task, change, expected):
    token = TOKEN
    with database() as connection:
        if change == 'token':
            token = 'z' * 43
        elif change == 'expiry':
            connection.execute("UPDATE hermes_tasks SET lease_until=now()-interval '1 second' WHERE id=%s", (active_task['id'],))
        elif change == 'owner':
            connection.execute("UPDATE hermes_tasks SET owner_id='somebody_else' WHERE id=%s", (active_task['id'],))
        elif change == 'binding':
            connection.execute('UPDATE portal_dota_profiles SET account_id=1001 WHERE owner_id=%s', (OWNER,))
        elif change == 'source':
            connection.execute("UPDATE replay_jobs SET result_payload=result_payload || '{\"changed\":true}'::jsonb WHERE owner_id=%s", (OWNER,))
        elif change == 'position':
            connection.execute('UPDATE hero_pool_matches SET position=4 WHERE owner_id=%s', (OWNER,))
        elif change == 'disabled':
            connection.execute('UPDATE video_ai_budget SET enabled=false WHERE id=1')
        else:
            connection.execute('UPDATE video_ai_budget SET reserved_microusd=limit_microusd WHERE id=1')
    class NeverDispatch(SyntheticProvider):
        def analyze(self, request):
            pytest.fail('Denied call reached provider')
    with pytest.raises(ValueError, match=expected):
        broker.complete(token, broker.validate_request(REQUEST), NeverDispatch)
    with database() as connection:
        assert connection.execute('SELECT count(*) AS n FROM video_provider_calls WHERE hermes_task_id=%s', (active_task['id'],)).fetchone()['n'] == 0


def test_concurrent_retries_authorize_only_one_durable_attempt(active_task):
    barrier = Barrier(2)
    def attempt():
        barrier.wait(timeout=10)
        try:
            with database() as connection:
                task = broker.authorize_call(connection, TOKEN)
                budget.reserve_hermes(connection, task, budget.MODEL)
            return 'reserved'
        except ValueError as error:
            return str(error)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(attempt) for _ in range(2)]
        assert sorted(result.result(timeout=30) for result in results) == ['HERMES_REQUEST_BUDGET_EXCEEDED', 'reserved']
    assert budget.status()['reserved_microusd'] == budget.RESERVATION


def test_models_probe_is_authenticated_without_any_reservation(active_task):
    client = TestClient(broker.app)
    response = client.get('/v1/models', headers={'Authorization': f'Bearer {TOKEN}'})
    assert response.status_code == 200
    assert response.json()['data'][0]['id'] == budget.MODEL
    assert budget.status()['reserved_microusd'] == budget.status()['spent_microusd'] == 0
    with database() as connection:
        connection.execute("UPDATE hermes_tasks SET lease_until=now()-interval '1 second' WHERE id=%s", (active_task['id'],))
    assert client.get('/v1/models', headers={'Authorization': f'Bearer {TOKEN}'}).status_code == 409


def test_budget_lock_wait_cannot_dispatch_after_task_lease_expires(active_task, monkeypatch):
    with database() as connection:
        if 'PGlite' in connection.execute('SELECT version() AS version').fetchone()['version']:
            pytest.skip('PGlite multiplexes one connection; native CI runs the overlapping row-lock gate')
    entered_reservation = Event()
    reserve = budget._reserve
    def marked_reserve(*args, **kwargs):
        entered_reservation.set()
        return reserve(*args, **kwargs)
    monkeypatch.setattr(budget, '_reserve', marked_reserve)
    with database() as connection:
        connection.execute("UPDATE hermes_tasks SET lease_until=clock_timestamp()+interval '3 seconds' WHERE id=%s",
                           (active_task['id'],))
    class NeverDispatch(SyntheticProvider):
        def analyze(self, request):
            pytest.fail('Provider dispatched after waiting beyond the task deadline')
    with ThreadPoolExecutor(max_workers=1) as pool:
        with database() as blocker:
            blocker.execute('SELECT id FROM video_ai_budget WHERE id=1 FOR UPDATE')
            result = pool.submit(broker.complete, TOKEN, broker.validate_request(REQUEST), NeverDispatch)
            assert entered_reservation.wait(timeout=5), 'Task did not reach reservation while its lease was valid'
            # This other transaction holds the shared budget row beyond the
            # lease, without changing the locked task row or simulating a clock.
            time.sleep(3.1)
            assert not result.done()
        with pytest.raises(ValueError, match='HERMES_LEASE_EXPIRED'):
            result.result(timeout=10)
    with database() as connection:
        assert connection.execute('SELECT count(*) AS n FROM video_provider_calls WHERE hermes_task_id=%s',
                                  (active_task['id'],)).fetchone()['n'] == 0
    assert budget.status()['reserved_microusd'] == 0
