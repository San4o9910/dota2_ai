"""Private deployment rollback metadata. Never stores environment variables."""
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys

ANALYSIS_SERVICES = ('worker', 'replay-worker')
HERMES_SERVICES = ('hermes-broker', 'hermes-runner')
SERVICES = ANALYSIS_SERVICES + HERMES_SERVICES
SHA = re.compile(r'^[0-9a-f]{40}$')
CONFIG = re.compile(r'^/opt/narma/releases/[0-9a-f]{40}/services/video/compose.yaml$')
ENV_FILE = '/opt/narma/secrets/video.env'

# Inspect the existing containers, whose environment may differ from the next
# release's env file. Importing these modules does not claim work or call a model.
# The salted connection identity is compared only in memory, never logged/saved.
DUAL_WORKER_PROBE = '''import hashlib,json,os,sys
from narma_video import db,resource_lock
assert os.environ.get('REPLAY_COACH_PROVIDER')=='openai_api'
assert resource_lock.MEDIA_LOCK==643847215
assert resource_lock.database is db.database
if sys.argv[1]=='worker':
 from narma_video import worker,video_analysis
 assert video_analysis.configured_mode()=='selective_v1'
 assert worker.media_slot is resource_lock.media_slot
 assert video_analysis.media_slot is resource_lock.media_slot
elif sys.argv[1]=='replay-worker':
 from narma_video import replay_worker
 assert replay_worker.media_slot is resource_lock.media_slot
else:
 raise AssertionError('unexpected_worker')
print(json.dumps({'contract':'openai-selective-media-lock-v1','lock':resource_lock.MEDIA_LOCK,
 'database':hashlib.sha256((sys.argv[2]+'\\0'+db.database_url()).encode()).hexdigest()}))
'''


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


def verify_analysis_workers(current):
    active = [item for item in current if item['running'] and item['service'] in ANALYSIS_SERVICES]
    if len(active) <= 1:
        return
    # Legacy video/Gemini/personal runtimes retain their one-worker restriction.
    # Both OpenAI containers must use one installed release and the same shared
    # PostgreSQL media lock before a rolling release may preserve their state.
    if ({item['service'] for item in active} != set(ANALYSIS_SERVICES)
            or len(active) != 2 or len({item['config'] for item in active}) != 1):
        raise RuntimeError('replay_activation_multiple_workers_running')
    challenge = secrets.token_hex(32)
    identities = []
    try:
        for item in active:
            proof = json.loads(run(['docker', 'exec', item['id'], 'python', '-c',
                DUAL_WORKER_PROBE, item['service'], challenge]))
            if (not isinstance(proof, dict) or set(proof) != {'contract', 'lock', 'database'}
                    or proof['contract'] != 'openai-selective-media-lock-v1'
                    or type(proof['lock']) is not int or proof['lock'] != 643847215
                    or not isinstance(proof['database'], str)
                    or not re.fullmatch('[0-9a-f]{64}', proof['database'])):
                raise ValueError('invalid_worker_proof')
            identities.append(proof['database'])
        if identities[0] != identities[1]:
            raise ValueError('different_worker_databases')
        if any(inspect_service(item['service']) != item for item in active):
            raise ValueError('worker_changed_during_snapshot')
    except (RuntimeError, ValueError, TypeError, KeyError):
        raise RuntimeError('replay_activation_multiple_workers_running') from None


DATABASE_STATE = '''import hashlib,json
from narma_video.db import database
with database() as c:
 b=c.execute("SELECT model,price_policy,expires_at::text,limit_microusd,spent_microusd,reserved_microusd,accounting_rub_per_usd FROM video_ai_budget WHERE id=1").fetchone()
 unknown=c.execute("SELECT id,reserved_microusd FROM video_provider_calls WHERE billing_status='unknown' ORDER BY id").fetchall()
 owners=c.execute("SELECT owner_id FROM portal_accounts ORDER BY owner_id").fetchall()
 bindings=c.execute("SELECT owner_id,account_id FROM portal_dota_profiles ORDER BY owner_id").fetchall()
 hermes_calls=c.execute("SELECT count(*) AS n FROM video_provider_calls WHERE call_kind='hermes'").fetchone()['n']
 identity=hashlib.sha256(json.dumps({'owners':owners,'bindings':bindings},sort_keys=True).encode()).hexdigest()
 print(json.dumps({'budget':b,'unknown':unknown,'owner_identity':identity,'hermes_calls':hermes_calls}))
'''


def snapshot(sha):
    os.umask(0o077)
    path = state_path(sha)
    current = [item for service in SERVICES if (item := inspect_service(service))]
    verify_analysis_workers(current)
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
