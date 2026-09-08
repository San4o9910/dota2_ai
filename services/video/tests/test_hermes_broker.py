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
from google import genai
from google.genai import errors, types
import httpx
from pydantic import ValidationError

from narma_video import budget, hermes_bridge, hermes_broker as broker
from narma_video.db import database
from test_hermes_bridge import OWNER, browser, pool_fixture, review_fixture

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


def test_real_sdk_serializes_supported_schema_and_preserves_raw_usage_without_network():
    pool = pool_fixture()
    pool['history'] = [deepcopy(pool['history'][i % 2]) for i in range(4)]
    for index, row in enumerate(pool['history']):
        row.update(job_id=str(uuid4()), match_id=str(8984479726 + index),
            evidence=[{'id': f'event-{number}', 'type': 'death', 'time': 420 + number} for number in range(40)])
    snapshot, digest, sources = hermes_bridge.build_snapshot(pool)
    packet = hermes_bridge.packet_for({'id': uuid4(), 'snapshot': snapshot, 'snapshot_sha256': digest})['packet']
    final = review_fixture(snapshot, digest)
    captured = []
    def respond(request):
        # Both SDK transports are mocked. This request never reaches a provider.
        assert request.method == 'POST'
        assert request.url.host == 'generativelanguage.googleapis.com'
        assert request.url.path == '/v1beta/models/' + budget.MODEL + ':generateContent'
        assert request.headers['x-goog-api-key'] == 'synthetic-not-real'
        captured.append(json.loads(request.content))
        return httpx.Response(200, json=response_body(parts=[{'text': json.dumps(final, ensure_ascii=False)}]))
    transport = httpx.MockTransport(respond)
    provider = broker.GeminiHermesProvider.__new__(broker.GeminiHermesProvider)
    provider.last_usage = None
    provider.client = genai.Client(api_key='synthetic-not-real', http_options=types.HttpOptions(
        timeout=1000, retry_options=types.HttpRetryOptions(attempts=1),
        client_args={'transport': transport, 'trust_env': False},
        async_client_args={'transport': transport, 'trust_env': False}))
    request = deepcopy(REQUEST)
    request['messages'][1]['content'] = json.dumps({'packet': packet}, ensure_ascii=False)
    assert 9000 < len(request['messages'][1]['content'].encode()) < broker.MAX_REQUEST_BYTES
    try:
        result = provider.analyze(broker.validate_request(request))
    finally:
        provider.close()
    assert len(captured) == 1
    sent = captured[0]
    config = sent['generationConfig']
    schema = config['responseJsonSchema']
    assert schema == broker.provider_review_schema()
    assert schema['properties']['schema_version']['enum'] == [1]
    assert schema['$defs']['Producer']['properties']['name']['enum'] == ['NousResearch/hermes-agent']
    def check_keywords(node):
        if not isinstance(node, dict):
            return
        assert set(node) <= broker._PROVIDER_SCHEMA_KEYS
        for key, value in node.items():
            if key in ('$defs', 'properties'):
                for child in value.values():
                    check_keywords(child)
            elif key in ('items', 'additionalProperties'):
                check_keywords(value)
            elif key in ('anyOf', 'oneOf', 'prefixItems'):
                for child in value:
                    check_keywords(child)
    check_keywords(schema)
    assert config['maxOutputTokens'] == 4096 and config['candidateCount'] == 1
    assert config['thinkingConfig'] == {'thinking_level': 'LOW'}
    assert config['responseMimeType'] == 'application/json' and sent['serviceTier'] == 'standard'
    assert provider.last_usage == USAGE
    assert hermes_bridge.validate_review(broker.Review.model_validate_json(result), snapshot, digest) == final


