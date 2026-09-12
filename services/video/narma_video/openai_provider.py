"""Bounded Responses API adapter for owner-funded, isolated customer coaching.

This endpoint uses a server API key. It never imports personal OAuth credentials,
follows redirects, retries, runs tools, or sends previous customers' responses.
Reservation and dispatch are separate so callers can fence their source context.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import time
from uuid import UUID, uuid4

import httpx

from . import openai_budget as budget
from .db import database

MODEL = budget.MODEL
ENDPOINT = 'https://api.openai.com/v1/responses'
MAX_INPUT_BYTES = 220000
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_OUTPUT_BYTES = 100000
MAX_SECONDS = 150
_KEY = re.compile(r'^[A-Za-z0-9:._-]{1,180}$')
_ERRORS = frozenset({'OPENAI_NOT_CONFIGURED', 'OPENAI_REQUEST_INVALID', 'OPENAI_REQUEST_TOO_LARGE',
    'OPENAI_MODEL_UNSUPPORTED', 'OPENAI_CALL_CONFLICT', 'OPENAI_CALL_ALREADY_ATTEMPTED',
    'OPENAI_CALL_NOT_FOUND', 'OPENAI_LEASE_LOST', 'OPENAI_CALL_EXPIRED', 'OPENAI_DAILY_LIMIT',
    'OPENAI_RESPONSE_INVALID', 'OPENAI_RESPONSE_INCOMPLETE', 'OPENAI_RESPONSE_REFUSED',
    'OPENAI_TOOLS_FORBIDDEN', 'OPENAI_OUTPUT_TOO_LARGE', 'OPENAI_TIMEOUT', 'OPENAI_TRANSPORT_ERROR',
    'OPENAI_AUTHENTICATION_FAILED', 'OPENAI_RATE_LIMITED', 'OPENAI_PROVIDER_UNAVAILABLE',
    'OPENAI_PROVIDER_REJECTED', 'OPENAI_USAGE_MISSING'})


class ProviderError(ValueError):
    def __init__(self, code):
        self.code = code if code in _ERRORS else 'OPENAI_PROVIDER_UNAVAILABLE'
        super().__init__(self.code)


def configured():
    return bool(os.environ.get('OPENAI_API_KEY', '').strip()) and os.environ.get('OPENAI_MODEL', MODEL) == MODEL


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def strict_schema(value):
    """Translate Pydantic defaults to the Responses strict-schema subset.

    A formerly optional field is required but nullable; existing nullable unions
    remain intact. Business validation still runs after generation in the caller.
    """
    if not isinstance(value, dict) or value.get('type') != 'object':
        raise ProviderError('OPENAI_REQUEST_INVALID')
    result = deepcopy(value)
    def visit(node, depth=0):
        if depth > 32:
            raise ProviderError('OPENAI_REQUEST_INVALID')
        if isinstance(node, dict):
            node.pop('default', None)
            if node.get('type') == 'object' or 'properties' in node:
                props = node.get('properties')
                if not isinstance(props, dict):
                    raise ProviderError('OPENAI_REQUEST_INVALID')
                required = node.get('required', [])
                for name, child in list(props.items()):
                    if name not in required and isinstance(child, dict):
                        nullable = child.get('type') == 'null' or (isinstance(child.get('type'), list)
                            and 'null' in child['type']) or any(part.get('type') == 'null'
                            for part in child.get('anyOf', []) if isinstance(part, dict))
                        if not nullable:
                            props[name] = {'anyOf': [child, {'type': 'null'}]}
                node['required'] = list(props)
                node['additionalProperties'] = False
            for child in node.values():
                visit(child, depth+1)
        elif isinstance(node, list):
            for child in node:
                visit(child, depth+1)
    visit(result)
    return result


def request_payload(instructions, input_data, schema, *, max_output_tokens=5000, model=MODEL):
    if model != MODEL:
        raise ProviderError('OPENAI_MODEL_UNSUPPORTED')
    if (any(not isinstance(value, str) or not value.strip() or '\x00' in value
            for value in (instructions, input_data))
            or type(max_output_tokens) is not int or not 256 <= max_output_tokens <= budget.MAX_OUTPUT_TOKENS):
        raise ProviderError('OPENAI_REQUEST_INVALID')
    # Cache only the reusable instructions. The explicit-only mode prevents the
    # provider's implicit breakpoint from writing unique customer evidence.
    # https://developers.openai.com/api/docs/guides/prompt-caching
    payload = {'model': model,
        'prompt_cache_options': {'mode': 'explicit'},
        'input': [
            {'role': 'developer', 'content': [{'type': 'input_text', 'text': instructions,
                'prompt_cache_breakpoint': {'mode': 'explicit'}}]},
            {'role': 'user', 'content': [{'type': 'input_text', 'text': input_data}]}],
        'tools': [], 'tool_choice': 'none', 'parallel_tool_calls': False,
        'reasoning': {'effort': 'low'}, 'store': False, 'stream': False,
        'service_tier': 'default', 'max_output_tokens': max_output_tokens,
        'text': {'format': {'type': 'json_schema', 'name': 'narma_coaching',
                            'strict': True, 'schema': strict_schema(schema)}}}
    try:
        size = len(_json(payload).encode())
    except (ValueError, TypeError, RecursionError):
        raise ProviderError('OPENAI_REQUEST_INVALID') from None
    if size > MAX_INPUT_BYTES:
        raise ProviderError('OPENAI_REQUEST_TOO_LARGE')
    return payload


def request_digest(instructions, input_data, schema, *, max_output_tokens=5000):
    return hashlib.sha256(_json(request_payload(instructions, input_data, schema,
        max_output_tokens=max_output_tokens)).encode()).hexdigest()


def input_token_bound(payload):
    # Text-only byte-level tokenization cannot need more than the serialized
    # UTF-8 bytes; reserve extra framing/schema overhead without a paid count call.
    # This is a cost ceiling, not a claimed actual tokenizer count.
    return len(_json(payload).encode()) + 8192


def daily_limit():
    value = os.environ.get('OPENAI_MAX_DAILY_CALLS', '20')
    if not value.isdecimal() or not 1 <= int(value) <= 250:
        raise ProviderError('OPENAI_NOT_CONFIGURED')
    return int(value)


def _source(connection, *, owner_id, kind, job_id=None, video_job_id=None, task_id=None,
            lease_token=None, source_sha256=None):
    # Static SQL choices, exact owner binding and live lease before every attempt.
    if kind == 'replay' and job_id and not video_job_id and not task_id:
        row = connection.execute('''SELECT r.*,r.lease_expires_at>clock_timestamp() AS live
            FROM replay_jobs r JOIN portal_dota_profiles p ON p.owner_id=r.owner_id AND p.account_id=r.account_id
            WHERE r.id=%s AND r.owner_id=%s AND r.state='processing' AND r.lease_token=%s
            FOR UPDATE OF r FOR SHARE OF p''', (job_id, owner_id, lease_token)).fetchone()
    elif kind == 'video' and video_job_id and not job_id and not task_id:
        row = connection.execute('''SELECT *,lease_expires_at>clock_timestamp() AS live FROM video_jobs
            WHERE id=%s AND owner_id=%s AND state='processing' AND lease_token=%s FOR UPDATE''',
            (video_job_id, owner_id, lease_token)).fetchone()
        if row and row.get('storage_deleted_at') is not None:
            row = None
    elif kind == 'hermes' and task_id and not job_id and not video_job_id:
        row = connection.execute('''SELECT *,lease_until>clock_timestamp() AS live FROM hermes_tasks
            WHERE id=%s AND owner_id=%s AND state='running' AND lease_token=%s
            AND provider='openai_api' AND model=%s FOR UPDATE''',
            (task_id, owner_id, lease_token, MODEL)).fetchone()
        if row:
            from . import hermes_tasks
            if (hermes_tasks.configured_provider() != 'openai_api'
                    or not hermes_tasks._sources_available(connection, owner_id, row['source_jobs'])
                    or not hermes_tasks._lease_valid(connection, row)):
                row = None
            elif hermes_tasks.task_model(row) != MODEL:
                row = None
    else:
        raise ProviderError('OPENAI_REQUEST_INVALID')
    if not row or not row['live']:
        raise ProviderError('OPENAI_LEASE_LOST')
    # SELECT expressions may have been evaluated before a row-lock wait. Re-read
    # server time after the lock, including the post-response persistence fence.
    if kind == 'replay':
        live = connection.execute('SELECT lease_expires_at>clock_timestamp() AS live FROM replay_jobs WHERE id=%s',
                                  (job_id,)).fetchone()
    elif kind == 'video':
        live = connection.execute('SELECT lease_expires_at>clock_timestamp() AS live FROM video_jobs WHERE id=%s',
                                  (video_job_id,)).fetchone()
    else:
        live = connection.execute('SELECT lease_until>clock_timestamp() AS live FROM hermes_tasks WHERE id=%s',
                                  (task_id,)).fetchone()
    if not live or not live['live']:
        raise ProviderError('OPENAI_LEASE_LOST')
    digest = row.get('snapshot_sha256' if kind == 'hermes' else 'source_sha256')
    if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
        raise ProviderError('OPENAI_REQUEST_INVALID')
    if source_sha256 is not None and digest != source_sha256:
        raise ProviderError('OPENAI_CALL_CONFLICT')
    return digest


def reserve_call(connection, *, owner_id, request_key, instructions, input_data, schema, kind,
                 lease_token, job_id=None, task_id=None, video_job_id=None, max_output_tokens=5000):
    """Reserve inside caller's source/context transaction; commit before dispatch."""
    if not configured():
        raise ProviderError('OPENAI_NOT_CONFIGURED')
    if not isinstance(owner_id, str) or not owner_id or not isinstance(request_key, str) or not _KEY.fullmatch(request_key):
        raise ProviderError('OPENAI_REQUEST_INVALID')
    try:
        lease_token = UUID(str(lease_token))
    except (ValueError, TypeError, AttributeError):
        raise ProviderError('OPENAI_REQUEST_INVALID') from None
    payload = request_payload(instructions, input_data, schema, max_output_tokens=max_output_tokens)
    digest = hashlib.sha256(_json(payload).encode()).hexdigest()
    bound = input_token_bound(payload)
    amount = budget.estimate_reservation(bound, max_output_tokens)
    connection.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,1))', (owner_id,))
    source = _source(connection, owner_id=owner_id, kind=kind, job_id=job_id,
        video_job_id=video_job_id, task_id=task_id, lease_token=lease_token)
    previous = connection.execute('SELECT * FROM openai_api_calls WHERE owner_id=%s AND request_key=%s',
                                  (owner_id, request_key)).fetchone()
    if previous:
        if (previous['request_sha256'] != digest or previous['kind'] != kind
                or previous['source_sha256'] != source
                or any(str(previous[key]) != str(value) for key, value in
                       (('job_id', job_id), ('video_job_id', video_job_id), ('task_id', task_id)))):
            raise ProviderError('OPENAI_CALL_CONFLICT')
        if previous['state'] == 'reserved' and str(previous['lease_token']) != str(lease_token):
            raise ProviderError('OPENAI_LEASE_LOST')
        return previous
    if connection.execute('''SELECT 1 FROM openai_api_calls WHERE job_id=%s OR video_job_id=%s OR task_id=%s''',
                          (job_id, video_job_id, task_id)).fetchone():
        raise ProviderError('OPENAI_CALL_ALREADY_ATTEMPTED')
    count = connection.execute('''SELECT count(*) AS count FROM openai_api_calls
        WHERE owner_id=%s AND created_at>now()-interval '1 day' ''', (owner_id,)).fetchone()['count']
    if count >= daily_limit():
        raise ProviderError('OPENAI_DAILY_LIMIT')
    budget.lock_allowance(connection, amount)
    # A contended shared allowance can outlive the source lease.
    _source(connection, owner_id=owner_id, kind=kind, job_id=job_id, video_job_id=video_job_id,
            task_id=task_id, lease_token=lease_token, source_sha256=source)
    row = connection.execute('''INSERT INTO openai_api_calls(id,owner_id,request_key,request_sha256,
        kind,job_id,video_job_id,task_id,lease_token,source_sha256,budget_id,model,price_policy,
        input_token_bound,max_output_tokens,reserved_microusd)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s,%s,%s,%s,%s) RETURNING *''',
        (uuid4(), owner_id, request_key, digest, kind, job_id, video_job_id, task_id, lease_token,
         source, MODEL, budget.POLICY, bound, max_output_tokens, amount)).fetchone()
    connection.execute('UPDATE openai_api_budget SET reserved_microusd=reserved_microusd+%s,updated_at=now() WHERE id=1', (amount,))
    return row


