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
              ('/api/replays', 401), ('/api/hero-pool', 401), ('/api/learning', 401), ('/v1/videos', 401)]
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
 assert {'005_replay_analysis.sql','006_replay_shared_ai_budget.sql','007_hero_pool.sql',
         '008_replay_coaching_history.sql','009_hermes_reviews.sql','010_hero_pool_progress.sql',
         '011_hermes_runtime.sql','012_learning_curriculum.sql'}<=names
 for table in ('replay_jobs','replay_workers','hero_pool_match_notes','hero_pool_matches',
               'hero_pool_favorites','hero_pool_goals','hero_pool_goal_checks',
               'replay_report_history','hermes_exports','hermes_reviews','learning_plans','learning_checks'):
  assert c.execute("SELECT to_regclass(%s) AS r",('public.'+table,)).fetchone()['r']
 assert c.execute("SELECT 1 FROM pg_constraint WHERE conname='provider_call_exactly_one_job' AND conrelid='video_provider_calls'::regclass").fetchone()
 print('REPLAY_SCHEMA_OK')
'''

POOL_CHECK = '''import json
from narma_video.db import database
from narma_video.hero_pool import get_pool
from narma_video.replay_jobs import get_replay
with database() as c:
 owners=c.execute('SELECT owner_id,account_id FROM portal_dota_profiles ORDER BY owner_id').fetchall()
 calls_before=c.execute('SELECT count(*) AS n FROM video_provider_calls').fetchone()['n']
counts=[]
context_reports=0
for owner in owners:
 pool=get_pool(owner['owner_id'])
 assert pool['schema_version']=='narma.hero-pool.v1'
 assert pool['profile']['account_id']==owner['account_id']
 history=pool['history']
 summary=pool['summary']
 assert len({m['match_id'] for m in history})==len(history)==summary['matches']
 assert all(m['outcome'] in ('win','loss',None) for m in history)
 wins=sum(m['outcome']=='win' for m in history)
 losses=sum(m['outcome']=='loss' for m in history)
 assert summary['wins']==wins and summary['losses']==losses
 assert summary['known_outcomes']==wins+losses
 assert summary['unknown_outcomes']==len(history)-wins-losses
 assert summary['winrate_pct']==(round(100*wins/(wins+losses),1) if wins+losses else None)
 assert sum(hero['matches'] for hero in pool['heroes'])==len(history)
 for match in history[:3]:
  detail=get_replay(match['job_id'],owner['owner_id'])
  context=detail['hero_context']
  assert context and context['schema_version']=='narma.hero-context.v1'
  assert context['hero']==match['hero']==detail['report']['player']['hero']
  assert context['position']==match['position']
  context_reports+=1
 counts.append({'matches':len(history),'heroes':len(pool['heroes']),
                'known_outcomes':summary['known_outcomes'],'unknown_outcomes':summary['unknown_outcomes']})
with database() as c:
 assert c.execute('SELECT count(*) AS n FROM video_provider_calls').fetchone()['n']==calls_before
print(json.dumps({'verified':True,'owners':len(owners),'counts':counts,
                 'hero_context_reports':context_reports,'provider_calls_created':0}))
'''


LEARNING_CHECK = '''import json,os
# Every connection opened by the real learning read functions is read-only.
# No temporary owner, session, plan, answer or provider request is created.
os.environ['PGOPTIONS']='-c default_transaction_read_only=on'
from narma_video.db import database
from narma_video.learning import get_learning,get_report_learning,_full_report
from narma_video.curriculum import get_catalog
with database() as c:
 assert c.execute('SHOW transaction_read_only').fetchone()['transaction_read_only']=='on'
 owners=c.execute('SELECT owner_id FROM portal_accounts ORDER BY owner_id').fetchall()
 calls_before=c.execute('SELECT count(*) AS n FROM video_provider_calls').fetchone()['n']
role_actions=[]
for position in (None,1,2,3,4,5):
 catalog=get_catalog(position)
 assert catalog['schema_version']==catalog['version']=='narma.curriculum.v1'
 assert [stage['id'] for stage in catalog['stages']]==['lane','map','risk','items','fights','decisions']
 cards=catalog['exercises']
 assert len(cards)==len({card['id'] for card in cards})==(10 if position is None else 12 if position in (4,5) else 11)
 assert all(not card['roles'] or position in card['roles'] for card in cards)
 if position is None:
  assert catalog['role_context'] is None
 else:
  assert catalog['role_context']['position']==position
  assert all(card['position']==position for card in cards)
  role_actions.append(next(card['action'] for card in cards if card['id']=='r1'))
