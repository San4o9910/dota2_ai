"""Saved AI status must not confuse parser completion, billing and fresh calls."""
from copy import deepcopy
import json

import pytest

from narma_video.replay_coaching_status import owned_call, project


ROW = {'id': 'job', 'owner_id': 'owner', 'account_id': 123,
       'match_id': '8984479726', 'source_sha256': 'a' * 64, 'state': 'ready'}
REPORT = {'player': {'account_id': 123}, 'match_id': '8984479726',
          'coverage': {'source_sha256': 'a' * 64, 'complete': True},
          'coaching': {'status': 'ready', 'usage_kind': 'openai_api', 'call_id': 'call'}}
CALL = {'id': 'call', 'owner_id': 'owner', 'job_id': 'job', 'source_sha256': 'a' * 64,
        'state': 'succeeded', 'billing_status': 'settled', 'charged_microusd': 541,
        'usage': {'input_tokens': 100, 'output_tokens': 10, 'total_tokens': 110,
                  'input_tokens_details': {'cached_tokens': 10}}, 'error_code': None}


def test_completed_parser_without_ai_is_unavailable_and_budget_reason_is_explicit():
    report = {**REPORT, 'coaching': {'status': 'unavailable', 'failure_code': 'OPENAI_BUDGET_EXCEEDED'}}
    status = project(ROW, report)
    assert status['state'] == 'unavailable' and status['provider'] == 'openai_api'
    assert status['reason_code'] == 'OPENAI_BUDGET_EXCEEDED'
    assert status['billing_state'] == 'none' and status['usage'] is None
    assert status['charged_microusd'] is None and not status['verified_openai']


def test_reopening_verified_result_keeps_same_historical_usage_without_mutation():
    before = deepcopy((ROW, REPORT, CALL))
    first = project(ROW, REPORT, CALL)
    assert first == project(ROW, REPORT, CALL)
    assert first['state'] == 'ready' and first['verified_openai']
    assert first['usage'] == {'input_tokens': 100, 'output_tokens': 10, 'cached_input_tokens': 10}
    assert first['charged_microusd'] == 541
    assert (ROW, REPORT, CALL) == before


def test_paid_invalid_output_does_not_appear_as_success_or_as_free():
    report = {**REPORT, 'coaching': {'status': 'unavailable', 'failure_code': 'REPLAY_COACH_NUMERIC_CLAIM'}}
    status = project(ROW, report, CALL)
    assert status['state'] == 'unavailable' and status['reason_code'] == 'REPLAY_COACH_NUMERIC_CLAIM'
    assert status['usage']['output_tokens'] == 10 and status['charged_microusd'] == 541
    assert status['billing_state'] == 'settled' and not status['verified_openai']


@pytest.mark.parametrize('field,value', [('owner_id', 'foreign'), ('job_id', 'foreign'),
                                       ('source_sha256', 'b' * 64), ('id', 'different-call')])
def test_unrelated_ledger_cannot_verify_report_or_leak_usage(field, value):
    call = {**CALL, field: value}
    status = project(ROW, REPORT, call, archived=True)
    assert not status['verified_openai']
    assert status['usage'] is None and status['charged_microusd'] is None


@pytest.mark.parametrize('change', ['account', 'source', 'match', 'incomplete'])
def test_report_identity_mismatch_suppresses_billing_and_generation_claim(change):
    report = deepcopy(REPORT)
    if change == 'account': report['player']['account_id'] = 456
    elif change == 'source': report['coverage']['source_sha256'] = 'b' * 64
    elif change == 'match': report['match_id'] = '9999999999'
    else: report['coverage']['complete'] = False
    status = project(ROW, report, CALL)
    assert status['state'] == 'unknown' and not status['verified_openai']
    assert status['usage'] is None and status['charged_microusd'] is None


def test_successful_ledger_alone_does_not_make_missing_comment_ready():
    report = {**REPORT, 'coaching': {}}
    assert project(ROW, report, CALL)['state'] == 'unavailable'
    assert project({**ROW, 'state': 'queued'}, None, CALL)['state'] == 'pending'


