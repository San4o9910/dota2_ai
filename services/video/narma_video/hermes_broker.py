"""Private, metered provider boundary for the isolated Hermes runtime.

Only the broker has the provider key and database access. Each expiring task
credential permits one provider attempt; retries and auxiliary agent requests
cannot bypass the shared allowance. This app is never mounted on the portal.
"""
from contextlib import asynccontextmanager
import asyncio
import json
import math
import os
import re
import time

from fastapi import FastAPI, Request
from google import genai
from google.genai import errors, types
import httpx
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from . import budget
from .db import database
from .gemini import generate_usage

MAX_REQUEST_BYTES = 512 * 1024
MAX_RESPONSE_BYTES = 100000
MAX_MESSAGES = 32
TOKEN = re.compile(r'^[A-Za-z0-9_-]{40,128}$')
_FIELDS = frozenset({'model', 'messages', 'max_tokens', 'max_completion_tokens', 'temperature',
    'top_p', 'stream', 'n', 'response_format', 'stop', 'tools', 'tool_choice', 'reasoning_effort'})
_SAFE_FAILURES = frozenset({'HERMES_TOKEN_INVALID', 'HERMES_LEASE_EXPIRED', 'HERMES_SOURCE_CHANGED',
    'HERMES_REQUEST_INVALID', 'HERMES_REQUEST_TOO_LARGE', 'HERMES_MODEL_UNSUPPORTED',
    'HERMES_REQUEST_BUDGET_EXCEEDED', 'HERMES_NOT_CONFIGURED', 'HERMES_PROVIDER_RESPONSE_INVALID',
    'VIDEO_GLOBAL_BUDGET_DISABLED', 'VIDEO_GLOBAL_BUDGET_EXCEEDED', 'VIDEO_GLOBAL_BUDGET_INVALID',
    'VIDEO_BUDGET_PRICE_POLICY_EXPIRED', 'VIDEO_REQUEST_BUDGET_EXCEEDED',
    'VIDEO_BUDGET_RECONCILIATION_REQUIRED', 'VIDEO_BUDGET_ACCOUNTING_FAILED', 'GEMINI_USAGE_UNSUPPORTED'})
_FINISH_REASONS = frozenset({'STOP', 'MAX_TOKENS', 'SAFETY', 'RECITATION', 'OTHER', 'BLOCKLIST',
    'PROHIBITED_CONTENT', 'SPII', 'MALFORMED_FUNCTION_CALL', 'FINISH_REASON_UNSPECIFIED',
    'IMAGE_SAFETY', 'IMAGE_PROHIBITED_CONTENT', 'IMAGE_RECITATION', 'NO_IMAGE',
    'UNEXPECTED_TOOL_CALL', 'TOO_MANY_TOOL_CALLS'})
_PART_KEYS = frozenset({'text', 'thought', 'thoughtSignature', 'functionCall', 'functionResponse',
    'inlineData', 'fileData', 'executableCode', 'codeExecutionResult', 'videoMetadata'})
_API_STATUSES = frozenset({'INVALID_ARGUMENT', 'FAILED_PRECONDITION', 'OUT_OF_RANGE', 'UNAUTHENTICATED',
    'PERMISSION_DENIED', 'NOT_FOUND', 'ALREADY_EXISTS', 'RESOURCE_EXHAUSTED', 'CANCELLED',
    'DATA_LOSS', 'UNKNOWN', 'INTERNAL', 'UNIMPLEMENTED', 'UNAVAILABLE', 'DEADLINE_EXCEEDED'})


def authorize_call(connection, token):
    from .hermes_tasks import authorize_call as authorize
    return authorize(connection, token)


