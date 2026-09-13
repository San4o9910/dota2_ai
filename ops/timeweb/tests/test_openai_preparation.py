"""New API setup preserves service state, keys and durable money accounting."""
from contextlib import ExitStack
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import openai_secrets as secrets
import openai_support as support
import prepare_openai_api as preparation
import pilot

SHA = 'a' * 40
KEY = 'sk-synthetic-test-key-never-a-real-provider-credential'
BASE = {'DATABASE_URL': 'unchanged-db', 'POSTGRES_PASSWORD': 'unchanged-password',
        'VIDEO_SERVICE_TOKEN': 'unchanged-service', 'GEMINI_API_KEY': 'unchanged-gemini',
        'NARMA_CHATGPT_ENCRYPTION_KEY': 'unchanged-encryption',
        'REPLAY_COACH_PROVIDER': 'chatgpt_subscription', 'HERMES_PROVIDER': 'chatgpt_subscription',
        'HERMES_RUNTIME_ENABLED': '1'}
NOW = datetime(2026, 9, 12, tzinfo=timezone.utc)


class OpenAISecretTest(unittest.TestCase):
    def test_first_key_installation_and_retry_preserve_every_other_setting(self):
        values = dict(BASE)
        secrets.install_key(values, KEY)
        secrets.install_key(values, KEY)
        self.assertEqual(values, {**BASE, 'OPENAI_API_KEY': KEY})
        with self.assertRaisesRegex(RuntimeError, 'openai_existing_key_preserved'):
            secrets.install_key(values, KEY + '-replacement')
        self.assertEqual(values['OPENAI_API_KEY'], KEY)

    def test_invalid_or_injected_key_cannot_mutate_configuration(self):
        for value in (None, '', [], '${SECRET}', KEY+'\nDATABASE_URL=replaced', KEY+'"', 'bad key', 'sk-'+('x'*501)):
            values = dict(BASE)
            with self.subTest(type=type(value).__name__), self.assertRaises(RuntimeError):
                secrets.install_key(values, value)
            self.assertEqual(values, BASE)

    def test_inspect_never_transfers_available_secret(self):
        self.assertEqual(support.payload_for('inspect', SHA, {'OPENAI_API_KEY': KEY}),
                         {'mode': 'inspect', 'expected_release': SHA})

    def test_explicit_selection_and_rollback_preserve_credential_and_other_values(self):
        values = {**BASE, 'OPENAI_API_KEY': KEY}
        checkpoint = secrets.prepare_openai_settings(values, SHA)
        self.assertEqual(values['HERMES_PROVIDER'], 'openai_api')
        self.assertEqual(values['VIDEO_ANALYSIS_MODE'], 'selective_v1')
        self.assertNotIn(KEY, json.dumps(checkpoint))
        secrets.restore_openai_settings(values, checkpoint, SHA)
        self.assertEqual(values, {**BASE, 'OPENAI_API_KEY': KEY})

    def test_runtime_is_preserved_unless_explicit_activation_selects_it(self):
        values = {**BASE, 'OPENAI_API_KEY': KEY, 'HERMES_RUNTIME_ENABLED': '0'}
        secrets.prepare_openai_settings(values, SHA)
        self.assertEqual(values['HERMES_RUNTIME_ENABLED'], '0')
        secrets.prepare_openai_settings(values, SHA, enable_runtime=True)
        self.assertEqual(values['HERMES_RUNTIME_ENABLED'], '1')

    def test_second_same_sha_attempt_rolls_back_to_successful_openai_activation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            saved, path = root / 'settings.json', root / 'video.env'
            values = {**BASE, 'OPENAI_API_KEY': KEY, 'HERMES_RUNTIME_ENABLED': '0'}
            with patch.object(secrets, 'settings_path', return_value=saved):
                secrets.prepare_deployment_settings(values, SHA, enable_runtime=True, attempt='a'*32)
                secrets.write_values(path, values)  # First attempt succeeded.
                first_checkpoint = json.loads(saved.read_text())
                activated = dict(values)
                self.assertEqual(first_checkpoint['settings']['HERMES_PROVIDER'], 'chatgpt_subscription')
                # A new attempt at the exact same SHA must refresh its baseline.
                secrets.prepare_deployment_settings(values, SHA, enable_runtime=True, attempt='b'*32)
                secrets.write_values(path, values)
                self.assertEqual(json.loads(saved.read_text())['settings']['HERMES_PROVIDER'], 'openai_api')
                self.assertTrue(secrets.restore_settings(SHA, path, attempt='b'*32))
            self.assertEqual(secrets.read_values(path), activated)
            self.assertEqual(saved.stat().st_mode & 0o777, 0o600)
            checkpoint = saved.read_text()
            for name in ('OPENAI_API_KEY', 'DATABASE_URL', 'GEMINI_API_KEY', 'spent_microusd', 'reserved_microusd'):
                self.assertNotIn(name, checkpoint)
            self.assertNotIn(KEY, checkpoint)

    def test_failure_before_new_checkpoint_cannot_restore_older_same_sha_attempt(self):
        for previous_attempt in (None, 'a'*32):
            with self.subTest(previous_attempt=previous_attempt), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                saved, path = root / 'settings.json', root / 'video.env'
                values = {**BASE, 'OPENAI_API_KEY': KEY}
                with patch.object(secrets, 'settings_path', return_value=saved):
                    secrets.prepare_deployment_settings(values, SHA, enable_runtime=True, attempt=previous_attempt)
                    secrets.write_values(path, values)
                    active = path.read_bytes()
                    # A second attempt's invalid secret never wrote its checkpoint.
                    self.assertFalse(secrets.restore_settings(SHA, path, attempt='b'*32))
                    self.assertEqual(path.read_bytes(), active)

    def test_failed_first_attempt_restores_prior_provider_and_keeps_installed_key(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            saved, path = root / 'settings.json', root / 'video.env'
            values = {**BASE, 'OPENAI_API_KEY': KEY}
            with patch.object(secrets, 'settings_path', return_value=saved):
                secrets.prepare_deployment_settings(values, SHA, enable_runtime=True)
                secrets.write_values(path, values)
                secrets.restore_settings(SHA, path)
            self.assertEqual(secrets.read_values(path), {**BASE, 'OPENAI_API_KEY': KEY})

    def test_install_only_needs_exact_release_and_has_private_idempotent_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = root / SHA
            current.mkdir()
            path = root / 'video.env'
            original = ''.join(k+'='+v+'\n' for k,v in BASE.items())
            path.write_text(original)
            payload = {'mode': 'install-key', 'expected_release': SHA, 'key': KEY}
            result = secrets.process(payload, path=path, current=current)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertTrue(result['key_present'])
            self.assertFalse(result['provider_access_verified'])
            self.assertFalse(result['services_changed'])
            self.assertFalse(result['budgets_changed'])
            self.assertNotIn(KEY, json.dumps(result))
            before = path.stat().st_mtime_ns
            secrets.process(payload, path=path, current=current)
            self.assertEqual(path.stat().st_mtime_ns, before)
            with self.assertRaisesRegex(RuntimeError, 'openai_installed_release_mismatch'):
                secrets.process({**payload, 'expected_release': 'b'*40}, path=path, current=current)

    def test_unknown_environment_state_is_rejected_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'video.env'
            path.write_text('DATABASE_URL=old\nDATABASE_URL=new\n')
            with self.assertRaisesRegex(RuntimeError, 'openai_existing_settings_invalid'):
                secrets.read_values(path)

    def test_remote_output_cannot_forward_extra_sensitive_fields(self):
        safe = secrets.safe_status({**BASE, 'OPENAI_API_KEY': KEY}, SHA)
        self.assertEqual(support.public_result(safe, SHA), safe)
        for result in ({**safe, 'key': KEY}, {**safe, 'replay_provider': KEY},
                       {**safe, 'generation_requests': True}, {**safe, 'services_changed': True}):
            with self.assertRaises(pilot.CheckError):
                support.public_result(result, SHA)


class OpenAIReleaseSelection(unittest.TestCase):
    def test_prebootstrap_rollback_uses_only_current_openai_attempt(self):
        import chatgpt_secrets
        code = pilot.prebootstrap_rollback_code('/opt/narma/releases/'+SHA, SHA, 'b'*32,
                                               prepare_openai_api=True)
        with patch.object(secrets, 'restore_settings') as restore, \
                patch.object(chatgpt_secrets, 'restore_settings') as personal, \
                patch.object(sys, 'path', list(sys.path)):
            exec(code, {})
        restore.assert_called_once_with(SHA, attempt='b'*32)
        personal.assert_not_called()

    def test_ordinary_release_keeps_api_without_selecting_personal_oauth(self):
        self.assertEqual(pilot.provider_modes({'replay': 'openai_api', 'hermes': 'openai_api'}), (False, True))
        self.assertEqual(pilot.provider_modes({'replay': None, 'hermes': None}), (False, False))
        self.assertEqual(pilot.provider_modes({'replay': 'gemini', 'hermes': 'gemini'}), (False, False))
        self.assertEqual(pilot.provider_modes({'replay': 'chatgpt_subscription', 'hermes': 'chatgpt_subscription'}), (True, False))

    def test_mixed_or_conflicting_selection_fails_before_mutation(self):
        with self.assertRaises(pilot.CheckError):
            pilot.provider_modes({'replay': 'openai_api', 'hermes': 'chatgpt_subscription'})
        for flags in ({'activate_hermes': True, 'prepare_openai_api': True},
                      {'prepare_chatgpt_auth': True, 'prepare_openai_api': True},
                      {'activate_hermes': True, 'prepare_chatgpt_auth': True}):
            with self.subTest(flags=flags), self.assertRaises(pilot.CheckError):
                pilot.provider_modes({}, **flags)

    def test_allowance_requires_explicit_bounded_pair_and_no_default_enable(self):
        self.assertIsNone(preparation.allowance_input('', '', now=NOW))
        self.assertEqual(preparation.allowance_input('2000000', '2026-10-01T00:00:00Z', now=NOW),
                         {'limit_microusd': 2000000, 'expires_at': '2026-10-01T00:00:00Z'})
        for limit, expires in (('10000001','2026-10-01T00:00:00Z'), ('1',''), ('','2026-10-01T00:00:00Z'),
                               ('10','2026-12-01T00:00:00Z'), ('10','2026-09-01T00:00:00Z'),
                               ('0','2026-10-01T00:00:00Z'), ('2; true','2026-10-01T00:00:00Z')):
            with self.subTest(limit=limit, expires=expires), self.assertRaises(RuntimeError):
                preparation.allowance_input(limit, expires, now=NOW)

    def test_status_only_does_not_change_services_or_issue_model_calls(self):
        result = {'event':'openai_api_preflight','configured':True,'database_read_only':True,'generation_requests':0}
        with patch.object(preparation, 'api_json', return_value=result) as api, \
                patch.object(preparation, 'run') as run, patch.object(preparation, 'inspect_service') as inspect:
            self.assertEqual(preparation.status_only(SHA), result)
        api.assert_called_once()
        run.assert_not_called()
        inspect.assert_not_called()
        self.assertIn('default_transaction_read_only=on', api.call_args.args[1])
        self.assertNotIn('UPDATE ', api.call_args.args[1])
        self.assertNotIn('process_once', api.call_args.args[1])

    def test_preflight_proof_does_not_claim_actual_provider_access(self):
        proof = {'event':'openai_api_ready','provider':'openai_api','configured':True,
                 'video_mode':'selective_v1','network_isolation_verified':True,'resource_lock_available':True,
                 'generation_smoke_performed':False,'provider_calls_created_by_preflight':0,
                 'existing_ledgers_preserved':True}
        with patch.object(pilot, 'event') as event:
            pilot.validate_openai_preparation(proof)
        self.assertFalse(event.call_args.kwargs['provider_access_verified'])
        for field in ('configured','network_isolation_verified','resource_lock_available','existing_ledgers_preserved'):
            with self.subTest(field=field), self.assertRaises(pilot.CheckError):
                pilot.validate_openai_preparation({**proof, field:False})


class OpenAICutoverTest(unittest.TestCase):
    def mocks(self, stack, *, ledger_changed=False):
        saved = {'release': SHA, 'before': None}
        stack.enter_context(patch.object(preparation, 'state_path',
            return_value=Mock(read_text=Mock(return_value=json.dumps(saved)))))
        stack.enter_context(patch.object(preparation, 'inspect_service', return_value=None))
        stack.enter_context(patch.object(preparation, 'resource_check', return_value={}))
        stack.enter_context(patch.object(preparation, 'api_json', return_value={}))
        stack.enter_context(patch.object(preparation, 'verify_preserved'))
        stack.enter_context(patch.object(preparation, 'verify_private_network'))
        stack.enter_context(patch.object(preparation, 'write_private'))
        checks = stack.enter_context(patch.object(preparation, 'status_only', side_effect=[
            {'ledger_sha256': 'original'}, {'ledger_sha256': 'changed' if ledger_changed else 'original'}]))
        def run(args, **kwargs):
            if args[-1] == preparation.NETWORK_PROBE:
                return b'{"broker_reachable":true,"blocked":5}'
            if 'OPENAI_BROKER_READY' in args[-1]:
                return b'OPENAI_BROKER_READY\n'
            return b''
        commands = stack.enter_context(patch.object(preparation, 'run', side_effect=run))
        return checks, commands

    def test_normal_prepare_preserves_allowance_and_never_generates_a_probe(self):
        with ExitStack() as stack:
            checks, commands = self.mocks(stack)
            result = preparation.prepare(SHA)
        self.assertEqual(checks.call_count, 2)
        self.assertFalse(result['explicit_allowance_configured'])
        self.assertEqual(result['provider_calls_created_by_preflight'], 0)
        self.assertFalse(result['provider_access_verified'])
        for call in commands.call_args_list:
            args = call.args[0]
            self.assertNotIn('configure', args)
            self.assertNotIn('process_once', ' '.join(args))
            self.assertNotIn('activate_video.py', ' '.join(args))

    def test_failed_preflight_cannot_enable_a_budget(self):
        with ExitStack() as stack:
            checks, commands = self.mocks(stack, ledger_changed=True)
            with self.assertRaisesRegex(RuntimeError, 'openai_preflight_ledger_changed'):
                preparation.prepare(SHA, allowance={'limit_microusd': 1000000, 'expires_at': '2026-10-01T00:00:00Z'})
        self.assertEqual(checks.call_count, 2)
        self.assertTrue(any('stop' in call.args[0] for call in commands.call_args_list))
        self.assertFalse(any('configure' in call.args[0] for call in commands.call_args_list))

    def test_explicit_allowance_runs_once_after_two_readonly_checks(self):
        with ExitStack() as stack:
            checks, commands = self.mocks(stack)
            stack.enter_context(patch.object(preparation, 'allowance_input', return_value={
                'limit_microusd': 1000000, 'expires_at': '2026-10-01T00:00:00Z'}))
            result = preparation.prepare(SHA, allowance={
                'limit_microusd': 1000000, 'expires_at': '2026-10-01T00:00:00Z'})
        self.assertEqual(checks.call_count, 2)
        self.assertTrue(result['explicit_allowance_configured'])
        configured = [call.args[0] for call in commands.call_args_list if 'configure' in call.args[0]]
        self.assertEqual(len(configured), 1)
        self.assertIn('--enable', configured[0])
        self.assertIn('1000000', configured[0])


if __name__ == '__main__':
    unittest.main()
