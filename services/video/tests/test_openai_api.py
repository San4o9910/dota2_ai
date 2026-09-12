"""Mock transport and isolated SQL accounting; never real provider calls."""
from copy import deepcopy
import json
import os
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from narma_video import openai_provider as provider, openai_budget as budget
from narma_video.db import database, migrate

SCHEMA = {'type': 'object', 'additionalProperties': False,
          'properties': {'summary': {'type': 'string'}}, 'required': ['summary']}
TEXT = '{"summary":"Проверь контекст перед решением"}'


def response(text=TEXT, **changes):
    return {'model': provider.MODEL, 'status': 'completed', 'service_tier': 'default',
        'output': [{'type': 'reasoning', 'summary': [{'text': 'private reasoning'}]},
            {'type': 'message', 'role': 'assistant', 'status': 'completed',
             'content': [{'type': 'output_text', 'text': text}]}],
        'usage': {'input_tokens': 100, 'output_tokens': 50, 'total_tokens': 150,
                  'input_tokens_details': {'cached_tokens': 75, 'cache_write_tokens': 0},
                  'output_tokens_details': {'reasoning_tokens': 30}}, **changes}


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'synthetic-key-never-real')
    monkeypatch.setenv('OPENAI_MODEL', provider.MODEL)
    monkeypatch.setenv('OPENAI_MAX_DAILY_CALLS', '20')
    return monkeypatch


def transport(monkeypatch, handler):
    original = httpx.Client
    def client(**kwargs):
        assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
        return original(**kwargs, transport=httpx.MockTransport(handler))
    monkeypatch.setattr(provider.httpx, 'Client', client)


def test_fixed_https_tool_free_bounded_request(configured):
    seen = []
    def handler(request):
        seen.append(request)
        assert str(request.url) == 'https://api.openai.com/v1/responses'
        assert request.headers['authorization'] == 'Bearer synthetic-key-never-real'
        assert 'chatgpt-account-id' not in request.headers
        value = json.loads(request.content)
        assert value['tools'] == [] and value['tool_choice'] == 'none'
        assert value['store'] is False and value['stream'] is False
        assert value['text']['format']['strict'] is True
        assert value['max_output_tokens'] == 5000 and value['service_tier'] == 'default'
        assert 'previous_response_id' not in value
        return httpx.Response(200, json=response())
    transport(configured, handler)
    value = provider._generate(provider.request_payload('Instructions', 'Evidence', SCHEMA))
    assert provider._text(value) == TEXT and len(seen) == 1


@pytest.mark.parametrize('status,code', [(401, 'AUTHENTICATION_FAILED'), (403, 'AUTHENTICATION_FAILED'),
    (429, 'RATE_LIMITED'), (503, 'PROVIDER_UNAVAILABLE'), (400, 'PROVIDER_REJECTED'), (302, 'PROVIDER_REJECTED')])
def test_private_errors_no_retry_or_redirect(configured, status, code):
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(status, headers={'location': 'https://attacker.test'}, content=b'private-key private-evidence')
    transport(configured, handler)
    with pytest.raises(provider.ProviderError, match=code) as failure:
        provider._generate(provider.request_payload('Instructions', 'Evidence', SCHEMA))
    assert len(seen) == 1 and 'private' not in str(failure.value)


def test_timeout_is_not_retried(configured):
    seen = []
    def handler(request):
        seen.append(request)
        raise httpx.ReadTimeout('private URL/token')
    transport(configured, handler)
    with pytest.raises(provider.ProviderError, match='TIMEOUT'):
        provider._generate(provider.request_payload('Instructions', 'Evidence', SCHEMA))
    assert len(seen) == 1


def test_nested_optional_strict_schema_not_mutated():
    schema = {'type': 'object', 'properties': {'summary': {'type': 'string'},
        'optional': {'type': 'string', 'default': 'value'},
        'children': {'type': 'array', 'items': {'type': 'object', 'properties': {
            'note': {'anyOf': [{'type': 'string'}, {'type': 'null'}], 'default': None}}}}},
        'required': ['summary', 'children']}
    before = deepcopy(schema)
    value = provider.strict_schema(schema)
    assert schema == before and set(value['required']) == {'summary', 'optional', 'children'}
    assert value['properties']['optional']['anyOf'][1] == {'type': 'null'}
    child = value['properties']['children']['items']
    assert child['required'] == ['note'] and child['additionalProperties'] is False
    assert 'default' not in json.dumps(value)