def response_diagnostics(raw):
    """Only fixed vocabulary and bounded counts; no provider text or field values."""
    candidates = raw.get('candidates')
    first = candidates[0] if isinstance(candidates, list) and candidates and isinstance(candidates[0], dict) else {}
    finish = first.get('finishReason')
    content = first.get('content')
    parts = content.get('parts') if isinstance(content, dict) else None
    kinds, output_bytes = set(), 0
    if isinstance(parts, list):
        for part in parts:
            if not isinstance(part, dict):
                kinds.add('invalid_part')
                continue
            for key, value in part.items():
                if key not in _PART_KEYS:
                    kinds.add('unrecognized_key')
                    continue
                kind = ('null' if value is None else 'boolean' if type(value) is bool else
                        'string' if isinstance(value, str) else 'object' if isinstance(value, dict) else
                        'array' if isinstance(value, list) else 'number' if type(value) in (int, float) else 'other')
                kinds.add(key + ':' + kind)
            if isinstance(part.get('text'), str) and not part.get('thought'):
                output_bytes += len(part['text'].encode('utf-8', errors='replace'))
    return {'candidate_count': min(len(candidates), 10000) if isinstance(candidates, list) else None,
        'finish_reason': finish if isinstance(finish, str) and finish in _FINISH_REASONS else
            'missing' if finish is None else 'unrecognized',
        'part_count': min(len(parts), 10000) if isinstance(parts, list) else None,
        'part_types': sorted(kinds), 'output_bytes': min(output_bytes, 1024 * 1024)}


def provider_error_hints(error):
    """Classify a bounded API error using fixed labels; never retain its text."""
    if not isinstance(error, errors.APIError) or not isinstance(error.details, dict):
        return {'reason_flags': [], 'field_labels': []}
    detail = error.details.get('error', error.details)
    if not isinstance(detail, dict):
        return {'reason_flags': [], 'field_labels': []}
    texts = []
    def take(value):
        if isinstance(value, str):
            texts.append(value[:4096])
    take(detail.get('message'))
    nested = detail.get('details')
    if isinstance(nested, list):
        for entry in nested[:8]:
            if not isinstance(entry, dict):
                continue
            take(entry.get('reason'))
            violations = entry.get('fieldViolations')
            if isinstance(violations, list):
                for violation in violations[:16]:
                    if isinstance(violation, dict):
                        take(violation.get('field'))
                        take(violation.get('description'))
    source = '\n'.join(texts)[:16384].casefold()
    compact = re.sub('[^a-z0-9]', '', source)
    aliases = {
        'response_json_schema': ('responsejsonschema',), 'response_schema': ('responseschema',),
        'response_format': ('responseformat',), 'response_mime_type': ('responsemimetype',),
        'thinking_config': ('thinkingconfig', 'thinkinglevel', 'thinkingbudget'),
        'service_tier': ('servicetier',), 'max_output_tokens': ('maxoutputtokens',),
        'temperature': ('temperature',), 'top_p': ('topp',), 'contents': ('contents',),
        'model': ('model',),
    }
    labels = {label for label, variants in aliases.items() if any(value in compact for value in variants)}
    unsupported = any(value in source for value in ('not supported', 'unsupported', 'not allowed', 'not available'))
    invalid = unsupported or any(value in source for value in ('invalid', 'not valid', 'unknown', 'expected', 'must', 'requires'))
    checks = {
        'schema_complexity': 'schema' in source and any(value in source for value in ('complex', 'too many states', 'too large', 'deeply nested')),
        'schema_keyword_unsupported': 'schema' in source and unsupported,
        'schema_reference_invalid': 'schema' in source and invalid and any(value in source for value in ('$ref', 'reference')),
        'enum_invalid': 'enum' in source and invalid,
        'thinking_unsupported': 'thinking_config' in labels and invalid,
        'service_tier_unsupported': 'service_tier' in labels and invalid,
        'location_unsupported': any(value in source for value in ('location', 'region', 'country')) and unsupported,
        'permission_denied': 'permission denied' in source or 'permission_denied' in source or 'denied access' in source,
        'billing_required': 'billing' in source and any(value in source for value in ('enable', 'required', 'disabled', 'without')),
        'api_key_invalid': ('apikey' in compact or 'api key' in source) and (invalid or 'leaked' in source or 'expired' in source),
        'model_unsupported': 'model' in labels and unsupported,
        'parameter_out_of_range': any(value in source for value in ('out of range', 'must be between', 'must be greater', 'must be less', 'exceeds the maximum')),
        'unexpected_field': any(value in source for value in ('unknown name', 'unknown field', 'unrecognized field', 'unexpected field')),
    }
    return {'reason_flags': sorted(label for label, matched in checks.items() if matched),
        'field_labels': sorted(labels)}


