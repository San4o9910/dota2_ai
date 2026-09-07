"""Inspect an existing pilot through ephemeral SSH; never provisions resources.

Only safe operational categories leave the host. Raw parser output stays in its
owner's private directory. Inspection does not change job state or call Gemini.
Explicit recovery queues one identified upload and preserves its attempts and
existing AI budget. A reviewed refresh keeps the old report for failure recovery.
"""
import json
from pathlib import Path
import re
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).parent / 'timeweb'))
from pilot import Cloud, CheckError, MARKER, NAME, PRESET, address, command, event

SERVER = 9037783
PROJECT = 2655641

PROBE = r'''
import hashlib,json,os,pathlib,re,resource,shutil,subprocess,time
from narma_video.db import database
from narma_video.replay_jobs import replay_directory
with database() as c:
 rows=c.execute("SELECT id,state,progress,failure_code,attempt,size_bytes,source_sha256,created_at::text FROM replay_jobs WHERE state<>'deleted' ORDER BY created_at DESC LIMIT 8").fetchall()
 active=c.execute("SELECT count(*) AS n FROM replay_jobs WHERE state='processing' AND lease_expires_at>now()").fetchone()['n']
print(json.dumps({'event':'replay_jobs_state','jobs':[{k:r[k] if k!='id' else str(r[k]) for k in ('id','state','progress','failure_code','attempt','size_bytes','created_at')} for r in rows]}),flush=True)
print(json.dumps({'event':'replay_environment','tmp_mounts':[x.split()[3] for x in pathlib.Path('/proc/mounts').read_text().splitlines() if x.split()[1]=='/tmp'],'tmp_free_bytes':shutil.disk_usage('/tmp').free}),flush=True)
job=next((r for r in rows if r['state']=='failed'),None)
if active or not job:
 print(json.dumps({'event':'replay_probe_skipped','active_jobs':active,'failed_job_found':bool(job)}),flush=True)
 raise SystemExit(0)
source=replay_directory(job['id'])/'source.dem'
if not source.is_file():
 print(json.dumps({'event':'replay_source_missing','job_id':str(job['id'])}),flush=True);raise SystemExit(0)
with source.open('rb') as stream:valid=source.stat().st_size==job['size_bytes'] and hashlib.file_digest(stream,'sha256').hexdigest()==job['source_sha256']
print(json.dumps({'event':'replay_source_integrity','job_id':str(job['id']),'matches_uploaded_source':valid}),flush=True)
if not valid:raise SystemExit(1)
os.umask(0o077)
output=pathlib.Path(tempfile.mkdtemp(prefix='diagnostic-',dir=source.parent))
def limits():
 resource.setrlimit(resource.RLIMIT_CPU,(295,300));resource.setrlimit(resource.RLIMIT_FSIZE,(50*1024**2,50*1024**2));resource.setrlimit(resource.RLIMIT_CORE,(0,0))
start=time.monotonic()
args=['java','-Xms256m','-Xmx2g','-XX:ActiveProcessorCount=2','-Dorg.slf4j.simpleLogger.defaultLogLevel=warn','-cp','/opt/narma/replay/target/classes:/opt/narma/replay/target/dependency/*','vision.narma.replay.ReplayProbe',str(source),str(output/'events.jsonl')]
if pathlib.Path('/opt/narma/replay/native/libsnappyjava.so').is_file():
 args[1:1]=['-Dorg.xerial.snappy.lib.path=/opt/narma/replay/native','-Dorg.xerial.snappy.lib.name=libsnappyjava.so']
with (output/'summary.json').open('wb') as out,(output/'parser.log').open('wb') as err:
 try:code=subprocess.run(args,stdout=out,stderr=err,stdin=subprocess.DEVNULL,env={'PATH':'/usr/local/bin:/usr/bin:/bin','LANG':'C.UTF-8','TMPDIR':'/tmp'},preexec_fn=limits,timeout=310).returncode
 except subprocess.TimeoutExpired:code=124
with (output/'parser.log').open('rb') as stream:private=stream.read(512*1024).decode(errors='replace')
patterns={'native_library_load':['unsatisfiedlinkerror','failed to map segment','no native library','snappyerror'],'noexec':['failed to map segment','operation not permitted'],'heap_limit':['outofmemoryerror','java heap space'],'disk_full':['no space left'],'read_only':['read-only file system'],'permission':['permission denied','accessdeniedexception'],'packet_invalid':['invalidprotocolbufferexception','invalidwiretypeexception'],'missing_class':['classnotfoundexception','noclassdeffounderror'],'unsupported_property':['fieldpath','unknown property']}
classes=sorted(set(re.findall(r'\b((?:java|org|com|skadistats)\.[A-Za-z0-9_.$]+(?:Exception|Error))\b',private)))[:15]
print(json.dumps({'event':'replay_parser_probe','job_id':str(job['id']),'exit_code':code,'seconds':round(time.monotonic()-start,2),'categories':[k for k,patterns_ in patterns.items() if any(p in private.lower() for p in patterns_)],'exception_classes':classes,'output_bytes':(output/'events.jsonl').stat().st_size if (output/'events.jsonl').exists() else 0}),flush=True)
if code==0:
 from narma_video.replay_report import build_report
 with database() as c:full=c.execute('SELECT * FROM replay_jobs WHERE id=%s',(job['id'],)).fetchone()
 try:
  report=build_report(output/'events.jsonl',output/'summary.json',full)
  print(json.dumps({'event':'replay_report_probe','complete':report['coverage']['complete'],'final_tick':report['coverage']['final_tick'],'evidence_count':len(report['evidence'])}),flush=True)
 except Exception as error:
  code_=str(error) if isinstance(error,ValueError) and re.fullmatch('REPLAY_[A-Z_]{1,70}',str(error)) else 'REPLAY_REPORT_FAILURE'
  print(json.dumps({'event':'replay_report_probe','code':code_}),flush=True)
# Keep only bounded private stderr for incident evidence, not the roster/events.
for filename in ('events.jsonl','summary.json'):(output/filename).unlink(missing_ok=True)
'''.replace('import hashlib,json,os,pathlib,re,resource,shutil,subprocess,time', 'import hashlib,json,os,pathlib,re,resource,shutil,subprocess,tempfile,time')

