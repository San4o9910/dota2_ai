"""Paid replay routing keeps selected-player and training-context boundaries."""
from copy import deepcopy
import json
import os
from uuid import uuid4

import pytest

from narma_video import replay_coach as coach, openai_provider as provider, openai_budget as budget
from narma_video.db import database, migrate
from test_replay_coach import FACTS, RESULT


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

