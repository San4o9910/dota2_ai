"""Read-only API preflight and explicit existing-host release preparation.

`--status-only` never changes services/configuration/budgets. `prepare()` is used
inside the normal release cutover after its worker snapshot/stop phase. It makes
no inference smoke request; normal queues resume only after the release gates.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import tempfile
import time

from activate_hermes import REVISION, api_json, resource_check, verify_private_network
from activate_replays import verify_preserved
from prepare_chatgpt_auth import NETWORK_PROBE
from snapshot_worker_state import DATABASE_STATE, SERVICES, compose, inspect_service, run, state_path, write_private

PRICE_EXPIRES = datetime(2026, 11, 21, tzinfo=timezone.utc)


def allowance_input(limit=None, expires=None, *, now=None):
    if limit in (None, '') and expires in (None, ''):
        return None
    if not isinstance(limit, str) or not re.fullmatch(r'[0-9]{1,8}', limit) or not 0 < int(limit) <= 10_000_000:
        raise RuntimeError('openai_explicit_allowance_invalid')
    if not isinstance(expires, str) or not re.fullmatch(r'2026-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z', expires):
        raise RuntimeError('openai_explicit_expiry_invalid')
    try:
        parsed = datetime.fromisoformat(expires.replace('Z', '+00:00'))
    except ValueError:
        raise RuntimeError('openai_explicit_expiry_invalid') from None
    if not (now or datetime.now(timezone.utc)) < parsed <= PRICE_EXPIRES:
        raise RuntimeError('openai_explicit_expiry_invalid')
    return {'limit_microusd': int(limit), 'expires_at': expires}


PRECHECK = '''import hashlib,importlib.util,json,os
os.environ['PGOPTIONS']='-c default_transaction_read_only=on'
from narma_video.db import database
from narma_video import openai_budget,openai_provider,budget
assert importlib.util.find_spec('narma_video.resource_lock') is not None
assert os.getenv('REPLAY_COACH_PROVIDER')=='openai_api'
assert os.getenv('HERMES_PROVIDER')=='openai_api'
assert os.getenv('VIDEO_ANALYSIS_MODE')=='selective_v1'
assert openai_provider.configured()
with database() as c:
 assert c.execute('SHOW transaction_read_only').fetchone()['transaction_read_only']=='on'
 names={r['name'] for r in c.execute('SELECT name FROM video_schema_migrations').fetchall()}
 assert {'018_openai_api.sql','020_hermes_openai.sql','021_portal_multiple_accounts.sql'}<=names
 queries=(
  'SELECT row_to_json(t)::text AS value FROM video_ai_budget t ORDER BY id',
  'SELECT id,billing_status,reserved_microusd,charged_microusd FROM video_provider_calls ORDER BY id',
  'SELECT row_to_json(t)::text AS value FROM openai_api_budget t ORDER BY id',
  'SELECT id::text,state,billing_status,reserved_microusd,charged_microusd FROM openai_api_calls ORDER BY id',
  'SELECT count(*) AS n FROM chatgpt_calls')
 ledger=[]
 for query in queries:
  ledger.append(c.execute(query).fetchall())
 openai=openai_budget.status(c)
 gemini=budget.status(c)
 print(json.dumps({'event':'openai_api_preflight','database_read_only':True,
  'configured':True,'provider':'openai_api','video_mode':'selective_v1',
  'openai_budget':openai,'gemini_budget':gemini,
  'ledger_sha256':hashlib.sha256(json.dumps(ledger,sort_keys=True).encode()).hexdigest(),
  'provider_access_verified':False,'generation_requests':0,'resource_lock_available':True}))
'''


def status_only(sha):
    config = '/opt/narma/releases/' + sha + '/services/video/compose.yaml'
    # compose() validates the full path/SHA before any subprocess starts.
    compose(config)
    result = api_json(config, PRECHECK, timeout=45)
    if (result.get('event') != 'openai_api_preflight' or result.get('database_read_only') is not True
            or result.get('configured') is not True or result.get('generation_requests') != 0):
        raise RuntimeError('openai_configuration_unverified')
    return result


def prepare(sha, *, allowance=None):
    saved = json.loads(state_path(sha).read_text())
    if saved.get('release') != sha:
        raise RuntimeError('openai_release_snapshot_invalid')
    config = '/opt/narma/releases/' + sha + '/services/video/compose.yaml'
    # This check belongs only to release cutover. It is not run by install-only
    # support or status-only preflight and does not itself stop a service.
    if any(item and item['running'] for item in (inspect_service(name) for name in SERVICES)):
        raise RuntimeError('openai_release_workers_not_paused')
    resources = resource_check()
    before = api_json(config, DATABASE_STATE)
    initial = status_only(sha)
    try:
        with tempfile.TemporaryDirectory(prefix='narma-openai-readiness-') as directory:
            override = Path(directory) / 'paused.json'
            write_private(override, {'services': {'hermes-broker': {'environment': {'HERMES_RUNTIME_ENABLED': '0'}}}})
            run(compose(config) + ['--file', str(override), '--profile', 'hermes', 'up', '-d',
                '--no-deps', '--no-build', '--pull', 'never', 'hermes-runner', 'hermes-broker'], timeout=90)
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
                raise RuntimeError('openai_hermes_network_unverified')
            final = status_only(sha)
            if initial['ledger_sha256'] != final['ledger_sha256']:
                raise RuntimeError('openai_preflight_ledger_changed')
            verify_preserved(before, api_json(config, DATABASE_STATE))
            verify_preserved(saved.get('before'), api_json(config, DATABASE_STATE))
        # Only concrete operator inputs alter the OpenAI ceiling. The budget CLI
        # preserves spent/reserved and refuses reconciliation/frozen states.
        if allowance is not None:
            checked = allowance_input(str(allowance['limit_microusd']), allowance['expires_at'])
            run(compose(config) + ['exec', '-T', 'api', 'python', '-m', 'narma_video.openai_budget',
                'configure', '--limit-microusd', str(checked['limit_microusd']),
                '--expires-at', checked['expires_at'], '--enable'], timeout=30)
        # Ordinary runtime resumes with its configured flag; no synthetic task
        # is created. Its provider/owner guards and durable allowance still apply.
        run(compose(config) + ['--profile', 'hermes', 'up', '-d', '--no-deps', '--no-build',
            '--pull', 'never', '--force-recreate', 'hermes-broker'], timeout=60)
        broker_check = '''import json,urllib.request
result=json.load(urllib.request.urlopen('http://127.0.0.1:8091/healthz',timeout=5))
assert result=={'ok':True,'service':'hermes-broker'}
print('OPENAI_BROKER_READY')
'''
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                if run(compose(config) + ['exec', '-T', 'hermes-broker', 'python', '-c', broker_check], timeout=10).strip() == b'OPENAI_BROKER_READY':
                    break
            except RuntimeError:
                pass
            time.sleep(2)
        else:
            raise RuntimeError('openai_broker_readiness_timeout')
        result = {'event': 'openai_api_ready', 'release': sha, 'provider': 'openai_api',
            'configured': True, 'video_mode': 'selective_v1', 'runtime_revision': REVISION,
            'network_isolation_verified': True, 'resource_lock_available': True,
            'generation_smoke_performed': False, 'provider_access_verified': False,
            'provider_calls_created_by_preflight': 0, 'existing_ledgers_preserved': True,
            'explicit_allowance_configured': allowance is not None, 'resources': resources}
        write_private(Path('/opt/narma/checks/openai-api-readiness.json'), result)
        return result
    except Exception:
        # Normal outer release rollback restores the prior services/settings.
        run(compose(config) + ['--profile', 'hermes', 'stop', '--timeout', '20', 'hermes-broker', 'hermes-runner'])
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('sha')
    parser.add_argument('--status-only', action='store_true')
    parser.add_argument('--limit-microusd')
    parser.add_argument('--expires-at')
    args = parser.parse_args()
    try:
        allowance = allowance_input(args.limit_microusd, args.expires_at)
        if args.status_only and allowance:
            raise RuntimeError('openai_readonly_allowance_conflict')
        print(json.dumps(status_only(args.sha) if args.status_only else prepare(args.sha, allowance=allowance)), flush=True)
    except Exception as error:
        code = str(error) if isinstance(error, RuntimeError) and re.fullmatch('openai_[a-z_]{1,100}', str(error)) else 'openai_preparation_failed'
        print(json.dumps({'event': 'openai_preparation_failure', 'code': code}), flush=True)
        sys.exit(1)
