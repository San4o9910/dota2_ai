"""Offline protocol fixtures and native PostgreSQL at-most-once accounting gates."""
import copy
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
import pytest

from narma_video import chatgpt_provider as provider
from narma_video.db import database, migrate


def message(text='{"summary":"Проверь карту"}'):
    return {'type': 'message', 'id': 'msg_1', 'role': 'assistant', 'status': 'completed',
        'content': [{'type': 'output_text', 'text': text}]}


def completed(text='{"summary":"Проверь карту"}'):
    return {'type': 'response.completed', 'response': {'id': 'resp_1', 'status': 'completed',
        'model': provider.MODEL, 'output': [message(text)],
        'usage': {'input_tokens': 100, 'output_tokens': 20, 'total_tokens': 120}}}


def wire(*events):
    return b''.join(b'data: ' + json.dumps(event, ensure_ascii=False).encode() + b'\n\n' for event in events)


def test_native_stream_utf8_chunk_boundaries_only_terminal_output_and_subscription_usage():
    raw = wire({'type': 'response.created', 'response': {'id': 'resp_1'}},
        {'type': 'response.output_text.delta', 'delta': 'Do not use deltas as the final response'}, completed()) + b'data: [DONE]\n\n'
    result = provider.parse_stream([raw[i:i+3] for i in range(0, len(raw), 3)])
    assert result['text'] == message()['content'][0]['text']
    assert result['usage'] == {'kind': 'chatgpt_subscription', 'api_cost_microusd': None,
        'input_tokens': 100, 'output_tokens': 20, 'total_tokens': 120}


def test_final_whitespace_matches_pinned_hermes_normalization():
    assert provider.parse_stream([wire(completed('  {"answer":true}\n'))])['text'] == '{"answer":true}'


@pytest.mark.parametrize('output', [None, []])
def test_native_codex_null_terminal_output_uses_finished_items(output):
    final = completed()
    final['response']['output'] = output
    raw = wire({'type': 'response.created', 'response': {'id': 'resp_1'}},
        {'type': 'response.output_item.done', 'output_index': 0,
            'item': {'id': 'reason_1', 'type': 'reasoning', 'summary': []}},
        {'type': 'response.output_item.done', 'output_index': 1, 'item': message()}, final)
    assert provider.parse_stream([raw])['text'] == message()['content'][0]['text']


@pytest.mark.parametrize('events,code', [
    ([{'type': 'response.output_text.delta', 'delta': 'partial'}], 'INCOMPLETE'),
    ([{'type': 'response.incomplete', 'response': {'status': 'incomplete'}}], 'INCOMPLETE'),
    ([{'type': 'response.failed', 'response': {'status': 'failed'}}], 'REJECTED'),
    ([{'type': 'response.function_call_arguments.delta', 'delta': '{}'}], 'TOOLS_FORBIDDEN'),
    ([{'type': 'response.output_item.done', 'item': {'type': 'web_search_call'}, 'output_index': 0}], 'TOOLS_FORBIDDEN'),
    ([{'type': 'response.refusal.delta', 'delta': 'no'}], 'REFUSED'),
    ([completed(), completed()], 'INVALID'),
    ([{'type': 'response.created', 'response': {'id': 'other'}}, completed()], 'INVALID'),
])
def test_bad_streams_never_become_successful(events, code):
    with pytest.raises(provider.ProviderError, match=code):
        provider.parse_stream([wire(*events)])


@pytest.mark.parametrize('mutate,code', [
    (lambda value: value['response'].update(status='incomplete'), 'INVALID'),
    (lambda value: value['response'].update(model='another-model'), 'INVALID'),
    (lambda value: value['response'].update(output=[{'type': 'function_call'}]), 'TOOLS_FORBIDDEN'),
    (lambda value: value['response']['output'][0].update(content=[{'type': 'refusal', 'refusal': 'no'}]), 'REFUSED'),
    (lambda value: value['response'].update(usage={'input_tokens': True, 'output_tokens': 0, 'total_tokens': 1}), 'INVALID'),
    (lambda value: value['response'].update(usage={'input_tokens': 100, 'output_tokens': 20, 'total_tokens': 121}), 'INVALID'),
])
def test_terminal_envelope_rejects_incomplete_tools_refusal_and_invalid_usage(mutate, code):
    value = completed()
    mutate(value)
    with pytest.raises(provider.ProviderError, match=code):
        provider.parse_stream([wire(value)])