def _generate(payload):
    if not configured():
        raise ProviderError('OPENAI_NOT_CONFIGURED')
    headers = {'Authorization': 'Bearer ' + os.environ['OPENAI_API_KEY'].strip(),
               'Content-Type': 'application/json', 'Accept': 'application/json'}
    started = time.monotonic()
    try:
        with httpx.Client(timeout=httpx.Timeout(150, connect=10, write=20, pool=5),
                          trust_env=False, follow_redirects=False) as client:
            with client.stream('POST', ENDPOINT, headers=headers, json=payload) as response:
                if response.status_code in (401, 403):
                    raise ProviderError('OPENAI_AUTHENTICATION_FAILED')
                if response.status_code == 429:
                    raise ProviderError('OPENAI_RATE_LIMITED')
                if response.status_code != 200:
                    raise ProviderError('OPENAI_PROVIDER_UNAVAILABLE' if response.status_code >= 500
                                        else 'OPENAI_PROVIDER_REJECTED')
                if response.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
                    raise ProviderError('OPENAI_RESPONSE_INVALID')
                raw = bytearray()
                for chunk in response.iter_bytes():
                    if time.monotonic() - started > MAX_SECONDS:
                        raise ProviderError('OPENAI_TIMEOUT')
                    raw.extend(chunk)
                    if len(raw) > MAX_RESPONSE_BYTES:
                        raise ProviderError('OPENAI_OUTPUT_TOO_LARGE')
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ProviderError('OPENAI_RESPONSE_INVALID')
        return value
    except httpx.TimeoutException:
        raise ProviderError('OPENAI_TIMEOUT') from None
    except httpx.TransportError:
        raise ProviderError('OPENAI_TRANSPORT_ERROR') from None
    except (ValueError, UnicodeError) as error:
        if isinstance(error, ProviderError):
            raise
        raise ProviderError('OPENAI_RESPONSE_INVALID') from None


