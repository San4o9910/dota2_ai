"""Owner-scoped explanation of saved coaching and recorded OpenAI usage.

This projection never calls a provider, requeues a report or changes accounting.
An available parser report alone does not establish a successful AI response.
"""
from __future__ import annotations

import re


_REASONS = frozenset({
    'REPLAY_COACH_INPUT_INVALID', 'REPLAY_COACH_INPUT_TOO_LARGE',
    'REPLAY_COACH_RESPONSE_INVALID', 'REPLAY_COACH_EVIDENCE_MISMATCH',
    'REPLAY_COACH_NUMERIC_CLAIM', 'REPLAY_COACH_LEASE_LOST',
    'REPLAY_COACH_REQUEST_BUDGET_EXCEEDED', 'REPLAY_COACH_NOT_CONFIGURED',
    'REPLAY_COACH_UNAVAILABLE', 'REPLAY_COACH_CONTEXT_CHANGED',
    'OPENAI_NOT_CONFIGURED', 'OPENAI_AUTHENTICATION_FAILED',
    'OPENAI_RATE_LIMITED', 'OPENAI_DAILY_LIMIT', 'OPENAI_TIMEOUT',
    'OPENAI_TRANSPORT_ERROR', 'OPENAI_PROVIDER_UNAVAILABLE', 'OPENAI_PROVIDER_REJECTED',
    'OPENAI_REQUEST_TOO_LARGE', 'OPENAI_REQUEST_INVALID', 'OPENAI_MODEL_UNSUPPORTED',
    'OPENAI_RESPONSE_INVALID', 'OPENAI_RESPONSE_INCOMPLETE', 'OPENAI_RESPONSE_REFUSED',
    'OPENAI_OUTPUT_TOO_LARGE', 'OPENAI_TOOLS_FORBIDDEN', 'OPENAI_USAGE_MISSING',
    'OPENAI_CALL_ALREADY_ATTEMPTED', 'OPENAI_CALL_EXPIRED', 'OPENAI_CALL_CONFLICT',
    'OPENAI_CALL_NOT_FOUND', 'OPENAI_LEASE_LOST', 'OPENAI_SOURCE_DELETED',
    'OPENAI_BUDGET_DISABLED', 'OPENAI_BUDGET_EXCEEDED', 'OPENAI_BUDGET_INVALID',
    'OPENAI_BUDGET_PRICE_POLICY_EXPIRED', 'OPENAI_BUDGET_BOUND_INVALID',
    'OPENAI_BUDGET_USAGE_INVALID', 'OPENAI_BUDGET_ACCOUNTING_FAILED',
    'OPENAI_BUDGET_RECONCILIATION_REQUIRED', 'OPENAI_PROVENANCE_UNVERIFIED',
    'CHATGPT_NOT_CONNECTED', 'CHATGPT_AUTH_EXPIRED', 'CHATGPT_CONNECTION_CHANGED',
    'CHATGPT_NOT_CONFIGURED', 'CHATGPT_AUTH_UNAVAILABLE', 'CHATGPT_QUOTA',
    'CHATGPT_DAILY_LIMIT', 'CHATGPT_TIMEOUT', 'CHATGPT_TRANSPORT_ERROR',
    'CHATGPT_LEASE_LOST', 'CHATGPT_CALL_ALREADY_ATTEMPTED',
    'VIDEO_GLOBAL_BUDGET_DISABLED', 'VIDEO_GLOBAL_BUDGET_EXCEEDED',
    'VIDEO_GLOBAL_BUDGET_INVALID', 'VIDEO_BUDGET_PRICE_POLICY_EXPIRED',
    'VIDEO_REQUEST_BUDGET_EXCEEDED', 'VIDEO_BUDGET_RECONCILIATION_REQUIRED',
    'VIDEO_BUDGET_ACCOUNTING_FAILED', 'GEMINI_USAGE_UNSUPPORTED',
})


def _reason(value):
    return value if isinstance(value, str) and value in _REASONS else 'REPLAY_COACH_UNAVAILABLE'


def _tokens(usage):
    """Expose only bounded numerical usage, never raw response metadata."""
    if not isinstance(usage, dict):
        return None
    values = [usage.get(key) for key in ('input_tokens', 'output_tokens', 'total_tokens')]
    if (any(type(value) is not int or not 0 <= value <= 10_000_000 for value in values)
            or values[0] + values[1] != values[2]):
        return None
    details = usage.get('input_tokens_details')
    cached = details.get('cached_tokens', 0) if isinstance(details, dict) else 0
    if type(cached) is not int or not 0 <= cached <= values[0]:
        return None
    return {'input_tokens': values[0], 'output_tokens': values[1], 'cached_input_tokens': cached}


