from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coaching_evidence import collect_rollout_snapshot, public_snapshot


def fixture():
    return {'schema_version': 1, 'snapshot_at': '2026-09-13T19:00:00Z',
        'window': {'since_inclusive': '2026-09-06T19:00:00Z', 'until_exclusive': '2026-09-13T19:00:00Z'},
        'ready_reports': [{'kind': 'replay', 'ready_reports': 4, 'coaching_ready_reports': 2,
            'coaching_unavailable_reports': 2, 'ready_with_confirmed_openai_call': 2}],
        'calls_created_in_window': [{'provider': 'openai', 'kind': 'replay', 'state': 'succeeded',
            'billing_status': 'settled', 'calls': 2, 'calls_with_recorded_charge': 2,
            'recorded_charge_microusd': 1234, 'retained_reservation_microusd': 0, 'unknown_calls': 0}],
        'failures': [{'source': 'coaching', 'code': 'OPENAI_REQUEST_TOO_LARGE', 'occurrences': 2}],
        'current_cumulative_budgets': [{'provider': 'openai', 'enabled': True, 'unexpired': True,
            'frozen': False, 'expires_at': '2026-09-19T23:59:59Z', 'limit_microusd': 5000000,
            'spent_microusd': 1234, 'reserved_microusd': 0, 'remaining_ceiling_microusd': 4998766,
            'ledger_recorded_microusd': 1234, 'ledger_held_microusd': 0}]}


class CoachingEvidenceTest(unittest.TestCase):
    def test_distinguishes_reports_from_confirmed_calls_and_retained_holds(self):
        data = fixture()
        call = data['calls_created_in_window'][0]
        call.update(state='unknown', billing_status='unknown', calls_with_recorded_charge=0,
                    unknown_calls=2, retained_reservation_microusd=1000000)
        result = public_snapshot(json.dumps(data))
        self.assertEqual(result['reports'][0]['ready_reports'], 4)
        self.assertEqual(result['reports'][0]['ready_with_confirmed_openai_call'], 2)
        self.assertEqual(result['openai_calls'][0]['retained_reservation_microusd'], 1000000)
        self.assertTrue(result['recorded_costs_are_not_provider_invoices'])

    def test_projects_only_allowed_aggregate_fields(self):
        data = fixture()
        data['private_text'] = 'private fixture'
        for collection in ('ready_reports', 'calls_created_in_window', 'failures', 'current_cumulative_budgets'):
            data[collection][0].update(owner_id='private fixture', output_text='private fixture')
        self.assertNotIn('private fixture', json.dumps(public_snapshot(json.dumps(data))))

    def test_rejects_unbounded_values_codes_and_free_text(self):
        base = fixture()
        cases = []
        for collection, key, value in (
                ('failures', 'code', 'OPENAI_ERROR provider response private fixture'),
                ('calls_created_in_window', 'state', 'private fixture'),
                ('ready_reports', 'kind', 'private fixture'),
                ('ready_reports', 'ready_reports', True),
                ('current_cumulative_budgets', 'spent_microusd', -1),
                ('current_cumulative_budgets', 'expires_at', 'private fixture'),
                ('current_cumulative_budgets', 'frozen', 'false')):
            data = deepcopy(base)
            data[collection][0][key] = value
            cases.append(json.dumps(data))
        cases.extend(('[]', 'x' * 131073))
        for raw in cases:
            with self.subTest(raw=raw[:40]), self.assertRaises((ValueError, KeyError, TypeError)):
                public_snapshot(raw)

    def test_probe_runs_only_read_only_cli_and_sanitizes_failures(self):
        command, event = Mock(return_value=json.dumps(fixture())), Mock()
        release = '/opt/narma/releases/' + 'a' * 40
        collect_rollout_snapshot(['ssh', 'fixture-host'], release, command, event)
        self.assertTrue(command.call_args.args[0][-1].endswith('python -m narma_video.pilot_evidence --days 7'))
        self.assertEqual(event.call_args.args, ('coaching_usage_snapshot',))
        command.side_effect = RuntimeError('private fixture')
        event.reset_mock()
        collect_rollout_snapshot(['ssh'], release, command, event)
        event.assert_called_once_with('coaching_usage_snapshot_unavailable', read_only=True, provider_calls_created=0)

    def test_monitor_uses_existing_installation_without_installing_or_restarting(self):
        command, event = Mock(return_value=json.dumps(fixture())), Mock()
        collect_rollout_snapshot(['ssh'], '/opt/narma/current', command, event)
        self.assertTrue(command.call_args.args[0][-1].startswith('cd /opt/narma/current/services/video && '))
        self.assertEqual(event.call_args.args, ('coaching_usage_snapshot',))
        command.reset_mock()
        collect_rollout_snapshot(['ssh'], '/opt/narma/current; invalid', command, event)
        command.assert_not_called()


if __name__ == '__main__':
    unittest.main()