RECOVERY = r'''
import hashlib,json,re,time
from uuid import UUID
from narma_video.db import database
from narma_video.replay_jobs import replay_directory,get_replay
from narma_video.replay_worker import verify_runtime

def recovery_row(request,lock=False):
 with database() as c:
  row=c.execute("SELECT * FROM replay_jobs WHERE id=%s AND state<>'deleted'"+(' FOR UPDATE' if lock else ''),(request['job_id'],)).fetchone()
  if not row:raise ValueError('REPLAY_RECOVERY_NOT_FOUND')
  profile=c.execute('SELECT account_id FROM portal_dota_profiles WHERE owner_id=%s',(row['owner_id'],)).fetchone()
  if not profile or profile['account_id']!=row['account_id'] or row['source_sha256']!=request['source_sha256']:
   raise ValueError('REPLAY_RECOVERY_SOURCE_OR_PLAYER_MISMATCH')
 return row

def queue_retry(request):
 UUID(request['job_id'])
 if not re.fullmatch('[0-9a-f]{64}',request['source_sha256']) or type(request['expected_attempt']) is not int or not 1<=request['expected_attempt']<3:
  raise ValueError('REPLAY_RECOVERY_REQUEST_INVALID')
 verify_runtime()
 row=recovery_row(request)
 source=replay_directory(row['id'])/'source.dem'
 with source.open('rb') as stream:
  if source.stat().st_size!=row['size_bytes'] or hashlib.file_digest(stream,'sha256').hexdigest()!=request['source_sha256']:
   raise ValueError('REPLAY_RECOVERY_SOURCE_CHANGED')
 with database() as c:
  row=c.execute("SELECT * FROM replay_jobs WHERE id=%s AND state<>'deleted' FOR UPDATE",(request['job_id'],)).fetchone()
  if not row:raise ValueError('REPLAY_RECOVERY_NOT_FOUND')
  if row['state'] in ('queued','processing','ready'):return row
  if (row['state']!='failed' or row['failure_code']!=request['expected_failure_code'] or row['attempt']!=request['expected_attempt']
      or row['lease_token'] is not None or row['source_sha256']!=request['source_sha256']):
   raise ValueError('REPLAY_RECOVERY_STATE_CHANGED')
  # Preserve attempts, identity, source, provider ledger and the global allowance.
  row=c.execute("UPDATE replay_jobs SET state='queued',progress=0,failure_code=NULL,updated_at=now() WHERE id=%s RETURNING *",(row['id'],)).fetchone()
 return row

def recover(request):
 row=queue_retry(request)
 print(json.dumps({'event':'replay_recovery_queued','job_id':str(row['id']),'state':row['state'],'attempts_preserved':row['attempt']}),flush=True)
 deadline=time.monotonic()+300
 previous=None
 while time.monotonic()<deadline:
  row=recovery_row(request)
  signal=(row['state'],row['progress'])
  if signal!=previous:
   print(json.dumps({'event':'replay_recovery_state','job_id':str(row['id']),'state':row['state'],'progress':row['progress'],'failure_code':row['failure_code']}),flush=True)
   previous=signal
  if row['state']=='ready':
   detail=get_replay(row['id'],row['owner_id']); report=detail['report']
   assert (report['match_id']==row['match_id'] and report['player']['account_id']==row['account_id']
    and report['coverage']['source_sha256']==row['source_sha256'] and report['coverage']['complete'] is True
    and report['coverage']['final_tick']==report['coverage']['playback_ticks'])
   with database() as c:
    calls=c.execute('SELECT billing_status,charged_microusd FROM video_provider_calls WHERE replay_job_id=%s ORDER BY id',(row['id'],)).fetchall()
   print(json.dumps({'event':'replay_recovery_complete','job_id':str(row['id']),'owner_report_available':detail['replay']['state']=='ready',
    'complete':True,'player_and_source_verified':True,'final_tick':report['coverage']['final_tick'],'evidence_count':len(report['evidence']),
    'coaching_status':report.get('coaching',{}).get('status'),'coaching_failure_code':report.get('coaching',{}).get('failure_code'),
    'provider_calls':calls}),flush=True)
   return
  if row['state']=='failed':raise ValueError('REPLAY_RECOVERY_FAILED_AGAIN')
  time.sleep(5)
 raise ValueError('REPLAY_RECOVERY_WAIT_TIMEOUT')
'''

