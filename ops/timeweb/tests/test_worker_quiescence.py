"""The legacy-worker cutover refuses paid work and fences idle consumers."""
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import quiesce_workers as quiesce
import pilot
import prebuilt_images as images
import chatgpt_secrets
import openai_secrets
import snapshot_worker_state

IDENTITY = 'd' * 64
CONFIG = '/opt/narma/releases/' + 'a' * 40 + '/services/video/compose.yaml'


def services():
    return {name: {'service': name, 'id': str(index) * 64, 'image': 'sha256:' + str(index) * 64,
                  'config': CONFIG, 'running': True}
            for index, name in enumerate((*quiesce.SERVICES, 'api'), 1)}


class QuiescenceTest(unittest.TestCase):
    def test_first_install_without_consumers_does_not_require_an_api(self):
        with patch.object(quiesce, 'inspect_service', return_value=None), patch.object(quiesce, 'run') as run:
            result = quiesce.stop_idle_workers()
        self.assertEqual(result['stopped_services'], [])
        self.assertFalse(result['idle_guard_verified'])
        run.assert_not_called()

    def test_busy_or_unreadable_database_never_stops_a_worker(self):
        current = services()
        for code in ('deployment_workers_busy', 'deployment_idle_guard_lost', 'deployment_idle_guard_invalid'):
            with self.subTest(code=code), patch.object(quiesce, 'inspect_service', side_effect=current.get), \
                    patch.object(quiesce, 'idle_guard', side_effect=RuntimeError(code)), patch.object(quiesce, 'run') as run:
                with self.assertRaisesRegex(RuntimeError, code):
                    quiesce.stop_idle_workers()
                run.assert_not_called()

    def test_all_consumers_stop_only_inside_the_held_guard(self):
        current = services()
        held = False
        confirmations = []
        commands = []

        @contextmanager
        def guard(api, challenge):
            nonlocal held
            self.assertEqual(api, current['api'])
            self.assertEqual(len(challenge), 64)
            held = True
            try:
                yield IDENTITY, lambda: confirmations.append(held)
            finally:
                held = False

        def run(command, timeout):
            commands.append(command)
            self.assertTrue(held)
            if command[:2] == ['docker', 'exec']:
                self.assertNotEqual(command[2], current['hermes-runner']['id'])
                return (IDENTITY + '\n').encode()
            self.assertEqual(command, ['docker', 'stop', '--time', '15',
                *[current[name]['id'] for name in quiesce.SERVICES]])
            for name in quiesce.SERVICES:
                current[name] = {**current[name], 'running': False}
            return b''

        with patch.object(quiesce, 'inspect_service', side_effect=lambda name: deepcopy(current.get(name))), \
                patch.object(quiesce, 'idle_guard', side_effect=guard), patch.object(quiesce, 'run', side_effect=run):
            result = quiesce.stop_idle_workers()
        self.assertEqual(confirmations, [True, True])
        self.assertFalse(held)
        self.assertTrue(result['idle_guard_verified'])
        self.assertEqual(len(commands), 4)

    def test_different_worker_database_is_rejected_before_stop(self):
        current = services()

        @contextmanager
        def guard(*args):
            yield IDENTITY, lambda: None

        with patch.object(quiesce, 'inspect_service', side_effect=current.get), \
                patch.object(quiesce, 'idle_guard', side_effect=guard), \
                patch.object(quiesce, 'run', return_value=b'wrong\n') as run:
            with self.assertRaisesRegex(RuntimeError, 'deployment_worker_database_mismatch'):
                quiesce.stop_idle_workers()
        self.assertTrue(all(call.args[0][:2] != ['docker', 'stop'] for call in run.call_args_list))

    def test_missing_api_or_mixed_release_cannot_prove_idle(self):
        for api in (None, {**services()['api'], 'config': CONFIG.replace('a' * 40, 'b' * 40)}):
            current = services()
            current['api'] = api
            with self.subTest(api=api), patch.object(quiesce, 'inspect_service', side_effect=current.get), \
                    patch.object(quiesce, 'idle_guard') as guard:
                with self.assertRaisesRegex(RuntimeError, 'deployment_idle_api_unavailable'):
                    quiesce.stop_idle_workers()
                guard.assert_not_called()

    def test_probe_receipts_are_whitelisted_and_never_relay_arbitrary_text(self):
        for receipt in ([], {'status': 'failed', 'secret': 'must-not-log'},
                        {'status': 'locked', 'database': True}, {'status': 'locked', 'database': 'g' * 64}):
            with self.subTest(receipt=receipt), self.assertRaisesRegex(RuntimeError, 'deployment_idle_guard_invalid'):
                quiesce.validate_receipt(receipt)
        with self.assertRaisesRegex(RuntimeError, 'deployment_workers_busy'):
            quiesce.validate_receipt({'status': 'busy'})

    def test_receipt_reader_handles_pipe_eof_and_oversized_output(self):
        for value in ('', 'x' * 300, 'not-json\n'):
            process = subprocess.Popen([sys.executable, '-c', 'import sys;sys.stdout.write(sys.argv[1])', value],
                stdout=subprocess.PIPE)
            try:
                with self.assertRaises(RuntimeError):
                    quiesce.receive(process, 2)
            finally:
                process.wait(timeout=2)
                process.stdout.close()

    def test_receipt_reader_accepts_one_fixed_size_json_receipt(self):
        value = {'status': 'locked', 'database': IDENTITY}
        process = subprocess.Popen([sys.executable, '-c', 'import sys;print(sys.argv[1])', json.dumps(value)],
            stdout=subprocess.PIPE)
        try:
            self.assertEqual(quiesce.receive(process, 2), value)
        finally:
            process.wait(timeout=2)
            process.stdout.close()

    def test_busy_bootstrap_uses_current_attempt_receipt_and_never_restarts_containers(self):
        attempt = 'b' * 32
        receipt = {'event': 'deployment_quiescence_failed', 'code': 'deployment_workers_busy',
                   'disposition': 'deferred_before_stop', 'attempt': attempt}
        result = SimpleNamespace(returncode=75,
            stdout=b'NARMA_BOOTSTRAP_STAGE:quiesce_workers\n' + json.dumps(receipt).encode() + b'\n',
            stderr=b'NARMA_BOOTSTRAP_FAILURE:quiesce_workers:75\n')
        with patch.object(pilot.subprocess, 'run', return_value=result), patch.object(pilot, 'event'):
            with self.assertRaises(pilot.BootstrapDeferred) as failure:
                pilot.command(['ssh'], bootstrap=True, phase='bootstrap', deferred_attempt=attempt)
        with patch.object(pilot, 'command') as command, patch.object(pilot, 'event'):
            pilot.restore_bootstrap_failure(failure.exception, ['ssh'], '/opt/narma/releases/'+'a'*40,
                                            'a'*40, 'narma.example')
        self.assertEqual(command.call_count, 1)
        self.assertIn('prebuilt_images.py rollback-tags ', command.call_args.args[0][-1])
        self.assertNotIn('activate_replays.py', command.call_args.args[0][-1])

    def test_missing_stale_or_poststop_evidence_keeps_normal_rollback(self):
        attempt = 'b' * 32
        receipt = {'event': 'deployment_quiescence_failed', 'code': 'deployment_workers_busy',
                   'disposition': 'deferred_before_stop', 'attempt': attempt}
        valid = SimpleNamespace(returncode=75,
            stdout=b'NARMA_BOOTSTRAP_STAGE:quiesce_workers\n'+json.dumps(receipt).encode()+b'\n',
            stderr=b'NARMA_BOOTSTRAP_FAILURE:quiesce_workers:75\n')
        cases = [(valid, 'c'*32), (valid, None),
                 (SimpleNamespace(**{**vars(valid), 'returncode': 1}), attempt),
                 (SimpleNamespace(**{**vars(valid), 'stderr': b''}), attempt),
                 (SimpleNamespace(**{**vars(valid), 'stdout': valid.stdout+b'NARMA_BOOTSTRAP_STAGE:stop_worker\n'}), attempt)]
        for result, nonce in cases:
            with self.subTest(nonce=nonce), patch.object(pilot.subprocess, 'run', return_value=result), \
                    patch.object(pilot, 'event'):
                with self.assertRaises(pilot.CheckError) as failure:
                    pilot.command(['ssh'], bootstrap=True, phase='bootstrap', deferred_attempt=nonce)
                self.assertNotIsInstance(failure.exception, pilot.BootstrapDeferred)
                with patch.object(pilot, 'command') as command:
                    pilot.restore_bootstrap_failure(failure.exception, ['ssh'], '/opt/narma/releases/'+'a'*40,
                                                    'a'*40, 'narma.example')
                    self.assertEqual(command.call_count, 2)
                    self.assertIn(' --rollback-only', command.call_args.args[0][-1])

    def test_tags_only_rollback_never_inspects_or_recreates_api(self):
        sha = 'a' * 40
        identifier = 'sha256:' + '1' * 64
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'checkpoint.json'
            path.write_text(json.dumps({'release': sha, 'images': {'narma-video-api': identifier},
                                       'api': {'running': True, 'invalid': 'must-not-be-used'}}))
            with patch.object(images, 'checkpoint_path', return_value=path), \
                    patch.object(images, 'image_info'), patch.object(images, 'run') as run, \
                    patch.object(chatgpt_secrets, 'restore_settings'), \
                    patch.object(openai_secrets, 'restore_settings'), \
                    patch.object(snapshot_worker_state, 'inspect_service') as inspect:
                images.rollback_images(sha, restore_api=False)
            run.assert_called_once_with(['docker', 'image', 'tag', identifier, 'narma-video-api'])
            inspect.assert_not_called()

    def test_image_preparation_failures_restore_current_settings_without_container_rollback(self):
        sha, attempt = 'a' * 40, 'b' * 32
        for failed_phase in ('transfer', 'install'):
            commands = []

            def command(args, **kwargs):
                commands.append(args[-1])
                if failed_phase == 'install' and '/prebuilt_images.py install ' in args[-1]:
                    raise pilot.CheckError('synthetic_image_install_failure')
                return b''

            def transfer(*args, **kwargs):
                if failed_phase == 'transfer':
                    raise pilot.CheckError('synthetic_image_transfer_failure')

            with self.subTest(phase=failed_phase), patch.object(pilot, 'command', side_effect=command), \
                    patch.object(pilot, 'transfer_image_archive', side_effect=transfer), \
                    patch.object(pilot, 'event'), patch.object(pilot, 'restore_bootstrap_failure') as rollback:
                with self.assertRaises(pilot.CheckError):
                    pilot.prepare_before_bootstrap(['ssh'], '/opt/narma/releases/'+sha, sha, attempt,
                        b'private-payload', Path('/synthetic/images.tar.gz'), server_id=9037783,
                        prepare_openai_api=True)
            rollback.assert_not_called()
            self.assertTrue(commands[-1].startswith('python3 -c '))
            self.assertIn(attempt, commands[-1])
            self.assertFalse(any('/prebuilt_images.py rollback' in value or '/activate_replays.py ' in value
                                 or '/bootstrap.sh ' in value or 'docker stop ' in value for value in commands))


if __name__ == '__main__':
    unittest.main()
