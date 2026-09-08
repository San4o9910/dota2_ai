"""OAuth release must preserve credentials and make no generation probe."""
import base64
from contextlib import ExitStack
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chatgpt_secrets as secrets
import prepare_chatgpt_auth as preparation
import pilot

SHA = 'a' * 40
KEY = base64.urlsafe_b64encode(b'x' * 32).decode()


class ChatGPTSecretTest(unittest.TestCase):
    def test_first_key_is_generated_once_and_subsequent_release_reuses_it(self):
        values = {'DATABASE_URL': 'existing-db-identity'}
        with patch.object(secrets, 'existing_connections', return_value=0) as existing, \
                patch.object(secrets, 'write_private') as checkpoint:
            secrets.prepare_settings(values, SHA)
            first = values['NARMA_CHATGPT_ENCRYPTION_KEY']
            secrets.validate_key(first)
            secrets.prepare_settings(values, 'b' * 40)
        self.assertEqual(values['NARMA_CHATGPT_ENCRYPTION_KEY'], first)
        self.assertEqual(values['DATABASE_URL'], 'existing-db-identity')
        self.assertEqual(values['HERMES_PROVIDER'], 'chatgpt_subscription')
        existing.assert_called_once()
        self.assertNotIn(first, json.dumps(checkpoint.call_args_list, default=str))

    def test_existing_encrypted_connection_with_missing_key_cannot_be_rekeyed(self):
        values = {'DATABASE_URL': 'existing-db-identity'}
        with patch.object(secrets, 'existing_connections', return_value=1), \
                patch.object(secrets, 'write_private') as checkpoint, \
                patch.object(secrets.secrets, 'token_bytes') as random:
            with self.assertRaisesRegex(RuntimeError, 'chatgpt_existing_encryption_key_required'):
                secrets.prepare_settings(values, SHA)
        self.assertEqual(values, {'DATABASE_URL': 'existing-db-identity'})
        checkpoint.assert_not_called(); random.assert_not_called()

    def test_invalid_existing_key_is_not_silently_replaced(self):
        with patch.object(secrets, 'existing_connections') as existing, \
                patch.object(secrets, 'write_private') as checkpoint:
            with self.assertRaisesRegex(RuntimeError, 'chatgpt_encryption_key_invalid'):
                secrets.prepare_settings({'NARMA_CHATGPT_ENCRYPTION_KEY': 'invalid'}, SHA)
        existing.assert_not_called(); checkpoint.assert_not_called()

    def test_rollback_preserves_generated_key_and_unrelated_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'video.env'
            saved = Path(directory) / 'settings.json'
            path.write_text('NARMA_CHATGPT_ENCRYPTION_KEY=' + KEY + '\nGEMINI_API_KEY=unchanged\n'
                'HERMES_PROVIDER=chatgpt_subscription\nREPLAY_COACH_PROVIDER=chatgpt_subscription\nHERMES_RUNTIME_ENABLED=1\n')
            saved.write_text(json.dumps({'release': SHA, 'settings': {
                'HERMES_PROVIDER': 'gemini', 'REPLAY_COACH_PROVIDER': None, 'HERMES_RUNTIME_ENABLED': '0'}}))
            with patch.object(secrets, 'settings_path', return_value=saved):
                self.assertTrue(secrets.restore_settings(SHA, path))
            result = dict(line.split('=', 1) for line in path.read_text().splitlines())
            self.assertEqual(result['NARMA_CHATGPT_ENCRYPTION_KEY'], KEY)
            self.assertEqual(result['GEMINI_API_KEY'], 'unchanged')
            self.assertEqual(result['HERMES_PROVIDER'], 'gemini')
            self.assertNotIn('REPLAY_COACH_PROVIDER', result)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