REFRESH = r'''
from copy import deepcopy
from psycopg.types.json import Jsonb

def refresh_event(name,**fields):
 print(json.dumps({'event':name,**fields}),flush=True)

def refresh_request(request):
 try:UUID(request['job_id'])
 except (ValueError,TypeError,KeyError):raise ValueError('REPLAY_REFRESH_REQUEST_INVALID') from None
 if (not isinstance(request.get('source_sha256'),str) or not re.fullmatch('[0-9a-f]{64}',request['source_sha256'])
     or type(request.get('expected_attempt')) is not int or request['expected_attempt']!=2
     or request.get('expected_insights_schema')!='narma.replay-insights.v1'):
  raise ValueError('REPLAY_REFRESH_REQUEST_INVALID')

def refresh_row(connection,request,lock=False):
 row=connection.execute("SELECT * FROM replay_jobs WHERE id=%s AND state<>'deleted'"+(' FOR UPDATE' if lock else ''),(request['job_id'],)).fetchone()
 if not row:raise ValueError('REPLAY_REFRESH_NOT_FOUND')
 profile=connection.execute('SELECT account_id FROM portal_dota_profiles WHERE owner_id=%s'+(' FOR SHARE' if lock else ''),(row['owner_id'],)).fetchone()
 if (not profile or profile['account_id']!=row['account_id'] or row['source_sha256']!=request['source_sha256']):
  raise ValueError('REPLAY_REFRESH_SOURCE_OR_PLAYER_MISMATCH')
 return row

def refresh_report_identity(report,row):
 if not isinstance(report,dict):raise ValueError('REPLAY_REFRESH_REPORT_INVALID')
 player=report.get('player',{});coverage=report.get('coverage',{})
 if (not isinstance(player,dict) or not isinstance(coverage,dict) or str(report.get('match_id'))!=str(row['match_id'])
     or player.get('account_id')!=row['account_id'] or coverage.get('source_sha256')!=row['source_sha256']
     or coverage.get('complete') is not True or type(coverage.get('final_tick')) is not int
     or coverage['final_tick']<=0 or coverage['final_tick']!=coverage.get('playback_ticks')):
  raise ValueError('REPLAY_REFRESH_REPORT_IDENTITY_INVALID')

def refreshed(report,request):
 return isinstance(report,dict) and isinstance(report.get('insights'),dict) and report['insights'].get('schema_version')==request['expected_insights_schema']

def refresh_source(row,request):
 source=replay_directory(row['id'])/'source.dem'
 try:
  with source.open('rb') as stream:
   valid=source.stat().st_size==row['size_bytes'] and hashlib.file_digest(stream,'sha256').hexdigest()==request['source_sha256']
 except OSError:raise ValueError('REPLAY_REFRESH_SOURCE_UNAVAILABLE') from None
 if not valid:raise ValueError('REPLAY_REFRESH_SOURCE_CHANGED')

def queue_refresh(request):
 refresh_request(request)
 with database() as c:row=refresh_row(c,request)
 if row['state']=='ready' and refreshed(row['result_payload'],request):
  refresh_report_identity(row['result_payload'],row)
  return row,None
 if row['state']!='ready' or row['attempt']!=request['expected_attempt'] or row['lease_token'] is not None or row['lease_expires_at'] is not None:
  raise ValueError('REPLAY_REFRESH_STATE_CHANGED')
 refresh_report_identity(row['result_payload'],row)
 previous=deepcopy(row['result_payload'])
 verify_runtime()
 refresh_source(row,request)
 with database() as c:
  row=refresh_row(c,request,lock=True)
  if row['state']=='ready' and refreshed(row['result_payload'],request):
   refresh_report_identity(row['result_payload'],row)
   return row,None
  if (row['state']!='ready' or row['attempt']!=request['expected_attempt'] or row['lease_token'] is not None
      or row['lease_expires_at'] is not None or row['result_payload']!=previous):
   raise ValueError('REPLAY_REFRESH_STATE_CHANGED')
  # Keep the good payload until finish_replay atomically replaces it. Only the
  # normal worker claims the next attempt and reserves a metered provider call.
  row=c.execute("UPDATE replay_jobs SET state='queued',progress=0,failure_code=NULL,updated_at=now() WHERE id=%s RETURNING *",(row['id'],)).fetchone()
 return row,previous

def restore_refresh(request,previous):
 if previous is None:return False
 with database() as c:
  row=refresh_row(c,request,lock=True)
  if (row['state']!='failed' or row['attempt']!=request['expected_attempt']+1
      or row['lease_token'] is not None or row['lease_expires_at'] is not None):
   return False
  refresh_report_identity(previous,row)
  if row['result_payload']!=previous:raise ValueError('REPLAY_REFRESH_PREVIOUS_REPORT_CHANGED')
  # Never rewind attempts, ownership, source, charges or uncertain reservations.
  c.execute("UPDATE replay_jobs SET state='ready',progress=100,result_payload=%s,failure_code=NULL,updated_at=now() WHERE id=%s",(Jsonb(previous),row['id']))
 return True

def refresh_complete(row,request):
 detail=get_replay(row['id'],row['owner_id']);report=detail.get('report')
 if detail['replay']['state']!='ready' or not refreshed(report,request):
  raise ValueError('REPLAY_REFRESH_INSIGHTS_MISSING')
 refresh_report_identity(report,row)
 insights=report['insights'];gold=insights.get('gold',{})
 if not isinstance(gold,dict):raise ValueError('REPLAY_REFRESH_INSIGHTS_INVALID')
 def count(value):return len(value) if isinstance(value,(list,dict)) else 0
 counts={'gold_bins':count(gold.get('bins')),'gold_sources':count(gold.get('sources')),
  'key_items':count(insights.get('items')),'pace_points':count(insights.get('pace')),
  'death_intervals':count(insights.get('death_intervals')),'training_actions':count(insights.get('training_plan'))}
 if not all(counts.values()):raise ValueError('REPLAY_REFRESH_VISUALS_INCOMPLETE')
 coaching=report.get('coaching',{})
 if not isinstance(coaching,dict):raise ValueError('REPLAY_REFRESH_COACHING_INVALID')
 next_game=count(coaching.get('next_game'))
 if coaching.get('status')=='ready' and next_game==0:raise ValueError('REPLAY_REFRESH_NEXT_GAME_MISSING')
 with database() as c:
  calls=c.execute('SELECT billing_status,charged_microusd FROM video_provider_calls WHERE replay_job_id=%s ORDER BY id',(row['id'],)).fetchall()
 refresh_event('replay_refresh_complete',job_id=str(row['id']),owner_report_available=True,complete=True,
  player_and_source_verified=True,final_tick=report['coverage']['final_tick'],insights_schema=insights['schema_version'],
  **counts,coaching_status=coaching.get('status'),coaching_failure_code=coaching.get('failure_code'),
  next_game_actions=next_game,attempt=row['attempt'],provider_calls=calls)

def refresh(request):
 row,previous=queue_refresh(request)
 if previous is None:
  refresh_complete(row,request)
  return
 refresh_event('replay_refresh_queued',job_id=str(row['id']),state=row['state'],attempts_preserved=row['attempt'],previous_report_preserved=True)
 deadline=time.monotonic()+480
 last=None
 while time.monotonic()<deadline:
  with database() as c:row=refresh_row(c,request)
  signal=(row['state'],row['progress'])
  if signal!=last:
   refresh_event('replay_refresh_state',job_id=str(row['id']),state=row['state'],progress=row['progress'],failure_code=row['failure_code'])
   last=signal
  if row['state']=='ready':
   refresh_complete(row,request)
   return
  if row['state']=='failed':
   restored=restore_refresh(request,previous)
   refresh_event('replay_refresh_restored',job_id=str(row['id']),previous_report_available=restored,attempts_preserved=row['attempt'],failure_code=row['failure_code'])
   raise ValueError('REPLAY_REFRESH_WORKER_FAILED')
  if row['attempt']>request['expected_attempt']+1:raise ValueError('REPLAY_REFRESH_ATTEMPT_CHANGED')
  time.sleep(5)
 # An active worker owns its lease. A monitor timeout must never overwrite it.
 raise ValueError('REPLAY_REFRESH_WAIT_TIMEOUT')

def run_refresh(request):
 try:refresh(request)
 except Exception as error:
  code=str(error) if isinstance(error,ValueError) and re.fullmatch('REPLAY_REFRESH_[A-Z_]{1,70}',str(error)) else 'REPLAY_REFRESH_UNEXPECTED_FAILURE'
  refresh_event('replay_refresh_failed',code=code)
  raise SystemExit(1) from None
'''