def test_absent_usage_is_unknown_not_zero_and_no_reasoning_leaks():
    value = completed()
    value['response'].pop('usage')
    value['response']['output'].insert(0, {'type': 'reasoning', 'summary': [{'text': 'private reasoning'}]})
    value['response']['output'].insert(0, {**message('private analysis'), 'phase': 'analysis'})
    value['response']['output'].insert(0, {**message('private commentary'), 'phase': 'commentary'})
    result = provider.parse_stream([wire(value)])
    assert result['usage'] is None
    assert 'private' not in str(result)


def test_payload_is_fixed_endpoint_tool_free_no_store_no_unsupported_api_token_limit():
    value = provider.request_payload('Instructions', 'Evidence')
    assert value['tools'] == [] and value['tool_choice'] == 'none'
    assert value['store'] is False and value['stream'] is True
    assert 'max_output_tokens' not in value and 'temperature' not in value
    with pytest.raises(provider.ProviderError, match='TOO_LARGE'):
        provider.request_payload('Instructions', 'x' * provider.MAX_INPUT_BYTES)
    with pytest.raises(provider.ProviderError, match='MODEL_UNSUPPORTED'):
        provider.request_payload('Instructions', 'Evidence', 'gpt-5.4-pro')


def test_bounded_stream_and_output(monkeypatch):
    with pytest.raises(provider.ProviderError, match='OUTPUT_TOO_LARGE'):
        provider.parse_stream([wire(completed('x' * (provider.MAX_OUTPUT_BYTES + 1)))])
    monkeypatch.setattr(provider, 'MAX_STREAM_BYTES', 100)
    with pytest.raises(provider.ProviderError, match='OUTPUT_TOO_LARGE'):
        provider.parse_stream([b':' + b'x' * 100])
    with pytest.raises(provider.ProviderError, match='TIMEOUT'):
        provider.parse_stream([b''], started=provider.time.monotonic() - 121)


def transport_fixture(monkeypatch, handler):
    original = httpx.Client
    def client(**kwargs):
        assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
        return original(**kwargs, transport=httpx.MockTransport(handler))
    monkeypatch.setattr(provider.httpx, 'Client', client)


def test_transport_one_native_request_sanitized_headers_and_no_alternate_host(monkeypatch):
    requests = []
    def handler(request):
        requests.append(request)
        assert str(request.url) == provider.ENDPOINT
        assert request.headers['Authorization'] == 'Bearer synthetic-token'
        assert request.headers['ChatGPT-Account-Id'] == 'synthetic-account'
        assert request.headers['originator'] == 'narma-vision'
        assert json.loads(request.content)['store'] is False
        return httpx.Response(200, headers={'Content-Type': 'text/event-stream'}, content=wire(completed()))
    transport_fixture(monkeypatch, handler)
    result = provider._generate({'access_token': 'synthetic-token', 'account_id': 'synthetic-account'}, 'Instructions', 'Evidence')
    assert result['text'] and len(requests) == 1


@pytest.mark.parametrize('status,code', [(401, 'AUTH_EXPIRED'), (403, 'AUTH_EXPIRED'),
    (429, 'QUOTA'), (503, 'UNAVAILABLE'), (400, 'REJECTED'), (302, 'REJECTED')])
def test_transport_error_body_never_surfaces_or_retries(monkeypatch, status, code):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, headers={'Retry-After': '125'}, content=b'private-token private-match')
    transport_fixture(monkeypatch, handler)
    with pytest.raises(provider.ProviderError, match=code) as error:
        provider._generate({'access_token': 'synthetic-token'}, 'Instructions', 'Evidence')
    assert 'private' not in str(error.value) and len(calls) == 1
    if status == 429:
        assert error.value.retry_after == 125


