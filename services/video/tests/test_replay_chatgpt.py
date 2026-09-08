"""Personal ChatGPT replay coaching: source fences and no paid fallback."""
from copy import deepcopy
import json
import os
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet

from narma_video import replay_coach as coach
from narma_video import chatgpt_auth as auth, chatgpt_provider as provider
from narma_video.db import database, migrate
from test_replay_coach import FACTS, RESULT


@pytest.fixture
def subscription(monkeypatch):
    monkeypatch.setenv('REPLAY_COACH_PROVIDER', 'chatgpt_subscription')
    def forbidden(*args, **kwargs):
        pytest.fail('Personal ChatGPT must never construct Gemini or settle its budget')
    monkeypatch.setattr(coach, 'GeminiReplayCoach', forbidden)
    monkeypatch.setattr(coach.ai_budget, 'settle', forbidden)
    return monkeypatch


def test_subscription_result_keeps_facts_and_correct_provenance(subscription):
    seen = []
    def analyze(job, facts, context, encoded, ids):
        seen.append(json.loads(encoded))
        return coach.validate_coaching(RESULT, ids), 'call', 'generation'
    subscription.setattr(coach, 'analyze_subscription_replay', analyze)
    before = deepcopy(FACTS)
    report = coach.enrich_report({'id': 'job'}, FACTS)
    assert report['coaching']['status'] == 'ready'
    assert report['coaching']['provider'] == 'openai-codex'
    assert report['coaching']['model'] == provider.MODEL
    assert report['coaching']['usage_kind'] == 'chatgpt_subscription'
    assert FACTS == before and report['evidence'] == FACTS['evidence']
    assert len(seen) == 1 and 'account_id' not in seen[0]['player']


@pytest.mark.parametrize('error,code,category', [
    (provider.ProviderError('CHATGPT_NOT_CONNECTED'), 'CHATGPT_NOT_CONNECTED', 'authentication'),
    (provider.ProviderError('CHATGPT_QUOTA'), 'CHATGPT_QUOTA', 'rate_limited'),
    (provider.ProviderError('CHATGPT_CALL_ALREADY_ATTEMPTED'), 'CHATGPT_CALL_ALREADY_ATTEMPTED', 'provider_unavailable'),
    (auth.AuthError('CHATGPT_AUTH_EXPIRED'), 'CHATGPT_AUTH_EXPIRED', 'authentication'),
    (RuntimeError('secret provider response must not be stored'), 'REPLAY_COACH_UNAVAILABLE', 'unknown'),
])
def test_failed_subscription_keeps_report_without_fallback(subscription, error, code, category, capsys):
    def unavailable(*args):
        raise error
    subscription.setattr(coach, 'analyze_subscription_replay', unavailable)
    report = coach.enrich_report({'id': 'job'}, FACTS)
    assert report['metrics'] == FACTS['metrics'] and report['evidence'] == FACTS['evidence']
    assert report['coaching']['status'] == 'unavailable'
    assert report['coaching']['failure_code'] == code
    assert report['coaching']['failure_category'] == category
    assert 'secret provider' not in json.dumps(report) + capsys.readouterr().out


@pytest.mark.parametrize('invalid', ['foreign_evidence', 'disconnect', 'unknown'])
def test_output_is_validated_and_unknown_calls_never_resend(subscription, invalid):
    row = {'id': 'call', 'state': 'unknown' if invalid == 'unknown' else 'reserved'}
    subscription.setattr(coach, 'reserve_subscription_replay', lambda *args: row)
    response = deepcopy(RESULT)
    if invalid == 'foreign_evidence':
        response['points'][0]['evidence_ids'] = ['someone-else']
    calls = []
    def perform(*args):
        calls.append(args)
        return {'text': json.dumps(response), 'connection_generation': 'generation'}
    subscription.setattr(provider, 'perform_reserved', perform)
    subscription.setattr(auth, 'credentials_current', lambda *args: invalid != 'disconnect')
    report = coach.enrich_report({'id': 'job', 'owner_id': 'owner'}, FACTS)
    assert report['coaching']['status'] == 'unavailable'
    assert len(calls) == (0 if invalid == 'unknown' else 1)
    assert report['coaching']['failure_code'] == {
        'foreign_evidence': 'REPLAY_COACH_EVIDENCE_MISMATCH',
        'disconnect': 'CHATGPT_CONNECTION_CHANGED',
        'unknown': 'CHATGPT_CALL_ALREADY_ATTEMPTED'}[invalid]