REMOTE = r'''
import json,pathlib,re,subprocess,sys
payload=json.loads(sys.stdin.read())
release=pathlib.Path('/opt/narma/current').resolve()
if release.name!=payload['expected_release'] or not re.fullmatch('[0-9a-f]{40}',release.name):raise SystemExit('SUPPORT_RELEASE_MISMATCH')
compose=['docker','compose','--project-name','narma-video','--env-file','/opt/narma/secrets/video.env','--file',str(release/'services/video/compose.yaml')]
ids=subprocess.run(compose+['--profile','analysis','ps','--quiet','replay-worker'],capture_output=True,check=True).stdout.splitlines()
if len(ids)!=1:raise SystemExit('SUPPORT_WORKER_NOT_RUNNING')
template='{"running":{{json .State.Running}},"oom_killed":{{json .State.OOMKilled}},"exit_code":{{json .State.ExitCode}},"restart_count":{{json .RestartCount}}}'
status=json.loads(subprocess.run(['docker','inspect','--format',template,ids[0].decode()],capture_output=True,check=True).stdout)
print(json.dumps({'event':'replay_container_state',**status}),flush=True)
result=subprocess.run(compose+['exec','-T','replay-worker','python','-c',payload['probe']],capture_output=True,timeout=550 if payload.get('action')=='refresh' else 370)
for line in result.stdout.splitlines():
 try:item=json.loads(line)
 except ValueError:continue
 if item.get('event') in ('replay_jobs_state','replay_environment','replay_probe_skipped','replay_source_missing','replay_source_integrity','replay_parser_probe','replay_report_probe','replay_recovery_queued','replay_recovery_state','replay_recovery_complete','replay_recovery_failed','replay_refresh_queued','replay_refresh_state','replay_refresh_complete','replay_refresh_restored','replay_refresh_failed'):print(json.dumps(item),flush=True)
if result.returncode:raise SystemExit('SUPPORT_PROBE_FAILED')
'''


