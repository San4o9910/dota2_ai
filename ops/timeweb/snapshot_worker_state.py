"""Private deployment rollback metadata. Never stores environment variables."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

SERVICES = ('worker', 'replay-worker')
SHA = re.compile(r'^[0-9a-f]{40}$')
CONFIG = re.compile(r'^/opt/narma/releases/[0-9a-f]{40}/services/video/compose.yaml$')
ENV_FILE = '/opt/narma/secrets/video.env'


def run(args, timeout=30, input=None):
    try:
        result = subprocess.run(args, input=input, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError('replay_activation_command_failed') from None
    if result.returncode:
        raise RuntimeError('replay_activation_command_failed')
    return result.stdout


def compose(config):
    if not CONFIG.fullmatch(str(config)):
        raise RuntimeError('replay_activation_config_invalid')
    return ['docker', 'compose', '--project-name', 'narma-video', '--env-file', ENV_FILE,
            '--file', str(config)]


def state_path(sha):
    if not SHA.fullmatch(sha):
        raise RuntimeError('replay_activation_release_invalid')
    return Path('/opt/narma/checks') / ('workers-before-' + sha + '.json')


def write_private(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix('.new')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(value, stream, separators=(',', ':')); stream.flush(); os.fsync(stream.fileno())
    temporary.replace(path)


def inspect_service(service):
    ids = run(['docker', 'ps', '--all', '--quiet',
        '--filter', 'label=com.docker.compose.project=narma-video',
        '--filter', 'label=com.docker.compose.oneoff=False',
        '--filter', 'label=com.docker.compose.service=' + service]).splitlines()
    if len(ids) > 1:
        raise RuntimeError('replay_activation_container_ambiguous')
    if not ids:
        return None
    identifier = ids[0].decode()
    # Output only explicitly selected non-secret fields; never docker inspect env.
    template = '{"id":{{json .Id}},"image":{{json .Image}},"running":{{json .State.Running}},"config":{{json (index .Config.Labels "com.docker.compose.project.config_files")}}}'
    item = json.loads(run(['docker', 'inspect', '--format', template, identifier]))
    # Rollback uses a temporary image-only override. Its exact image ID is
    # captured separately; the durable release file remains the first config.
    if isinstance(item.get('config'), str):
        item['config'] = item['config'].split(',')[0]
    if (not re.fullmatch(r'[0-9a-f]{64}', item.get('id', ''))
            or not re.fullmatch(r'sha256:[0-9a-f]{64}', item.get('image', ''))
            or type(item.get('running')) is not bool
            or not CONFIG.fullmatch(item.get('config', ''))):
        raise RuntimeError('replay_activation_container_invalid')
    return {'service': service, **item}


DATABASE_STATE = '''import hashlib,json
from narma_video.db import database
with database() as c:
 b=c.execute("SELECT model,price_policy,expires_at::text,limit_microusd,spent_microusd,reserved_microusd,accounting_rub_per_usd FROM video_ai_budget WHERE id=1").fetchone()
 unknown=c.execute("SELECT id,reserved_microusd FROM video_provider_calls WHERE billing_status='unknown' ORDER BY id").fetchall()
 owners=c.execute("SELECT owner_id FROM portal_accounts ORDER BY owner_id").fetchall()
 bindings=c.execute("SELECT owner_id,account_id FROM portal_dota_profiles ORDER BY owner_id").fetchall()
 identity=hashlib.sha256(json.dumps({'owners':owners,'bindings':bindings},sort_keys=True).encode()).hexdigest()
 print(json.dumps({'budget':b,'unknown':unknown,'owner_identity':identity}))
'''


def snapshot(sha):
    os.umask(0o077)
    path = state_path(sha)
    current = [item for service in SERVICES if (item := inspect_service(service))]
    if sum(item['running'] for item in current) > 1:
        raise RuntimeError('replay_activation_multiple_workers_running')
    config = '/opt/narma/releases/' + sha + '/services/video/compose.yaml'
    before = None
    # An established portal must have its account and allowance recorded before
    # migrations. Failure reading an existing API is a deployment blocker.
    api_ids = run(['docker', 'ps', '--quiet', '--filter', 'label=com.docker.compose.project=narma-video',
                   '--filter', 'label=com.docker.compose.service=api']).splitlines()
    if len(api_ids) > 1:
        raise RuntimeError('replay_activation_api_ambiguous')
    if api_ids:
        before = json.loads(run(compose(config) + ['exec', '-T', 'api', 'python', '-c', DATABASE_STATE]))
    write_private(path, {'release': sha, 'services': current, 'before': before})
    print(json.dumps({'event': 'replay_worker_snapshot_ready',
        'running_services': [item['service'] for item in current if item['running']],
        'existing_account_and_budget_captured': before is not None}), flush=True)


if __name__ == '__main__':
    try:
        if len(sys.argv) != 2: raise RuntimeError('replay_activation_release_invalid')
        snapshot(sys.argv[1])
    except Exception:
        print(json.dumps({'event': 'replay_activation_failure', 'code': 'replay_worker_snapshot_failed'}), flush=True)
        sys.exit(1)
