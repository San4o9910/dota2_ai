"""Cache boundaries and reservation fencing; no database or provider requests."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib

import pytest

from narma_video import openai_provider as provider


SCHEMA = {'type': 'object', 'properties': {'summary': {'type': 'string'}},
          'required': ['summary'], 'additionalProperties': False}
INSTRUCTIONS = 'Coach only the selected player using the supplied evidence.'


def test_only_reusable_instructions_are_inside_cache_boundary():
    alice = provider.request_payload(INSTRUCTIONS, 'private Alice evidence', SCHEMA)
    bob = provider.request_payload(INSTRUCTIONS, 'private Bob evidence', SCHEMA)

    assert alice['prompt_cache_options'] == {'mode': 'explicit'}
    assert alice['input'][0] == bob['input'][0]
    assert alice['input'][0]['role'] == 'developer'
    assert alice['input'][0]['content'] == [{'type': 'input_text', 'text': INSTRUCTIONS,
        'prompt_cache_breakpoint': {'mode': 'explicit'}}]
    for payload, evidence, other in (
            (alice, 'private Alice evidence', 'private Bob evidence'),
            (bob, 'private Bob evidence', 'private Alice evidence')):
        assert len(payload['input']) == 2
        assert payload['input'][1] == {'role': 'user', 'content': [
            {'type': 'input_text', 'text': evidence}]}
        assert provider._json(payload).count('prompt_cache_breakpoint') == 1
        assert other not in provider._json(payload)
        assert 'instructions' not in payload
        assert 'previous_response_id' not in payload and 'conversation' not in payload
        assert 'prompt_cache_key' not in payload
        assert payload['store'] is False and payload['stream'] is False
        assert payload['tools'] == [] and payload['tool_choice'] == 'none'


def test_digest_binds_cache_policy_evidence_instructions_schema_and_output_cap():
    original = deepcopy(SCHEMA)
    payload = provider.request_payload(INSTRUCTIONS, 'Evidence', SCHEMA)
    digest = provider.request_digest(INSTRUCTIONS, 'Evidence', SCHEMA)
    assert digest == hashlib.sha256(provider._json(payload).encode()).hexdigest()
    assert digest == provider.request_digest(INSTRUCTIONS, 'Evidence', deepcopy(SCHEMA))
    assert digest != provider.request_digest(INSTRUCTIONS, 'Different evidence', SCHEMA)
    assert digest != provider.request_digest('Different instructions', 'Evidence', SCHEMA)
    changed_schema = {**SCHEMA, 'description': 'A revised coaching contract'}
    assert digest != provider.request_digest(INSTRUCTIONS, 'Evidence', changed_schema)
    assert digest != provider.request_digest(INSTRUCTIONS, 'Evidence', SCHEMA,
                                             max_output_tokens=4096)
    implicit = deepcopy(payload)
    implicit['prompt_cache_options'] = {'mode': 'implicit'}
    assert digest != hashlib.sha256(provider._json(implicit).encode()).hexdigest()
    assert SCHEMA == original


def test_cache_metadata_counts_toward_request_size_and_reservation_bound(monkeypatch):
    payload = provider.request_payload(INSTRUCTIONS, 'Evidence', SCHEMA)
    size = len(provider._json(payload).encode())
    assert provider.input_token_bound(payload) >= size
    monkeypatch.setattr(provider, 'MAX_INPUT_BYTES', size - 1)
    with pytest.raises(provider.ProviderError, match='OPENAI_REQUEST_TOO_LARGE'):
        provider.request_payload(INSTRUCTIONS, 'Evidence', SCHEMA)


def test_pre_cache_reservation_cannot_dispatch_changed_request(monkeypatch):
    # An older worker reserved a different serialized request. A rolling update
    # must fail closed instead of silently paying for an unreserved payload.
    legacy = provider.request_payload(INSTRUCTIONS, 'Evidence', SCHEMA)
    del legacy['prompt_cache_options']
    del legacy['input'][0]
    legacy['instructions'] = INSTRUCTIONS
    row = {'state': 'reserved',
           'request_sha256': hashlib.sha256(provider._json(legacy).encode()).hexdigest()}

    class Connection:
        def execute(self, query, parameters):
            assert (query.startswith('SELECT pg_advisory_xact_lock')
                    or query.startswith('SELECT * FROM openai_api_calls'))
            return self

        def fetchone(self):
            return row

    @contextmanager
    def database():
        yield Connection()

    def unexpected(*args, **kwargs):
        pytest.fail('A mismatched reservation must stop before dispatch or settlement')

    monkeypatch.setattr(provider, 'configured', lambda: True)
    monkeypatch.setattr(provider, 'database', database)
    monkeypatch.setattr(provider, '_source', unexpected)
    monkeypatch.setattr(provider, '_generate', unexpected)
    monkeypatch.setattr(provider.budget, 'settle', unexpected)
    with pytest.raises(provider.ProviderError, match='OPENAI_CALL_CONFLICT'):
        provider.perform_reserved('old-call', 'owner', INSTRUCTIONS, 'Evidence', SCHEMA)