def main():
    request = json.loads((Path(__file__).parent/'replay-support-request.json').read_text())
    if request.get('action') not in ('inspect','retry','refresh') or not re.fullmatch('[0-9a-f]{40}',request.get('expected_release','')):
        raise CheckError('support_request_invalid')
    cloud = Cloud()
    server = cloud.call('GET', f'/api/v1/servers/{SERVER}')['server']
    if server.get('project_id') != PROJECT or server.get('comment') != MARKER or server.get('name') != NAME or server.get('preset_id') != PRESET:
        raise CheckError('support_server_identity_mismatch')
    host = address(server)
    if host != '72.56.98.68':
        raise CheckError('support_server_address_mismatch')
    ssh_id = None
    with tempfile.TemporaryDirectory(prefix='narma-support-') as folder:
        folder = Path(folder); private = folder/'key'
        command(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(private)])
        try:
            key = cloud.call('POST','/api/v1/ssh-keys',{'name':'narma-replay-support','body':private.with_suffix('.pub').read_text().strip(),'is_default':False})
            ssh_id = int(key['ssh_key']['id'])
            cloud.call('POST',f'/api/v1/servers/{SERVER}/ssh-keys',{'ssh_key_ids':[ssh_id]})
            ssh=['ssh','-i',str(private),'-o','BatchMode=yes','-o','IdentitiesOnly=yes','-o','StrictHostKeyChecking=accept-new','-o','UserKnownHostsFile='+str(folder/'known_hosts'),'-o','ConnectTimeout=8','-o','ServerAliveInterval=15','root@'+host]
            for attempt in range(12):
                try:command(ssh+['true'],timeout=15);break
                except CheckError:
                    if attempt==11:raise
                    time.sleep(5)
            # The remote script is source code from this reviewed checkout. JSON
            # travels on stdin; no secret, replay, or prompt enters command text.
            import shlex
            probe=PROBE if request['action']=='inspect' else RECOVERY+'\nrecover(json.loads('+repr(json.dumps(request))+'))'
            if request['action']=='refresh':probe=RECOVERY+REFRESH+'\nrun_refresh(json.loads('+repr(json.dumps(request))+'))'
            body=json.dumps({'expected_release':request['expected_release'],'action':request['action'],'probe':probe}).encode()
            import subprocess
            result=subprocess.run(ssh+['python3 -c '+shlex.quote(REMOTE)],input=body,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=570 if request['action']=='refresh' else 390)
            for line in result.stdout.splitlines():
                item=json.loads(line)
                if item.get('event','').startswith('replay_'):print(json.dumps(item),flush=True)
            if result.returncode:raise CheckError('support_probe_failed')
        finally:
            if ssh_id is not None:
                try:cloud.call('DELETE',f'/api/v1/servers/{SERVER}/ssh-keys/{ssh_id}')
                except CheckError:event('support_key_binding_cleanup_unconfirmed')
                try:cloud.call('DELETE',f'/api/v1/ssh-keys/{ssh_id}')
                except CheckError:event('support_key_cleanup_unconfirmed')


if __name__=='__main__':
    try:main()
    except Exception:
        event('support_failed',code='support_inspection_failed');raise SystemExit(1)
