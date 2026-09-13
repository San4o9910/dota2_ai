"""Paid replay routing keeps selected-player and training-context boundaries."""
from copy import deepcopy
from contextlib import contextmanager
import json
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest

from narma_video import replay_coach as coach, openai_provider as provider, openai_budget as budget
from narma_video.db import database, migrate
from test_replay_coach import FACTS, RESULT, RESULT_V2


@pytest.fixture
def paid(monkeypatch):
    monkeypatch.setenv('REPLAY_COACH_PROVIDER', 'openai_api')
    monkeypatch.setenv('OPENAI_API_KEY', 'synthetic-unused-key')
    monkeypatch.setenv('OPENAI_MODEL', provider.MODEL)
    def forbidden(*args, **kwargs):
        pytest.fail('Paid API must never use Gemini or personal OAuth')
    monkeypatch.setattr(coach, 'GeminiReplayCoach', forbidden)
    monkeypatch.setattr(coach, 'analyze_subscription_replay', forbidden)
    return monkeypatch


def test_explicit_api_route_preserves_facts_and_provenance(paid):
    seen = []
    def analyze(job, facts, context, encoded, ids):
        seen.append(json.loads(encoded))
        return coach.validate_coaching(RESULT, ids), 'call'
    paid.setattr(coach, 'analyze_api_replay', analyze)
    before = deepcopy(FACTS)
    result = coach.enrich_report({'id': 'job'}, FACTS)
    assert result['coaching']['status'] == 'ready'
    assert result['coaching']['usage_kind'] == 'openai_api'
    assert result['coaching']['provider'] == 'openai' and result['coaching']['model'] == provider.MODEL
    assert FACTS == before and result['evidence'] == FACTS['evidence']
    assert 'account_id' not in seen[0]['player']


@pytest.mark.parametrize('error,code,category', [
    (provider.ProviderError('OPENAI_NOT_CONFIGURED'), 'OPENAI_NOT_CONFIGURED', 'configuration'),
    (provider.ProviderError('OPENAI_AUTHENTICATION_FAILED'), 'OPENAI_AUTHENTICATION_FAILED', 'authentication'),
    (provider.ProviderError('OPENAI_TIMEOUT'), 'OPENAI_TIMEOUT', 'timeout'),
    (ValueError('OPENAI_BUDGET_DISABLED'), 'OPENAI_BUDGET_DISABLED', 'budget'),
    (RuntimeError('secret provider body'), 'REPLAY_COACH_UNAVAILABLE', 'unknown'),
])
def test_api_failure_keeps_parser_report_no_fallback(paid, error, code, category, capsys):
    def fail(*args):
        raise error
    paid.setattr(coach, 'analyze_api_replay', fail)
    value = coach.enrich_report({'id': 'job'}, FACTS)
    assert value['coaching']['status'] == 'unavailable'
    assert value['coaching']['failure_code'] == code and value['coaching']['failure_category'] == category
    assert value['metrics'] == FACTS['metrics'] and value['evidence'] == FACTS['evidence']
    assert 'secret' not in json.dumps(value) + capsys.readouterr().out


@pytest.mark.parametrize('change', ['evidence', 'numeric', 'unknown', 'success'])
def test_paid_output_business_validation_and_cache(paid, change):
    value = deepcopy(RESULT)
    if change == 'evidence': value['points'][0]['evidence_ids'] = ['another-owner-evidence']
    elif change == 'numeric': value['summary'] = 'Ты умер 10 раз'
    row = {'id': 'call', 'state': 'unknown' if change == 'unknown' else 'succeeded',
           'output_text': json.dumps(value)}
    paid.setattr(coach, 'reserve_api_replay', lambda *args: row)
    paid.setattr(provider, 'perform_reserved', lambda *args: pytest.fail('No repeat request'))
    result = coach.enrich_report({'id': 'job', 'owner_id': 'owner'}, FACTS)
    assert result['coaching']['status'] == ('ready' if change == 'success' else 'unavailable')