def _text(response):
    if response.get('status') != 'completed':
        raise ProviderError('OPENAI_RESPONSE_INCOMPLETE')
    if (response.get('error') is not None or response.get('service_tier') not in (None, 'default')
            or not re.fullmatch(re.escape(MODEL) + r'(?:-\d{4}-\d{2}-\d{2})?', str(response.get('model', '')))):
        raise ProviderError('OPENAI_RESPONSE_INVALID')
    output = response.get('output')
    if not isinstance(output, list) or not 1 <= len(output) <= 32:
        raise ProviderError('OPENAI_RESPONSE_INVALID')
    texts = []
    for item in output:
        if not isinstance(item, dict):
            raise ProviderError('OPENAI_RESPONSE_INVALID')
        if item.get('type') == 'reasoning':
            continue
        if item.get('type') != 'message':
            raise ProviderError('OPENAI_TOOLS_FORBIDDEN')
        if item.get('role') != 'assistant' or item.get('status') not in (None, 'completed'):
            raise ProviderError('OPENAI_RESPONSE_INVALID')
        parts = item.get('content')
        if not isinstance(parts, list) or not 1 <= len(parts) <= 32:
            raise ProviderError('OPENAI_RESPONSE_INVALID')
        for part in parts:
            if isinstance(part, dict) and part.get('type') == 'refusal':
                raise ProviderError('OPENAI_RESPONSE_REFUSED')
            if not isinstance(part, dict) or part.get('type') != 'output_text' or not isinstance(part.get('text'), str):
                raise ProviderError('OPENAI_RESPONSE_INVALID')
            if item.get('phase') not in (None, 'final', 'final_answer'):
                raise ProviderError('OPENAI_RESPONSE_INVALID')
            texts.append(part['text'])
    text = ''.join(texts).strip()
    if not text or '\x00' in text or len(text.encode()) > MAX_OUTPUT_BYTES:
        raise ProviderError('OPENAI_OUTPUT_TOO_LARGE')
    try:
        parsed = json.loads(text)
    except ValueError:
        raise ProviderError('OPENAI_RESPONSE_INVALID') from None
    if not isinstance(parsed, dict):
        raise ProviderError('OPENAI_RESPONSE_INVALID')
    return text


