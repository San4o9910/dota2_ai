"""Pinned source fetch auth, caching and throttling without network requests."""
from contextlib import redirect_stdout
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[3] / 'services/hermes/fetch_source.py'
spec = importlib.util.spec_from_file_location('narma_hermes_source', PATH)
source = importlib.util.module_from_spec(spec)
spec.loader.exec_module(source)
TOKEN = 'unit_test_only_' + 'x' * 30


def result(code=0, output=b'', error=b''):
    return SimpleNamespace(returncode=code, stdout=output, stderr=error)


class HermesSourceTest(unittest.TestCase):
    def fixture(self, directory):
        cache = Path(directory) / 'cache'; cache.mkdir()
        (cache / 'HEAD').write_text('ref: refs/heads/main\n')
        token = Path(directory) / 'token'; token.write_text(TOKEN)
        return cache, token

    def test_verified_cache_requires_neither_token_nor_network(self):
        with tempfile.TemporaryDirectory() as directory:
            cache, token = self.fixture(directory)
            token.unlink()
            with patch.object(source, 'identity', return_value=True), patch.object(source, 'git') as git:
                source.fetch(cache, token)
            git.assert_not_called()

    def test_auth_never_enters_arguments_output_or_repository_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            cache, token = self.fixture(directory)
            output = io.StringIO()
            with patch.object(source, 'identity', side_effect=[False, True]), \
                    patch.object(source.subprocess, 'run', return_value=result()) as run, redirect_stdout(output):
                source.fetch(cache, token)
            args = run.call_args.args[0]
            environment = run.call_args.kwargs['env']
            self.assertIn(source.ORIGIN, args)
            self.assertIn(source.REVISION, args)
            self.assertIn('http.followRedirects=false', args)
            self.assertIn('credential.helper=', args)
            self.assertNotIn(TOKEN, str(args))
            self.assertNotIn(TOKEN, output.getvalue())
            self.assertEqual(environment['GIT_CONFIG_KEY_0'], 'http.https://github.com/.extraheader')
            self.assertTrue(environment['GIT_CONFIG_VALUE_0'].startswith('AUTHORIZATION: basic '))
            self.assertEqual({path.name for path in cache.iterdir()}, {'HEAD', 'config'})
            self.assertNotIn(TOKEN, (cache / 'config').read_text())

    def test_429_waits_one_minute_then_makes_one_authenticated_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            cache, token = self.fixture(directory)
            with patch.object(source, 'identity', side_effect=[False, True]), \
                    patch.object(source, 'git', side_effect=[result(128, error=b'HTTP 429'), result()]) as git, \
                    patch.object(source.time, 'sleep') as sleep, redirect_stdout(io.StringIO()):
                source.fetch(cache, token)
            self.assertEqual(git.call_count, 2)
            sleep.assert_called_once_with(60)
            for call in git.call_args_list:
                self.assertIn('GIT_CONFIG_VALUE_0', call.kwargs['environment'])

    def test_retry_after_is_respected_and_oversized_delay_aborts(self):
        self.assertEqual(source.retry_delay(b'Retry-After: 120\r\n'), 120)
        self.assertEqual(source.retry_delay(b'Retry-After: 2\r\n'), 60)
        with tempfile.TemporaryDirectory() as directory:
            cache, token = self.fixture(directory)
            with patch.object(source, 'identity', return_value=False), \
                    patch.object(source, 'git', return_value=result(128, error=b'HTTP 429\nRetry-After: 600')) as git, \
                    patch.object(source.time, 'sleep') as sleep:
                with self.assertRaisesRegex(source.SourceError, 'RETRY_AFTER_EXCEEDS_BUILD_BUDGET'):
                    source.fetch(cache, token)
            git.assert_called_once(); sleep.assert_not_called()

    def test_failed_retry_is_bounded_and_does_not_expose_transport_error(self):
        with tempfile.TemporaryDirectory() as directory:
            cache, token = self.fixture(directory)
            output = io.StringIO()
            with patch.object(source, 'identity', return_value=False), \
                    patch.object(source, 'git', return_value=result(128, error=('HTTP 429 ' + TOKEN).encode())) as git, \
                    patch.object(source.time, 'sleep') as sleep, redirect_stdout(output):
                with self.assertRaisesRegex(source.SourceError, '^HERMES_SOURCE_FETCH_FAILED$'):
                    source.fetch(cache, token)
            self.assertEqual(git.call_count, 2)
            sleep.assert_called_once_with(60)
            self.assertNotIn(TOKEN, output.getvalue())

    def test_wrong_tree_or_corrupt_git_objects_cannot_be_used(self):
        for outputs, code in (
            ([result(output=source.REVISION.encode()), result(output=b'wrong')], 'IDENTITY_MISMATCH'),
            ([result(output=source.REVISION.encode()), result(output=source.TREE.encode()), result(1)], 'CACHE_CORRUPT'),
        ):
            with self.subTest(code=code), patch.object(source, 'git', side_effect=outputs):
                with self.assertRaisesRegex(source.SourceError, code):
                    source.identity(Path('/synthetic-cache'))

    def test_authentication_rejection_does_not_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            cache, token = self.fixture(directory)
            with patch.object(source, 'identity', return_value=False), \
                    patch.object(source, 'git', return_value=result(128, error=b'HTTP 401')) as git, \
                    patch.object(source.time, 'sleep') as sleep:
                with self.assertRaises(source.SourceError):
                    source.fetch(cache, token)
            git.assert_called_once(); sleep.assert_not_called()

    def test_inherited_git_tracing_and_tokens_are_not_forwarded(self):
        with patch.dict(os.environ, {'GITHUB_TOKEN': TOKEN, 'HERMES_SOURCE_GITHUB_TOKEN': TOKEN,
                'GIT_TRACE': '1', 'GIT_CONFIG_VALUE_7': TOKEN}):
            environment = source.clean_environment()
        self.assertNotIn(TOKEN, str(environment))
        self.assertEqual(environment['GIT_TRACE'], '0')
        self.assertEqual(environment['GIT_CONFIG_GLOBAL'], '/dev/null')
        self.assertEqual(environment['GIT_NO_REPLACE_OBJECTS'], '1')

    def test_cached_url_rewrites_and_export_overrides_are_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            cache, token = self.fixture(directory)
            (cache / 'config').write_text('[url "https://untrusted.invalid/"]\ninsteadOf = https://github.com/\n')
            (cache / 'info').mkdir()
            (cache / 'info/attributes').write_text('* export-ignore\n')
            with patch.object(source, 'identity', return_value=True):
                source.fetch(cache, token)
            self.assertNotIn('untrusted', (cache / 'config').read_text())
            self.assertFalse((cache / 'info/attributes').exists())

    def test_external_common_config_is_forbidden_for_the_dedicated_bare_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            cache, token = self.fixture(directory)
            (cache / 'commondir').write_text('../untrusted-config\n')
            with patch.object(source, 'git') as git:
                with self.assertRaisesRegex(source.SourceError, 'HERMES_SOURCE_CACHE_INVALID'):
                    source.fetch(cache, token)
            git.assert_not_called()

    def test_git_replace_ref_cannot_substitute_exported_lock_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); repo = root / 'repo'; repo.mkdir()
            def git(*args, data=None):
                return subprocess.run(['git', '-C', str(repo), *args], input=data,
                    capture_output=True, check=True).stdout.strip().decode()
            git('init', '--quiet')
            (repo / 'uv.lock').write_text('trusted lock\n')
            git('add', 'uv.lock')
            git('-c', 'user.name=Source test', '-c', 'user.email=source@example.invalid', 'commit', '--quiet', '-m', 'fixture')
            revision = git('rev-parse', 'HEAD'); tree = git('rev-parse', 'HEAD^{tree}')
            original = git('rev-parse', 'HEAD:uv.lock')
            replacement = git('hash-object', '-w', '--stdin', data=b'replaced lock\n')
            git('replace', original, replacement)
            with patch.object(source, 'REVISION', revision), patch.object(source, 'TREE', tree), redirect_stdout(io.StringIO()):
                source.fetch(repo / '.git', root / 'missing-token')
                source.extract(repo / '.git', root / 'export')
            self.assertEqual((root / 'export/uv.lock').read_text(), 'trusted lock\n')


if __name__ == '__main__':
    unittest.main()