def test_retry_reset_is_never_guessed():
    assert provider._retry_after({}) is None
    assert provider._retry_after({'retry-after': 'garbage'}) is None
    assert provider._retry_after({'retry-after': '604801'}) is None
    assert provider._retry_after({'retry-after': '120'}) == 120


@pytest.fixture
def ledger(monkeypatch):
    if not os.environ.get('TEST_DATABASE_URL'):
        pytest.skip('Set isolated TEST_DATABASE_URL; native PostgreSQL runs in CI')
    from narma_video import chatgpt_auth as auth
    monkeypatch.setenv('DATABASE_URL', os.environ['TEST_DATABASE_URL'])
    migrate()
    owner, generation = 'synthetic-chatgpt-' + uuid4().hex, str(uuid4())
    job_id, lease = uuid4(), uuid4()
    current = {'generation': generation, 'connected': True, 'available': True}
    monkeypatch.setattr(auth, 'current_connection', lambda connection, given_owner: current if given_owner == owner else None)
    monkeypatch.setattr(auth, 'get_access_credentials', lambda given_owner: {
        'access_token': 'never-log-me', 'account_id': 'synthetic-account', 'generation': generation})
    monkeypatch.setattr(auth, 'credentials_current', lambda given_owner, given_generation:
        given_owner == owner and given_generation == current['generation'] and current['connected'])
    monkeypatch.setattr(auth, 'record_provider_pause', lambda given_owner, given_generation, **kwargs: current.update(available=False))
    monkeypatch.setattr(auth, 'mark_reconnect_required', lambda given_owner, given_generation: current.update(connected=False, available=False))
    with database() as connection:
        connection.execute("INSERT INTO portal_accounts(owner_id,email,password_hash) VALUES (%s,%s,'unused')", (owner, owner + '@example.test'))
        connection.execute("""INSERT INTO portal_dota_profiles(owner_id,account_id,nickname,match_id,hero_name,side,source_sha256)
            VALUES (%s,1000,'synthetic','8984479726','npc_dota_hero_axe','radiant',%s)""", (owner, 'a'*64))
        connection.execute("""INSERT INTO replay_jobs(id,owner_id,filename,size_bytes,requested_nickname,nickname,
            state,match_id,account_id,source_sha256,lease_token,lease_expires_at)
            VALUES (%s,%s,'synthetic.dem',100,'synthetic','synthetic','processing','8984479726',1000,%s,%s,now()+interval '1 hour')""",
            (job_id, owner, 'a'*64, lease))
    fixture = {'owner_id': owner, 'job_id': job_id, 'generation': generation, 'current': current}
    yield fixture
    with database() as connection:
        connection.execute('DELETE FROM chatgpt_calls WHERE owner_id=%s', (owner,))
        connection.execute('DELETE FROM portal_accounts WHERE owner_id=%s', (owner,))


def reserve(fixture, **overrides):
    kwargs = {'owner_id': fixture['owner_id'], 'job_id': fixture['job_id'],
        'expected_generation': fixture['generation'], 'request_key': 'replay:' + str(fixture['job_id']),
        'instructions': 'Instructions', 'input_data': 'Evidence'}
    kwargs.update(overrides)
    with database() as connection:
        return provider.reserve_call(connection, **kwargs)


def another_job(fixture):
    identity = uuid4()
    with database() as connection:
        connection.execute("""INSERT INTO replay_jobs(id,owner_id,filename,size_bytes,requested_nickname,nickname,
            state,match_id,account_id,source_sha256,lease_token,lease_expires_at)
            SELECT %s,owner_id,filename,size_bytes,requested_nickname,nickname,state,match_id,account_id,
                source_sha256,lease_token,lease_expires_at FROM replay_jobs WHERE id=%s""",
            (identity, fixture['job_id']))
    return identity