def perform_reserved(call_id, owner_id, instructions, input_data, schema, *, max_output_tokens=5000):
    """One compare-and-set before I/O; all observed usage settles in a finally path."""
    if not configured():
        raise ProviderError('OPENAI_NOT_CONFIGURED')
    payload = request_payload(instructions, input_data, schema, max_output_tokens=max_output_tokens)
    digest = hashlib.sha256(_json(payload).encode()).hexdigest()
    with database() as connection:
        connection.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,1))', (owner_id,))
        row = connection.execute('SELECT * FROM openai_api_calls WHERE id=%s AND owner_id=%s', (call_id, owner_id)).fetchone()
        if not row:
            raise ProviderError('OPENAI_CALL_NOT_FOUND')
        if row['state'] != 'reserved':
            raise ProviderError('OPENAI_CALL_ALREADY_ATTEMPTED')
        if row['request_sha256'] != digest:
            raise ProviderError('OPENAI_CALL_CONFLICT')
        _source(connection, owner_id=owner_id, kind=row['kind'], job_id=row['job_id'],
            video_job_id=row['video_job_id'], task_id=row['task_id'], lease_token=row['lease_token'],
            source_sha256=row['source_sha256'])
        # Disable/freeze/expiry takes effect for queued reservations too.
        budget.lock_allowance(connection, 0)
        _source(connection, owner_id=owner_id, kind=row['kind'], job_id=row['job_id'],
            video_job_id=row['video_job_id'], task_id=row['task_id'], lease_token=row['lease_token'],
            source_sha256=row['source_sha256'])
        active = connection.execute('''UPDATE openai_api_calls SET state='calling',started_at=clock_timestamp()
            WHERE id=%s AND owner_id=%s AND state='reserved' AND expires_at>clock_timestamp() RETURNING id''',
            (call_id, owner_id)).fetchone()
        if not active:
            raise ProviderError('OPENAI_CALL_EXPIRED')
    response, output, failure = None, None, None
    try:
        response = _generate(payload)
        output = _text(response)
        if response.get('usage') is None:
            raise ProviderError('OPENAI_USAGE_MISSING')
    except Exception as error:
        failure = error if isinstance(error, ProviderError) else ProviderError('OPENAI_PROVIDER_UNAVAILABLE')
    # Even an incomplete/refused/invalid output incurs its actual reported usage.
    usage = response.get('usage') if response else None
    if response and (response.get('service_tier') not in (None, 'default') or not re.fullmatch(
            re.escape(MODEL) + r'(?:-\d{4}-\d{2}-\d{2})?', str(response.get('model', '')))):
        usage = {'unsupported_model_or_tier': True}  # Freeze unpriceable responses.
    settled = budget.settle(call_id, owner_id, usage, text=output if failure is None else None,
                            error_code=failure.code if failure else None)
    if failure:
        raise failure from None
    if settled['state'] != 'succeeded':
        raise ProviderError('OPENAI_RESPONSE_INVALID')
    return {'text': output, 'model': MODEL, 'usage': settled['usage'], 'call_id': str(call_id),
            'cost_microusd': settled['charged_microusd']}