assert len(set(role_actions))==5
reports=0
matches=0
for owner in owners:
 state=get_learning(owner['owner_id'])
 assert state['schema_version']=='narma.learning.v1'
 assert state['progress_source']=='player_self_report'
 profile=state['profile']
 history=state['history']
 assert len({row['match_id'] for row in history})==len(history)
 if profile is None:
  assert not history and not state['plans']
  continue
 with database() as c:
  binding=c.execute('SELECT account_id FROM portal_dota_profiles WHERE owner_id=%s',(owner['owner_id'],)).fetchone()
  assert binding and binding['account_id']==profile['account_id']
  owned={str(row['id']):row for row in c.execute("SELECT id,match_id,source_sha256 FROM replay_jobs WHERE owner_id=%s AND account_id=%s AND state<>'deleted'",(owner['owner_id'],profile['account_id'])).fetchall()}
 assert all(row['job_id'] in owned and owned[row['job_id']]['match_id']==row['match_id'] and owned[row['job_id']]['source_sha256']==row['source_sha256'] for row in history)
 matches+=len(history)
 for fact in history[:3]:
  detail=get_report_learning(owner['owner_id'],fact['job_id'])
  assert detail['schema_version']=='narma.learning.v1'
  assert (detail['job_id'],detail['match_id'],detail['hero'],detail['position'])==(fact['job_id'],fact['match_id'],fact['hero'],fact['position'])
  with database() as c:
   report=_full_report(c,owner['owner_id'],profile['account_id'],fact['job_id'])
  assert report and report['coverage']['source_sha256']==fact['source_sha256']
  events={event['id']:event for event in (report.get('evidence') or []) if isinstance(event,dict) and isinstance(event.get('id'),str)}
  for group in [detail['review_candidates'],*detail['exercise_candidates'].values()]:
   assert len(group)==len({item['evidence_id'] for item in group})
   for item in group:
    event=events[item['evidence_id']]
    assert (item['time'],item['type'])==(event['time'],event['type'])
  allowed={item['evidence_id'] for item in detail['review_candidates']}
  for suggestion in detail['suggestions']:
   assert suggestion['hero']==fact['hero'] and suggestion['position']==fact['position']
   assert set(suggestion['evidence_ids'])<=allowed
  reports+=1
with database() as c:
 assert c.execute('SELECT count(*) AS n FROM video_provider_calls').fetchone()['n']==calls_before
