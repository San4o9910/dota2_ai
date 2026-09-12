"""Durable owner-funded OpenAI allowance; integer micro-USD, no resets.

Standard GPT-5.6 Sol text pricing verified 2026-09-12: $4/M input,
$0.40/M cache reads, $5/M cache writes and $20/M output, including reasoning.
Reservations cover cache writes; settlement rounds fractional micro-USD upward.
Missing cache-write telemetry is conservatively priced as writes, never as free.
The promotional tariff must be reviewed before this policy expires.
"""
import hashlib
import json
from datetime import datetime, timezone

from psycopg.types.json import Jsonb

from .db import database

MODEL = 'gpt-5.6-sol'
POLICY = 'gpt-5.6-sol-standard-cache-v2-2026-09-12'
PRICE_EXPIRES = '2026-11-21T00:00:00Z'
MAX_ALLOWANCE = 10_000_000
MAX_INPUT_TOKENS = 240000
MAX_OUTPUT_TOKENS = 8192


def estimate_reservation(input_token_bound, max_output_tokens):
    if (type(input_token_bound) is not int or not 1 <= input_token_bound <= MAX_INPUT_TOKENS
            or type(max_output_tokens) is not int or not 256 <= max_output_tokens <= MAX_OUTPUT_TOKENS):
        raise ValueError('OPENAI_BUDGET_BOUND_INVALID')
    # An uncached prompt may be written to the cache at 1.25x ordinary input.
    # Reserve the largest possible bucket without assuming a cache hit.
    return 5 * input_token_bound + 20 * max_output_tokens


def lock_allowance(connection, amount):
    row = connection.execute("""SELECT *,expires_at>clock_timestamp()
        AND expires_at<=%s::timestamptz AS price_valid
        FROM openai_api_budget WHERE id=1 FOR UPDATE""", (PRICE_EXPIRES,)).fetchone()
    if not row or not row['enabled']:
        raise ValueError('OPENAI_BUDGET_DISABLED')
    if row['model'] != MODEL or row['price_policy'] != POLICY or not row['price_valid']:
        raise ValueError('OPENAI_BUDGET_PRICE_POLICY_EXPIRED')
    if not 0 < row['limit_microusd'] <= MAX_ALLOWANCE:
        raise ValueError('OPENAI_BUDGET_INVALID')
    if row['spent_microusd'] + row['reserved_microusd'] + amount > row['limit_microusd']:
        raise ValueError('OPENAI_BUDGET_EXCEEDED')
    return row


def normalize_usage(usage):
    if usage is None:
        return None, None
    if not isinstance(usage, dict) or set(usage) - {
            'input_tokens', 'output_tokens', 'total_tokens', 'input_tokens_details', 'output_tokens_details'}:
        raise ValueError('OPENAI_BUDGET_USAGE_INVALID')
    result = {}
    for name in ('input_tokens', 'output_tokens', 'total_tokens'):
        value = usage.get(name)
        if type(value) is not int or not 0 <= value <= 10_000_000:
            raise ValueError('OPENAI_BUDGET_USAGE_INVALID')
        result[name] = value
    if result['total_tokens'] != result['input_tokens'] + result['output_tokens']:
        raise ValueError('OPENAI_BUDGET_USAGE_INVALID')
    for field, details, total in (
            ('input_tokens_details', ('cached_tokens', 'cache_write_tokens'), 'input_tokens'),
            ('output_tokens_details', ('reasoning_tokens',), 'output_tokens')):
        values = usage.get(field)
        if values is None:
            continue
        if (not isinstance(values, dict) or not values or set(values) - set(details)
                or any(type(value) is not int or not 0 <= value <= result[total]
                       for value in values.values())
                or sum(values.values()) > result[total]):
            raise ValueError('OPENAI_BUDGET_USAGE_INVALID')
        result[field] = dict(values)
    inputs = result.get('input_tokens_details', {})
    cached = inputs.get('cached_tokens', 0)
    # Older response shapes may omit write telemetry. In that case all input
    # outside a reported cache read could have incurred the write premium.
    written = inputs.get('cache_write_tokens', result['input_tokens'] - cached)
    ordinary = result['input_tokens'] - cached - written
    # Reasoning is already included in output_tokens: never charge it twice.
    # Cache reads cost 0.4 micro-USD/token. Use tenths and one upward rounding
    # per call so the allowance never understates a fractional provider charge.
    tenths = 40 * ordinary + 4 * cached + 50 * written + 200 * result['output_tokens']
    return result, (tenths + 9) // 10


