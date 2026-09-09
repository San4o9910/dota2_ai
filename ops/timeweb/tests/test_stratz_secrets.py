import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from stratz_secrets import (build_stats_payload, build_stats_source,
                           install_build_statistics, install_stratz)


class StratzSecretInstallation(unittest.TestCase):
    def test_install_preserves_database_and_other_credentials(self):
        values={'DATABASE_URL':'unchanged','GEMINI_API_KEY':'old'}
        install_stratz(values,'synthetic.token-value')
        self.assertEqual(values,{'DATABASE_URL':'unchanged','GEMINI_API_KEY':'old','STRATZ_API_TOKEN':'synthetic.token-value'})

    def test_omitted_secret_does_not_clear_existing_configuration(self):
        values={'STRATZ_API_TOKEN':'existing'}
        install_stratz(values,None);install_stratz(values,'')
        self.assertEqual(values['STRATZ_API_TOKEN'],'existing')

    def test_reject_environment_injection_without_partial_mutation(self):
        for token in ('secret\nDATABASE_URL=replaced','${OTHER_KEY}','secret with spaces',[], 'x'*8193):
            values={'DATABASE_URL':'unchanged'}
            with self.subTest(token_type=type(token).__name__),self.assertRaises(ValueError):
                install_stratz(values,token)
            self.assertEqual(values,{'DATABASE_URL':'unchanged'})


class BuildStatisticsSourceSelection(unittest.TestCase):
    def test_authored_default_does_not_transfer_available_provider_secret(self):
        for configured in ({}, {'STRATZ_API_TOKEN': 'synthetic.token-value'},
                           {'STRATZ_API_TOKEN': 'invalid\nsecret'}):
            self.assertEqual(build_stats_payload(configured), {'build_stats_source': 'authored'})

    def test_explicit_stratz_transfers_only_validated_credential_and_source(self):
        payload = build_stats_payload({'NARMA_BUILD_STATS_SOURCE': 'stratz',
            'STRATZ_API_TOKEN': 'synthetic.token-value', 'GEMINI_API_KEY': 'unrelated'})
        self.assertEqual(payload, {'build_stats_source': 'stratz',
                                  'stratz_token': 'synthetic.token-value'})

    def test_unknown_or_empty_explicit_mode_fails(self):
        for source in ('', 'STRATZ', 'other', 'authored\n', []):
            with self.subTest(source=source), self.assertRaises(ValueError):
                build_stats_source(source)

    def test_explicit_stratz_cannot_use_missing_or_malformed_token(self):
        for token in (None, '', 'invalid token', 'bad\nDATABASE_URL=replaced'):
            with self.subTest(token=token), self.assertRaises(ValueError):
                build_stats_payload({'NARMA_BUILD_STATS_SOURCE': 'stratz',
                                     'STRATZ_API_TOKEN': token})

    def test_authored_release_disables_old_provider_without_resetting_identity_or_ai(self):
        original = {'DATABASE_URL': 'existing-db', 'POSTGRES_PASSWORD': 'existing-db-key',
            'VIDEO_SERVICE_TOKEN': 'existing-private-api', 'GEMINI_API_KEY': 'existing-gemini',
            'HERMES_PROVIDER': 'chatgpt_subscription', 'HERMES_RUNTIME_ENABLED': '1',
            'NARMA_CHATGPT_ENCRYPTION_KEY': 'existing-chatgpt-key',
            'STRATZ_API_TOKEN': 'old-provider-key', 'NARMA_BUILD_STATS_SOURCE': 'stratz',
            'NARMA_STRATZ_REFRESH_ENABLED': '1'}
        values = dict(original)
        install_build_statistics(values, {'build_stats_source': 'authored',
                                         'stratz_token': 'ignored-new-secret'})
        self.assertEqual(values, {**original, 'NARMA_BUILD_STATS_SOURCE': 'authored',
                                 'NARMA_STRATZ_REFRESH_ENABLED': '0'})

    def test_omitted_mode_is_authored_even_with_existing_provider_secret(self):
        values = {'STRATZ_API_TOKEN': 'existing-secret'}
        install_build_statistics(values, {})
        self.assertEqual(values, {'STRATZ_API_TOKEN': 'existing-secret',
            'NARMA_BUILD_STATS_SOURCE': 'authored', 'NARMA_STRATZ_REFRESH_ENABLED': '0'})

    def test_explicit_stratz_enables_refresh_without_changing_other_settings(self):
        values = {'DATABASE_URL': 'existing-db', 'NARMA_STRATZ_REFRESH_ENABLED': '0'}
        install_build_statistics(values, {'build_stats_source': 'stratz',
                                         'stratz_token': 'synthetic.token-value'})
        self.assertEqual(values, {'DATABASE_URL': 'existing-db',
            'NARMA_STRATZ_REFRESH_ENABLED': '1', 'NARMA_BUILD_STATS_SOURCE': 'stratz',
            'STRATZ_API_TOKEN': 'synthetic.token-value'})

    def test_invalid_remote_configuration_preserves_all_existing_values(self):
        original = {'DATABASE_URL': 'existing-db', 'STRATZ_API_TOKEN': 'existing-secret',
                    'NARMA_BUILD_STATS_SOURCE': 'authored', 'NARMA_STRATZ_REFRESH_ENABLED': '0'}
        for incoming in ({'build_stats_source': 'unknown'}, {'build_stats_source': 'stratz'},
                         {'build_stats_source': 'stratz', 'stratz_token': 'bad token'}):
            values = dict(original)
            with self.subTest(incoming=incoming), self.assertRaises(ValueError):
                install_build_statistics(values, incoming)
            self.assertEqual(values, original)
