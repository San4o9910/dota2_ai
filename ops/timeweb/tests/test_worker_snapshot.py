"""A redeployment preserves only a verified pair of selective OpenAI workers."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import snapshot_worker_state as snapshot

SHA = 'a' * 40
CONFIG = '/opt/narma/releases/' + SHA + '/services/video/compose.yaml'


def workers():
    return [{'service': service, 'id': str(index) * 64, 'image': 'sha256:' + str(index) * 64,
             'config': CONFIG, 'running': True}
            for index, service in enumerate(snapshot.ANALYSIS_SERVICES, 1)]


def proof(database='d' * 64):
    return json.dumps({'contract': 'openai-selective-media-lock-v1',
                       'lock': 643847215, 'database': database}).encode()


class WorkerSnapshotTest(unittest.TestCase):
    def test_single_or_stopped_legacy_workers_do_not_need_a_dual_contract(self):
        pair = workers()
        pair[1]['running'] = False
        for current in ([], pair[:1], pair):
            with self.subTest(current=current), patch.object(snapshot, 'run') as run:
                snapshot.verify_analysis_workers(current)
                run.assert_not_called()

    def test_verified_pair_uses_existing_container_ids_and_one_unpersisted_challenge(self):
        current = workers()
        with patch.object(snapshot, 'run', return_value=proof()) as run, \
                patch.object(snapshot, 'inspect_service', side_effect=current):
            snapshot.verify_analysis_workers(current)
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(len(commands), 2)
        self.assertEqual([command[2] for command in commands], [item['id'] for item in current])
        self.assertEqual(commands[0][-1], commands[1][-1])
        self.assertEqual(len(commands[0][-1]), 64)
        self.assertTrue(all(command[:2] == ['docker', 'exec'] for command in commands))

    def test_mixed_installed_releases_remain_blocked_without_probing(self):
        current = workers()
        current[1]['config'] = CONFIG.replace(SHA, 'b' * 40)
        with patch.object(snapshot, 'run') as run, \
                self.assertRaisesRegex(RuntimeError, 'replay_activation_multiple_workers_running'):
            snapshot.verify_analysis_workers(current)
        run.assert_not_called()

    def test_unverified_legacy_pair_malformed_proof_and_different_database_stay_blocked(self):
        for outputs in ([RuntimeError('legacy_or_missing_lock')], [b'not-json'], [b'[]'],
                        [proof(), proof('e' * 64)],
                        [json.dumps({'contract': 'other', 'lock': 643847215, 'database': 'd'*64}).encode()],
                        [json.dumps({'contract': 'openai-selective-media-lock-v1', 'lock': True,
                                     'database': 'd'*64}).encode()]):
            with self.subTest(outputs=outputs), patch.object(snapshot, 'run', side_effect=outputs), \
                    self.assertRaisesRegex(RuntimeError, 'replay_activation_multiple_workers_running'):
                snapshot.verify_analysis_workers(workers())

    def test_container_replacement_during_probe_is_rejected(self):
        current = workers()
        changed = deepcopy(current)
        changed[0]['id'] = 'f' * 64
        with patch.object(snapshot, 'run', return_value=proof()), \
                patch.object(snapshot, 'inspect_service', side_effect=changed), \
                self.assertRaisesRegex(RuntimeError, 'replay_activation_multiple_workers_running'):
            snapshot.verify_analysis_workers(current)

    def test_failed_dual_verification_does_not_overwrite_worker_rollback_state(self):
        current = workers()
        with patch.object(snapshot, 'inspect_service', side_effect=current + [None, None]), \
                patch.object(snapshot, 'run', side_effect=RuntimeError('legacy_pair')), \
                patch.object(snapshot, 'write_private') as write, \
                self.assertRaisesRegex(RuntimeError, 'replay_activation_multiple_workers_running'):
            snapshot.snapshot(SHA)
        write.assert_not_called()


if __name__ == '__main__':
    unittest.main()
