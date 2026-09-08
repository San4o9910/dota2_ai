"""Start isolated Hermes ready for owner login, without a generation smoke test."""
import argparse
import json
import os
from pathlib import Path
import re
import ssl
import sys
import tempfile
import time

from activate_hermes import REVISION, api_json, resource_check, verify_private_network
from activate_replays import LocalHTTPS, verify_preserved
from snapshot_worker_state import ANALYSIS_SERVICES, DATABASE_STATE, HERMES_SERVICES, compose, inspect_service, run, state_path, write_private

NETWORK_PROBE = '''import json,socket,urllib.request
runner=json.load(urllib.request.urlopen('http://127.0.0.1:8092/healthz',timeout=5))
assert runner['status']=='ready' and runner['runtime_revision']=='9fd44b4dfc44138b9e5d5689acb56c438364ff7b'
json.load(urllib.request.urlopen('http://hermes-broker:8091/healthz',timeout=5))
blocked=0
for host in ('generativelanguage.googleapis.com','api.openai.com','chatgpt.com','auth.openai.com','1.1.1.1'):
 try:
  connection=socket.create_connection((host,443),3)
 except OSError:
  blocked+=1
 else:
  connection.close()
  raise RuntimeError('hermes_external_egress_detected')
print(json.dumps({'broker_reachable':True,'blocked':blocked}))
'''


LEDGER_STATE = '''import hashlib,json
from narma_video.db import database
with database() as c:
 c.execute('SET TRANSACTION READ ONLY')
 budget=c.execute('SELECT row_to_json(b)::text AS value FROM video_ai_budget b ORDER BY id').fetchall()
 calls=c.execute('SELECT row_to_json(p)::text AS value FROM video_provider_calls p ORDER BY id').fetchall()
 total=c.execute('SELECT count(*) AS n FROM chatgpt_calls').fetchone()['n']
 digest=hashlib.sha256(json.dumps([budget,calls],sort_keys=True).encode()).hexdigest()
 print(json.dumps({'gemini_ledger_sha256':digest,'subscription_calls':total}))
'''

AUTH_STATE = '''import json,os
os.environ['PGOPTIONS']='-c default_transaction_read_only=on'
from narma_video.db import database
from narma_video.chatgpt_auth import connection_status
from narma_video.hermes_tasks import get_runtime_status
with database() as c:
 assert c.execute('SHOW transaction_read_only').fetchone()['transaction_read_only']=='on'
 names={row['name'] for row in c.execute('SELECT name FROM video_schema_migrations').fetchall()}
 assert {'013_chatgpt_auth.sql','014_chatgpt_calls.sql','015_hermes_chatgpt_provider.sql'} <= names
 for name in ('chatgpt_connections','chatgpt_calls'):
  assert c.execute('SELECT to_regclass(%s) AS r',('public.'+name,)).fetchone()['r']
 owners=c.execute('SELECT owner_id FROM portal_accounts').fetchall()
 assert len(owners)==1
 assert os.environ.get('REPLAY_COACH_PROVIDER')=='chatgpt_subscription'
 assert os.environ.get('HERMES_PROVIDER')=='chatgpt_subscription'
 state=connection_status(owners[0]['owner_id'])
 assert state['configured'] and state['can_connect']
 runtime=get_runtime_status(owners[0]['owner_id'])
 print(json.dumps({'auth_status':state['status'],'configured':True,'owner_count':1,
   'database_read_only':True,'provider':runtime['provider'],
   'services_ready':runtime['services_ready'],'readiness':runtime['readiness'],
   'runtime_verified':runtime['runtime_verified']}))
'''


def access_checks(hostname):
    checks = [('GET', '/api/integrations/chatgpt', 401), ('POST', '/api/integrations/chatgpt/connect', 403)]
    for method, path, expected in checks:
        connection = LocalHTTPS(hostname, timeout=10, context=ssl.create_default_context())
        try:
            connection.request(method, path, body=b'{}' if method == 'POST' else None,
                headers={'Host': hostname, 'Content-Type': 'application/json', 'Origin': 'https://invalid.example'})
            response = connection.getresponse()
            body = response.read(65537)
            if response.status != expected or len(body) > 65536:
                raise RuntimeError('hermes_chatgpt_access_check_failed')
        finally:
            connection.close()