def settle(call_id, owner_id, usage, *, text=None, error_code=None):
    """Charge attempted calls even when output fails validation or lease is lost.

    No valid usage => retain the entire reservation. Invalid accounting freezes
    future dispatches. Settlement is idempotent and never automatically retries.
    """
    invalid = False
    try:
        values, cost = normalize_usage(usage)
    except (ValueError, TypeError):
        values, cost, invalid = None, None, True
    if text is not None and (not isinstance(text, str) or not text.strip()
                             or len(text.encode()) > 100000):
        raise ValueError('OPENAI_RESPONSE_INVALID')
    frozen = False
    with database() as connection:
        connection.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,1))', (owner_id,))
        # Fence output persistence against concurrent deletion/profile changes.
        # Lock order is owner, source, shared allowance, call (also used at dispatch).
        identity = connection.execute('SELECT * FROM openai_api_calls WHERE id=%s AND owner_id=%s',
                                      (call_id, owner_id)).fetchone()
        if text is not None and identity:
            from . import openai_provider
            try:
                openai_provider._source(connection, owner_id=owner_id, kind=identity['kind'],
                    job_id=identity['job_id'], video_job_id=identity['video_job_id'],
                    task_id=identity['task_id'], lease_token=identity['lease_token'],
                    source_sha256=identity['source_sha256'])
            except openai_provider.ProviderError:
                text, error_code = None, 'OPENAI_LEASE_LOST'
        budget = connection.execute('SELECT * FROM openai_api_budget WHERE id=1 FOR UPDATE').fetchone()
        call = connection.execute('SELECT * FROM openai_api_calls WHERE id=%s AND owner_id=%s FOR UPDATE',
                                  (call_id, owner_id)).fetchone()
        if not budget or not call or call['budget_id'] != 1:
            raise ValueError('OPENAI_BUDGET_ACCOUNTING_FAILED')
        if call['billing_status'] != 'reserved':
            return call
        if call['state'] != 'calling':
            raise ValueError('OPENAI_BUDGET_ACCOUNTING_FAILED')
        if cost is None:
            # Store only a bounded diagnostic, never a provider body or reasoning.
            diagnostic = {'usage_missing': not invalid, 'usage_invalid': invalid}
            connection.execute("""UPDATE openai_api_calls SET state='unknown',billing_status='unknown',
                usage=%s,error_code=%s,finished_at=now() WHERE id=%s""",
                (Jsonb(diagnostic), error_code or 'OPENAI_USAGE_MISSING', call_id))
            frozen = invalid
            if invalid:
                connection.execute("""UPDATE openai_api_budget SET enabled=false,
                    frozen_reason='INVALID_PROVIDER_USAGE',updated_at=now() WHERE id=1""")
        else:
            frozen = (cost > call['reserved_microusd'] or values['input_tokens'] > call['input_token_bound']
                      or values['output_tokens'] > call['max_output_tokens'])
            connection.execute("""UPDATE openai_api_budget SET reserved_microusd=reserved_microusd-%s,
                spent_microusd=spent_microusd+%s,enabled=enabled AND NOT %s,
                frozen_reason=CASE WHEN %s THEN 'PROVIDER_PRICE_BOUND_EXCEEDED' ELSE frozen_reason END,
                updated_at=now() WHERE id=1""", (call['reserved_microusd'], cost, frozen, frozen))
            if call['error_code'] == 'OPENAI_SOURCE_DELETED':
                text, error_code = None, 'OPENAI_SOURCE_DELETED'
            successful = text is not None and error_code is None and not frozen
            connection.execute("""UPDATE openai_api_calls SET state=%s,billing_status=%s,
                charged_microusd=%s,usage=%s,output_text=%s,output_sha256=%s,error_code=%s,
                finished_at=now() WHERE id=%s""", ('succeeded' if successful else 'failed',
                'breach' if frozen else 'settled', cost, Jsonb(values), text if successful else None,
                hashlib.sha256(text.encode()).hexdigest() if successful else None, error_code, call_id))
        result = connection.execute('SELECT * FROM openai_api_calls WHERE id=%s', (call_id,)).fetchone()
    print(json.dumps({'event': 'openai_api_accounting', 'call_id': str(call_id),
        'charged_microusd': cost, 'reservation_retained': cost is None, 'budget_frozen': frozen}), flush=True)
    if frozen:
        raise ValueError('OPENAI_BUDGET_RECONCILIATION_REQUIRED')
    return result


