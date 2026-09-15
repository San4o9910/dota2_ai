"""GitHub-runner bridge: inspect/install one key on the existing pinned VPS.

No host provisioning, deployment, service restart, budget change or model call.
Temporary SSH access follows the existing Timeweb operational path and is removed.
"""
import argparse
import json
import os
from pathlib import Path
import shlex
import tempfile
import time

from openai_secrets import validate_key, validate_release
from pilot import Cloud, CheckError, address, command, event, pinned_existing_server


def payload_for(mode, release, environment):
    validate_release(release)
    if mode not in ('inspect', 'install-key'):
        raise RuntimeError('openai_support_mode_invalid')
    payload = {'mode': mode, 'expected_release': release}
    if mode == 'install-key':
        key = environment.get('OPENAI_API_KEY')
        validate_key(key)
        payload['key'] = key
    return payload


def public_result(result, release):
    """Never forward an unexpected remote field or arbitrary diagnostic text."""
    booleans = ('key_present', 'key_format_valid', 'model_supported',
                'provider_access_verified', 'services_changed', 'budgets_changed')
    expected = set(booleans) | {'event', 'release', 'replay_provider', 'hermes_provider',
                                'video_mode', 'generation_requests'}
    if (not isinstance(result, dict) or set(result) != expected
            or result.get('event') != 'openai_server_configuration' or result.get('release') != release
            or any(type(result.get(name)) is not bool for name in booleans)
            or type(result.get('generation_requests')) is not int or result['generation_requests'] != 0
            or any(result[name] for name in ('provider_access_verified', 'services_changed', 'budgets_changed'))
            or result.get('replay_provider') not in {'gemini', 'chatgpt_subscription', 'openai_api', 'unset_or_unknown'}
            or result.get('hermes_provider') not in {'gemini', 'chatgpt_subscription', 'openai_api', 'unset_or_unknown'}
            or result.get('video_mode') not in {'full_frames_v1', 'selective_v1', 'unknown'}):
        raise CheckError('openai_support_result_invalid')
    return result


def execute(mode, release):
    payload = payload_for(mode, release, os.environ)
    cloud = Cloud()
    server = pinned_existing_server(cloud)
    ssh_id = None
    with tempfile.TemporaryDirectory(prefix='narma-openai-support-') as directory:
        directory = Path(directory)
        key = directory / 'key'
        command(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(key)])
        try:
            created = cloud.call('POST', '/api/v1/ssh-keys', {
                'name': 'narma-openai-configuration',
                'body': key.with_suffix('.pub').read_text().strip(), 'is_default': False})
            ssh_id = created['ssh_key']['id']
            if type(ssh_id) is not int or ssh_id <= 0:
                raise CheckError('openai_support_key_invalid')
            cloud.call('POST', f"/api/v1/servers/{server['id']}/ssh-keys", {'ssh_key_ids': [ssh_id]})
            ssh = ['ssh', '-i', str(key), '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes',
                '-o', 'StrictHostKeyChecking=accept-new',
                '-o', 'UserKnownHostsFile=' + str(directory / 'known_hosts'),
                '-o', 'ConnectTimeout=8', '-o', 'ServerAliveInterval=15',
                'root@' + address(server)]
            for attempt in range(12):
                try:
                    command(ssh + ['true'], timeout=15)
                    break
                except CheckError:
                    if attempt == 11:
                        raise CheckError('openai_support_ssh_unavailable') from None
                    time.sleep(5)
            # Public, reviewed code goes in argv; the credential goes only through
            # encrypted SSH stdin and is never interpolated into shell command text.
            code = Path(__file__).with_name('openai_secrets.py').read_text()
            output = command(ssh + ['python3 -c ' + shlex.quote(code)],
                input=json.dumps(payload).encode(), timeout=60)
            result = public_result(json.loads(output), release)
            print(json.dumps(result), flush=True)
        finally:
            if ssh_id is not None:
                try:
                    cloud.call('DELETE', f"/api/v1/servers/{server['id']}/ssh-keys/{ssh_id}")
                except CheckError:
                    event('openai_support_binding_cleanup_unconfirmed')
                try:
                    cloud.call('DELETE', f'/api/v1/ssh-keys/{ssh_id}')
                except CheckError:
                    event('openai_support_key_cleanup_unconfirmed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=('inspect', 'install-key'), default='inspect')
    parser.add_argument('--expected-release', required=True)
    args = parser.parse_args()
    try:
        execute(args.mode, args.expected_release)
    except Exception:
        # Never print exception text from libraries, remote stderr or input payload.
        event('openai_support_failed', code='openai_configuration_not_completed')
        raise SystemExit(1) from None