def failure_diagnostics(error, code):
    """Provider exception messages and bodies can contain private request data."""
    status = (error.code if isinstance(error, errors.APIError) else
              error.response.status_code if isinstance(error, httpx.HTTPStatusError) else None)
    status = status if type(status) is int and 100 <= status <= 599 else None
    api_status = error.status if isinstance(error, errors.APIError) else None
    api_status = api_status if isinstance(api_status, str) and api_status in _API_STATUSES else None
    if isinstance(error, (TimeoutError, httpx.TimeoutException)):
        category = 'timeout'
    elif isinstance(error, (ConnectionError, httpx.TransportError)):
        category = 'transport'
    elif status == 429:
        category = 'rate_limited'
    elif status in (401, 403):
        category = 'authentication'
    elif status is not None and status >= 500:
        category = 'provider_unavailable'
    elif status is not None and status >= 400:
        category = 'provider_rejected'
    elif 'BUDGET' in code or code == 'GEMINI_USAGE_UNSUPPORTED':
        category = 'budget'
    elif code == 'HERMES_NOT_CONFIGURED':
        category = 'configuration'
    elif code == 'HERMES_LEASE_EXPIRED':
        category = 'lease'
    elif code in _SAFE_FAILURES:
        category = 'validation'
    else:
        category = 'unknown'
    return {'category': category, 'provider_http_status': status, 'provider_status': api_status,
        **provider_error_hints(error)}


def _plain_content(value):
    if isinstance(value, str):
        return value
    if (not isinstance(value, list) or not 1 <= len(value) <= 32
            or any(not isinstance(part, dict) or set(part) != {'type', 'text'}
                   or part['type'] != 'text' or not isinstance(part['text'], str) for part in value)):
        raise ValueError('HERMES_REQUEST_INVALID')
    return '\n'.join(part['text'] for part in value)


def validate_request(value):
    """Accept only the bounded text-only subset used by the pinned AIAgent."""
    if not isinstance(value, dict) or set(value) - _FIELDS:
        raise ValueError('HERMES_REQUEST_INVALID')
    if value.get('model') != budget.MODEL:
        raise ValueError('HERMES_MODEL_UNSUPPORTED')
    for key in ('max_tokens', 'max_completion_tokens'):
        if key in value and (type(value[key]) is not int or not 1 <= value[key] <= 4096):
            raise ValueError('HERMES_REQUEST_INVALID')
    if (value.get('stream', False) is not False or type(value.get('n', 1)) is not int
            or value.get('n', 1) != 1 or value.get('tools', []) != []
            or value.get('tool_choice', 'none') != 'none'):
        raise ValueError('HERMES_REQUEST_INVALID')
    if 'response_format' in value and value['response_format'] != {'type': 'json_object'}:
        raise ValueError('HERMES_REQUEST_INVALID')
    if value.get('reasoning_effort', 'low') not in ('low', 'minimal', 'none'):
        raise ValueError('HERMES_REQUEST_INVALID')
    for key, high in (('temperature', 2), ('top_p', 1)):
        number = value.get(key, .2 if key == 'temperature' else 1)
        if type(number) not in (int, float) or not math.isfinite(number) or not 0 <= number <= high:
            raise ValueError('HERMES_REQUEST_INVALID')
    stop = value.get('stop')
    if stop is not None:
        stop = [stop] if isinstance(stop, str) else stop
        if not isinstance(stop, list) or not 1 <= len(stop) <= 4 or any(
                not isinstance(item, str) or not 1 <= len(item) <= 100 for item in stop):
            raise ValueError('HERMES_REQUEST_INVALID')
    messages = value.get('messages')
    if not isinstance(messages, list) or not 1 <= len(messages) <= MAX_MESSAGES:
        raise ValueError('HERMES_REQUEST_INVALID')
    clean, total, has_user = [], 0, False
    for message in messages:
        if (not isinstance(message, dict) or set(message) != {'role', 'content'}
                or message['role'] not in ('system', 'developer', 'user', 'assistant')):
            raise ValueError('HERMES_REQUEST_INVALID')
        content = _plain_content(message['content'])
        if not content.strip() or '\x00' in content:
            raise ValueError('HERMES_REQUEST_INVALID')
        total += len(content.encode('utf-8'))
        if total > MAX_REQUEST_BYTES:
            raise ValueError('HERMES_REQUEST_TOO_LARGE')
        has_user |= message['role'] == 'user'
        clean.append({'role': message['role'], 'content': content})
    if not has_user:
        raise ValueError('HERMES_REQUEST_INVALID')
    return {'messages': clean, 'max_tokens': min(value.get('max_tokens', 4096),
            value.get('max_completion_tokens', 4096)), 'temperature': value.get('temperature', .2),
            'top_p': value.get('top_p', 1), 'stop': stop}


