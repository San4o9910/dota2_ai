"""Dispatch receipts locate input loss without exposing secrets or changing policy."""
from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import deployment_inputs as diagnostic


DEFAULT_ENV = {
    'GITHUB_EVENT_NAME': 'workflow_dispatch',
    'NARMA_BUILD_STATS_SOURCE': 'authored',
    'PREPARE_CHATGPT_AUTH': 'false',
    'ACTIVATE_HERMES': 'false',
    'PREPARE_OPENAI_API': 'false',
    'OPENAI_LIMIT_MICROUSD': '',
    'OPENAI_EXPIRES_AT': '',
}
SELECTED_INPUTS = {
    'build_stats_source': 'authored',
    'prepare_chatgpt_auth': False,
    'activate_hermes': False,
    'prepare_openai_api': True,
    'openai_limit_microusd': '5000000',
    'openai_expires_at': '2026-09-19T23:59:59Z',
}
SELECTED_ENV = {
    **DEFAULT_ENV,
    'PREPARE_OPENAI_API': 'true',
    'OPENAI_LIMIT_MICROUSD': '5000000',
    'OPENAI_EXPIRES_AT': '2026-09-19T23:59:59Z',
}


class DeploymentInputTest(unittest.TestCase):
    def run_receipt(self, event, environment):
        with tempfile.TemporaryDirectory() as directory:
            path, summary = Path(directory) / 'event.json', Path(directory) / 'summary.md'
            path.write_text(json.dumps(event), encoding='utf-8')
            env = {**environment, 'GITHUB_EVENT_PATH': str(path), 'GITHUB_STEP_SUMMARY': str(summary)}
            output = StringIO()
            before = path.read_bytes()
            with patch.dict(os.environ, env, clear=True), redirect_stdout(output):
                status = diagnostic.main()
                self.assertEqual(dict(os.environ), env)
            self.assertEqual(path.read_bytes(), before)
            self.assertLessEqual({file.name for file in Path(directory).iterdir()}, {'event.json', 'summary.md'})
            return status, output.getvalue(), summary.read_text() if summary.exists() else ''

    def test_selected_allowance_matches_without_activation_or_environment_mutation(self):
        status, output, summary = self.run_receipt({'inputs': SELECTED_INPUTS}, SELECTED_ENV)
        self.assertEqual(status, 0)
        self.assertIn('5000000', summary)
        self.assertIn('2026-09-19T23:59:59Z', summary)
        self.assertIn('activation is not yet confirmed', output)
        self.assertNotIn('::error::', output)

    def test_lost_toggle_and_money_are_reported_without_fallback(self):
        status, output, summary = self.run_receipt({'inputs': SELECTED_INPUTS}, DEFAULT_ENV)
        self.assertEqual(status, 1)
        self.assertIn('::error::Workflow input contexts differ', output)
        self.assertIn('| prepare_openai_api | true | true | false | false |', summary)
        self.assertIn('| openai_limit_microusd | true | 5000000 | [empty] | false |', summary)

    def test_missing_inputs_and_explicit_false_have_same_values_but_distinct_presence(self):
        for inputs, present in (({}, False), ({'prepare_openai_api': False}, True),
                                ({'prepare_openai_api': 'false'}, True)):
            with self.subTest(inputs=inputs):
                rows, mismatches, preserve = diagnostic.inspect_inputs({'inputs': inputs}, DEFAULT_ENV)
                self.assertEqual(mismatches, [])
                self.assertTrue(preserve)
                self.assertEqual(rows['prepare_openai_api']['present'], present)
                self.assertEqual(rows['prepare_openai_api']['event'], 'false')

    def test_runner_event_boolean_strings_are_normalized_without_truthiness(self):
        inputs = {**SELECTED_INPUTS, 'prepare_chatgpt_auth': 'false',
                  'activate_hermes': 'false', 'prepare_openai_api': 'true'}
        self.assertEqual(self.run_receipt({'inputs': inputs}, SELECTED_ENV)[0], 0)

    def test_preserve_sentinel_maps_only_to_empty_expiry(self):
        event = {'inputs': {'openai_expires_at': 'Сохранить текущий срок'}}
        status, output, summary = self.run_receipt(event, DEFAULT_ENV)
        self.assertEqual(status, 0)
        self.assertIn('GitHub передал режим сохранения провайдера', output)
        self.assertIn('| openai_expires_at | true | [empty] | [empty] | true |', summary)
        self.assertNotIn('5000000', output + summary)

    def test_push_ignores_event_inputs_and_keeps_activation_disabled(self):
        env = {**DEFAULT_ENV, 'GITHUB_EVENT_NAME': 'push'}
        status, output, summary = self.run_receipt({'inputs': SELECTED_INPUTS}, env)
        self.assertEqual(status, 0)
        self.assertNotIn('5000000', output + summary)
        self.assertIn('| prepare_openai_api | false | false | false | true |', summary)
        self.assertEqual(self.run_receipt({'inputs': SELECTED_INPUTS},
                                         {**env, 'PREPARE_OPENAI_API': 'true'})[0], 1)

    def test_unknown_fields_and_other_environment_secrets_are_never_logged(self):
        secret = 'sk-not-a-real-key-do-not-display'
        event = {'inputs': {**SELECTED_INPUTS, 'OPENAI_API_KEY': secret},
                 'token': secret, 'unknown-secret-name': secret}
        status, output, summary = self.run_receipt(event, {**SELECTED_ENV, 'OPENAI_API_KEY': secret})
        self.assertEqual(status, 0)
        for forbidden in (secret, 'OPENAI_API_KEY', 'unknown-secret-name'):
            self.assertNotIn(forbidden, output + summary)

    def test_malicious_known_input_is_redacted_from_both_contexts(self):
        malicious = 'private-value\n::error::injected | [click](https://example.invalid)'
        for name, env_name in (('build_stats_source', 'NARMA_BUILD_STATS_SOURCE'),
                               ('openai_limit_microusd', 'OPENAI_LIMIT_MICROUSD'),
                               ('openai_expires_at', 'OPENAI_EXPIRES_AT'),
                               ('prepare_openai_api', 'PREPARE_OPENAI_API')):
            with self.subTest(name=name):
                _, output, summary = self.run_receipt({'inputs': {name: malicious}},
                                                       {**DEFAULT_ENV, env_name: malicious})
                self.assertNotIn('private-value', output + summary)
                self.assertNotIn('injected', output + summary)
                self.assertNotIn('example.invalid', output + summary)
                self.assertIn('[invalid]', output + summary)

    def test_invalid_boolean_types_cannot_match_or_activate(self):
        for value in ('TRUE', 'yes', 1, 0, None, [], {}):
            with self.subTest(value=value):
                self.assertEqual(self.run_receipt({'inputs': {'prepare_openai_api': value}}, DEFAULT_ENV)[0], 1)

    def test_missing_resolved_environment_is_a_mismatch(self):
        env = dict(DEFAULT_ENV)
        del env['OPENAI_LIMIT_MICROUSD']
        self.assertEqual(self.run_receipt({'inputs': {}}, env)[0], 1)

    def test_malformed_event_shape_has_no_payload_in_error(self):
        for event in (None, [], {'inputs': None}, {'inputs': 'private-value'}):
            with self.subTest(event=event):
                status, output, summary = self.run_receipt(event, DEFAULT_ENV)
                self.assertEqual(status, 1)
                self.assertNotIn('private-value', output + summary)
                self.assertIn('Cannot compare workflow input contexts', output)

    def test_only_bounded_amounts_and_full_timestamp_shapes_can_be_displayed(self):
        for value in ('123456789', '-5', '5.00', '5e6', '５００００００'):
            self.assertEqual(diagnostic.safe_value('openai_limit_microusd', value), '[invalid]')
        for value in ('2026-09-19T23:59:59Z\n', '2026-09-19', '2026-09-19T23:59:59Z extra'):
            self.assertEqual(diagnostic.safe_value('openai_expires_at', value), '[invalid]')


if __name__ == '__main__':
    unittest.main()
