"""Synthetic coach/ledger tests. No network requests or API credentials required."""
from contextlib import contextmanager
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from narma_video import replay_coach as coach


FACTS = {
    'player': {'account_id': 123, 'nickname': 'untrusted nickname'},
    'metrics': {'kills': 16, 'deaths': 16, 'assists': 20},
    'evidence': [
        {'id': 'death.1', 'type': 'death', 'time': 701.5, 'details': {'killer': 'opponent'}},
        {'id': 'buyback.1', 'type': 'buyback', 'time': 705.0, 'details': {'spent': 1700}},
    ],
}
RESULT = {
    'summary': 'Разбери возвращение в игру после смерти.',
    'points': [{
        'title': 'Решение о выкупе',
        'observation': 'После смерти последовал выкуп.',
        'advice': 'Проверь в реплее, какую задачу команда могла выполнить после возвращения.',
        'evidence_ids': ['death.1', 'buyback.1'],
    }],
    'next_game': [{
        'title': 'Цель возвращения в игру',
        'action': 'Перед выкупом назови цель и проверь, кто из союзников может поддержать возвращение.',
        'measure': 'После матча проверь по эпизоду, удалось ли выполнить выбранную цель.',
        'evidence_ids': ['buyback.1'],
    }],
}


def test_evidence_contract_rejects_missing_ambiguous_or_oversized_data():
    encoded, ids = coach.prepare_evidence({**FACTS, 'private_token': 'never send this'})
    assert 'private_token' not in encoded
    assert ids == {'death.1', 'buyback.1'}
    for bad in [{**FACTS, 'evidence': []}, {**FACTS, 'evidence': FACTS['evidence'] * 2},
                {**FACTS, 'evidence': [{'id': 'invalid id'}]}, {**FACTS, 'metrics': None}]:
        with pytest.raises(ValueError, match='INPUT_INVALID'):
            coach.prepare_evidence(bad)
    with pytest.raises(ValueError, match='INPUT_TOO_LARGE'):
        coach.prepare_evidence({**FACTS, 'metrics': {'payload': 'a' * 512001}})


@pytest.mark.parametrize('change,code', [
    ({'evidence_ids': ['unknown.9']}, 'EVIDENCE_MISMATCH'),
    ({'evidence_ids': []}, 'RESPONSE_INVALID'),
    ({'evidence_ids': ['death.1', 'death.1']}, 'EVIDENCE_MISMATCH'),
    ({'observation': 'Ты потерял 900 золота.'}, 'NUMERIC_CLAIM'),
    ({'advice': 'Нажми <script>alert</script>'}, 'RESPONSE_INVALID'),
])
def test_model_cannot_invent_evidence_or_numeric_stats(change, code):
    value = deepcopy(RESULT)
    value['points'][0].update(change)
    with pytest.raises(ValueError, match=code):
        coach.validate_coaching(value, {'death.1', 'buyback.1'})


def test_numeric_match_summary_is_also_rejected():
    with pytest.raises(ValueError, match='NUMERIC_CLAIM'):
        coach.validate_coaching({**RESULT, 'summary': 'Потеряно ２０ минут.'}, {'death.1', 'buyback.1'})


@pytest.mark.parametrize('change,code', [
    ({'evidence_ids': ['unknown']}, 'EVIDENCE_MISMATCH'),
    ({'measure': 'Набери 100 добиваний.'}, 'NUMERIC_CLAIM'),
    ({'action': 'Открой https://example.invalid'}, 'RESPONSE_INVALID'),
    ({'measure': ''}, 'RESPONSE_INVALID'),
])
def test_next_game_tasks_require_safe_measurable_evidence(change, code):
    value = deepcopy(RESULT)
    value['next_game'][0].update(change)
    with pytest.raises(ValueError, match=code):
        coach.validate_coaching(value, {'death.1', 'buyback.1'})