@pytest.mark.parametrize('field,value', [('max_output_tokens', 0), ('max_output_tokens', True),
    ('max_output_tokens', 8193), ('model', 'gpt-6-astra')])
def test_no_model_upgrade_or_unbounded_output(field, value):
    with pytest.raises(provider.ProviderError):
        provider.request_payload('Instructions', 'Evidence', SCHEMA, **{field: value})


def test_input_bound_includes_utf8_and_schema():
    with pytest.raises(provider.ProviderError, match='TOO_LARGE'):
        provider.request_payload('Instructions', 'я' * (provider.MAX_INPUT_BYTES // 2), SCHEMA)
    value = provider.request_payload('Instructions', 'Evidence', SCHEMA)
    assert provider.input_token_bound(value) > len(json.dumps(value).encode())


@pytest.mark.parametrize('mutate,code', [
    (lambda v: v.update(status='incomplete'), 'INCOMPLETE'),
    (lambda v: v.update(output=[{'type': 'function_call'}]), 'TOOLS_FORBIDDEN'),
    (lambda v: v['output'][1].update(content=[{'type': 'refusal', 'refusal': 'no'}]), 'REFUSED'),
    (lambda v: v.update(model='gpt-6-astra'), 'INVALID'),
    (lambda v: v.update(service_tier='priority'), 'INVALID'),
    (lambda v: v['output'][1].update(content=[{'type': 'output_text', 'text': 'not json'}]), 'INVALID'),
])
def test_unusable_output_rejected(mutate, code):
    value = response()
    mutate(value)
    with pytest.raises(provider.ProviderError, match=code):
        provider._text(value)


def test_reasoning_not_double_charged_and_cache_read_discount():
    values, cost = budget.normalize_usage(response()['usage'])
    assert cost == 1130 and values['output_tokens_details']['reasoning_tokens'] == 30
    assert budget.normalize_usage(None) == (None, None)


@pytest.mark.parametrize('details,cost', [
    ({'cached_tokens': 60, 'cache_write_tokens': 20}, 1204),
    ({'cached_tokens': 0, 'cache_write_tokens': 100}, 1500),
    ({'cache_write_tokens': 100}, 1500),
    ({'cached_tokens': 100, 'cache_write_tokens': 0}, 1040),
    ({'cached_tokens': 75}, 1155),
    (None, 1500),
])
def test_cache_buckets_are_disjoint_and_charged_once(details, cost):
    usage = {**response()['usage'], 'input_tokens_details': details}
    before = deepcopy(usage)
    assert budget.normalize_usage(usage)[1] == cost
    assert usage == before


@pytest.mark.parametrize('tokens,cost', [(1, 1), (2, 1), (3, 2), (5, 2), (6, 3)])
def test_fractional_cache_read_cost_rounds_up_once(tokens, cost):
    usage = {'input_tokens': tokens, 'output_tokens': 0, 'total_tokens': tokens,
             'input_tokens_details': {'cached_tokens': tokens, 'cache_write_tokens': 0}}
    assert budget.normalize_usage(usage)[1] == cost


def test_reservation_covers_all_input_being_written_to_cache():
    usage = {'input_tokens': budget.MAX_INPUT_TOKENS, 'output_tokens': 5000,
             'total_tokens': budget.MAX_INPUT_TOKENS + 5000,
             'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': budget.MAX_INPUT_TOKENS}}
    assert budget.estimate_reservation(budget.MAX_INPUT_TOKENS, 5000) == 1300000
    assert budget.normalize_usage(usage)[1] == budget.estimate_reservation(budget.MAX_INPUT_TOKENS, 5000)


@pytest.mark.parametrize('usage', [
    {'input_tokens': True, 'output_tokens': 1, 'total_tokens': 2},
    {'input_tokens': 100, 'output_tokens': 1, 'total_tokens': 100},
    {**response()['usage'], 'output_tokens_details': {'reasoning_tokens': 51}},
    {**response()['usage'], 'input_tokens_details': {'cached_tokens': 101}},
    {**response()['usage'], 'input_tokens_details': {'cached_tokens': 80, 'cache_write_tokens': 21}},
    {**response()['usage'], 'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 101}},
    {**response()['usage'], 'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': True}},
    {**response()['usage'], 'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': -1}},
    {**response()['usage'], 'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 1.5}},
    {**response()['usage'], 'input_tokens_details': {'cached_tokens': 0, 'unpriced_tokens': 20}},
    {**response()['usage'], 'input_tokens_details': {}},
    {**response()['usage'], 'unpriced_audio_tokens': 200},
])
def test_invalid_usage_never_free(usage):
    with pytest.raises(ValueError, match='USAGE_INVALID'):
        budget.normalize_usage(usage)


@pytest.fixture
def sql(configured):
    url = os.environ.get('TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set isolated TEST_DATABASE_URL')
    configured.setenv('DATABASE_URL', url)
    migrate()
    with database() as connection:
        connection.execute('TRUNCATE openai_api_calls')
        connection.execute("""UPDATE openai_api_budget SET enabled=true,limit_microusd=10000000,
            reserved_microusd=0,spent_microusd=0,frozen_reason=NULL,model=%s,price_policy=%s,
            expires_at=%s::timestamptz WHERE id=1""", (provider.MODEL, budget.POLICY, budget.PRICE_EXPIRES))
    yield configured
    with database() as connection:
        connection.execute('TRUNCATE openai_api_calls')
        connection.execute("DELETE FROM video_jobs WHERE owner_id LIKE 'synthetic-openai-%%'")


def video(owner=None):
    with database() as connection:
        return connection.execute("""INSERT INTO video_jobs(id,owner_id,account_id,nickname,filename,
            size_bytes,source_sha256,state,lease_token,lease_expires_at)
            VALUES (%s,%s,123,'Player','test.mp4',100,%s,'processing',%s,now()+interval '10 minutes')
            RETURNING *""", (uuid4(), owner or 'synthetic-openai-' + uuid4().hex, 'a' * 64, uuid4())).fetchone()


def reserve(job, key='video-test', **changes):
    args = dict(owner_id=job['owner_id'], request_key=key, instructions='Instructions', input_data='Evidence',
        schema=SCHEMA, kind='video', video_job_id=job['id'], lease_token=job['lease_token'])
    args.update(changes)
    with database() as connection:
        return provider.reserve_call(connection, **args)


def perform(row):
    return provider.perform_reserved(row['id'], row['owner_id'], 'Instructions', 'Evidence', SCHEMA)


def lookup(row):
    with database() as connection:
        return connection.execute('SELECT * FROM openai_api_calls WHERE id=%s', (row['id'],)).fetchone()


def test_owner_bound_idempotent_reservation_unique_source(sql):
    job = video()
    row = reserve(job)
    assert reserve(job)['id'] == row['id']
    assert budget.status()['reserved_microusd'] == row['reserved_microusd']
    with pytest.raises(provider.ProviderError, match='CONFLICT'):
        reserve(job, input_data='Changed evidence')
    with pytest.raises(provider.ProviderError, match='ALREADY_ATTEMPTED'):
        reserve(job, key='another-key')
    with pytest.raises(provider.ProviderError, match='LEASE_LOST'):
        reserve(job, owner_id='synthetic-openai-other')


def test_settle_once_reuse_after_worker_reclaim(sql):
    job, calls = video(), []
    row = reserve(job)
    sql.setattr(provider, '_generate', lambda payload: calls.append(payload) or response())
    result = perform(row)
    assert result['cost_microusd'] == 1130 and len(calls) == 1
    assert budget.status()['spent_microusd'] == 1130 and budget.status()['reserved_microusd'] == 0
    budget.settle(row['id'], row['owner_id'], response()['usage'], text=TEXT)
    assert budget.status()['spent_microusd'] == 1130
    with database() as connection:
        job = connection.execute('UPDATE video_jobs SET lease_token=%s WHERE id=%s RETURNING *',
                                 (uuid4(), job['id'])).fetchone()
    assert reserve(job)['output_text'] == TEXT
    with pytest.raises(provider.ProviderError, match='ALREADY_ATTEMPTED'):
        perform(row)
    assert len(calls) == 1


def test_cache_write_response_settles_within_ceiling_without_freezing(sql):
    row = reserve(video())
    usage = {'input_tokens': row['input_token_bound'], 'output_tokens': row['max_output_tokens'],
        'total_tokens': row['input_token_bound'] + row['max_output_tokens'],
        'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': row['input_token_bound']},
        'output_tokens_details': {'reasoning_tokens': 30}}
    sql.setattr(provider, '_generate', lambda payload: response(usage=usage))
    value = perform(row)
    assert value['cost_microusd'] == row['reserved_microusd']
    assert lookup(row)['usage']['input_tokens_details'] == usage['input_tokens_details']
    assert budget.status()['enabled'] and budget.status()['frozen_reason'] is None
    assert budget.status()['reserved_microusd'] == 0
    assert budget.status()['spent_microusd'] == row['reserved_microusd']


