"""Verify a product release preserves an already stopped Hermes runtime.

This command does not stop services, start a review or change the allowance.
An active previous runtime needs the separate explicit activation path, with
its existing settlement, source-proof and network checks.
"""
import json
import re
import sys

from activate_replays import verify_preserved
from snapshot_worker_state import (
    DATABASE_STATE, HERMES_SERVICES, compose, inspect_service, run, state_path,
)


def check(sha):
    saved = json.loads(state_path(sha).read_text())
    if saved.get('release') != sha or not isinstance(saved.get('services'), list):
        raise RuntimeError('hermes_disabled_snapshot_invalid')
    if any(item['running'] for item in saved['services'] if item['service'] in HERMES_SERVICES):
        raise RuntimeError('hermes_disabled_previous_runtime_active')
    if any(item and item['running'] for item in (inspect_service(service) for service in HERMES_SERVICES)):
        raise RuntimeError('hermes_disabled_runtime_active')
    config = '/opt/narma/releases/' + sha + '/services/video/compose.yaml'
    before = saved.get('before')
    if before is not None:
        after = json.loads(run(compose(config) + ['exec', '-T', 'api', 'python', '-c', DATABASE_STATE]))
        verify_preserved(before, after)
        if type(before.get('hermes_calls')) is not int or before['hermes_calls'] != after.get('hermes_calls'):
            raise RuntimeError('hermes_disabled_provider_calls_changed')
    return {'event': 'hermes_runtime_preserved', 'release': sha, 'automatic_tracking': False,
            'previous_runtime_disabled': True, 'services_stopped': True,
            'provider_calls_created': 0, 'existing_account_and_budget_preserved': before is not None}


if __name__ == '__main__':
    try:
        if len(sys.argv) != 2:
            raise RuntimeError('hermes_disabled_arguments_invalid')
        print(json.dumps(check(sys.argv[1])), flush=True)
    except Exception as error:
        code = str(error) if isinstance(error, RuntimeError) and re.fullmatch('hermes_[a-z_]{1,100}', str(error)) else 'hermes_disabled_check_failed'
        print(json.dumps({'event': 'hermes_activation_failure', 'code': code}), flush=True)
        sys.exit(1)
