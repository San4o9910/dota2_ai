"""Switch the existing pilot to .dem analysis without creating a paid test job.

Requires a snapshot taken BEFORE bootstrap stops workers. Uses the existing
PostgreSQL volume, owner and allowance; does not rotate or display secrets.
"""
import argparse
from datetime import datetime, timezone
import http.client
import json
import os
from pathlib import Path
import re
import socket
import ssl
import sys
import tempfile
import time

from snapshot_worker_state import (
    CONFIG, DATABASE_STATE, SERVICES, compose, inspect_service, run, state_path, write_private,
)


class LocalHTTPS(http.client.HTTPSConnection):
    def connect(self):
        self.sock = self._context.wrap_socket(socket.create_connection(('127.0.0.1', 443), self.timeout),
                                             server_hostname=self.host)


def anonymous_checks(hostname):
    checks = [('/livez', 200), ('/hero-pool', 200), ('/api/session', 200),
              ('/api/replays', 401), ('/api/hero-pool', 401), ('/v1/videos', 401)]
    for path, expected in checks:
        connection = LocalHTTPS(hostname, timeout=10, context=ssl.create_default_context())
        try:
            connection.request('GET', path, headers={'Host': hostname})
            response = connection.getresponse()
            body = response.read(65537)
            if response.status != expected or len(body) > 65536:
                raise RuntimeError('replay_https_access_check_failed')
            if path == '/api/session':
                session = json.loads(body)
                if session.get('authenticated') is not False or session.get('user') is not None:
                    raise RuntimeError('replay_https_access_check_failed')
        finally:
            connection.close()


PARSER_CHECK = '''import hashlib,json,pathlib,subprocess
import narma_video.replay_worker,narma_video.replay_jobs,narma_video.replay_report,narma_video.replay_coach
root=pathlib.Path('/opt/narma/replay')
assert (root/'target/classes/vision/narma/replay/ReplayProbe.class').is_file()
for item in json.loads((root/'dependencies.lock.json').read_text()):
 if item.get('buildOnly'): continue
 p=root/'target/dependency'/(item['artifact']+'.jar')
 assert p.stat().st_size==item['bytes'] and hashlib.sha256(p.read_bytes()).hexdigest()==item['sha256']
v=subprocess.run(['java','-version'],capture_output=True,timeout=10)
assert v.returncode==0 and 'version "17.' in (v.stdout+v.stderr).decode()
from narma_video.replay_runtime_check import check_runtime
check_runtime()
print('REPLAY_RUNTIME_OK')
'''

SCHEMA_CHECK = '''import json
from narma_video.db import database
with database() as c:
 names={r['name'] for r in c.execute('SELECT name FROM video_schema_migrations').fetchall()}
 assert {'005_replay_analysis.sql','006_replay_shared_ai_budget.sql','007_hero_pool.sql'}<=names
 assert c.execute("SELECT to_regclass('public.replay_jobs') AS r").fetchone()['r']
 assert c.execute("SELECT to_regclass('public.replay_workers') AS r").fetchone()['r']
 assert c.execute("SELECT 1 FROM pg_constraint WHERE conname='provider_call_exactly_one_job' AND conrelid='video_provider_calls'::regclass").fetchone()
 print('REPLAY_SCHEMA_OK')
'''

POOL_CHECK = '''import json
from narma_video.db import database
from narma_video.hero_pool import get_pool
with database() as c:
 owners=c.execute('SELECT owner_id FROM portal_dota_profiles').fetchall()
counts=[]
for owner in owners:
 pool=get_pool(owner['owner_id'])
 assert pool['schema_version']=='narma.hero-pool.v1'
 assert len({m['match_id'] for m in pool['matches']})==len(pool['matches'])
 assert pool['summary']['wins']+pool['summary']['losses']+pool['summary']['unknown']==pool['summary']['matches']
 counts.append({'matches':pool['summary']['matches'],'heroes':len(pool['heroes'])})
print(json.dumps({'verified':True,'owners':len(owners),'counts':counts}))
'''


def verify_preserved(before, after):
    if before is None:
        return
    old, new = before['budget'], after['budget']
    for key in ('model', 'price_policy', 'expires_at', 'limit_microusd', 'accounting_rub_per_usd'):
        if new[key] != old[key]:
            raise RuntimeError('replay_existing_budget_changed')
    if new['spent_microusd'] < old['spent_microusd']:
        raise RuntimeError('replay_existing_budget_changed')
    # Unknown charges may never be refunded by a deployment. Concurrent known
    # settlements can legitimately reduce total reserved balance before stop.
    unknown = {row['id']: row['reserved_microusd'] for row in after['unknown']}
    if any(unknown.get(row['id']) != row['reserved_microusd'] for row in before['unknown']):
        raise RuntimeError('replay_existing_unknown_charges_changed')
    if new['reserved_microusd'] < sum(unknown.values()):
        raise RuntimeError('replay_existing_budget_changed')
    if before['owner_identity'] != after['owner_identity']:
        raise RuntimeError('replay_existing_owner_changed')