@pytest.mark.parametrize('failure', ['timeout', 'missing_usage', 'incomplete', 'invalid_json'])
def test_failures_keep_cost_or_unknown_hold_and_never_retry(sql, failure):
    row = reserve(video())
    calls = []
    def generate(payload):
        calls.append(payload)
        if failure == 'timeout':
            raise provider.ProviderError('OPENAI_TIMEOUT')
        return response(usage=None) if failure == 'missing_usage' else (
            response(status='incomplete') if failure == 'incomplete' else response(text='not json'))
    sql.setattr(provider, '_generate', generate)
    with pytest.raises(provider.ProviderError):
        perform(row)
    charged = failure in ('incomplete', 'invalid_json')
    value = lookup(row)
    assert value['billing_status'] == ('settled' if charged else 'unknown')
    assert value['charged_microusd'] == (1130 if charged else None)
    assert budget.status()['reserved_microusd'] == (0 if charged else row['reserved_microusd'])
    with pytest.raises(provider.ProviderError, match='ALREADY_ATTEMPTED'):
        perform(row)
    assert len(calls) == 1


@pytest.mark.parametrize('bad', ['invalid_usage', 'above_cap', 'wrong_model', 'overlapping_cache_buckets'])
def test_usage_violation_freezes_durably(sql, bad):
    row = reserve(video())
    value = response()
    if bad == 'invalid_usage': value['usage']['total_tokens'] = 1
    elif bad == 'above_cap': value['usage'] = {'input_tokens': 100, 'output_tokens': 8193, 'total_tokens': 8293}
    elif bad == 'wrong_model': value['model'] = 'gpt-6-astra'
    else: value['usage']['input_tokens_details'] = {'cached_tokens': 80, 'cache_write_tokens': 21}
    sql.setattr(provider, '_generate', lambda payload: value)
    with pytest.raises(ValueError, match='RECONCILIATION_REQUIRED'):
        perform(row)
    assert not budget.status()['enabled'] and budget.status()['frozen_reason']
    with pytest.raises(ValueError, match='DISABLED'):
        reserve(video())