def test_exact_succeeded_output_can_be_reused_without_new_generation(subscription):
    subscription.setattr(coach, 'reserve_subscription_replay', lambda *args: {
        'id': 'call', 'state': 'succeeded', 'output_text': json.dumps(RESULT),
        'connection_generation': 'generation'})
    subscription.setattr(provider, 'perform_reserved', lambda *args: pytest.fail('Must reuse the settled response'))
    subscription.setattr(auth, 'credentials_current', lambda *args: True)
    report = coach.enrich_report({'id': 'job', 'owner_id': 'owner'}, FACTS)
    assert report['coaching']['status'] == 'ready'


@pytest.fixture
def owned_job(subscription):
    url = os.environ.get('TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set isolated TEST_DATABASE_URL')
    subscription.setenv('DATABASE_URL', url)
    subscription.setenv('NARMA_CHATGPT_ENCRYPTION_KEY', Fernet.generate_key().decode())
    subscription.delenv('NARMA_CHATGPT_OWNER_ID', raising=False)
    migrate()
    owner, job_id, generation, lease = 'synthetic_chatgpt_replay', uuid4(), uuid4(), uuid4()
    with database() as connection:
        connection.execute('TRUNCATE portal_accounts CASCADE')
        connection.execute('TRUNCATE chatgpt_calls')
        connection.execute("INSERT INTO portal_accounts(owner_id,email,password_hash) VALUES (%s,'coach@example.test','unused')", (owner,))
        connection.execute('''INSERT INTO portal_dota_profiles(owner_id,account_id,nickname,match_id,hero_name,side,source_sha256)
            VALUES (%s,123,'Player','8984479726','npc_dota_hero_viper','radiant',%s)''', (owner, 'a' * 64))
        job = connection.execute('''INSERT INTO replay_jobs(id,owner_id,filename,size_bytes,requested_nickname,nickname,
            match_id,account_id,source_sha256,state,lease_token,lease_expires_at)
            VALUES (%s,%s,'synthetic.dem',100,'Player','Player','8984479726',123,%s,'processing',%s,now()+interval '5 minutes')
            RETURNING *''', (job_id, owner, 'a' * 64, lease)).fetchone()
        connection.execute('''INSERT INTO chatgpt_connections(owner_id,generation,state,secret_ciphertext,connected_at)
            VALUES (%s,%s,'connected',%s,now())''', (owner, generation, 'synthetic-encrypted-placeholder-do-not-use'))
    facts = {**deepcopy(FACTS), 'match_id': job['match_id'],
             'player': {**FACTS['player'], 'hero': 'npc_dota_hero_viper'},
             'coverage': {'source_sha256': job['source_sha256'], 'complete': True}}
    yield job, facts, generation
    with database() as connection:
        connection.execute('TRUNCATE portal_accounts CASCADE')
        connection.execute('TRUNCATE chatgpt_calls')


def test_owned_reservation_pins_source_and_lease_and_does_not_touch_gemini(owned_job):
    job, facts, generation = owned_job
    context = coach.resolve_learning_context(job, facts)
    encoded, _ = coach.prepare_evidence(facts)
    with database() as connection:
        before = connection.execute('SELECT count(*) AS count FROM video_provider_calls').fetchone()['count']
    row = coach.reserve_subscription_replay(job, facts, context, coach.SYSTEM, encoded)
    assert row['state'] == 'reserved' and row['model'] == provider.MODEL
    assert row['connection_generation'] == generation
    assert row['lease_token'] == job['lease_token'] and row['source_sha256'] == job['source_sha256']
    assert row['api_cost_microusd'] is None
    again = coach.reserve_subscription_replay(job, facts, context, coach.SYSTEM, encoded)
    assert again['id'] == row['id']
    with database() as connection:
        assert connection.execute('SELECT count(*) AS count FROM video_provider_calls').fetchone()['count'] == before


@pytest.mark.parametrize('change', ['source', 'account', 'incomplete', 'lease', 'role'])
def test_unbound_or_changed_facts_never_reserve(owned_job, change):
    job, facts, _ = owned_job
    context = coach.resolve_learning_context(job, facts)
    if change == 'source': facts['coverage']['source_sha256'] = 'b' * 64
    elif change == 'account': facts['player']['account_id'] = 999
    elif change == 'incomplete': facts['coverage']['complete'] = False
    elif change == 'lease': job['lease_token'] = uuid4()
    elif change == 'role': context['position'] = 3
    encoded, _ = coach.prepare_evidence(facts)
    with pytest.raises(ValueError, match='REPLAY_COACH_(INPUT_INVALID|LEASE_LOST)'):
        coach.reserve_subscription_replay(job, facts, context, coach.SYSTEM, encoded)
    with database() as connection:
        assert connection.execute('SELECT count(*) AS count FROM chatgpt_calls').fetchone()['count'] == 0