def rollback(config, snapshot):
    # Always stop the new worker first: old + new workers must not compete for RAM.
    run(compose(config) + ['--profile', 'analysis', 'stop', '--timeout', '20', 'replay-worker'])
    restored = []
    for previous in snapshot['services']:
        if not previous['running']:
            continue
        service = previous['service']
        if service not in SERVICES or not CONFIG.fullmatch(previous['config']):
            raise RuntimeError('replay_rollback_snapshot_invalid')
        current = inspect_service(service)
        if current and current['id'] == previous['id'] and current['image'] == previous['image']:
            # The stopped old video container retains the exact image/config.
            run(['docker', 'start', previous['id']])
        else:
            # Repeat deployments may have recreated a previous replay container.
            # Restore its previous release config and pinned local image only.
            run(['docker', 'image', 'inspect', '--format', '{{.Id}}', previous['image']])
            with tempfile.TemporaryDirectory(prefix='narma-replay-rollback-') as directory:
                override = Path(directory) / 'image.json'
                write_private(override, {'services': {service: {'image': previous['image']}}})
                run(compose(previous['config']) + ['--file', str(override), '--profile', 'analysis',
                    'up', '-d', '--no-deps', '--no-build', '--pull', 'never', service], timeout=90)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            state = inspect_service(service)
            if state and state['running'] and state['image'] == previous['image']:
                restored.append(service)
                break
            time.sleep(1)
        else:
            raise RuntimeError('replay_rollback_worker_not_running')
    return restored


def activate(sha, hostname):
    os.umask(0o077)
    path = state_path(sha)
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?', hostname) or '..' in hostname:
        raise RuntimeError('replay_https_hostname_invalid')
    snapshot = json.loads(path.read_text())
    if snapshot.get('release') != sha:
        raise RuntimeError('replay_activation_snapshot_invalid')
    config = '/opt/narma/releases/' + sha + '/services/video/compose.yaml'
    try:
        # bootstrap stopped both before migrations; enforce again before checking.
        run(compose(config) + ['--profile', 'analysis', 'stop', '--timeout', '20', *SERVICES])
        if any(item and item['running'] for item in (inspect_service(service) for service in SERVICES)):
            raise RuntimeError('replay_previous_worker_still_running')
        run(compose(config) + ['exec', '-T', 'api', 'python', '-c', SCHEMA_CHECK])
        pool_status = json.loads(run(compose(config) + ['exec', '-T', 'api', 'python', '-c', POOL_CHECK]))
        if pool_status.get('verified') is not True:
            raise RuntimeError('replay_hero_pool_check_failed')
        after = json.loads(run(compose(config) + ['exec', '-T', 'api', 'python', '-c', DATABASE_STATE]))
        verify_preserved(snapshot.get('before'), after)
        # Compose's default image name is project-service. Confirm it exists so
        # `run` cannot trigger an implicit missing-image build on the live host.
        run(['docker', 'image', 'inspect', '--format', '{{.Id}}', 'narma-video-replay-worker'])
        if run(compose(config) + ['--profile', 'analysis', 'run', '--rm', '--no-deps',
            '--pull', 'never', '--entrypoint', 'python', 'replay-worker', '-c', PARSER_CHECK], timeout=70).strip() != b'REPLAY_RUNTIME_OK':
            raise RuntimeError('replay_runtime_check_failed')
        anonymous_checks(hostname)
        started = datetime.now(timezone.utc).isoformat()
        heartbeat = '''import json
from narma_video.db import database
with database() as c:
 row=c.execute("SELECT last_seen>%%s::timestamptz AS fresh FROM replay_workers WHERE id='replay'",(%r,)).fetchone()
 print(json.dumps({'fresh':bool(row and row['fresh'])}))
''' % started
        run(compose(config) + ['--profile', 'analysis', 'up', '-d', '--no-deps', '--no-build', '--pull', 'never', 'replay-worker'])
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            current = inspect_service('replay-worker')
            status = json.loads(run(compose(config) + ['exec', '-T', 'api', 'python', '-c', heartbeat], timeout=15))
            if current and current['running'] and status.get('fresh') is True:
                if (video := inspect_service('worker')) and video['running']:
                    raise RuntimeError('replay_video_worker_must_remain_stopped')
                write_private(Path('/opt/narma/checks/replay-worker-activation.json'),
                    {'release': sha, 'activated_at': started, 'worker': 'replay', 'synthetic_paid_calls': 0})
                return {'event': 'replay_pipeline_ready', 'worker_enabled': True, 'fresh_worker_heartbeat': True,
                        'video_worker_stopped': True, 'schema_verified': True, 'parser_runtime_verified': True,
                        'existing_account_and_budget_preserved': snapshot.get('before') is not None,
                        'hero_pool': pool_status,
                        'synthetic_paid_calls': 0, 'anonymous_replays_status': 401}
            time.sleep(2)
        raise RuntimeError('replay_worker_heartbeat_timeout')
    except Exception:
        try:
            restored = rollback(config, snapshot)
            print(json.dumps({'event': 'replay_activation_rollback', 'restored_services': restored}), flush=True)
        except Exception:
            print(json.dumps({'event': 'replay_activation_failure', 'code': 'replay_rollback_unconfirmed'}), flush=True)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('sha'); parser.add_argument('hostname'); parser.add_argument('--rollback-only', action='store_true'); args = parser.parse_args()
    try:
        if args.rollback_only:
            saved = json.loads(state_path(args.sha).read_text())
            if saved.get('release') != args.sha:
                raise RuntimeError('replay_activation_snapshot_invalid')
            restored = rollback('/opt/narma/releases/' + args.sha + '/services/video/compose.yaml', saved)
            print(json.dumps({'event': 'replay_activation_rollback', 'restored_services': restored}), flush=True)
        else:
            print(json.dumps(activate(args.sha, args.hostname)), flush=True)
    except Exception as error:
        code = str(error) if isinstance(error, RuntimeError) and re.fullmatch('replay_[a-z_]{1,100}', str(error)) else 'replay_activation_failed'
        print(json.dumps({'event': 'replay_activation_failure', 'code': code}), flush=True)
        sys.exit(1)