def test_next_game_plan_is_required_and_coach_uses_only_selected_analytics():
    with pytest.raises(ValueError, match='RESPONSE_INVALID'):
        coach.validate_coaching({**RESULT, 'next_game': []}, {'death.1', 'buyback.1'})
    encoded, _ = coach.prepare_evidence({**FACTS, 'insights': {
        'items': [{'item': 'item_blink', 'realization': {'casts': 1}}],
        'training_plan': [{'action': 'never send this'}],
        'private_key': 'never send this',
    }})
    payload = json.loads(encoded)
    assert payload['insights']['items'][0]['item'] == 'item_blink'
    assert 'private_key' not in encoded and 'training_plan' not in encoded
    assert 'nickname' not in payload['player'] and 'account_id' not in payload['player']


def test_coach_receives_selected_hero_and_recorded_spells_without_private_fields():
    original = {**deepcopy(FACTS),
        'player': {**FACTS['player'], 'hero': 'npc_dota_hero_necrolyte', 'team': 'radiant'},
        'ability_usage': [{'name': 'necrolyte_death_pulse', 'casts': 12,
                           'first_time': -10, 'last_time': 500, 'private_note': 'never-send'}],
        'item_usage': [{'name': 'item_hood_of_defiance', 'casts': 4, 'first_time': 200,
                       'last_time': 700, 'owner_id': 'never-send'}],
        'other_player': {'hero': 'npc_dota_hero_lina'},
    }
    snapshot = deepcopy(original)
    encoded, ids = coach.prepare_evidence(original)
    payload = json.loads(encoded)
    assert payload['player'] == {'hero': 'npc_dota_hero_necrolyte', 'team': 'radiant'}
    assert payload['ability_usage'] == [{'name': 'necrolyte_death_pulse', 'casts': 12,
                                         'first_time': -10, 'last_time': 500}]
    assert payload['item_usage'][0]['name'] == 'item_hood_of_defiance'
    assert payload['hero_context']['hero'] == payload['player']['hero']
    assert payload['hero_context']['position'] is None
    assert 'never-send' not in encoded and 'npc_dota_hero_lina' not in encoded
    assert 'training_plan' not in payload['hero_context'] and 'focus' not in payload['hero_context']
    assert original == snapshot and ids == {'death.1', 'buyback.1'}


def test_usage_projection_keeps_unknown_and_invalid_telemetry_out_of_prompt():
    rows = [None, {'name': '<injected>', 'casts': 2}, {'name': 'valid', 'casts': True},
            {'name': 'valid', 'casts': -1}, {'name': 'valid', 'casts': 3,
             'first_time': float('inf'), 'last_time': float('nan')},
            {'name': 'valid', 'casts': 99}, {'name': 'second', 'casts': 1,
             'first_time': -2, 'last_time': 20}]
    assert coach.usage_facts(rows) == [{'name': 'valid', 'casts': 3},
        {'name': 'second', 'casts': 1, 'first_time': -2, 'last_time': 20}]
    assert coach.usage_facts({'name': 'not-a-list'}) == []


def test_manual_position_and_catalog_are_separate_from_match_evidence():
    facts = {**deepcopy(FACTS), 'player': {**FACTS['player'], 'hero': 'npc_dota_hero_viper'}}
    encoded, ids = coach.prepare_evidence(facts, position=3)
    assert json.loads(encoded)['hero_context']['position'] == 3
    for invalid in (True, '3', 0, 6):
        encoded, _ = coach.prepare_evidence(facts, position=invalid)
        assert json.loads(encoded)['hero_context']['position'] is None
    encoded, _ = coach.prepare_evidence({**facts, 'learning_context': {'note': 'never send'}},
                                        position=3, exercise_id='unrecognized')
    assert 'learning_context' not in json.loads(encoded)
    assert ids == {'death.1', 'buyback.1'}


