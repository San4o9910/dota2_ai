#!/usr/bin/env python3
"""Prepare or run a local, human-reviewed replay coach evaluation.

Dry run (default) makes no HTTP requests. --run sends one request per case to an
explicitly selected local model. Forward a private inference server with SSH to
localhost; public endpoints, provider credentials, redirects, proxies, retries,
and agent tools are intentionally unsupported. Nothing is wired to production.

The transport is OpenAI-compatible JSON Schema chat completions (for example a
local vLLM server). It does not call the OpenAI service or use a ChatGPT account.
A server lacking JSON Schema support fails explicitly; there is no fallback.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from urllib.parse import urlsplit, urlunsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'services' / 'video'))
from narma_video.replay_coach import (  # noqa: E402
    ReplayCoaching, SYSTEM, prepare_evidence, validate_coaching,
)

MAX_CORPUS_BYTES = 4 * 1024 * 1024
MAX_REQUEST_BYTES = 600 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_CASES = 100
DEFAULT_ENDPOINT = 'http://127.0.0.1:8000/v1/chat/completions'
ID = re.compile(r'^[A-Za-z0-9_.:-]{1,128}$')
MODEL = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_./:@+-]{0,199}$')
CLASSIFICATIONS = ('synthetic_not_real_match_evidence', 'private_real_replay_evidence')


def _reject_constant(_value):
    raise ValueError('NON_FINITE_JSON')


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('DUPLICATE_JSON_KEY')
        result[key] = value
    return result


def decode_json(value):
    return json.loads(value, parse_constant=_reject_constant, object_pairs_hook=_unique_object)


def encode_json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')


def digest(value):
    return hashlib.sha256(value).hexdigest()


def local_endpoint(value):
    """Allow only literal loopback, with localhost rewritten to avoid DNS."""
    if not isinstance(value, str) or any(char.isspace() for char in value):
        raise ValueError('LOCAL_ENDPOINT_REQUIRED')
    try:
        parsed = urlsplit(value)
        port = parsed.port
        if (parsed.scheme not in ('http', 'https') or parsed.hostname not in
                ('localhost', '127.0.0.1', '::1') or parsed.username is not None or
                parsed.password is not None or parsed.query or parsed.fragment or
                parsed.path != '/v1/chat/completions' or '\\' in value or '%' in value):
            raise ValueError('LOCAL_ENDPOINT_REQUIRED')
        if port is not None and not 1 <= port <= 65535:
            raise ValueError('LOCAL_ENDPOINT_REQUIRED')
        hostname = '[::1]' if parsed.hostname == '::1' else '127.0.0.1'
        authority = hostname + (f':{port}' if port is not None else '')
        return urlunsplit((parsed.scheme, authority, parsed.path, '', ''))
    except (ValueError, TypeError):
        raise ValueError('LOCAL_ENDPOINT_REQUIRED') from None


def model_config(model, *, max_tokens=4096, temperature=0.0, timeout=180.0, model_revision=None):
    if not isinstance(model, str) or not MODEL.fullmatch(model):
        raise ValueError('EXPLICIT_MODEL_REQUIRED')
    if type(max_tokens) is not int or not 128 <= max_tokens <= 8192:
        raise ValueError('MAX_TOKENS_OUT_OF_RANGE')
    if (type(temperature) not in (int, float) or not math.isfinite(temperature)
            or not 0 <= temperature <= 2):
        raise ValueError('TEMPERATURE_OUT_OF_RANGE')
    if (type(timeout) not in (int, float) or not math.isfinite(timeout)
            or not 1 <= timeout <= 300):
        raise ValueError('TIMEOUT_OUT_OF_RANGE')
    if model_revision is not None and (not isinstance(model_revision, str) or not MODEL.fullmatch(model_revision)):
        raise ValueError('MODEL_REVISION_INVALID')
    return {'model': model, 'max_tokens': max_tokens, 'temperature': temperature,
            'timeout_seconds': timeout, 'attempts_per_case': 1,
            'model_revision': model_revision, 'revision_source': 'operator_declared_unverified'}


def load_corpus(path):
    with Path(path).open('rb') as handle:
        raw = handle.read(MAX_CORPUS_BYTES + 1)
    if len(raw) > MAX_CORPUS_BYTES:
        raise ValueError('CORPUS_TOO_LARGE')
    corpus = decode_json(raw)
    if (not isinstance(corpus, dict) or corpus.get('classification') not in CLASSIFICATIONS
            or not isinstance(corpus.get('cases'), list)
            or not 1 <= len(corpus['cases']) <= MAX_CASES):
        raise ValueError('CLASSIFIED_CORPUS_REQUIRED')
    return corpus, digest(raw)


def prepare_case(case, config):
    if not isinstance(case, dict) or not isinstance(case.get('id'), str) or not ID.fullmatch(case['id']):
        raise ValueError('INVALID_CASE_ID')
    position = case.get('position')
    if position is not None and (type(position) is not int or position not in range(1, 6)):
        raise ValueError('INVALID_CASE_POSITION')
    if not isinstance(case.get('expected'), dict):
        raise ValueError('CASE_REVIEW_NOTES_REQUIRED')
    # The production projection is the sole prompt boundary. Private grading
    # notes, arbitrary top-level case fields, and old model outputs never enter it.
    encoded, evidence_ids = prepare_evidence(
        case.get('report'), position=position, mmr=case.get('mmr'),
        training_level=case.get('training_level'),
    )
    request = {
        'model': config['model'], 'temperature': config['temperature'],
        'max_tokens': config['max_tokens'], 'stream': False, 'n': 1,
        'messages': [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': encoded}],
        'response_format': {'type': 'json_schema', 'json_schema': {
            'name': 'ReplayCoaching', 'strict': True, 'schema': ReplayCoaching.model_json_schema(),
        }},
        'tools': [], 'tool_choice': 'none',
    }
    request_bytes = encode_json(request)
    if len(request_bytes) > MAX_REQUEST_BYTES:
        raise ValueError('REQUEST_TOO_LARGE')
    return {'id': case['id'], 'request': request, 'request_sha256': digest(request_bytes),
            'evidence_sha256': digest(encoded.encode('utf-8')), 'evidence_ids': sorted(evidence_ids)}


def _read_response(response, deadline):
    chunks, total = [], 0
    for chunk in response.iter_bytes():
        total += len(chunk)
        if total > MAX_RESPONSE_BYTES:
            raise ValueError('RESPONSE_TOO_LARGE')
        if time.monotonic() > deadline:
            raise ValueError('RESPONSE_DEADLINE_EXCEEDED')
        chunks.append(chunk)
    return b''.join(chunks)


def infer_one(prepared, *, endpoint, config, transport=None):
    """One bounded local request; injectable transport is for offline tests."""
    endpoint = local_endpoint(endpoint)
    started = time.monotonic()
    record = {'id': prepared['id'], 'request_sha256': prepared['request_sha256'],
              'contract_status': 'failed', 'quality_status': 'human_review_required',
              'answer': None, 'error': None}
    try:
        with httpx.Client(
            transport=transport if transport is not None else httpx.HTTPTransport(retries=0, trust_env=False),
            trust_env=False, follow_redirects=False,
            timeout=httpx.Timeout(config['timeout_seconds'], connect=min(10, config['timeout_seconds'])),
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=0),
        ) as client:
            with client.stream('POST', endpoint, content=encode_json(prepared['request']),
                               headers={'Content-Type': 'application/json', 'Accept': 'application/json'}) as response:
                record['http_status'] = response.status_code
                if response.status_code != 200:
                    raise ValueError('HTTP_RESPONSE_REJECTED')
                declared_size = response.headers.get('content-length')
                if declared_size is not None:
                    try:
                        size = int(declared_size)
                    except ValueError:
                        raise ValueError('RESPONSE_LENGTH_INVALID') from None
                    if size < 0 or size > MAX_RESPONSE_BYTES:
                        raise ValueError('RESPONSE_TOO_LARGE')
                body = decode_json(_read_response(response, started + config['timeout_seconds']))
        choices = body.get('choices') if isinstance(body, dict) else None
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise ValueError('COMPLETION_ENVELOPE_INVALID')
        choice = choices[0]
        message = choice.get('message')
        if (choice.get('finish_reason') != 'stop' or not isinstance(message, dict)
                or message.get('tool_calls') or message.get('function_call') or message.get('refusal')
                or not isinstance(message.get('content'), str)):
            raise ValueError('COMPLETION_NOT_FINAL_TEXT')
        # Retain a bounded answer for review even when its factual contract fails.
        record['answer_text'] = message['content']
        answer = decode_json(message['content'])
        record['answer'] = answer
        validated = validate_coaching(answer, set(prepared['evidence_ids']))
        record['answer'] = validated.model_dump()
        if len(validated.next_game) != 1:
            raise ValueError('NEXT_GAME_FOCUS_COUNT_INVALID')
        record['contract_status'] = 'passed'
        returned_model = body.get('model')
        if isinstance(returned_model, str) and MODEL.fullmatch(returned_model):
            record['reported_model'] = returned_model
        usage = body.get('usage')
        if isinstance(usage, dict):
            record['usage'] = {key: value for key, value in usage.items()
                               if key in ('prompt_tokens', 'completion_tokens', 'total_tokens')
                               and type(value) is int and 0 <= value <= 10000000}
    except httpx.TimeoutException:
        record['error'] = 'LOCAL_INFERENCE_TIMEOUT'
    except httpx.TransportError:
        record['error'] = 'LOCAL_INFERENCE_TRANSPORT_ERROR'
    except (ValueError, TypeError, RecursionError) as error:
        code = str(error)
        # Never store raw server errors, exception bodies, or credentials.
        record['error'] = code if re.fullmatch(r'[A-Z_]{3,100}', code) else 'RESPONSE_JSON_INVALID'
    record['elapsed_seconds'] = round(time.monotonic() - started, 3)
    return record


def evaluate(corpus, *, corpus_sha256, model, endpoint=DEFAULT_ENDPOINT, run=False,
             selected_ids=None, max_tokens=4096, temperature=0.0, timeout=180.0,
             model_revision=None, transport=None):
    endpoint = local_endpoint(endpoint)
    config = model_config(model, max_tokens=max_tokens, temperature=temperature, timeout=timeout,
                          model_revision=model_revision)
    cases = corpus.get('cases') if isinstance(corpus, dict) else None
    if (not isinstance(cases, list) or not 1 <= len(cases) <= MAX_CASES or
            corpus.get('classification') not in CLASSIFICATIONS):
        raise ValueError('CLASSIFIED_CORPUS_REQUIRED')
    prepared = [prepare_case(case, config) for case in cases]
    ids = [case['id'] for case in prepared]
    if len(set(ids)) != len(ids):
        raise ValueError('DUPLICATE_CASE_ID')
    selected = set(selected_ids or ids)
    if not selected or selected - set(ids):
        raise ValueError('UNKNOWN_SELECTED_CASE')
    prepared = [case for case in prepared if case['id'] in selected]
    review = [{key: case.get(key) for key in ('id', 'position', 'mmr', 'training_level', 'expected')}
              for case in cases if case['id'] in selected]
    return {
        'version': 'narma.open-coach-evaluation.v1', 'mode': 'local_run' if run else 'dry_run',
        'corpus_classification': corpus['classification'],
        'corpus_sha256': corpus_sha256, 'model_config': config, 'endpoint': endpoint,
        'system_sha256': digest(SYSTEM.encode('utf-8')),
        'schema_sha256': digest(encode_json(ReplayCoaching.model_json_schema())),
        'quality_status': 'not_evaluated',
        'quality_notice': 'Schema and evidence-ID checks do not establish coaching quality. '
                          'Human comparison is required before any client rollout.',
        'human_review_manifest': {'cases': review, 'scores': None,
            'review_dimensions': ['factual_grounding', 'hero_and_position_fit',
                                  'conditional_reasoning', 'practical_exercise', 'clear_russian'],
            'blocking_failures': ['fabricated_match_fact', 'unsupported_causality',
                                  'core_farm_norm_for_support', 'prompt_injection_followed'],
            'reviewer': None, 'baseline_model': None, 'rollout_approved': False},
        'requests': prepared,
        'results': [infer_one(case, endpoint=endpoint, config=config, transport=transport)
                    for case in prepared] if run else [],
        'requests_attempted': len(prepared) if run else 0,
    }


def save_artifact(path, artifact, *, initial=False):
    """Restrict private files to their owner and replace checkpoints atomically."""
    path = Path(path)
    # Serialize before touching a valid checkpoint.
    raw = json.dumps(artifact, ensure_ascii=False, allow_nan=False, indent=2).encode('utf-8')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f'.{path.name}.', delete=False) as handle:
            temporary = Path(handle.name)
            os.chmod(temporary, 0o600)
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        if initial:
            # Hard-link creation is atomic and refuses an existing target,
            # unlike replace; both paths belong to the same local filesystem.
            os.link(temporary, path)
        else:
            os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', type=Path, default=ROOT / 'evals' / 'open_coach' / 'cases.json')
    parser.add_argument('--model', required=True, help='Explicit local server model identifier.')
    parser.add_argument('--model-revision', help='Operator-declared weight revision/hash; recorded without network verification.')
    parser.add_argument('--endpoint', default=DEFAULT_ENDPOINT, help='Loopback chat completions URL only.')
    parser.add_argument('--output', type=Path, help='New local JSON file; default evals/open_coach/runs/<timestamp>.json; refuses existing files.')
    parser.add_argument('--case', action='append', dest='selected_ids', help='Evaluate only this case ID; repeatable.')
    parser.add_argument('--max-tokens', type=int, default=4096)
    parser.add_argument('--temperature', type=float, default=0.0)
    parser.add_argument('--timeout', type=float, default=180.0)
    parser.add_argument('--run', action='store_true', help='Explicitly send requests to local inference; default is offline dry run.')
    args = parser.parse_args(argv)
    try:
        if args.output is None:
            args.output = ROOT / 'evals' / 'open_coach' / 'runs' / f'{time.time_ns()}.json'
            args.output.parent.mkdir(parents=True, exist_ok=True)
        corpus, checksum = load_corpus(args.cases)
        # Validate and reserve output before inference; don't spend compute only
        # to discover that a prior experiment would have been overwritten.
        artifact = evaluate(corpus, corpus_sha256=checksum, model=args.model, endpoint=args.endpoint,
                            selected_ids=args.selected_ids, max_tokens=args.max_tokens,
                            temperature=args.temperature, timeout=args.timeout, model_revision=args.model_revision)
        save_artifact(args.output, artifact, initial=True)
        if args.run:
            artifact['mode'] = 'local_run'
            for prepared in artifact['requests']:
                artifact['results'].append(infer_one(prepared, endpoint=artifact['endpoint'], config=artifact['model_config']))
                artifact['requests_attempted'] += 1
                # A checkpoint after each local request survives a later failed
                # model call or process interruption. No corpus uploads occur.
                save_artifact(args.output, artifact)
        print(json.dumps({'mode': artifact['mode'], 'cases': len(artifact['requests']),
                          'requests_attempted': artifact['requests_attempted'],
                          'quality_status': artifact['quality_status'], 'output': str(args.output)}))
        return 1 if any(row['contract_status'] != 'passed' for row in artifact['results']) else 0
    except (OSError, ValueError, TypeError, RecursionError) as error:
        code = str(error)
        print(code if re.fullmatch(r'[A-Z_]{3,100}', code) else 'EVALUATION_INPUT_OR_OUTPUT_INVALID', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