class GeminiHermesProvider:
    """One GenerateContent attempt with raw usage captured before output checks."""
    def __init__(self):
        key = os.environ.get('GEMINI_API_KEY', '')
        if not key or os.environ.get('GEMINI_MODEL', '') != budget.MODEL:
            raise ValueError('HERMES_NOT_CONFIGURED')
        self.last_usage = None
        self.client = genai.Client(api_key=key, http_options=types.HttpOptions(
            timeout=120000, retry_options=types.HttpRetryOptions(attempts=1)))

    def analyze(self, request):
        self.last_usage = None
        system = '\n\n'.join(message['content'] for message in request['messages']
                             if message['role'] in ('system', 'developer'))
        contents = [types.Content(role='model' if message['role'] == 'assistant' else 'user',
            parts=[types.Part.from_text(text=message['content'])]) for message in request['messages']
            if message['role'] in ('user', 'assistant')]
        response = self.client.models.generate_content(model=budget.MODEL, contents=contents,
            config=types.GenerateContentConfig(system_instruction=system or None,
                max_output_tokens=request['max_tokens'], candidate_count=1, service_tier='standard',
                temperature=request['temperature'], top_p=request['top_p'], stop_sequences=request['stop'],
                thinking_config=types.ThinkingConfig(thinking_level='low'),
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                # Hermes requested json_object. Its full Review contract is in
                # the prompt and is checked locally with match-local evidence;
                # do not add an unrequested provider schema-compilation mode.
                response_mime_type='application/json',
                should_return_http_response=True))
        body = response.sdk_http_response.body
        if not body or len(body) > 1024 * 1024:
            raise ValueError('HERMES_PROVIDER_RESPONSE_INVALID')
        try:
            raw = json.loads(body)
        except (TypeError, ValueError):
            raise ValueError('HERMES_PROVIDER_RESPONSE_INVALID') from None
        if not isinstance(raw, dict):
            raise ValueError('HERMES_PROVIDER_RESPONSE_INVALID')
        print(json.dumps({'event': 'hermes_provider_response', **response_diagnostics(raw)}), flush=True)
        usage = raw.get('usageMetadata')
        # Unknown fields remain visible to settlement; never let the SDK silently
        # discard a new billable counter or refund an uncertain attempt.
        self.last_usage = {'unrecognized_generate_content_usage': usage}
        normalized = generate_usage(usage)
        if any(item.get('modality') != 'text' and item.get('tokens') for key in (
                'input_tokens_by_modality', 'output_tokens_by_modality', 'cached_tokens_by_modality')
                for item in normalized.get(key, [])):
            raise ValueError('GEMINI_USAGE_UNSUPPORTED')
        self.last_usage = normalized
        candidates = raw.get('candidates')
        if (not isinstance(candidates, list) or len(candidates) != 1 or not isinstance(candidates[0], dict)
                or candidates[0].get('finishReason') != 'STOP'):
            raise ValueError('HERMES_PROVIDER_RESPONSE_INVALID')
        content = candidates[0].get('content')
        parts = content.get('parts') if isinstance(content, dict) else None
        if not isinstance(parts, list) or any(not isinstance(part, dict)
                or set(part) - {'text', 'thought', 'thoughtSignature'} for part in parts):
            raise ValueError('HERMES_PROVIDER_RESPONSE_INVALID')
        output = ''.join(part['text'] for part in parts if isinstance(part.get('text'), str) and not part.get('thought'))
        if not output or len(output.encode('utf-8')) > MAX_RESPONSE_BYTES:
            raise ValueError('HERMES_PROVIDER_RESPONSE_INVALID')
        return output

    def close(self):
        self.client.close()