def test_learning_context_requires_bound_identity_and_live_lease(monkeypatch):
    job = {'id': 'job', 'owner_id': 'owner', 'account_id': 123, 'match_id': '8984479726',
           'source_sha256': 'a' * 64, 'lease_token': 'lease'}
    facts = {**deepcopy(FACTS), 'match_id': job['match_id'],
             'player': {**FACTS['player'], 'hero': 'npc_dota_hero_viper'},
             'coverage': {'source_sha256': 'a' * 64}}
    queries = []
    class Connection:
        def execute(self, sql, params=None):
            queries.append((sql, params))
            return SimpleNamespace(fetchone=lambda: {'position': 3} if 'FROM replay_jobs' in sql else None)
    @contextmanager
    def db():
        yield Connection()
    monkeypatch.setattr(coach, 'database', db)
    scopes = []
    def active(connection, owner, account, hero, position):
        scopes.append((owner, account, hero, position))
        return 'r1'
    monkeypatch.setattr(coach, 'resolve_active_exercise', active)
    result = coach.resolve_learning_context(job, facts)
    assert result['position'] == 3 and result['position_source'] == 'player'
    assert result['hero'] == 'npc_dota_hero_viper'
    assert 'REPEATABLE READ, READ ONLY' in queries[0][0]
    assert 'r.owner_id=%s' in queries[1][0] and 'p.account_id=r.account_id' in queries[1][0]
    assert 'lease_expires_at>now()' in queries[1][0]
    assert scopes == [('owner', 123, 'npc_dota_hero_viper', 3)]
    assert result['exercise_id'] == 'r1'
    with pytest.raises(ValueError, match='INPUT_INVALID'):
        coach.resolve_learning_context(job, {**facts, 'match_id': '8984479727'})
    assert len(queries) == 2


def test_changed_role_cannot_carry_old_coaching_forward():
    previous, current = prior_report(), refreshed_facts()
    previous['coaching']['context'] = {'position': 3, 'exercise_id': None}
    current['coaching'] = {'status': 'unavailable', 'context': {'position': 2, 'exercise_id': None}}
    assert not coach.carry_forward_coaching(previous, current)
    assert current['coaching']['status'] == 'unavailable'


def response(value=RESULT, **changes):
    body = {
        'usageMetadata': {'promptTokenCount': 100, 'candidatesTokenCount': 20, 'totalTokenCount': 120},
        'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': json.dumps(value)}]}}],
        **changes,
    }
    return SimpleNamespace(sdk_http_response=SimpleNamespace(body=json.dumps(body)))


def synthetic_adapter(reply):
    requests = []
    def generate_content(**request):
        requests.append(request)
        return reply
    model = object.__new__(coach.GeminiReplayCoach)
    model.model = coach.ai_budget.MODEL
    model.client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    return model, requests


def test_one_text_only_request_standard_tier_and_full_report():
    model, requests = synthetic_adapter(response())
    encoded, ids = coach.prepare_evidence(FACTS)
    assert model.analyze(encoded, ids).model_dump() == RESULT
    assert len(requests) == 1
    assert requests[0]['contents'][0].text == encoded
    assert len(requests[0]['contents']) == 1
    config = requests[0]['config']
    assert config.service_tier == 'standard' and config.candidate_count == 1
    assert config.automatic_function_calling.disable and not config.tools
    assert model.last_usage['total_tokens'] == 120


def test_unknown_billable_fields_are_retained_for_frozen_settlement():
    model, requests = synthetic_adapter(response(usageMetadata={
        'promptTokenCount': 100, 'candidatesTokenCount': 20, 'totalTokenCount': 120, 'newBillableThing': 7,
    }))
    with pytest.raises(ValueError, match='USAGE_UNSUPPORTED'):
        model.analyze(*coach.prepare_evidence(FACTS))
    assert len(requests) == 1
    assert model.last_usage['unrecognized_generate_content_usage']['newBillableThing'] == 7