def prepare(sha, hostname):
    os.umask(0o077)
    saved = json.loads(state_path(sha).read_text())
    if saved.get('release') != sha:
        raise RuntimeError('hermes_chatgpt_snapshot_invalid')
    if any(item and item['running'] for item in (inspect_service(name) for name in ANALYSIS_SERVICES)):
        raise RuntimeError('hermes_chatgpt_analysis_not_paused')
    config = '/opt/narma/releases/' + sha + '/services/video/compose.yaml'
    resources = resource_check()
    before = api_json(config, DATABASE_STATE)
    ledger_before = api_json(config, LEDGER_STATE)
    try:
        with tempfile.TemporaryDirectory(prefix='narma-chatgpt-readiness-') as directory:
            override = Path(directory) / 'paused.json'
            write_private(override, {'services': {'hermes-broker': {'environment': {'HERMES_RUNTIME_ENABLED': '0'}}}})
            run(compose(config) + ['--file', str(override), '--profile', 'hermes', 'up', '-d',
                '--no-deps', '--no-build', '--pull', 'never', *reversed(HERMES_SERVICES)], timeout=60)
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                try:
                    verify_private_network()
                    probe = json.loads(run(compose(config) + ['exec', '-T', 'hermes-runner',
                        '/opt/hermes-venv/bin/python', '-c', NETWORK_PROBE], timeout=20))
                    if probe == {'broker_reachable': True, 'blocked': 5}:
                        break
                except (RuntimeError, ValueError):
                    pass
                time.sleep(2)
            else:
                raise RuntimeError('hermes_chatgpt_private_runtime_not_ready')
            auth = api_json(config, AUTH_STATE)
            access_checks(hostname)
            ledger_after = api_json(config, LEDGER_STATE)
            after = api_json(config, DATABASE_STATE)
            verify_preserved(before, after)
            verify_preserved(saved.get('before'), after)
            if ledger_before != ledger_after:
                raise RuntimeError('hermes_chatgpt_generation_during_preflight')
        # All no-generation gates have passed. The configured provider blocks
        # scheduling until this owner completes ChatGPT authorization. An
        # already authorized owner resumes ordinary work after this point.
        run(compose(config) + ['--profile', 'hermes', 'up', '-d', '--no-deps', '--no-build',
            '--pull', 'never', '--force-recreate', 'hermes-broker'], timeout=60)
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            auth = api_json(config, AUTH_STATE)
            if auth['services_ready'] and auth['provider'] == 'chatgpt_subscription':
                result = {'event': 'hermes_chatgpt_auth_ready', 'release': sha,
                    'runtime_revision': REVISION, 'provider': 'chatgpt_subscription',
                    'network_isolation_verified': True, 'generation_smoke_performed': False,
                    'provider_calls_created_by_preflight': 0, 'gemini_ledger_preserved': True,
                    'auth': auth, 'resources': resources}
                write_private(Path('/opt/narma/checks/chatgpt-auth-readiness.json'), result)
                return result
            time.sleep(2)
        raise RuntimeError('hermes_chatgpt_scheduler_heartbeat_timeout')
    except Exception:
        run(compose(config) + ['--profile', 'hermes', 'stop', '--timeout', '20', *HERMES_SERVICES])
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('sha'); parser.add_argument('hostname')
    args = parser.parse_args()
    try:
        print(json.dumps(prepare(args.sha, args.hostname)), flush=True)
    except Exception as error:
        code = str(error) if isinstance(error, RuntimeError) and re.fullmatch('hermes_[a-z_]{1,100}', str(error)) else 'hermes_chatgpt_preparation_failed'
        print(json.dumps({'event': 'hermes_activation_failure', 'code': code}), flush=True)
        sys.exit(1)