class ChatGPTPreparationTest(unittest.TestCase):
    def prepare_mocks(self, stack, *, ledger_changed=False):
        saved = {'release': SHA, 'before': None}
        auth = {'configured': True, 'services_ready': True, 'database_read_only': True,
                'provider': 'chatgpt_subscription', 'readiness': 'waiting_auth', 'runtime_verified': False}
        ledger_reads = 0
        def api(config, code):
            nonlocal ledger_reads
            if code == preparation.AUTH_STATE:
                return dict(auth)
            if code == preparation.LEDGER_STATE:
                ledger_reads += 1
                return {'gemini_ledger_sha256': 'unchanged',
                        'subscription_calls': int(ledger_changed and ledger_reads > 1)}
            self.assertEqual(code, preparation.DATABASE_STATE)
            return {'preserved': True}
        stack.enter_context(patch.object(preparation, 'state_path', return_value=Mock(read_text=Mock(return_value=json.dumps(saved)))))
        stack.enter_context(patch.object(preparation, 'inspect_service', return_value=None))
        stack.enter_context(patch.object(preparation, 'resource_check', return_value={}))
        stack.enter_context(patch.object(preparation, 'api_json', side_effect=api))
        stack.enter_context(patch.object(preparation, 'verify_preserved'))
        stack.enter_context(patch.object(preparation, 'verify_private_network'))
        stack.enter_context(patch.object(preparation, 'access_checks'))
        stack.enter_context(patch.object(preparation, 'write_private'))
        return stack.enter_context(patch.object(preparation, 'run',
            return_value=b'{"broker_reachable":true,"blocked":5}'))

    def test_waiting_login_is_ready_without_claiming_runtime_review_or_model_call(self):
        with ExitStack() as stack:
            run = self.prepare_mocks(stack)
            result = preparation.prepare(SHA, 'narma.example')
        self.assertEqual(result['auth']['readiness'], 'waiting_auth')
        self.assertFalse(result['auth']['runtime_verified'])
        self.assertFalse(result['generation_smoke_performed'])
        self.assertEqual(result['provider_calls_created_by_preflight'], 0)
        commands = [call.args[0] for call in run.call_args_list]
        self.assertIn('--force-recreate', commands[-1])
        self.assertFalse(any('process_once' in part or 'generate_content' in part
            for command in commands for part in command))
        with patch.object(pilot, 'event'):
            pilot.validate_chatgpt_preparation(result)

    def test_ledger_change_blocks_scheduler_and_stops_new_runtime(self):
        with ExitStack() as stack:
            run = self.prepare_mocks(stack, ledger_changed=True)
            with self.assertRaisesRegex(RuntimeError, 'hermes_chatgpt_generation_during_preflight'):
                preparation.prepare(SHA, 'narma.example')
        commands = [call.args[0] for call in run.call_args_list]
        self.assertIn('stop', commands[-1])
        self.assertFalse(any('--force-recreate' in command for command in commands))

    def test_public_oauth_get_requires_login_and_connect_rejects_foreign_origin(self):
        connections = []
        for code in (401, 403):
            connection = Mock()
            connection.getresponse.return_value.status = code
            connection.getresponse.return_value.read.return_value = b'{}'
            connections.append(connection)
        with patch.object(preparation, 'LocalHTTPS', side_effect=connections):
            preparation.access_checks('narma.example')
        self.assertEqual(connections[0].request.call_args.args[:2], ('GET', '/api/integrations/chatgpt'))
        self.assertEqual(connections[1].request.call_args.args[:2], ('POST', '/api/integrations/chatgpt/connect'))
        self.assertEqual(connections[1].request.call_args.kwargs['headers']['Origin'], 'https://invalid.example')

    def test_missing_network_or_no_generation_evidence_cannot_pass_deployment(self):
        with patch.object(pilot, 'event'):
            for bad in ({}, {'event': 'hermes_chatgpt_auth_ready', 'runtime_verified': True}):
                with self.subTest(state=bad), self.assertRaisesRegex(pilot.CheckError, 'hermes_chatgpt_preparation_unverified'):
                    pilot.validate_chatgpt_preparation(bad)


if __name__ == '__main__':
    unittest.main()