@pytest.mark.parametrize('change', [
    lambda review: review.update(schema_version=2),
    lambda review: review['patterns'][0].update(id='../not-an-evidence-id'),
    lambda review: review['patterns'][0].update(title=''),
    lambda review: review['patterns'][0].update(observation='x' * 501),
])
def test_provider_schema_projection_never_relaxes_saved_review_validation(change):
    original = broker.Review.model_json_schema()
    broker.provider_review_schema()
    assert broker.Review.model_json_schema() == original
    assert original['properties']['schema_version']['const'] == 1
    assert 'pattern' in original['$defs']['Pattern']['properties']['id']
    assert original['$defs']['Pattern']['properties']['observation']['maxLength'] == 500
    snapshot, digest, _ = hermes_bridge.build_snapshot(pool_fixture())
    review = review_fixture(snapshot, digest)
    change(review)
    with pytest.raises(ValidationError):
        broker.Review.model_validate(review)


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


def test_candidate_diagnostics_expose_only_counts_and_fixed_vocabulary(capsys):
    secret = 'private prompt, task-token and provider-key'
    body = response_body(finish='MAX_TOKENS', parts=[{'text': secret}, {'thought': True, 'text': secret},
        {'thoughtSignature': secret}, {'functionCall': {'secret': secret}}, {secret: secret}])
    provider, _ = provider_with_response(body)
    with pytest.raises(ValueError, match='RESPONSE_INVALID'):
        provider.analyze(broker.validate_request(REQUEST))
    logged = capsys.readouterr().out
    assert secret not in logged
    event = json.loads(logged)
    assert event == {'event': 'hermes_provider_response', 'candidate_count': 1, 'finish_reason': 'MAX_TOKENS',
        'part_count': 5, 'part_types': ['functionCall:object', 'text:string', 'thought:boolean',
            'thoughtSignature:string', 'unrecognized_key'], 'output_bytes': len(secret.encode())}
    assert provider.last_usage == USAGE
    assert broker.response_diagnostics({'candidates': [{'finishReason': secret}]})['finish_reason'] == 'unrecognized'


@pytest.mark.parametrize('error,expected', [
    (errors.ClientError(400, {'error': {'status': 'INVALID_ARGUMENT', 'message': 'private prompt and secret'}}),
        {'category': 'provider_rejected', 'provider_http_status': 400, 'provider_status': 'INVALID_ARGUMENT'}),
    (errors.ClientError(401, {'error': {'status': 'UNAUTHENTICATED', 'message': 'private prompt and secret'}}),
        {'category': 'authentication', 'provider_http_status': 401, 'provider_status': 'UNAUTHENTICATED'}),
    (errors.ClientError(429, {'error': {'status': 'RESOURCE_EXHAUSTED', 'message': 'private prompt and secret'}}),
        {'category': 'rate_limited', 'provider_http_status': 429, 'provider_status': 'RESOURCE_EXHAUSTED'}),
    (errors.ServerError(503, {'error': {'status': 'UNAVAILABLE', 'message': 'private prompt and secret'}}),
        {'category': 'provider_unavailable', 'provider_http_status': 503, 'provider_status': 'UNAVAILABLE'}),
    (httpx.ReadTimeout('private prompt and secret'),
        {'category': 'timeout', 'provider_http_status': None, 'provider_status': None}),
    (httpx.ConnectError('private prompt and secret'),
        {'category': 'transport', 'provider_http_status': None, 'provider_status': None}),
    (RuntimeError('private prompt and secret'),
        {'category': 'unknown', 'provider_http_status': None, 'provider_status': None}),
])
def test_provider_failure_diagnostics_omit_exception_messages_and_bodies(error, expected, capsys):
    response = broker._failure(error)
    logged = capsys.readouterr().out
    assert 'private prompt and secret' not in logged and b'private prompt and secret' not in response.body
    assert json.loads(logged) == {'event': 'hermes_broker_rejected', 'code': 'HERMES_PROVIDER_UNAVAILABLE', **expected}


def test_provider_diagnostics_do_not_log_unrecognized_status_values():
    error = errors.ClientError(400, {'error': {'status': 'private secret', 'message': 'private secret'}})
    assert broker.failure_diagnostics(error, 'HERMES_PROVIDER_UNAVAILABLE')['provider_status'] is None


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