def complete_metered(*, owner_id, request_key, instructions, input_data, schema, kind,
                     lease_token, job_id=None, task_id=None, video_job_id=None, max_output_tokens=5000):
    with database() as connection:
        row = reserve_call(connection, owner_id=owner_id, request_key=request_key,
            instructions=instructions, input_data=input_data, schema=schema, kind=kind,
            lease_token=lease_token, job_id=job_id, task_id=task_id, video_job_id=video_job_id,
            max_output_tokens=max_output_tokens)
    if row['state'] == 'succeeded':
        return {'text': row['output_text'], 'model': row['model'], 'usage': row['usage'],
                'call_id': str(row['id']), 'cost_microusd': row['charged_microusd']}
    return perform_reserved(row['id'], owner_id, instructions, input_data, schema,
                            max_output_tokens=max_output_tokens)


def verified_call(connection, *, owner_id, task_id, model, output_text):
    if model != MODEL or not isinstance(output_text, str):
        return False
    return bool(connection.execute('''SELECT 1 FROM openai_api_calls WHERE owner_id=%s AND task_id=%s
        AND model=%s AND state='succeeded' AND billing_status='settled' AND output_sha256=%s''',
        (owner_id, task_id, model, hashlib.sha256(output_text.encode()).hexdigest())).fetchone())


def forget_output(connection, *, owner_id, video_job_id=None, job_id=None):
    """Call in the source-deletion transaction after locking the owned source.

    Retain billing/attempt history. Mark in-flight calls so their settlement can
    charge usage without restoring deleted private output.
    """
    if bool(video_job_id) == bool(job_id):
        raise ProviderError('OPENAI_REQUEST_INVALID')
    return connection.execute('''UPDATE openai_api_calls SET output_text=NULL,output_sha256=NULL,
        state=CASE WHEN state='succeeded' THEN 'failed' ELSE state END,
        error_code='OPENAI_SOURCE_DELETED'
        WHERE owner_id=%s AND (video_job_id=%s OR job_id=%s) RETURNING id''',
        (owner_id, video_job_id, job_id)).fetchall()
