"""One bounded, tool-free Codex Responses attempt using personal ChatGPT OAuth.

Protocol follows the pinned Hermes native openai-codex adapter. This module is
not an API-key adapter and never falls back to another account/provider. A
durable compare-and-set precedes network I/O; uncertain attempts stay terminal.
"""
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import os
import re
import time
from uuid import UUID, uuid4

import httpx
from psycopg.types.json import Jsonb

from .db import database

MODEL = 'gpt-5.4'
ENDPOINT = 'https://chatgpt.com/backend-api/codex/responses'
MAX_INPUT_BYTES = 560000
MAX_OUTPUT_BYTES = 100000
MAX_STREAM_BYTES = 2 * 1024 * 1024
MAX_SECONDS = 120
_REQUEST_KEY = re.compile(r'^[A-Za-z0-9:._-]{1,180}$')
_ERROR_CODES = frozenset({'CHATGPT_REQUEST_INVALID', 'CHATGPT_REQUEST_TOO_LARGE',
    'CHATGPT_MODEL_UNSUPPORTED', 'CHATGPT_NOT_CONNECTED', 'CHATGPT_CONNECTION_CHANGED',
    'CHATGPT_QUOTA', 'CHATGPT_DAILY_LIMIT', 'CHATGPT_CALL_CONFLICT', 'CHATGPT_CALL_ALREADY_ATTEMPTED',
    'CHATGPT_CALL_EXPIRED', 'CHATGPT_CALL_NOT_FOUND', 'CHATGPT_RESPONSE_INVALID',
    'CHATGPT_RESPONSE_INCOMPLETE', 'CHATGPT_RESPONSE_REFUSED', 'CHATGPT_TOOLS_FORBIDDEN',
    'CHATGPT_OUTPUT_TOO_LARGE', 'CHATGPT_TIMEOUT', 'CHATGPT_TRANSPORT_ERROR',
    'CHATGPT_PROVIDER_UNAVAILABLE', 'CHATGPT_PROVIDER_REJECTED', 'CHATGPT_AUTH_EXPIRED',
    'CHATGPT_AUTH_UNAVAILABLE', 'CHATGPT_NOT_CONFIGURED', 'CHATGPT_LEASE_LOST'})


class ProviderError(ValueError):
    def __init__(self, code, *, unknown=False, retry_after=None):
        self.code = code if code in _ERROR_CODES else 'CHATGPT_PROVIDER_UNAVAILABLE'
        self.unknown = bool(unknown)
        self.retry_after = retry_after
        super().__init__(self.code)


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def request_payload(instructions, input_data, model=MODEL):
    if model != MODEL:
        raise ProviderError('CHATGPT_MODEL_UNSUPPORTED')
    if any(not isinstance(value, str) or not value.strip() or '\x00' in value
           for value in (instructions, input_data)):
        raise ProviderError('CHATGPT_REQUEST_INVALID')
    if len(instructions.encode()) + len(input_data.encode()) > MAX_INPUT_BYTES:
        raise ProviderError('CHATGPT_REQUEST_TOO_LARGE')
    # The Codex subscription endpoint rejects max_output_tokens/temperature.
    # Bound the wall time and received bytes locally; closing early is unknown
    # consumption, never a zero-cost API settlement or permission to retry.
    return {'model': model, 'instructions': instructions,
        'input': [{'role': 'user', 'content': [{'type': 'input_text', 'text': input_data}]}],
        'tools': [], 'tool_choice': 'none', 'parallel_tool_calls': False,
        'reasoning': {'effort': 'low'}, 'store': False, 'stream': True}


def request_digest(instructions, input_data, model=MODEL):
    return hashlib.sha256(_json(request_payload(instructions, input_data, model)).encode()).hexdigest()


def daily_limit():
    raw = os.environ.get('NARMA_CHATGPT_MAX_DAILY_CALLS', '6')
    if not raw.isdecimal() or not 1 <= int(raw) <= 20:
        raise ProviderError('CHATGPT_NOT_CONFIGURED')
    return int(raw)


