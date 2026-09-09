"""A curriculum release cannot accidentally start a paid Hermes attempt."""
from copy import deepcopy
from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_hermes_disabled as disabled
import activate_replays
import pilot

SHA = 'a' * 40
RELEASE = '/opt/narma/releases/' + SHA


def snapshot():
    return {'release': SHA, 'services': [
        {'service': 'hermes-broker', 'running': False},
        {'service': 'hermes-runner', 'running': False},
        {'service': 'replay-worker', 'running': True},
    ], 'before': {'budget': {'model': 'unchanged', 'price_policy': 'unchanged',
        'expires_at': 'unchanged', 'limit_microusd': 10_000_000,
        'accounting_rub_per_usd': 100, 'spent_microusd': 124_938,
        'reserved_microusd': 9_600_000},
        'unknown': [{'id': 9, 'reserved_microusd': 1_200_000}],
        'owner_identity': 'same-owner-hash', 'hermes_calls': 3}}


class ProductDeploymentTest(unittest.TestCase):
    def test_authored_review_gate_accepts_complete_catalog_with_honest_stale_states(self):
        guides = [{'id': 'guide-' + str(index)} for index in range(17)]
        for state in ('reviewed', 'review_due', 'patch_changed', 'unknown'):
            reviews = {'schema_version': 'narma.build-reviews.v1', 'guides': {
                guide['id']: {'state': state, 'adaptations': []} for guide in guides}}
            with self.subTest(state=state):
                pilot.validate_build_reviews(reviews, guides)

    def test_authored_review_gate_rejects_wrong_schema_or_incomplete_catalog(self):
        guides = [{'id': 'guide-' + str(index)} for index in range(17)]
        reviews = {'schema_version': 'narma.build-reviews.v1', 'guides': {
            guide['id']: {'state': 'unknown', 'adaptations': []} for guide in guides}}
        wrong_schema = {**reviews, 'schema_version': 'unrecognized'}
        missing = deepcopy(reviews)
        missing['guides'].pop('guide-1')
        unexpected = deepcopy(reviews)
        unexpected['guides']['other-guide'] = unexpected['guides'].pop('guide-1')
        invalid_state = deepcopy(reviews)
        invalid_state['guides']['guide-1']['state'] = 'fake-meta-ready'
        for evidence in (None, {}, wrong_schema, missing, unexpected, invalid_state):
            with self.subTest(evidence=evidence), self.assertRaises(pilot.CheckError):
                pilot.validate_build_reviews(evidence, guides)

    def test_live_learning_program_accepts_actual_catalog_for_all_six_role_variants(self):
        # Execute the shipped probe against the actual catalog, so adding a
        # role-specific exercise cannot silently break the live deploy gate.
        path = Path(__file__).resolve().parents[3] / 'services/video/narma_video/curriculum.py'
        sys.path.insert(0, str(path.parents[1]))
        from narma_video import curriculum
        db, learning = ModuleType('narma_video.db'), ModuleType('narma_video.learning')
        learning.get_learning = Mock()
        learning.get_report_learning = Mock()
        learning._full_report = Mock()
        class Connection:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def execute(self, sql):
                if sql == 'SHOW transaction_read_only':
                    self.row = {'transaction_read_only': 'on'}
                elif sql == 'SELECT count(*) AS n FROM video_provider_calls':
                    self.row = {'n': 0}
                else:
                    self.assert_owners_query(sql)
                return self
            def assert_owners_query(self, sql):
                if sql != 'SELECT owner_id FROM portal_accounts ORDER BY owner_id':
                    raise AssertionError('Unexpected SQL in catalog readiness probe')
            def fetchone(self): return self.row
            def fetchall(self): return []
        db.database = Connection
        output = io.StringIO()
        modules = {'narma_video.db': db, 'narma_video.learning': learning, 'narma_video.curriculum': curriculum}
        with patch.dict(sys.modules, modules), patch.dict(os.environ, {}), redirect_stdout(output):
            exec(activate_replays.LEARNING_CHECK, {})
        result = json.loads(output.getvalue())
        self.assertTrue(result['verified'])
        self.assertEqual(result['role_variants'], 6)
        self.assertEqual(result['evidence_reports'], 0)
        self.assertEqual(result['provider_calls_created'], 0)
        learning.get_learning.assert_not_called()

    def test_default_mode_checks_disabled_state_without_calling_activation(self):
        state = {'event': 'hermes_runtime_preserved', 'automatic_tracking': False,
                 'previous_runtime_disabled': True, 'services_stopped': True, 'provider_calls_created': 0}
        with patch.object(pilot, 'command', return_value=json.dumps(state).encode()) as command, \
                patch.object(pilot, 'event'):
            self.assertEqual(pilot.deploy_hermes(['ssh'], RELEASE, SHA), state)
        command.assert_called_once()
        self.assertIn('/check_hermes_disabled.py ', command.call_args.args[0][-1])
        self.assertNotIn('/activate_hermes.py ', command.call_args.args[0][-1])

    def test_explicit_activation_still_rejects_missing_settled_review_proof(self):
        state = {'event': 'hermes_runtime_ready', 'automatic_tracking': True,
                 'runtime_revision': '9fd44b4dfc44138b9e5d5689acb56c438364ff7b',
                 'network_isolation_verified': True, 'provider_calls_created': 1,
                 'review': {'verified': False}}
        with patch.object(pilot, 'command', return_value=json.dumps(state).encode()) as command:
            with self.assertRaisesRegex(pilot.CheckError, 'hermes_runtime_not_ready'):
                pilot.deploy_hermes(['ssh'], RELEASE, SHA, activate=True)
        self.assertIn('/activate_hermes.py ', command.call_args.args[0][-1])

    def test_disabled_check_preserves_exhausted_allowance_without_refunds_or_calls(self):
        saved = snapshot()
        with patch.object(disabled, 'state_path', return_value=Mock(read_text=Mock(return_value=json.dumps(saved)))), \
                patch.object(disabled, 'inspect_service', return_value={'running': False}), \
                patch.object(disabled, 'run', return_value=json.dumps(saved['before']).encode()) as run:
            result = disabled.check(SHA)
        self.assertFalse(result['automatic_tracking'])
        self.assertEqual(result['provider_calls_created'], 0)
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0][-5:-2], ['-T', 'api', 'python'])
        self.assertNotIn('process_once', run.call_args.args[0][-1])
        self.assertNotIn('UPDATE ', run.call_args.args[0][-1])

    def test_active_previous_runtime_cannot_be_silently_disabled(self):
        saved = snapshot()
        saved['services'][0]['running'] = True
        with patch.object(disabled, 'state_path', return_value=Mock(read_text=Mock(return_value=json.dumps(saved)))), \
                patch.object(disabled, 'inspect_service') as inspect, patch.object(disabled, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'hermes_disabled_previous_runtime_active'):
                disabled.check(SHA)
        inspect.assert_not_called()
        run.assert_not_called()

    def test_still_running_hermes_or_new_provider_call_fails_release(self):
        saved = snapshot()
        with patch.object(disabled, 'state_path', return_value=Mock(read_text=Mock(return_value=json.dumps(saved)))), \
                patch.object(disabled, 'inspect_service', return_value={'running': True}), \
                patch.object(disabled, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'hermes_disabled_runtime_active'):
                disabled.check(SHA)
        run.assert_not_called()
        after = deepcopy(saved['before'])
        after['hermes_calls'] += 1
        with patch.object(disabled, 'state_path', return_value=Mock(read_text=Mock(return_value=json.dumps(saved)))), \
                patch.object(disabled, 'inspect_service', return_value=None), \
                patch.object(disabled, 'run', return_value=json.dumps(after).encode()):
            with self.assertRaisesRegex(RuntimeError, 'hermes_disabled_provider_calls_changed'):
                disabled.check(SHA)

    def test_uncertain_reservations_stay_immutable_in_default_mode(self):
        saved = snapshot()
        after = deepcopy(saved['before'])
        after['unknown'] = []
        with patch.object(disabled, 'state_path', return_value=Mock(read_text=Mock(return_value=json.dumps(saved)))), \
                patch.object(disabled, 'inspect_service', return_value=None), \
                patch.object(disabled, 'run', return_value=json.dumps(after).encode()):
            with self.assertRaisesRegex(RuntimeError, 'replay_existing_unknown_charges_changed'):
                disabled.check(SHA)


if __name__ == '__main__':
    unittest.main()
