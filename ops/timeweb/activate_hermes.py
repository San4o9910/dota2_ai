"""Activate pinned Hermes on the existing host with one accounted review.

The first review uses the existing allowance and immutable player evidence.
An identical verified snapshot is reused on later releases. No uncertain charge
is refunded and a failed paid attempt is never retried by this activation.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time

from activate_replays import verify_preserved
from snapshot_worker_state import DATABASE_STATE, HERMES_SERVICES, compose, inspect_service, run, state_path, write_private

REVISION = '9fd44b4dfc44138b9e5d5689acb56c438364ff7b'
MIN_AVAILABLE_MEMORY = 1536 * 1024**2
MIN_DISK_FREE = 2 * 1024**3


def resource_check(meminfo=None, disk_free=None):
    memory = {}
    for line in (meminfo if meminfo is not None else Path('/proc/meminfo').read_text()).splitlines():
        name, value = line.split(':', 1)
        memory[name] = int(value.strip().split()[0]) * 1024
    free = shutil.disk_usage('/opt/narma').free if disk_free is None else disk_free
    if memory.get('MemAvailable', 0) < MIN_AVAILABLE_MEMORY:
        raise RuntimeError('hermes_memory_headroom_insufficient')
    if free < MIN_DISK_FREE:
        raise RuntimeError('hermes_disk_headroom_insufficient')
    return {'memory_total_bytes': memory.get('MemTotal'),
            'memory_available_bytes': memory['MemAvailable'], 'disk_free_bytes': free}


BEFORE = '''import json
from narma_video.db import database
from narma_video import budget
from narma_video.hermes_tasks import latest_valid_review
with database() as c:
 assert c.execute("SELECT 1 FROM video_schema_migrations WHERE name='011_hermes_runtime.sql'").fetchone()
 state=budget.status(c)
 owners=c.execute('SELECT owner_id FROM portal_dota_profiles').fetchall()
 existing=any(latest_valid_review(owner['owner_id']) for owner in owners)
 assert existing or (state['enabled'] and state['available_microusd']>=budget.RESERVATION)
 count=c.execute("SELECT count(*) AS n FROM video_provider_calls WHERE call_kind='hermes'").fetchone()['n']
 print(json.dumps({'budget':state,'hermes_calls':count,'verified_review_available':existing}))
'''

PROOF = '''import json
from narma_video.db import database
from narma_video.hermes_tasks import latest_valid_review,RUNTIME_REVISION
with database() as c:
 owners=c.execute("SELECT DISTINCT owner_id FROM hermes_tasks WHERE state='succeeded'").fetchall()
 verified=[]
 for owner in owners:
  review=latest_valid_review(owner['owner_id'])
  if review:
   verified.append(review)
 if not verified:
  raise RuntimeError('hermes_review_unverified')
 item=verified[0]
 task=c.execute("SELECT id,review,runtime_revision FROM hermes_tasks WHERE id=%s AND state='succeeded'",(item['id'],)).fetchone()
 assert task and task['runtime_revision']==RUNTIME_REVISION
 calls=c.execute("SELECT id,billing_status,charged_microusd FROM video_provider_calls WHERE hermes_task_id=%s AND call_kind='hermes'",(task['id'],)).fetchall()
 assert len(calls)==1 and calls[0]['billing_status']=='settled' and calls[0]['charged_microusd'] is not None
 count=c.execute("SELECT count(*) AS n FROM video_provider_calls WHERE call_kind='hermes'").fetchone()['n']
 review=task['review']
 print(json.dumps({'verified':True,'runtime_revision':RUNTIME_REVISION,'hermes_calls':count,
  'review_id':str(task['id']),'patterns':len(review['patterns']),'goals':len(review['goals']),
  'charged_microusd':calls[0]['charged_microusd'],'billing_status':calls[0]['billing_status']}))
'''

HEARTBEAT = '''import json
from narma_video.db import database
with database() as c:
 row=c.execute("SELECT runtime_revision,automatic_tracking,last_seen>now()-interval '45 seconds' AS fresh FROM hermes_workers WHERE id='scheduler'").fetchone()
 print(json.dumps(dict(row) if row else {}))
'''

NETWORK_PROBE = '''import json,socket,urllib.request
health=json.load(urllib.request.urlopen('http://hermes-broker:8091/healthz',timeout=5))
blocked=0
for host in ('generativelanguage.googleapis.com','api.openai.com','1.1.1.1'):
 try:
  connection=socket.create_connection((host,443),3)
 except OSError:
  blocked+=1
 else:
  connection.close()
  raise RuntimeError('hermes_external_egress_detected')
print(json.dumps({'broker_reachable':True,'blocked':blocked}))
'''


def api_json(config, code, timeout=30):
    return json.loads(run(compose(config) + ['exec', '-T', 'api', 'python', '-c', code], timeout=timeout))


def verify_private_network():
    runner = inspect_service('hermes-runner')
    if not runner or not runner['running']:
        raise RuntimeError('hermes_runner_not_running')
    networks = json.loads(run(['docker', 'inspect', '--format',
        '{{json .NetworkSettings.Networks}}', runner['id']]))
    if set(networks) != {'narma-video_hermes-private'}:
        raise RuntimeError('hermes_runner_network_invalid')
    internal = run(['docker', 'network', 'inspect', '--format', '{{.Internal}}',
                    'narma-video_hermes-private']).strip()
    if internal != b'true':
        raise RuntimeError('hermes_runner_network_not_internal')


def run_one_review(config, reuse):
    if reuse:
        code = ('import json; from narma_video.hermes_tasks import refresh_heartbeat; '
                'refresh_heartbeat(); print(json.dumps({"status":"idle"}))')
        return json.loads(run(compose(config) + ['exec', '-T', 'hermes-broker', 'python', '-c', code]))
    code = 'import json; from narma_video.hermes_tasks import process_once; print(json.dumps(process_once()))'
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        result = json.loads(run(compose(config) + ['exec', '-T', 'hermes-broker',
            'python', '-c', code], timeout=230))
        # Idle may mean a replay parser is using the existing VM's memory.
        # Wait only before a task is claimed; never retry a failed paid attempt.
        if result.get('status') != 'idle':
            return result
        time.sleep(5)
    raise RuntimeError('hermes_first_review_wait_timeout')


def activate(sha):
    os.umask(0o077)
    saved = json.loads(state_path(sha).read_text())
    if saved.get('release') != sha:
        raise RuntimeError('hermes_activation_snapshot_invalid')
    config = '/opt/narma/releases/' + sha + '/services/video/compose.yaml'
    resources = resource_check()
    before = api_json(config, DATABASE_STATE)
    ledger_before = api_json(config, BEFORE)
    try:
        # Start the exact tested broker with its scheduler paused. The task-level
        # credential still permits the one explicitly invoked accounted review.
        with tempfile.TemporaryDirectory(prefix='narma-hermes-activation-') as directory:
            override = Path(directory) / 'paused.json'
            write_private(override, {'services': {'hermes-broker': {'environment': {'HERMES_RUNTIME_ENABLED': '0'}}}})
            run(compose(config) + ['--file', str(override), '--profile', 'hermes',
                'up', '-d', '--no-deps', '--no-build', '--pull', 'never', *reversed(HERMES_SERVICES)], timeout=60)
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                try:
                    verify_private_network()
                    evidence = json.loads(run(compose(config) + ['exec', '-T', 'hermes-runner',
                        '/opt/hermes-venv/bin/python', '-c', NETWORK_PROBE], timeout=20))
                    if evidence == {'broker_reachable': True, 'blocked': 3}:
                        break
                except (RuntimeError, ValueError):
                    pass
                time.sleep(2)
            else:
                raise RuntimeError('hermes_private_runtime_not_ready')
            result = run_one_review(config, ledger_before['verified_review_available'])
            if result.get('status') not in ('succeeded', 'idle'):
                code = result.get('error_code', '')
                safe = code.lower() if isinstance(code, str) and re.fullmatch('HERMES_[A-Z_]{1,60}', code) else 'unknown'
                raise RuntimeError('hermes_first_review_failed_' + safe)
            proof = api_json(config, PROOF)
            after = api_json(config, DATABASE_STATE)
            verify_preserved(before, after)
            calls_created = proof['hermes_calls'] - ledger_before['hermes_calls']
            if calls_created not in (0, 1):
                raise RuntimeError('hermes_activation_call_limit_exceeded')
            if proof.get('verified') is not True or proof.get('runtime_revision') != REVISION:
                raise RuntimeError('hermes_runtime_provenance_invalid')
        # Recreate without the paused override only after runtime, source
        # evidence and shared-ledger settlement have all passed.
        run(compose(config) + ['--profile', 'hermes', 'up', '-d', '--no-deps',
            '--no-build', '--pull', 'never', '--force-recreate', 'hermes-broker'], timeout=60)
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            state = api_json(config, HEARTBEAT)
            if state.get('fresh') is True and state.get('automatic_tracking') is True and state.get('runtime_revision') == REVISION:
                activated = {'event': 'hermes_runtime_ready', 'release': sha,
                    'runtime_revision': REVISION, 'automatic_tracking': True,
                    'activated_at': datetime.now(timezone.utc).isoformat(),
                    'resources': resources, 'network_isolation_verified': True,
                    'provider_calls_created': calls_created, 'review': proof,
                    'budget_before': before['budget'], 'budget_after': after['budget']}
                write_private(Path('/opt/narma/checks/hermes-activation.json'), activated)
                return activated
            time.sleep(2)
        raise RuntimeError('hermes_scheduler_heartbeat_timeout')
    except Exception:
        run(compose(config) + ['--profile', 'hermes', 'stop', '--timeout', '20', *HERMES_SERVICES])
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('sha')
    args = parser.parse_args()
    try:
        print(json.dumps(activate(args.sha)), flush=True)
    except Exception as error:
        code = str(error) if isinstance(error, RuntimeError) and re.fullmatch('hermes_[a-z_]{1,100}', str(error)) else 'hermes_activation_failed'
        print(json.dumps({'event': 'hermes_activation_failure', 'code': code}), flush=True)
        sys.exit(1)