def reserve_call(connection, *, owner_id, request_key, instructions, input_data,
                 expected_generation, job_id=None, task_id=None, model=MODEL):
    """Call inside the caller's validated source/lease transaction; never commits."""
    from . import chatgpt_auth as auth
    if not isinstance(request_key, str) or not _REQUEST_KEY.fullmatch(request_key) or bool(job_id) == bool(task_id):
        raise ProviderError('CHATGPT_REQUEST_INVALID')
    try:
        generation = str(UUID(str(expected_generation)))
    except (ValueError, TypeError, AttributeError):
        raise ProviderError('CHATGPT_CONNECTION_CHANGED') from None
    digest = request_digest(instructions, input_data, model)
    connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,81944))", (str(owner_id),))
    current = auth.current_connection(connection, owner_id)
    if not current or not current.get('connected') or str(current.get('generation')) != generation:
        raise ProviderError('CHATGPT_CONNECTION_CHANGED')
    if not current.get('available'):
        raise ProviderError('CHATGPT_QUOTA')
    previous = connection.execute('SELECT * FROM chatgpt_calls WHERE owner_id=%s AND request_key=%s',
        (owner_id, request_key)).fetchone()
    if previous:
        if (previous['request_sha256'] != digest or str(previous['connection_generation']) != generation
                or str(previous['job_id']) != str(job_id) or str(previous['task_id']) != str(task_id)):
            raise ProviderError('CHATGPT_CALL_CONFLICT')
        return previous
    # The owner is checked here as defense in depth. Exact source/lease validation
    # belongs to the caller, whose transaction remains open through this insert.
    table, identity = ('replay_jobs', job_id) if job_id else ('hermes_tasks', task_id)
    source = connection.execute(f'SELECT * FROM {table} WHERE id=%s AND owner_id=%s FOR SHARE', (identity, owner_id)).fetchone()
    if not source:
        raise ProviderError('CHATGPT_CALL_NOT_FOUND')
    if (not source.get('lease_token') or source['state'] != ('processing' if job_id else 'running')
            or source['lease_expires_at' if job_id else 'lease_until'] <= datetime.now(timezone.utc)):
        raise ProviderError('CHATGPT_LEASE_LOST')
    source_digest = source['source_sha256' if job_id else 'snapshot_sha256']
    if connection.execute('SELECT 1 FROM chatgpt_calls WHERE job_id=%s OR task_id=%s', (job_id, task_id)).fetchone():
        raise ProviderError('CHATGPT_CALL_ALREADY_ATTEMPTED')
    if connection.execute("""SELECT 1 FROM chatgpt_calls WHERE owner_id=%s AND connection_generation=%s
            AND error_code='CHATGPT_QUOTA' AND (pause_until IS NULL OR pause_until>now()) LIMIT 1""",
            (owner_id, generation)).fetchone():
        raise ProviderError('CHATGPT_QUOTA')
    count = connection.execute("""SELECT count(*) AS count FROM chatgpt_calls WHERE owner_id=%s
        AND created_at >= date_trunc('day',now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'""", (owner_id,)).fetchone()['count']
    if count >= daily_limit():
        raise ProviderError('CHATGPT_DAILY_LIMIT')
    return connection.execute("""INSERT INTO chatgpt_calls(id,owner_id,request_key,request_sha256,
        job_id,task_id,model,connection_generation,lease_token,source_sha256)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (uuid4(), owner_id, request_key, digest, job_id, task_id, model, generation,
            source['lease_token'], source_digest)).fetchone()


def get_succeeded(connection, *, owner_id, request_key):
    return connection.execute("""SELECT * FROM chatgpt_calls WHERE owner_id=%s AND request_key=%s
        AND state='succeeded'""", (owner_id, request_key)).fetchone()


def verified_call(connection, *, owner_id, task_id, expected_generation, model, output_text):
    if not isinstance(output_text, str):
        return False
    digest = hashlib.sha256(output_text.encode()).hexdigest()
    return bool(connection.execute("""SELECT 1 FROM chatgpt_calls WHERE owner_id=%s AND task_id=%s
        AND connection_generation=%s AND model=%s AND state='succeeded' AND output_sha256=%s
        AND request_key=%s""", (owner_id, task_id, expected_generation, model, digest, f'hermes:{task_id}')).fetchone())


def settle_call(connection, call_id, *, owner_id, state, text=None, usage=None, error_code=None, retry_after=None):
    """Settle an attempted call in an existing transaction; terminal rows are immutable."""
    if state not in ('succeeded', 'failed', 'unknown'):
        raise ProviderError('CHATGPT_RESPONSE_INVALID')
    if state == 'succeeded' and (not isinstance(text, str) or not text.strip() or len(text.encode()) > MAX_OUTPUT_BYTES):
        raise ProviderError('CHATGPT_RESPONSE_INVALID')
    error_code = error_code if error_code in _ERROR_CODES else None
    pause_until = datetime.now(timezone.utc) + timedelta(seconds=retry_after) if retry_after is not None else None
    return connection.execute("""UPDATE chatgpt_calls SET state=%s,output_text=%s,output_sha256=%s,
        usage=%s,error_code=%s,pause_until=%s,finished_at=now() WHERE id=%s AND owner_id=%s
        AND state='calling' RETURNING *""", (state, text if state == 'succeeded' else None,
        hashlib.sha256(text.encode()).hexdigest() if state == 'succeeded' else None,
        Jsonb(usage) if usage is not None else None, error_code, pause_until, call_id, owner_id)).fetchone()


def _usage(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ProviderError('CHATGPT_RESPONSE_INVALID')
    result = {'kind': 'chatgpt_subscription', 'api_cost_microusd': None}
    for field in ('input_tokens', 'output_tokens', 'total_tokens'):
        number = value.get(field)
        if type(number) is not int or not 0 <= number <= 10_000_000:
            raise ProviderError('CHATGPT_RESPONSE_INVALID')
        result[field] = number
    if result['total_tokens'] != result['input_tokens'] + result['output_tokens']:
        raise ProviderError('CHATGPT_RESPONSE_INVALID')
    return result


def _completed(response, model):
    if not isinstance(response, dict) or response.get('status') != 'completed' or response.get('error') is not None:
        raise ProviderError('CHATGPT_RESPONSE_INVALID')
    if response.get('model') not in (None, model):
        raise ProviderError('CHATGPT_RESPONSE_INVALID')
    output = response.get('output')
    if not isinstance(output, list) or not output or len(output) > 32:
        raise ProviderError('CHATGPT_RESPONSE_INVALID')
    texts = []
    for item in output:
        if not isinstance(item, dict):
            raise ProviderError('CHATGPT_RESPONSE_INVALID')
        kind = item.get('type')
        if kind == 'reasoning':
            continue  # Never expose/store reasoning or encrypted reasoning contents.
        if kind != 'message':
            raise ProviderError('CHATGPT_TOOLS_FORBIDDEN')
        if item.get('role') != 'assistant' or item.get('status') not in (None, 'completed'):
            raise ProviderError('CHATGPT_RESPONSE_INVALID')
        phase = item.get('phase')
        if phase not in (None, 'final', 'final_answer', 'analysis', 'commentary'):
            raise ProviderError('CHATGPT_RESPONSE_INVALID')
        parts = item.get('content')
        if not isinstance(parts, list) or not parts or len(parts) > 32:
            raise ProviderError('CHATGPT_RESPONSE_INVALID')
        for part in parts:
            if not isinstance(part, dict):
                raise ProviderError('CHATGPT_RESPONSE_INVALID')
            if part.get('type') == 'refusal':
                raise ProviderError('CHATGPT_RESPONSE_REFUSED')
            if part.get('type') != 'output_text' or not isinstance(part.get('text'), str):
                raise ProviderError('CHATGPT_RESPONSE_INVALID')
            if phase in (None, 'final', 'final_answer'):
                texts.append(part['text'])
    # Pinned Hermes trims surrounding whitespace before returning final_response.
    # Normalize exactly once here so the broker and durable provenance agree;
    # substantive transformations still fail the exact digest check.
    text = ''.join(texts).strip()
    if not text.strip() or '\x00' in text:
        raise ProviderError('CHATGPT_RESPONSE_INVALID')
    if len(text.encode()) > MAX_OUTPUT_BYTES:
        raise ProviderError('CHATGPT_OUTPUT_TOO_LARGE')
    return {'text': text, 'model': model, 'usage': _usage(response.get('usage'))}


def parse_stream(chunks, *, model=MODEL, started=None):
    """SSE framing, not substring/delta concatenation; only a terminal response wins."""
    started = time.monotonic() if started is None else started
    pending = b''
    event_lines = []
    total = 0
    terminal = None
    seen_data = False
    done_items = {}
    response_id = None
    for chunk in chunks:
        if time.monotonic() - started > MAX_SECONDS:
            raise ProviderError('CHATGPT_TIMEOUT', unknown=True)
        total += len(chunk)
        if total > MAX_STREAM_BYTES:
            raise ProviderError('CHATGPT_OUTPUT_TOO_LARGE', unknown=True)
        pending += chunk
        if len(pending) > MAX_STREAM_BYTES:
            raise ProviderError('CHATGPT_OUTPUT_TOO_LARGE', unknown=True)
        while b'\n' in pending:
            line, pending = pending.split(b'\n', 1)
            line = line.rstrip(b'\r')
            if line:
                if line.startswith(b'data:'):
                    event_lines.append(line[5:].lstrip(b' '))
                continue
            if not event_lines:
                continue
            raw = b'\n'.join(event_lines)
            event_lines = []
            if raw == b'[DONE]':
                if terminal is None:
                    raise ProviderError('CHATGPT_RESPONSE_INCOMPLETE', unknown=True)
                continue
            try:
                event = json.loads(raw.decode('utf-8'))
            except (ValueError, UnicodeError):
                raise ProviderError('CHATGPT_RESPONSE_INVALID', unknown=True) from None
            if not isinstance(event, dict) or not isinstance(event.get('type'), str):
                raise ProviderError('CHATGPT_RESPONSE_INVALID', unknown=True)
            kind = event['type']
            seen_data = True
            if terminal is not None:
                raise ProviderError('CHATGPT_RESPONSE_INVALID')
            if kind == 'response.created':
                created = event.get('response')
                if not isinstance(created, dict) or not isinstance(created.get('id'), str):
                    raise ProviderError('CHATGPT_RESPONSE_INVALID')
                response_id = created['id']
            if kind.startswith('response.refusal'):
                raise ProviderError('CHATGPT_RESPONSE_REFUSED')
            if any(fragment in kind for fragment in ('function_call', 'tool_call', 'computer_call', 'web_search', 'file_search')):
                raise ProviderError('CHATGPT_TOOLS_FORBIDDEN')
            if kind in ('response.output_item.added', 'response.output_item.done'):
                item = event.get('item')
                if not isinstance(item, dict) or item.get('type') not in ('message', 'reasoning'):
                    raise ProviderError('CHATGPT_TOOLS_FORBIDDEN')
                if kind == 'response.output_item.done':
                    index = event.get('output_index')
                    if type(index) is not int or not 0 <= index < 32 or index in done_items:
                        raise ProviderError('CHATGPT_RESPONSE_INVALID')
                    done_items[index] = item
            if kind == 'response.completed':
                completed = event.get('response')
                if not isinstance(completed, dict) or (response_id is not None and completed.get('id') != response_id):
                    raise ProviderError('CHATGPT_RESPONSE_INVALID')
                # Native Codex may send output:null on the terminal envelope.
                # Only finished indexed items may fill it; deltas never count as
                # a complete response, and a terminal completed is still required.
                if not completed.get('output'):
                    if sorted(done_items) != list(range(len(done_items))):
                        raise ProviderError('CHATGPT_RESPONSE_INVALID')
                    completed = {**completed, 'output': [done_items[i] for i in sorted(done_items)]}
                terminal = _completed(completed, model)
            elif kind in ('response.incomplete', 'response.failed', 'error'):
                # These terminal errors do not license an automatic second request.
                raise ProviderError('CHATGPT_RESPONSE_INCOMPLETE' if kind == 'response.incomplete'
                                    else 'CHATGPT_PROVIDER_REJECTED')
    if pending.strip() or event_lines or terminal is None or not seen_data:
        raise ProviderError('CHATGPT_RESPONSE_INCOMPLETE', unknown=True)
    return terminal


def _retry_after(headers):
    value = headers.get('retry-after')
    if not isinstance(value, str) or len(value) > 100:
        return None
    try:
        seconds = int(value) if value.isdecimal() else int((parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None
    return seconds if 1 <= seconds <= 7 * 86400 else None


def _generate(credentials, instructions, input_data, model=MODEL):
    headers = {'Authorization': 'Bearer ' + credentials['access_token'],
        'Accept': 'text/event-stream', 'Content-Type': 'application/json',
        'User-Agent': 'NarmaVision/1.0', 'originator': 'narma-vision'}
    account = credentials.get('account_id')
    if isinstance(account, str) and account:
        headers['ChatGPT-Account-Id'] = account
    started = time.monotonic()
    # Fixed HTTPS endpoint, no redirects/proxies/SDK retries, no account fallback.
    try:
        with httpx.Client(timeout=httpx.Timeout(30, connect=10, write=20, pool=5),
                          trust_env=False, follow_redirects=False) as client:
            with client.stream('POST', ENDPOINT, headers=headers,
                               json=request_payload(instructions, input_data, model)) as response:
                if response.status_code == 429:
                    raise ProviderError('CHATGPT_QUOTA', retry_after=_retry_after(response.headers))
                if response.status_code in (401, 403):
                    raise ProviderError('CHATGPT_AUTH_EXPIRED')
                if response.status_code != 200:
                    raise ProviderError('CHATGPT_PROVIDER_UNAVAILABLE' if response.status_code >= 500
                                        else 'CHATGPT_PROVIDER_REJECTED', unknown=response.status_code >= 500)
                if response.headers.get('content-type', '').split(';')[0].strip().lower() != 'text/event-stream':
                    raise ProviderError('CHATGPT_RESPONSE_INVALID', unknown=True)
                # Do not buffer up to a fixed chunk size: small heartbeat events
                # must reach the wall-clock check immediately. Deadline120s plus
                # the bounded pending read30s gives a maximum150s transport wait.
                return parse_stream(response.iter_bytes(), model=model, started=started)
    except httpx.TimeoutException:
        raise ProviderError('CHATGPT_TIMEOUT', unknown=True) from None
    except httpx.TransportError:
        raise ProviderError('CHATGPT_TRANSPORT_ERROR', unknown=True) from None


def perform_reserved(call_id, owner_id, instructions, input_data):
    """Perform once after the reservation transaction commits; no implicit resend."""
    from . import chatgpt_auth as auth
    # No inference before credentials and immutable payload/generation agree.
    credentials = auth.get_access_credentials(owner_id)
    with database() as connection:
        # Match the broker/replay reservation lock order: owner, source, ledger.
        connection.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,1))', (owner_id,))
        row = connection.execute('SELECT * FROM chatgpt_calls WHERE id=%s AND owner_id=%s',
            (call_id, owner_id)).fetchone()
        if not row:
            raise ProviderError('CHATGPT_CALL_NOT_FOUND')
        if row['state'] != 'reserved':
            raise ProviderError('CHATGPT_CALL_ALREADY_ATTEMPTED')
        if row['request_sha256'] != request_digest(instructions, input_data, row['model']):
            raise ProviderError('CHATGPT_CALL_CONFLICT')
        # Caller validates lease/source atomically at reservation; recheck the
        # continuing job/task lease now so queued stale work cannot generate.
        if row['task_id']:
            from . import hermes_tasks
            task = connection.execute("""SELECT * FROM hermes_tasks WHERE id=%s AND owner_id=%s
                AND state='running' AND lease_token=%s AND snapshot_sha256=%s FOR UPDATE""",
                (row['task_id'], owner_id, row['lease_token'], row['source_sha256'])).fetchone()
            valid = (task and task.get('provider') == 'chatgpt_subscription'
                and task.get('model') == row['model']
                and str(task.get('connection_generation')) == str(row['connection_generation'])
                and hermes_tasks._sources_available(connection, owner_id, task['source_jobs'])
                and hermes_tasks._lease_valid(connection, task))
        else:
            source = connection.execute("""SELECT r.* FROM replay_jobs r JOIN portal_dota_profiles p
                ON p.owner_id=r.owner_id AND p.account_id=r.account_id
                WHERE r.id=%s AND r.owner_id=%s AND r.state='processing' AND r.lease_token=%s
                AND r.source_sha256=%s FOR UPDATE OF r FOR SHARE OF p""",
                (row['job_id'], owner_id, row['lease_token'], row['source_sha256'])).fetchone()
            valid = source and source['lease_expires_at'] > datetime.now(timezone.utc)
        if not valid:
            raise ProviderError('CHATGPT_LEASE_LOST')
        row = connection.execute('SELECT * FROM chatgpt_calls WHERE id=%s AND owner_id=%s FOR UPDATE',
            (call_id, owner_id)).fetchone()
        if row['state'] != 'reserved':
            raise ProviderError('CHATGPT_CALL_ALREADY_ATTEMPTED')
        current = auth.current_connection(connection, owner_id)
        if (not current or not current.get('available')
                or str(current.get('generation')) != str(row['connection_generation'])
                or str(credentials.get('generation')) != str(row['connection_generation'])):
            raise ProviderError('CHATGPT_CONNECTION_CHANGED')
        if row['expires_at'] <= datetime.now(timezone.utc):
            raise ProviderError('CHATGPT_CALL_EXPIRED')
        connection.execute("UPDATE chatgpt_calls SET state='calling',started_at=now() WHERE id=%s", (call_id,))
    result = None
    try:
        result = _generate(credentials, instructions, input_data, row['model'])
        if not auth.credentials_current(owner_id, credentials['generation']):
            raise ProviderError('CHATGPT_CONNECTION_CHANGED')
    except Exception as error:
        if isinstance(error, ProviderError):
            failure = error
        else:
            failure = ProviderError('CHATGPT_PROVIDER_UNAVAILABLE', unknown=True)
        with database() as connection:
            settle_call(connection, call_id, owner_id=owner_id,
                state='unknown' if failure.unknown else 'failed',
                usage=result.get('usage') if result else None,
                error_code=failure.code, retry_after=failure.retry_after)
        if failure.code == 'CHATGPT_QUOTA':
            auth.record_provider_pause(owner_id, credentials['generation'],
                seconds=failure.retry_after, code='CHATGPT_QUOTA')
        elif failure.code == 'CHATGPT_AUTH_EXPIRED':
            auth.mark_reconnect_required(owner_id, credentials['generation'])
        raise failure from None
    with database() as connection:
        settled = settle_call(connection, call_id, owner_id=owner_id, state='succeeded',
            text=result['text'], usage=result['usage'])
    if not settled:
        raise ProviderError('CHATGPT_CALL_ALREADY_ATTEMPTED')
    return {**result, 'call_id': str(call_id), 'connection_generation': credentials['generation']}