def complete(token, request, provider_factory=GeminiHermesProvider):
    """Reserve durably before dispatch; settle even on invalid output or failure."""
    provider = None
    try:
        with database() as connection:
            task = authorize_call(connection, token)
            # Configuration can fail without recording a provider attempt.
            provider = provider_factory()
            call_id = budget.reserve_hermes(connection, task, budget.MODEL)
        provider.last_usage = None
        try:
            output = provider.analyze(request)
        finally:
            budget.settle(call_id, provider.last_usage)
        usage = provider.last_usage
        return {'id': f'chatcmpl-narma-{call_id}', 'object': 'chat.completion', 'created': int(time.time()),
            'model': budget.MODEL, 'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': output},
                'finish_reason': 'stop'}], 'usage': {'prompt_tokens': usage['total_input_tokens'],
                    'completion_tokens': usage['total_output_tokens'] + usage['total_thought_tokens'],
                    'total_tokens': usage['total_tokens']}}
    finally:
        if provider is not None:
            try:
                provider.close()
            except Exception:
                pass


def _credential(request):
    authorization = request.headers.get('authorization', '')
    if not authorization.startswith('Bearer ') or not TOKEN.fullmatch(authorization[7:]):
        raise ValueError('HERMES_TOKEN_INVALID')
    return authorization[7:]


def _failure(error):
    code = str(error) if isinstance(error, ValueError) and str(error) in _SAFE_FAILURES else 'HERMES_PROVIDER_UNAVAILABLE'
    if code == 'HERMES_TOKEN_INVALID':
        status = 401
    elif code in ('HERMES_LEASE_EXPIRED', 'HERMES_SOURCE_CHANGED'):
        status = 409
    elif code in ('HERMES_REQUEST_INVALID', 'HERMES_MODEL_UNSUPPORTED'):
        status = 400
    elif code == 'HERMES_REQUEST_TOO_LARGE':
        status = 413
    elif code == 'HERMES_REQUEST_BUDGET_EXCEEDED':
        status = 403  # Non-retryable: this task has consumed its one attempt.
    elif 'BUDGET' in code:
        status = 429
    elif code == 'HERMES_NOT_CONFIGURED':
        status = 503
    else:
        status = 502
    # Neither provider bodies, prompts, task credentials nor exception strings are
    # returned or logged. Runtime failures remain an optional-coaching failure.
    print(json.dumps({'event': 'hermes_broker_rejected', 'code': code, **failure_diagnostics(error, code)}), flush=True)
    return JSONResponse({'error': {'message': code, 'type': 'invalid_request_error' if status < 500 else 'server_error',
        'param': None, 'code': code}}, status_code=status, headers={'Cache-Control': 'no-store'})


async def _scheduler():
    from .hermes_tasks import process_once
    while True:
        try:
            await asyncio.to_thread(process_once)
        except Exception:
            print(json.dumps({'event': 'hermes_scheduler_unavailable'}), flush=True)
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app):
    scheduler = asyncio.create_task(_scheduler()) if os.environ.get('HERMES_RUNTIME_ENABLED') == '1' else None
    try:
        yield
    finally:
        if scheduler:
            scheduler.cancel()
            try:
                await scheduler
            except asyncio.CancelledError:
                pass


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.get('/healthz')
def health():
    return {'ok': True, 'service': 'hermes-broker'}


@app.get('/v1/models')
async def models(request: Request):
    try:
        token = _credential(request)
        def read_model():
            with database() as connection:
                authorize_call(connection, token)
            return {'object': 'list', 'data': [{'id': budget.MODEL, 'object': 'model', 'created': 0,
                'owned_by': 'narma', 'context_length': 131072, 'max_output_tokens': 4096}]}
        return JSONResponse(await run_in_threadpool(read_model), headers={'Cache-Control': 'no-store'})
    except Exception as error:
        return _failure(error)


@app.post('/v1/chat/completions')
async def chat_completions(request: Request):
    try:
        token = _credential(request)
        size = request.headers.get('content-length')
        if size is not None and (not size.isdecimal() or int(size) > MAX_REQUEST_BYTES):
            raise ValueError('HERMES_REQUEST_TOO_LARGE')
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_REQUEST_BYTES:
                raise ValueError('HERMES_REQUEST_TOO_LARGE')
        try:
            value = json.loads(body)
        except (TypeError, ValueError, UnicodeError):
            raise ValueError('HERMES_REQUEST_INVALID') from None
        parsed = validate_request(value)
        return JSONResponse(await run_in_threadpool(complete, token, parsed), headers={'Cache-Control': 'no-store'})
    except Exception as error:
        return _failure(error)