@pytest.mark.parametrize('change', ['lease', 'deleted', 'owner', 'source', 'budget'])
def test_dispatch_rechecks_source_and_budget(sql, change):
    job = video()
    row = reserve(job)
    with database() as connection:
        if change == 'lease': connection.execute("UPDATE video_jobs SET lease_expires_at=now()-interval '1 second' WHERE id=%s", (job['id'],))
        elif change == 'deleted': connection.execute("UPDATE video_jobs SET state='deleted' WHERE id=%s", (job['id'],))
        elif change == 'owner': connection.execute("UPDATE video_jobs SET owner_id='synthetic-openai-other' WHERE id=%s", (job['id'],))
        elif change == 'source': connection.execute('UPDATE video_jobs SET source_sha256=%s WHERE id=%s', ('b' * 64, job['id']))
        else: connection.execute('UPDATE openai_api_budget SET enabled=false WHERE id=1')
    sql.setattr(provider, '_generate', lambda payload: pytest.fail('Must not dispatch'))
    with pytest.raises(ValueError):
        perform(row)
    assert lookup(row)['state'] == 'reserved'


def test_delete_during_call_charges_without_restoring_private_output(sql):
    job = video()
    row = reserve(job)
    def generate(payload):
        with database() as connection:
            connection.execute("UPDATE video_jobs SET state='deleted' WHERE id=%s", (job['id'],))
            provider.forget_output(connection, owner_id=job['owner_id'], video_job_id=job['id'])
        return response()
    sql.setattr(provider, '_generate', generate)
    with pytest.raises(provider.ProviderError):
        perform(row)
    value = lookup(row)
    assert value['state'] == 'failed' and value['output_text'] is None and value['charged_microusd'] == 1130
    assert budget.status()['spent_microusd'] == 1130