def test_invalid_model_result_still_settles_but_preserves_factual_report(monkeypatch):
    model, requests = synthetic_adapter(response({**RESULT, 'summary': 'У тебя 100 убийств.'}))
    settlements = []
    monkeypatch.setattr(coach, 'reserve_replay', lambda job, name: 91)
    monkeypatch.setattr(coach.ai_budget, 'settle', lambda call_id, usage: settlements.append((call_id, usage)))
    original = deepcopy(FACTS)
    report = coach.enrich_report({'id': 'test-job'}, FACTS, coach=model)
    assert len(requests) == len(settlements) == 1
    assert settlements[0][1]['total_tokens'] == 120
    assert FACTS == original
    assert report['metrics'] == original['metrics'] and report['evidence'] == original['evidence']
    assert report['coaching']['status'] == 'unavailable'
    assert report['coaching']['failure_code'] == 'REPLAY_COACH_NUMERIC_CLAIM'


def test_budget_denial_never_dispatches_or_settles(monkeypatch):
    model, requests = synthetic_adapter(response())
    def reject(*args):
        raise ValueError('VIDEO_GLOBAL_BUDGET_EXCEEDED')
    monkeypatch.setattr(coach, 'reserve_replay', reject)
    monkeypatch.setattr(coach.ai_budget, 'settle', lambda *args: pytest.fail('No reserved call exists'))
    report = coach.enrich_report({'id': 'test-job'}, FACTS, coach=model)
    assert not requests and report['coaching']['failure_code'] == 'VIDEO_GLOBAL_BUDGET_EXCEEDED'


@pytest.mark.parametrize('active,calls,expected', [
    (None, {'job_calls': 0, 'daily_calls': 0}, 'LEASE_LOST'),
    ({'id': 'job'}, {'job_calls': 2, 'daily_calls': 2}, 'REQUEST_BUDGET_EXCEEDED'),
    ({'id': 'job'}, {'job_calls': 0, 'daily_calls': 250}, 'REQUEST_BUDGET_EXCEEDED'),
])
def test_replay_lease_and_lifetime_shared_daily_caps(monkeypatch, active, calls, expected):
    queries = []
    class Connection:
        def execute(self, sql, params):
            queries.append((sql, params))
            return SimpleNamespace(fetchone=lambda: active if 'FROM replay_jobs' in sql else calls)
    @contextmanager
    def db():
        yield Connection()
    monkeypatch.setattr(coach, 'database', db)
    monkeypatch.setattr(coach.ai_budget, 'reserve', lambda *args, **kwargs: pytest.fail('Blocked before reservation'))
    with pytest.raises(ValueError, match=expected):
        coach.reserve_replay({'id': 'job', 'owner_id': 'owner', 'lease_token': 'lease'}, coach.ai_budget.MODEL)
    lease_sql = next(sql for sql, _ in queries if 'FROM replay_jobs' in sql)
    assert 'owner_id=%s' in lease_sql and 'lease_expires_at>now()' in lease_sql
    if active:
        # Daily count does not limit its source to replay calls.
        count_sql = next(sql for sql, _ in queries if 'FROM video_provider_calls' in sql)
        assert "WHERE owner_id=%s" in count_sql and 'call_kind=' not in count_sql


def prior_report():
    return {**deepcopy(FACTS), 'match_id': '8984479726',
            'coverage': {'complete': True, 'source_sha256': 'a' * 64},
            'coaching': {'status': 'ready', 'model': coach.ai_budget.MODEL, **deepcopy(RESULT)}}


def refreshed_facts():
    report = prior_report()
    report.pop('coaching')
    for event in report['evidence']:
        event['id'] = 'new-' + event['id']
    return report