def test_reservation_exact_request_idempotent_one_job_and_personal_generation(ledger):
    first = reserve(ledger)
    assert reserve(ledger)['id'] == first['id']
    assert first['usage_kind'] == 'chatgpt_subscription' and first['api_cost_microusd'] is None
    with pytest.raises(provider.ProviderError, match='CONFLICT'):
        reserve(ledger, input_data='Changed evidence')
    with pytest.raises(provider.ProviderError, match='ALREADY_ATTEMPTED'):
        reserve(ledger, request_key='other-key')
    with pytest.raises(provider.ProviderError, match='CONNECTION_CHANGED'):
        reserve(ledger, owner_id='another-owner')
    with pytest.raises(provider.ProviderError, match='CONNECTION_CHANGED'):
        reserve(ledger, expected_generation=str(uuid4()))


def test_daily_limit_counts_reserved_and_uncertain_attempts_before_more_network(ledger, monkeypatch):
    monkeypatch.setenv('NARMA_CHATGPT_MAX_DAILY_CALLS', '1')
    reserve(ledger)
    second = another_job(ledger)
    with pytest.raises(provider.ProviderError, match='DAILY_LIMIT'):
        reserve(ledger, job_id=second, request_key='replay:' + str(second))


def test_quota_without_confirmed_reset_blocks_new_job_even_if_auth_pause_races(ledger, monkeypatch):
    row = reserve(ledger)
    def generate(*args):
        raise provider.ProviderError('CHATGPT_QUOTA')
    monkeypatch.setattr(provider, '_generate', generate)
    with pytest.raises(provider.ProviderError, match='QUOTA'):
        provider.perform_reserved(row['id'], ledger['owner_id'], 'Instructions', 'Evidence')
    ledger['current']['available'] = True
    second = another_job(ledger)
    with pytest.raises(provider.ProviderError, match='QUOTA'):
        reserve(ledger, job_id=second, request_key='replay:' + str(second))


def test_success_exact_output_durable_no_second_attempt_or_paid_ledger_change(ledger, monkeypatch):
    calls = []
    def generate(*args):
        calls.append(True)
        return provider._completed(completed()['response'], provider.MODEL)
    monkeypatch.setattr(provider, '_generate', generate)
    with database() as connection:
        before = connection.execute('SELECT count(*) AS n FROM video_provider_calls').fetchone()['n']
    row = reserve(ledger)
    result = provider.perform_reserved(row['id'], ledger['owner_id'], 'Instructions', 'Evidence')
    assert result['connection_generation'] == ledger['generation']
    with database() as connection:
        saved = provider.get_succeeded(connection, owner_id=ledger['owner_id'], request_key=row['request_key'])
        assert saved['output_sha256'] == hashlib.sha256(result['text'].encode()).hexdigest()
        assert saved['usage']['kind'] == 'chatgpt_subscription'
        assert provider.get_succeeded(connection, owner_id='foreign', request_key=row['request_key']) is None
        assert connection.execute('SELECT count(*) AS n FROM video_provider_calls').fetchone()['n'] == before
    with pytest.raises(provider.ProviderError, match='ALREADY_ATTEMPTED'):
        provider.perform_reserved(row['id'], ledger['owner_id'], 'Instructions', 'Evidence')
    assert len(calls) == 1


@pytest.mark.parametrize('code,unknown', [('CHATGPT_TIMEOUT', True), ('CHATGPT_QUOTA', False), ('CHATGPT_AUTH_EXPIRED', False)])
def test_failure_is_terminal_never_resends_and_auth_failures_pause(ledger, monkeypatch, code, unknown):
    calls = []
    def generate(*args):
        calls.append(True)
        raise provider.ProviderError(code, unknown=unknown)
    monkeypatch.setattr(provider, '_generate', generate)
    row = reserve(ledger)
    with pytest.raises(provider.ProviderError, match=code):
        provider.perform_reserved(row['id'], ledger['owner_id'], 'Instructions', 'Evidence')
    with database() as connection:
        saved = connection.execute('SELECT * FROM chatgpt_calls WHERE id=%s', (row['id'],)).fetchone()
    assert saved['state'] == ('unknown' if unknown else 'failed')
    assert saved['error_code'] == code and saved['api_cost_microusd'] is None
    with pytest.raises(provider.ProviderError, match='ALREADY_ATTEMPTED'):
        provider.perform_reserved(row['id'], ledger['owner_id'], 'Instructions', 'Evidence')
    assert len(calls) == 1
    if code in ('CHATGPT_QUOTA', 'CHATGPT_AUTH_EXPIRED'):
        assert not ledger['current']['available']