print(json.dumps({'verified':True,'curriculum_version':'narma.curriculum.v1',
 'stages':6,'role_variants':6,'owners':len(owners),'owned_matches':matches,
 'evidence_reports':reports,'database_read_only':True,'provider_calls_created':0}))
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
    from chatgpt_secrets import restore_settings
    from openai_secrets import restore_settings as restore_openai_settings
    restore_settings(snapshot['release'])
    restore_openai_settings(snapshot['release'])
    # Always stop the new worker first: old + new workers must not compete for RAM.
    run(compose(config) + ['--profile', 'analysis', '--profile', 'hermes', 'stop', '--timeout', '20', *SERVICES])
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
                run(compose(previous['config']) + ['--file', str(override), '--profile', 'analysis', '--profile', 'hermes',
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


def activate(sha, hostname, *, prepare_chatgpt_auth=False, prepare_openai_api=False, openai_allowance=None):
    if prepare_chatgpt_auth and prepare_openai_api:
        raise RuntimeError('replay_conflicting_provider_modes')
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
        run(compose(config) + ['--profile', 'analysis', '--profile', 'hermes', 'stop', '--timeout', '20', *SERVICES])
        if any(item and item['running'] for item in (inspect_service(service) for service in SERVICES)):
            raise RuntimeError('replay_previous_worker_still_running')
        run(compose(config) + ['exec', '-T', 'api', 'python', '-c', SCHEMA_CHECK])
        pool_status = json.loads(run(compose(config) + ['exec', '-T', 'api', 'python', '-c', POOL_CHECK]))
        if pool_status.get('verified') is not True:
            raise RuntimeError('replay_hero_pool_check_failed')
        learning_status = json.loads(run(compose(config) + ['exec', '-T', 'api', 'python', '-c', LEARNING_CHECK], timeout=60))
        if (learning_status.get('verified') is not True
                or learning_status.get('database_read_only') is not True
                or learning_status.get('provider_calls_created') != 0):
            raise RuntimeError('replay_learning_check_failed')
        after = json.loads(run(compose(config) + ['exec', '-T', 'api', 'python', '-c', DATABASE_STATE]))
        verify_preserved(snapshot.get('before'), after)
        # Compose's default image name is project-service. Confirm it exists so
        # `run` cannot trigger an implicit missing-image build on the live host.
        run(['docker', 'image', 'inspect', '--format', '{{.Id}}', 'narma-video-replay-worker'])
        if run(compose(config) + ['--profile', 'analysis', 'run', '--rm', '--no-deps',
            '--pull', 'never', '--entrypoint', 'python', 'replay-worker', '-c', PARSER_CHECK], timeout=70).strip() != b'REPLAY_RUNTIME_OK':
            raise RuntimeError('replay_runtime_check_failed')
        anonymous_checks(hostname)
        chatgpt_status = None
        openai_status = None
        if prepare_chatgpt_auth:
            from prepare_chatgpt_auth import prepare
            chatgpt_status = prepare(sha, hostname)
        if prepare_openai_api:
            from prepare_openai_api import prepare
            openai_status = prepare(sha, allowance=openai_allowance)
        started = datetime.now(timezone.utc).isoformat()
        heartbeat = '''import json
from narma_video.db import database
with database() as c:
 row=c.execute("SELECT last_seen>%%s::timestamptz AS fresh FROM replay_workers WHERE id='replay'",(%r,)).fetchone()
 print(json.dumps({'fresh':bool(row and row['fresh'])}))
''' % started
        run(compose(config) + ['--profile', 'analysis', 'up', '-d', '--no-deps', '--no-build', '--pull', 'never', 'replay-worker'])
        if prepare_openai_api:
            run(compose(config) + ['--profile', 'analysis', 'up', '-d', '--no-deps', '--no-build', '--pull', 'never', 'worker'])
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            current = inspect_service('replay-worker')
            status = json.loads(run(compose(config) + ['exec', '-T', 'api', 'python', '-c', heartbeat], timeout=15))
            if current and current['running'] and status.get('fresh') is True:
                video = inspect_service('worker')
                if prepare_openai_api:
                    video_heartbeat = '''import json
from narma_video.db import database
with database() as c:
 row=c.execute("SELECT last_seen>%%s::timestamptz AS fresh FROM video_workers WHERE id='vision'",(%r,)).fetchone()
 print(json.dumps({'fresh':bool(row and row['fresh'])}))
''' % started
                    video_status = json.loads(run(compose(config) + ['exec', '-T', 'api', 'python', '-c', video_heartbeat], timeout=15))
                    if not video or not video['running'] or video_status.get('fresh') is not True:
                        time.sleep(2)
                        continue
                elif video and video['running']:
                    raise RuntimeError('replay_video_worker_must_remain_stopped')
                write_private(Path('/opt/narma/checks/replay-worker-activation.json'),
                    {'release': sha, 'activated_at': started, 'worker': 'replay', 'synthetic_paid_calls': 0})
                return {'event': 'replay_pipeline_ready', 'worker_enabled': True, 'fresh_worker_heartbeat': True,
                        'video_worker_stopped': not prepare_openai_api,
                        'video_worker_fresh': prepare_openai_api, 'schema_verified': True, 'parser_runtime_verified': True,
                        'existing_account_and_budget_preserved': snapshot.get('before') is not None,
                        'hero_pool': pool_status,
                        'learning': learning_status,
                        'chatgpt': chatgpt_status,
                        'openai': openai_status,
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
    parser.add_argument('sha'); parser.add_argument('hostname'); parser.add_argument('--rollback-only', action='store_true')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--prepare-chatgpt-auth', action='store_true')
    modes.add_argument('--prepare-openai-api', action='store_true')
    parser.add_argument('--openai-limit-microusd'); parser.add_argument('--openai-expires-at')
    args = parser.parse_args()
    try:
        if args.rollback_only:
            saved = json.loads(state_path(args.sha).read_text())
            if saved.get('release') != args.sha:
                raise RuntimeError('replay_activation_snapshot_invalid')
            restored = rollback('/opt/narma/releases/' + args.sha + '/services/video/compose.yaml', saved)
            print(json.dumps({'event': 'replay_activation_rollback', 'restored_services': restored}), flush=True)
        else:
            from prepare_openai_api import allowance_input
            allowance = allowance_input(args.openai_limit_microusd, args.openai_expires_at)
            if allowance and not args.prepare_openai_api:
                raise RuntimeError('replay_openai_allowance_mode_required')
            print(json.dumps(activate(args.sha, args.hostname, prepare_chatgpt_auth=args.prepare_chatgpt_auth,
                prepare_openai_api=args.prepare_openai_api, openai_allowance=allowance)), flush=True)
    except Exception as error:
        code = str(error) if isinstance(error, RuntimeError) and re.fullmatch('(replay|hermes)_[a-z_]{1,100}', str(error)) else 'replay_activation_failed'
        event = 'hermes_activation_failure' if code.startswith('hermes_') else 'replay_activation_failure'
        print(json.dumps({'event': event, 'code': code}), flush=True)
        sys.exit(1)