def project(row, report, call=None, *, archived=False):
    """Project one owned report, after current-role/source checks by the caller.

    The call must belong to this exact job, owner and immutable source. A paid
    failed response can have valid usage while its coaching remains unavailable.
    Existing usage is historical: opening this view never creates another call.
    """
    digest = row.get('source_sha256')
    if (not isinstance(call, dict) or not isinstance(digest, str)
            or not re.fullmatch(r'[0-9a-f]{64}', digest)
            or call.get('owner_id') != row.get('owner_id')
            or str(call.get('job_id')) != str(row.get('id'))
            or call.get('source_sha256') != digest):
        call = None
    coaching = report.get('coaching') if isinstance(report, dict) else None
    coaching = coaching if isinstance(coaching, dict) else {}
    original = coaching.get('status')
    code = coaching.get('refresh_failure_code') or coaching.get('failure_code')
    provider = coaching.get('usage_kind')
    if provider not in ('openai_api', 'chatgpt_subscription', 'gemini'):
        model = coaching.get('model')
        provider = 'gemini' if isinstance(model, str) and model.startswith('gemini-') else None
    saved = archived or coaching.get('origin') == 'previous_report'
    cited_call = bool(call and str(coaching.get('call_id')) == str(call.get('id')))
    if (call and (original != 'ready' or cited_call)
            or not saved and isinstance(code, str) and code.startswith('OPENAI_')):
        provider = 'openai_api'
    elif isinstance(code, str) and code.startswith('CHATGPT_'):
        provider = 'chatgpt_subscription'
    result = {'state': 'unknown', 'provider': provider, 'reason_code': None,
              'usage': None, 'billing_state': 'none', 'charged_microusd': None,
              'verified_openai': False}
    # An archive/carry-forward may describe different provider text. Only its
    # explicit call identity can attach historical usage to that displayed text.
    if call and (not saved or cited_call):
        billing = call.get('billing_status')
        result['billing_state'] = {'reserved': 'held', 'settled': 'settled',
                                   'unknown': 'unknown', 'breach': 'breach'}.get(billing, 'unknown')
        if billing in ('settled', 'breach'):
            result['usage'] = _tokens(call.get('usage'))
            charged = call.get('charged_microusd')
            if type(charged) is int and charged >= 0:
                result['charged_microusd'] = charged
    if not isinstance(report, dict):
        result['state'] = 'pending' if row.get('state') in ('uploading', 'queued', 'processing') else 'unavailable'
        return result
    player, coverage = report.get('player'), report.get('coverage')
    bound_report = (isinstance(player, dict) and isinstance(coverage, dict)
                    and coverage.get('complete') is True
                    and coverage.get('source_sha256') == digest
                    and type(player.get('account_id')) is int
                    and player.get('account_id') == row.get('account_id')
                    and str(report.get('match_id')) == row.get('match_id'))
    if not bound_report:
        return {**result, 'state': 'unknown', 'reason_code': 'OPENAI_PROVENANCE_UNVERIFIED',
                'usage': None, 'charged_microusd': None, 'billing_state': 'unknown'}
    if original == 'context_changed':
        result.update(state='context_changed', reason_code='REPLAY_COACH_CONTEXT_CHANGED')
    elif original == 'ready':
        verified = bool(provider == 'openai_api' and cited_call
                        and call.get('state') == 'succeeded'
                        and call.get('billing_status') == 'settled'
                        and result['usage'] is not None
                        and result['charged_microusd'] is not None)
        result['verified_openai'] = verified
        result['state'] = 'saved' if saved else 'ready'
        if provider == 'openai_api' and not verified and not saved:
            result.update(state='unknown', reason_code='OPENAI_PROVENANCE_UNVERIFIED')
        elif code:
            result['reason_code'] = _reason(code)
    else:
        result.update(state='unavailable', reason_code=_reason(code or (call or {}).get('error_code')))
    return result


def owned_call(connection, row):
    """Fixed read-only lookup after the API has authorized the owning account."""
    return connection.execute('''SELECT id,owner_id,job_id,source_sha256,state,billing_status,
        charged_microusd,usage,error_code FROM openai_api_calls
        WHERE owner_id=%s AND job_id=%s AND source_sha256=%s''',
        (row['owner_id'], row['id'], row['source_sha256'])).fetchone()