def test_operator_config_preserves_holds_and_spend_never_unfreezes(sql):
    row = reserve(video())
    with database() as connection:
        connection.execute('UPDATE openai_api_budget SET spent_microusd=777 WHERE id=1')
    value = budget.configure(limit_microusd=2000000, expires_at=budget.PRICE_EXPIRES, enable=True)
    assert value['spent_microusd'] == 777 and value['reserved_microusd'] == row['reserved_microusd']
    with pytest.raises(ValueError, match='CONFIG_INVALID'):
        budget.configure(limit_microusd=100, expires_at=budget.PRICE_EXPIRES, enable=True)
    with database() as connection:
        connection.execute("UPDATE openai_api_budget SET frozen_reason='needs-review' WHERE id=1")
    with pytest.raises(ValueError, match='RECONCILIATION_REQUIRED'):
        budget.configure(limit_microusd=2000000, expires_at=budget.PRICE_EXPIRES, enable=True)


def cache_pricing_migration(connection):
    path = Path(__file__).parent.parent / 'migrations' / '022_openai_cache_pricing.sql'
    connection.execute(path.read_text())


@pytest.mark.parametrize('enabled,frozen', [(True, None), (False, None), (False, 'needs-review')])
def test_cache_policy_migration_preserves_spend_history_and_authorization(sql, enabled, frozen):
    row = reserve(video())
    sql.setattr(provider, '_generate', lambda payload: response())
    perform(row)
    old_policy = 'gpt-5.6-sol-standard-2026-09-12'
    with database() as connection:
        connection.execute('UPDATE openai_api_calls SET price_policy=%s WHERE id=%s', (old_policy, row['id']))
        connection.execute('UPDATE openai_api_budget SET price_policy=%s,enabled=%s,frozen_reason=%s WHERE id=1',
                           (old_policy, enabled, frozen))
        before = connection.execute('SELECT * FROM openai_api_budget WHERE id=1').fetchone()
        historical = connection.execute('SELECT * FROM openai_api_calls WHERE id=%s', (row['id'],)).fetchone()
        cache_pricing_migration(connection)
        after = connection.execute('SELECT * FROM openai_api_budget WHERE id=1').fetchone()
        assert after['price_policy'] == budget.POLICY
        for name in ('spent_microusd', 'reserved_microusd', 'limit_microusd', 'enabled', 'frozen_reason', 'expires_at'):
            assert after[name] == before[name]
        assert connection.execute('SELECT * FROM openai_api_calls WHERE id=%s', (row['id'],)).fetchone() == historical


@pytest.mark.parametrize('state,billing', [('reserved', 'reserved'), ('calling', 'reserved'),
    ('unknown', 'unknown'), ('failed', 'breach')])
def test_cache_policy_migration_cannot_reprice_unresolved_obligations(sql, state, billing):
    row = reserve(video())
    old_policy = 'gpt-5.6-sol-standard-2026-09-12'
    with database() as connection:
        connection.execute('UPDATE openai_api_calls SET price_policy=%s,state=%s,billing_status=%s,'
                           'started_at=now(),finished_at=now() WHERE id=%s', (old_policy, state, billing, row['id']))
        connection.execute('UPDATE openai_api_budget SET price_policy=%s,spent_microusd=777 WHERE id=1', (old_policy,))
        before = connection.execute('SELECT * FROM openai_api_calls WHERE id=%s', (row['id'],)).fetchone()
        cache_pricing_migration(connection)
        after = connection.execute('SELECT * FROM openai_api_budget WHERE id=1').fetchone()
        assert after['price_policy'] == old_policy and not after['enabled']
        assert after['frozen_reason'] == 'PRICE_POLICY_UPGRADE_REQUIRES_RECONCILIATION'
        assert after['spent_microusd'] == 777 and after['reserved_microusd'] == row['reserved_microusd']
        assert connection.execute('SELECT * FROM openai_api_calls WHERE id=%s', (row['id'],)).fetchone() == before
    sql.setattr(provider, '_generate', lambda payload: pytest.fail('Old reservation must not dispatch'))
    with pytest.raises(ValueError):
        perform(row)