@pytest.mark.parametrize('change', ['valid', 'legacy_downgrade', 'invalid_condition', 'incomplete'])
def test_new_paid_call_requests_structured_decisions_once_and_keeps_failure_facts(paid, change):
    calls = []
    paid.setattr(coach, 'reserve_api_replay', lambda *args: {
        'id': 'call', 'state': 'reserved', '_coaching_contract': coach.COACHING_SCHEMA_V2})
    def perform(call_id, owner_id, instructions, encoded, schema):
        calls.append((call_id, owner_id, instructions, encoded, schema))
        if change == 'incomplete':
            raise provider.ProviderError('OPENAI_RESPONSE_INCOMPLETE')
        value = deepcopy(RESULT if change == 'legacy_downgrade' else RESULT_V2)
        if change == 'invalid_condition':
            value['points'][0]['when_to_apply'] = 'У тебя было 700 золота.'
        return {'text': json.dumps(value)}
    paid.setattr(provider, 'perform_reserved', perform)
    result = coach.enrich_report({'id': 'job', 'owner_id': 'owner'}, FACTS)
    assert len(calls) == 1
    assert calls[0][2] == coach.API_SYSTEM_V2
    assert calls[0][4] == coach.ReplayCoachingV2.model_json_schema()
    payload = provider.request_payload(calls[0][2], calls[0][3], calls[0][4])
    assert payload['max_output_tokens'] == 5000
    assert result['metrics'] == FACTS['metrics'] and result['evidence'] == FACTS['evidence']
    assert result['coaching']['status'] == ('ready' if change == 'valid' else 'unavailable')
    if change == 'valid':
        assert result['coaching']['schema_version'] == coach.COACHING_SCHEMA_V2
        assert result['coaching']['call_id'] == 'call'
        assert result['coaching']['points'] == RESULT_V2['points']


@pytest.mark.parametrize('legacy', [True, False])
def test_saved_versioned_output_does_not_generate_another_response(paid, legacy):
    value = RESULT if legacy else RESULT_V2
    paid.setattr(coach, 'reserve_api_replay', lambda *args: {
        'id': 'saved-call', 'state': 'succeeded', 'output_text': json.dumps(value),
        '_coaching_contract': 'legacy' if legacy else coach.COACHING_SCHEMA_V2})
    paid.setattr(provider, 'perform_reserved', lambda *args: pytest.fail('Saved output must not generate'))
    result = coach.enrich_report({'id': 'job', 'owner_id': 'owner'}, FACTS)
    assert result['coaching']['status'] == 'ready'
    assert result['coaching']['call_id'] == 'saved-call'
    assert {key: result['coaching'][key] for key in value} == value


@pytest.mark.parametrize('change', ['unchanged', 'facts', 'context'])
def test_legacy_request_selection_rebuilds_digest_from_current_facts_and_context(paid, change):
    job = {'id': 'job', 'owner_id': 'owner', 'account_id': 123, 'match_id': '8984479726',
           'source_sha256': 'a' * 64, 'lease_token': 'lease'}
    facts = {**deepcopy(FACTS), 'match_id': job['match_id'],
             'coverage': {'source_sha256': job['source_sha256'], 'complete': True}}
    original, _ = coach.prepare_evidence(facts)
    legacy_digest = provider.request_digest(coach.SYSTEM, original, coach.ReplayCoaching.model_json_schema())
    context = {'position': None, 'exercise_id': None, 'mmr': None, 'training_level': None}
    queries, reservations = [], []
    if change == 'facts':
        facts['metrics']['kills'] += 1
    if change == 'context':
        context['mmr'] = 5000
    encoded, _ = coach.prepare_evidence(facts, mmr=context['mmr'])
    class Connection:
        def execute(self, sql, params=None):
            queries.append((sql, params))
            row = {'id': job['id'], 'position': None, 'requested_mmr': context['mmr'], 'training_level': None}
            if 'FROM openai_api_calls' in sql:
                row = {'request_sha256': legacy_digest}
            return SimpleNamespace(fetchone=lambda: row)
    @contextmanager
    def db():
        yield Connection()
    def reserve(connection, **request):
        reservations.append(request)
        # The unchanged provider gate reuses only an exact stored request key;
        # changed inputs remain subject to the one-attempt rule.
        if request['request_key'] != f"replay:{job['id']}:{legacy_digest}":
            raise provider.ProviderError('OPENAI_CALL_ALREADY_ATTEMPTED')
        return {'id': 'saved-call', 'state': 'succeeded', 'output_text': json.dumps(RESULT)}
    paid.setattr(coach, 'database', db)
    paid.setattr(provider, 'reserve_call', reserve)
    if change == 'unchanged':
        row = coach.reserve_api_replay(job, facts, context, encoded)
        assert row['_coaching_contract'] == 'legacy'
        assert row['id'] == 'saved-call'
    else:
        with pytest.raises(provider.ProviderError, match='OPENAI_CALL_ALREADY_ATTEMPTED'):
            coach.reserve_api_replay(job, facts, context, encoded)
    assert len(reservations) == 1
    request = reservations[0]
    assert request['owner_id'] == job['owner_id'] and request['lease_token'] == job['lease_token']
    assert request['instructions'] == (coach.SYSTEM if change == 'unchanged' else coach.API_SYSTEM_V2)
    lookup = next((sql, args) for sql, args in queries if 'FROM openai_api_calls' in sql)
    assert 'owner_id=%s AND job_id=%s AND source_sha256=%s' in lookup[0]
    assert lookup[1] == (job['owner_id'], job['id'], job['source_sha256'])