@pytest.mark.parametrize('change,code', [
    ('lease', 'LEASE_LOST'), ('binding', 'LEASE_LOST'), ('generation', 'CONNECTION_CHANGED'),
    ('expires', 'CALL_EXPIRED'), ('payload', 'CONFLICT')])
def test_dispatch_rechecks_lease_binding_generation_expiry_and_exact_payload(ledger, monkeypatch, change, code):
    row = reserve(ledger)
    monkeypatch.setattr(provider, '_generate', lambda *args: pytest.fail('No provider call allowed'))
    if change == 'generation':
        ledger['current']['generation'] = str(uuid4())
    with database() as connection:
        if change == 'lease':
            connection.execute('UPDATE replay_jobs SET lease_token=%s WHERE id=%s', (uuid4(), ledger['job_id']))
        elif change == 'binding':
            connection.execute('DELETE FROM portal_dota_profiles WHERE owner_id=%s', (ledger['owner_id'],))
        elif change == 'expires':
            connection.execute("UPDATE chatgpt_calls SET expires_at=now()-interval '1 second' WHERE id=%s", (row['id'],))
    with pytest.raises(provider.ProviderError, match=code):
        provider.perform_reserved(row['id'], ledger['owner_id'], 'Instructions', 'Changed' if change == 'payload' else 'Evidence')


def test_disconnect_during_generation_discards_output(ledger, monkeypatch):
    row = reserve(ledger)
    def generate(*args):
        ledger['current']['connected'] = False
        return provider._completed(completed()['response'], provider.MODEL)
    monkeypatch.setattr(provider, '_generate', generate)
    with pytest.raises(provider.ProviderError, match='CONNECTION_CHANGED'):
        provider.perform_reserved(row['id'], ledger['owner_id'], 'Instructions', 'Evidence')
    with database() as connection:
        saved = connection.execute('SELECT state,output_text,usage FROM chatgpt_calls WHERE id=%s', (row['id'],)).fetchone()
    assert saved['state'] == 'failed' and saved['output_text'] is None and saved['usage']


@pytest.mark.skipif(os.environ.get('NARMA_SYNTHETIC_PGLITE') == '1', reason='Requires native PostgreSQL locks')
def test_native_concurrent_reservation_has_one_row(ledger):
    with ThreadPoolExecutor(max_workers=2) as workers:
        rows = list(workers.map(lambda _: reserve(ledger), range(2)))
    assert rows[0]['id'] == rows[1]['id']


@pytest.mark.skipif(os.environ.get('NARMA_SYNTHETIC_PGLITE') == '1', reason='Requires native PostgreSQL locks')
def test_native_concurrent_dispatch_has_one_network_attempt(ledger, monkeypatch):
    row = reserve(ledger)
    attempts = []
    def generate(*args):
        attempts.append(True)
        return provider._completed(completed()['response'], provider.MODEL)
    monkeypatch.setattr(provider, '_generate', generate)
    def run(_):
        try:
            provider.perform_reserved(row['id'], ledger['owner_id'], 'Instructions', 'Evidence')
            return 'succeeded'
        except provider.ProviderError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=2) as workers:
        states = list(workers.map(run, range(2)))
    assert states.count('succeeded') == 1 and states.count('CHATGPT_CALL_ALREADY_ATTEMPTED') == 1
    assert len(attempts) == 1