def test_cache_policy_migration_preserves_existing_freeze_and_unattributed_hold(sql):
    with database() as connection:
        connection.execute("""UPDATE openai_api_budget SET price_policy='gpt-5.6-sol-standard-2026-09-12',
            enabled=false,spent_microusd=777,reserved_microusd=123,frozen_reason='existing-freeze' WHERE id=1""")
        cache_pricing_migration(connection)
        after = connection.execute('SELECT * FROM openai_api_budget WHERE id=1').fetchone()
        assert after['price_policy'] == 'gpt-5.6-sol-standard-2026-09-12'
        assert not after['enabled'] and after['frozen_reason'] == 'existing-freeze'
        assert after['spent_microusd'] == 777 and after['reserved_microusd'] == 123


def test_disabled_budget_blocks_before_inference_and_keeps_gemini_ledger(sql):
    with database() as connection:
        connection.execute('UPDATE openai_api_budget SET enabled=false WHERE id=1')
        before = connection.execute('SELECT count(*) AS n FROM video_provider_calls').fetchone()['n']
    with pytest.raises(ValueError, match='DISABLED'):
        reserve(video())
    with database() as connection:
        assert connection.execute('SELECT count(*) AS n FROM video_provider_calls').fetchone()['n'] == before
        assert connection.execute('SELECT count(*) AS n FROM openai_api_calls').fetchone()['n'] == 0


def test_daily_call_limit_applies_per_client_but_allowance_is_shared(sql):
    sql.setenv('OPENAI_MAX_DAILY_CALLS', '1')
    owner = 'synthetic-openai-one'
    first = reserve(video(owner))
    with pytest.raises(provider.ProviderError, match='DAILY_LIMIT'):
        reserve(video(owner), key='second-job')
    second = reserve(video())
    assert budget.status()['reserved_microusd'] == first['reserved_microusd'] + second['reserved_microusd']


@pytest.mark.parametrize('change', ['expired', 'policy', 'model', 'exhausted'])
def test_stale_price_or_exhausted_allowance_never_reserves(sql, change):
    with database() as connection:
        if change == 'expired':
            connection.execute("UPDATE openai_api_budget SET expires_at=now()-interval '1 second' WHERE id=1")
        elif change == 'policy':
            connection.execute("UPDATE openai_api_budget SET price_policy='unverified' WHERE id=1")
        elif change == 'model':
            connection.execute("UPDATE openai_api_budget SET model='gpt-6-astra' WHERE id=1")
        else:
            connection.execute('UPDATE openai_api_budget SET limit_microusd=1 WHERE id=1')
    with pytest.raises(ValueError, match='OPENAI_BUDGET_'):
        reserve(video())
    assert budget.status()['reserved_microusd'] == 0


def test_native_postgres_concurrent_owners_cannot_overspend_shared_allowance(sql):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    with database() as connection:
        version = connection.execute('SELECT version() AS version').fetchone()['version'].lower()
    if any(word in version for word in ('emscripten', 'wasm', 'pglite')):
        pytest.skip('Native PostgreSQL row-lock concurrency gate runs in CI')
    jobs = [video(), video()]
    payload = provider.request_payload('Instructions', 'Evidence', SCHEMA)
    amount = budget.estimate_reservation(provider.input_token_bound(payload), 5000)
    with database() as connection:
        connection.execute('UPDATE openai_api_budget SET limit_microusd=%s WHERE id=1', (amount,))
    gate = Barrier(2)
    def attempt(job):
        gate.wait(timeout=5)
        try:
            return reserve(job)['state']
        except ValueError as error:
            return str(error)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, jobs))
    assert sorted(outcomes) == ['OPENAI_BUDGET_EXCEEDED', 'reserved']
    assert budget.status()['reserved_microusd'] == amount