def test_optional_failure_carries_forward_all_valid_evidence_without_retry(monkeypatch, capsys):
    previous, facts = prior_report(), refreshed_facts()
    model, requests = synthetic_adapter(response({**RESULT, 'summary': 'Unsupported 100'}))
    settlements = []
    monkeypatch.setattr(coach, 'reserve_replay', lambda *args: 91)
    monkeypatch.setattr(coach.ai_budget, 'settle', lambda *args: settlements.append(args))
    report = coach.enrich_report({'id': 'test', 'previous_report': previous, 'previous_report_id': 12}, facts, coach=model)
    assert len(requests) == len(settlements) == 1
    assert report['coaching']['status'] == 'ready'
    assert report['coaching']['origin'] == 'previous_report'
    assert report['coaching']['source_report_id'] == 12
    assert report['coaching']['refresh_failure_code'] == 'REPLAY_COACH_EVIDENCE_MISMATCH'
    assert report['coaching']['points'][0]['evidence_ids'] == ['new-death.1', 'new-buyback.1']
    assert report['coaching']['next_game'][0]['evidence_ids'] == ['new-buyback.1']
    assert previous == prior_report() and facts == refreshed_facts()
    assert 'previous_coaching_carried_forward": true' in capsys.readouterr().out


@pytest.mark.parametrize('change', ['account', 'match', 'source', 'incomplete', 'missing_source',
                                     'missing_reference', 'ambiguous_new', 'ambiguous_old', 'changed_fact',
                                     'changed_metrics', 'invalid_old_coaching'])
def test_prior_coaching_with_foreign_or_unverifiable_context_stays_archived(monkeypatch, change):
    previous, facts = prior_report(), refreshed_facts()
    if change == 'account': facts['player']['account_id'] += 1
    elif change == 'match': facts['match_id'] = '8984479727'
    elif change == 'source': facts['coverage']['source_sha256'] = 'b' * 64
    elif change == 'missing_source': previous['coverage'].pop('source_sha256')
    elif change == 'incomplete': facts['coverage']['complete'] = False
    elif change == 'missing_reference': facts['evidence'].pop()
    elif change == 'ambiguous_new': facts['evidence'].append({**facts['evidence'][0], 'id': 'duplicate-new'})
    elif change == 'ambiguous_old': previous['evidence'].append({**previous['evidence'][0], 'id': 'duplicate-old'})
    elif change == 'changed_fact': facts['evidence'][0]['details']['killer'] = 'different-opponent'
    elif change == 'changed_metrics': facts['metrics']['kills'] += 1
    elif change == 'invalid_old_coaching': previous['coaching']['points'][0]['evidence_ids'] = ['unknown']
    snapshot = deepcopy(previous)
    model, requests = synthetic_adapter(response())
    def deny(*args): raise ValueError('REPLAY_COACH_REQUEST_BUDGET_EXCEEDED')
    monkeypatch.setattr(coach, 'reserve_replay', deny)
    monkeypatch.setattr(coach.ai_budget, 'settle', lambda *args: pytest.fail('No new reservation'))
    report = coach.enrich_report({'id': 'test', 'previous_report': previous}, facts, coach=model)
    assert not requests
    assert report['coaching']['status'] == 'unavailable'
    assert previous == snapshot


@pytest.mark.parametrize('error,category', [
    (TimeoutError('secret timeout URL and credentials'), 'timeout'),
    (coach.httpx.ConnectError('secret transport URL and credentials'), 'transport'),
    (coach.errors.ClientError(429, {'error': {'message': 'secret prompt'}}), 'rate_limited'),
    (coach.errors.ServerError(503, {'error': {'message': 'secret prompt'}}), 'provider_unavailable'),
    (RuntimeError('secret credentials'), 'unknown'),
])
def test_failure_categories_never_expose_provider_text(monkeypatch, capsys, error, category):
    model, requests = synthetic_adapter(response())
    def fail(*args): raise error
    model.analyze = fail
    settlements = []
    monkeypatch.setattr(coach, 'reserve_replay', lambda *args: 91)
    monkeypatch.setattr(coach.ai_budget, 'settle', lambda *args: settlements.append(args))
    report = coach.enrich_report({'id': 'test'}, FACTS, coach=model)
    assert settlements == [(91, None)]
    assert report['coaching']['failure_category'] == category
    assert 'secret' not in json.dumps(report) + capsys.readouterr().out