@pytest.mark.parametrize('change', ['unchanged', 'facts', 'absent'])
def test_near_limit_legacy_cache_does_not_require_a_larger_v2_request(paid, change):
    job = {'id': 'job', 'owner_id': 'owner', 'account_id': 123, 'match_id': '8984479726',
           'source_sha256': 'a' * 64, 'lease_token': 'lease'}
    facts = {**deepcopy(FACTS), 'match_id': job['match_id'],
             'coverage': {'source_sha256': job['source_sha256'], 'complete': True}}
    # Synthetic request in the gap between the old and new schema overheads.
    facts['metrics']['padding'] = 'x' * 205000
    original, _ = coach.prepare_evidence(facts)
    legacy_digest = provider.request_digest(coach.SYSTEM, original, coach.ReplayCoaching.model_json_schema())
    with pytest.raises(provider.ProviderError, match='OPENAI_REQUEST_TOO_LARGE'):
        provider.request_digest(coach.API_SYSTEM_V2, original, coach.ReplayCoachingV2.model_json_schema())
    if change == 'facts':
        facts['metrics']['kills'] += 1
    encoded, ids = coach.prepare_evidence(facts)
    context = {'position': None, 'exercise_id': None, 'mmr': None, 'training_level': None}
    reservations, lookups = [], []
    class Connection:
        def execute(self, sql, params=None):
            row = {'id': job['id'], 'position': None, 'requested_mmr': None, 'training_level': None}
            if 'FROM openai_api_calls' in sql:
                lookups.append(params)
                row = None if change == 'absent' else {'request_sha256': legacy_digest}
            return SimpleNamespace(fetchone=lambda: row)
    @contextmanager
    def db():
        yield Connection()
    def reserve(connection, **request):
        reservations.append(request)
        assert request['instructions'] == coach.SYSTEM
        assert request['request_key'] == f"replay:{job['id']}:{legacy_digest}"
        return {'id': 'saved-call', 'state': 'succeeded', 'output_text': json.dumps(RESULT)}
    paid.setattr(coach, 'database', db)
    paid.setattr(provider, 'reserve_call', reserve)
    paid.setattr(provider, 'perform_reserved', lambda *args: pytest.fail('No paid dispatch or retry'))
    if change == 'unchanged':
        result, call_id = coach.analyze_api_replay(job, facts, context, encoded, ids)
        assert result.model_dump() == RESULT and call_id == 'saved-call'
        assert len(reservations) == 1
    else:
        with pytest.raises(provider.ProviderError, match='OPENAI_REQUEST_TOO_LARGE'):
            coach.analyze_api_replay(job, facts, context, encoded, ids)
        assert not reservations
    assert lookups == [(job['owner_id'], job['id'], job['source_sha256'])]