def status(connection=None):
    if connection is None:
        with database() as connection:
            return status(connection)
    row = connection.execute("""SELECT *,expires_at>clock_timestamp() AND expires_at<=%s::timestamptz
        AS price_valid FROM openai_api_budget WHERE id=1""", (PRICE_EXPIRES,)).fetchone()
    if not row:
        return {'enabled': False, 'reason': 'not_configured', 'model': MODEL}
    return {'enabled': bool(row['enabled'] and row['price_valid'] and row['model'] == MODEL
            and row['price_policy'] == POLICY and 0 < row['limit_microusd'] <= MAX_ALLOWANCE),
        **{key: row[key] for key in ('model', 'price_policy', 'price_valid', 'limit_microusd',
                                    'spent_microusd', 'reserved_microusd', 'frozen_reason')},
        'available_microusd': max(0, row['limit_microusd']-row['spent_microusd']-row['reserved_microusd'])}


def configure(*, limit_microusd, expires_at, enable=False):
    """Explicit operator action; never clear previous spend, holds or freezes."""
    try:
        expiry = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
        deadline = datetime.fromisoformat(PRICE_EXPIRES.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        raise ValueError('OPENAI_BUDGET_CONFIG_INVALID') from None
    if (type(limit_microusd) is not int or not 0 < limit_microusd <= MAX_ALLOWANCE
            or type(enable) is not bool or expiry.tzinfo is None
            or not datetime.now(timezone.utc) < expiry <= deadline):
        raise ValueError('OPENAI_BUDGET_CONFIG_INVALID')
    with database() as connection:
        row = connection.execute('SELECT * FROM openai_api_budget WHERE id=1 FOR UPDATE').fetchone()
        if (not row or row['model'] != MODEL or row['price_policy'] != POLICY
                or row['spent_microusd'] + row['reserved_microusd'] > limit_microusd):
            raise ValueError('OPENAI_BUDGET_CONFIG_INVALID')
        if row['frozen_reason']:
            raise ValueError('OPENAI_BUDGET_RECONCILIATION_REQUIRED')
        connection.execute('''UPDATE openai_api_budget SET limit_microusd=%s,expires_at=%s,
            enabled=%s,updated_at=now() WHERE id=1''', (limit_microusd, expiry, enable))
        return status(connection)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Inspect or explicitly configure the OpenAI allowance.')
    commands = parser.add_subparsers(dest='command')
    commands.add_parser('status')
    config = commands.add_parser('configure')
    config.add_argument('--limit-microusd', required=True, type=int)
    config.add_argument('--expires-at', required=True)
    config.add_argument('--enable', action='store_true')
    args = parser.parse_args()
    try:
        result = (configure(limit_microusd=args.limit_microusd, expires_at=args.expires_at, enable=args.enable)
                  if args.command == 'configure' else status())
        print(json.dumps({'event': 'openai_budget_status', **result}))
    except ValueError as error:
        parser.exit(2, str(error) + '\n')