def test_source_deleted_or_unverified_call_does_not_confirm_saved_ai_response():
    for call in (None, {**CALL, 'state': 'failed', 'error_code': 'OPENAI_SOURCE_DELETED'},
                 {**CALL, 'id': 'not-the-cited-call'}):
        status = project(ROW, REPORT, call)
        assert status['state'] == 'unknown' and not status['verified_openai']
        assert status['reason_code'] == 'OPENAI_PROVENANCE_UNVERIFIED'


def test_role_change_remains_unavailable_for_current_context_despite_paid_call():
    report = {**REPORT, 'coaching': {**REPORT['coaching'], 'status': 'context_changed'}}
    status = project(ROW, report, CALL)
    assert status['state'] == 'context_changed' and not status['verified_openai']
    assert status['reason_code'] == 'REPLAY_COACH_CONTEXT_CHANGED'
    assert status['charged_microusd'] == 541


def test_archive_has_its_own_status_and_requires_explicit_historical_call_binding():
    status = project(ROW, REPORT, CALL, archived=True)
    assert status['state'] == 'saved' and status['verified_openai']
    assert status['usage']['input_tokens'] == 100
    carried = {**REPORT, 'coaching': {'status': 'ready', 'origin': 'previous_report',
                'refresh_failure_code': 'OPENAI_CALL_ALREADY_ATTEMPTED'}}
    status = project(ROW, carried, CALL)
    assert status['state'] == 'saved' and not status['verified_openai']
    assert status['reason_code'] == 'OPENAI_CALL_ALREADY_ATTEMPTED'
    assert status['usage'] is None and status['charged_microusd'] is None


@pytest.mark.parametrize('billing,state', [('reserved', 'held'), ('unknown', 'unknown'), ('breach', 'breach')])
def test_unresolved_and_breached_calls_are_not_presented_as_free_or_successful(billing, state):
    report = {**REPORT, 'coaching': {'status': 'unavailable', 'failure_code': 'OPENAI_TIMEOUT'}}
    call = {**CALL, 'state': 'unknown', 'billing_status': billing,
            'usage': {'usage_missing': True}, 'charged_microusd': None}
    status = project(ROW, report, call)
    assert status['billing_state'] == state and status['state'] == 'unavailable'
    assert status['usage'] is None and status['charged_microusd'] is None


@pytest.mark.parametrize('usage', [None, {}, {'input_tokens': True, 'output_tokens': 1, 'total_tokens': 2},
    {'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 99},
    {'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2, 'input_tokens_details': {'cached_tokens': 2}}])
def test_malformed_usage_never_becomes_a_token_count_or_verified_result(usage):
    status = project(ROW, REPORT, {**CALL, 'usage': usage})
    assert status['usage'] is None and not status['verified_openai']


def test_status_does_not_export_provider_error_body_or_arbitrary_metadata():
    report = {**REPORT, 'coaching': {'status': 'unavailable', 'failure_code': 'secret provider body'}}
    call = {**CALL, 'error_code': 'secret provider body', 'output_text': 'private advice',
            'usage': {**CALL['usage'], 'extra': 'secret provider metadata'}}
    status = project(ROW, report, call)
    assert status['reason_code'] == 'REPLAY_COACH_UNAVAILABLE'
    assert 'secret' not in json.dumps(status) and 'private' not in json.dumps(status)


def test_lookup_is_owner_job_and_source_scoped_and_read_only():
    class Connection:
        def execute(self, query, parameters):
            assert query.lstrip().startswith('SELECT ')
            assert 'owner_id=%s AND job_id=%s AND source_sha256=%s' in query
            assert parameters == ('owner', 'job', 'a' * 64)
            assert 'budget' not in query
            return self
        def fetchone(self):
            return CALL
    assert owned_call(Connection(), ROW) == CALL