@pytest.fixture
def owned(paid):
    url = os.environ.get('TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set isolated TEST_DATABASE_URL')
    paid.setenv('DATABASE_URL', url)
    migrate()
    owner = 'synthetic-paid-replay'
    with database() as connection:
        connection.execute('TRUNCATE portal_accounts CASCADE')
        connection.execute('TRUNCATE openai_api_calls')
        connection.execute("""UPDATE openai_api_budget SET enabled=true,limit_microusd=10000000,
            spent_microusd=0,reserved_microusd=0,frozen_reason=NULL,expires_at=%s::timestamptz WHERE id=1""",
            (budget.PRICE_EXPIRES,))
        connection.execute("INSERT INTO portal_accounts(owner_id,email,password_hash) VALUES (%s,'paid@example.test','unused')", (owner,))
        connection.execute("""INSERT INTO portal_dota_profiles(owner_id,account_id,nickname,match_id,hero_name,side,source_sha256)
            VALUES (%s,123,'Player','8984479726','npc_dota_hero_viper','radiant',%s)""", (owner, 'a' * 64))
        job = connection.execute("""INSERT INTO replay_jobs(id,owner_id,filename,size_bytes,requested_nickname,nickname,
            match_id,account_id,source_sha256,state,lease_token,lease_expires_at,requested_position)
            VALUES (%s,%s,'synthetic.dem',100,'Player','Player','8984479726',123,%s,'processing',%s,now()+interval '5 minutes',5)
            RETURNING *""", (uuid4(), owner, 'a' * 64, uuid4())).fetchone()
    facts = {**deepcopy(FACTS), 'match_id': job['match_id'],
             'player': {**FACTS['player'], 'hero': 'npc_dota_hero_viper'},
             'coverage': {'source_sha256': job['source_sha256'], 'complete': True}}
    yield job, facts
    with database() as connection:
        connection.execute('TRUNCATE portal_accounts CASCADE')
        connection.execute('TRUNCATE openai_api_calls')


def test_real_api_reservation_binds_manual_role_and_source(owned):
    job, facts = owned
    context = coach.resolve_learning_context(job, facts)
    assert context['position'] == 5
    encoded, _ = coach.prepare_evidence(facts, position=context['position'])
    row = coach.reserve_api_replay(job, facts, context, encoded)
    assert row['lease_token'] == job['lease_token'] and row['source_sha256'] == job['source_sha256']
    assert row['kind'] == 'replay' and row['owner_id'] == job['owner_id']
    assert coach.reserve_api_replay(job, facts, context, encoded)['id'] == row['id']


def test_status_ledger_lookup_cannot_cross_owner_job_or_source(owned):
    from narma_video.replay_coaching_status import owned_call
    job, facts = owned
    context = coach.resolve_learning_context(job, facts)
    encoded, _ = coach.prepare_evidence(facts, position=context['position'])
    row = coach.reserve_api_replay(job, facts, context, encoded)
    with database() as connection:
        assert owned_call(connection, job)['id'] == row['id']
        assert owned_call(connection, {**job, 'owner_id': 'foreign-owner'}) is None
        assert owned_call(connection, {**job, 'id': uuid4()}) is None
        assert owned_call(connection, {**job, 'source_sha256': 'b' * 64}) is None


@pytest.mark.parametrize('change', ['source', 'account', 'incomplete', 'lease', 'role', 'mmr'])
def test_changed_or_unbound_source_never_reserves(owned, change):
    job, facts = owned
    context = coach.resolve_learning_context(job, facts)
    if change == 'source': facts['coverage']['source_sha256'] = 'b' * 64
    elif change == 'account': facts['player']['account_id'] = 999
    elif change == 'incomplete': facts['coverage']['complete'] = False
    elif change == 'lease': job['lease_token'] = uuid4()
    elif change == 'role': context['position'] = 1
    else: context['mmr'] = 8000
    encoded, _ = coach.prepare_evidence(facts)
    with pytest.raises(ValueError, match='REPLAY_COACH_(INPUT_INVALID|LEASE_LOST)'):
        coach.reserve_api_replay(job, facts, context, encoded)
    with database() as connection:
        assert connection.execute('SELECT count(*) AS n FROM openai_api_calls').fetchone()['n'] == 0
