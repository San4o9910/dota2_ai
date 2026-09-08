"""No paid retry, resource, source-proof and worker snapshot activation gates."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import activate_hermes as activation

CONFIG = '/opt/narma/releases/' + 'a' * 40 + '/services/video/compose.yaml'


class HermesActivationTest(unittest.TestCase):
    def test_resource_gate_uses_available_memory_and_free_disk_without_resizing(self):
        total = 'MemTotal: 8388608 kB\n'
        enough = total + 'MemAvailable: 1572864 kB\n'
        state = activation.resource_check(enough, 2 * 1024**3)
        self.assertEqual(state['memory_available_bytes'], activation.MIN_AVAILABLE_MEMORY)
        with self.assertRaisesRegex(RuntimeError, 'hermes_memory_headroom_insufficient'):
            activation.resource_check(total + 'MemAvailable: 1572863 kB\n', 20 * 1024**3)
        with self.assertRaisesRegex(RuntimeError, 'hermes_disk_headroom_insufficient'):
            activation.resource_check(enough, 2 * 1024**3 - 1)

    def test_wait_for_parser_drain_but_never_retry_a_failed_provider_attempt(self):
        outputs = [b'{"status":"idle"}', b'{"status":"failed","error_code":"HERMES_RUNNER_FAILED"}']
        with patch.object(activation, 'run', side_effect=outputs) as run, \
                patch.object(activation.time, 'sleep') as sleep:
            result = activation.run_one_review(CONFIG, False)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(run.call_count, 2)
        sleep.assert_called_once_with(5)

    def test_redeployment_reuses_verified_review_without_claiming_another_task(self):
        with patch.object(activation, 'run', return_value=b'{"status":"idle"}') as run:
            activation.run_one_review(CONFIG, True)
        code = run.call_args.args[0][-1]
        self.assertIn('refresh_heartbeat', code)
        self.assertNotIn('process_once', code)
        self.assertEqual(run.call_count, 1)

    def test_actual_proof_program_accepts_persisted_review_schema_and_settled_call(self):
        db = ModuleType('narma_video.db')
        tasks = ModuleType('narma_video.hermes_tasks')
        tasks.RUNTIME_REVISION = activation.REVISION
        tasks.latest_valid_review = lambda owner: {'id': 'test-task'}
        rows = [
            [{'owner_id': 'test-owner'}],
            {'id': 'test-task', 'review': {'patterns': [], 'goals': []}, 'runtime_revision': activation.REVISION},
            [{'id': 1, 'billing_status': 'settled', 'charged_microusd': 100}],
            {'n': 1},
        ]
        class Connection:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def execute(self, *args):
                self.value = rows.pop(0)
                return self
            def fetchall(self): return self.value
            def fetchone(self): return self.value
        db.database = Connection
        output = io.StringIO()
        with patch.dict(sys.modules, {'narma_video.db': db, 'narma_video.hermes_tasks': tasks}), redirect_stdout(output):
            exec(activation.PROOF, {})
        proof = json.loads(output.getvalue())
        self.assertTrue(proof['verified'])
        self.assertEqual(proof['runtime_revision'], activation.REVISION)
        self.assertEqual(proof['goals'], 0)
        self.assertEqual(proof['billing_status'], 'settled')
        self.assertEqual(rows, [])


if __name__ == '__main__':
    unittest.main()
