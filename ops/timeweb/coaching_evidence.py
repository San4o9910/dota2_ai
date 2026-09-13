"""Project a read-only server snapshot into bounded, anonymous rollout evidence.

Only aggregate counters and application codes may enter public Actions logs.
The underlying private CLI does not call a provider or reconcile money.
"""
from datetime import datetime
import json
import re


def _integer(value):
    if type(value) is not int or not 0 <= value <= 10**15:
        raise ValueError('coaching_evidence_invalid')
    return value


def _time(value):
    if not isinstance(value, str) or not re.fullmatch(
            r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z', value):
        raise ValueError('coaching_evidence_invalid')
    datetime.fromisoformat(value.replace('Z', '+00:00'))
    return value


def _rows(value, maximum):
    if not isinstance(value, list) or len(value) > maximum or any(
            not isinstance(row, dict) for row in value):
        raise ValueError('coaching_evidence_invalid')
    return value


def _enum(value, choices):
    if value not in choices:
        raise ValueError('coaching_evidence_invalid')
    return value


def public_snapshot(raw):
    if not isinstance(raw, (str, bytes)) or len(raw) > 131072:
        raise ValueError('coaching_evidence_invalid')
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get('schema_version') != 1:
        raise ValueError('coaching_evidence_invalid')
    result = {'snapshot_at': _time(data['snapshot_at']), 'read_only': True,
              'provider_calls_created': 0, 'recorded_costs_are_not_provider_invoices': True}
    window = data['window']
    result['window'] = {name: _time(window[name])
                        for name in ('since_inclusive', 'until_exclusive')}
    result['reports'] = []
    for row in _rows(data['ready_reports'], 2):
        result['reports'].append({'kind': _enum(row['kind'], ('replay', 'video')),
            **{name: _integer(row[name]) for name in ('ready_reports', 'coaching_ready_reports',
                'coaching_unavailable_reports', 'ready_with_confirmed_openai_call')}})
    result['openai_calls'] = []
    for row in _rows(data['calls_created_in_window'], 128):
        if row.get('provider') != 'openai':
            continue
        result['openai_calls'].append({
            'kind': _enum(row['kind'], ('replay', 'video', 'hermes')),
            'state': _enum(row['state'], ('reserved', 'calling', 'succeeded', 'failed', 'unknown')),
            'billing_status': _enum(row['billing_status'], ('reserved', 'settled', 'unknown', 'breach')),
            **{name: _integer(row[name]) for name in ('calls', 'calls_with_recorded_charge',
                'recorded_charge_microusd', 'retained_reservation_microusd', 'unknown_calls')}})
    result['failures'] = []
    for row in _rows(data['failures'], 30):
        code = row['code']
        if not isinstance(code, str) or not re.fullmatch(
                r'(?:OTHER|(?:REPLAY|OPENAI|VIDEO|GEMINI|HERMES)_[A-Z0-9_]{1,60})', code):
            raise ValueError('coaching_evidence_invalid')
        result['failures'].append({
            'source': _enum(row['source'], ('job', 'coaching', 'openai_call')),
            'code': code, 'occurrences': _integer(row['occurrences'])})
    result['openai_budget'] = None
    for row in _rows(data['current_cumulative_budgets'], 2):
        if row.get('provider') != 'openai':
            continue
        if result['openai_budget'] is not None:
            raise ValueError('coaching_evidence_invalid')
        flags = {}
        for name in ('enabled', 'unexpired', 'frozen'):
            if type(row[name]) is not bool:
                raise ValueError('coaching_evidence_invalid')
            flags[name] = row[name]
        result['openai_budget'] = {**flags, 'expires_at': _time(row['expires_at']),
            **{name: _integer(row[name]) for name in ('limit_microusd', 'spent_microusd',
                'reserved_microusd', 'remaining_ceiling_microusd',
                'ledger_recorded_microusd', 'ledger_held_microusd')}}
    return result


def collect_rollout_snapshot(ssh, release, command, event):
    """A telemetry failure must not roll back otherwise healthy services."""
    try:
        if release != '/opt/narma/current' and not re.fullmatch(r'/opt/narma/releases/[a-f0-9]{40}', release):
            raise ValueError('coaching_evidence_invalid')
        remote = ('cd ' + release + '/services/video && docker compose --project-name narma-video '
                  '--env-file /opt/narma/secrets/video.env exec -T api '
                  'python -m narma_video.pilot_evidence --days 7')
        result = public_snapshot(command(ssh + [remote], timeout=90))
    except Exception:
        event('coaching_usage_snapshot_unavailable', read_only=True, provider_calls_created=0)
        return
    event('coaching_usage_snapshot', **result)
