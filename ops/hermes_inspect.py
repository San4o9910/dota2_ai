"""Read-only runtime and accounting diagnostic on the existing Narma server.

Only allowlisted status fields leave the host. No worker is started, task
requeued, generation called or allowance changed. Provider metadata access has
and synthetic token counting have already been checked. This status probe makes
no provider requests and only reads operational state.
"""
import json
from pathlib import Path
import re
import shlex
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).parent / 'timeweb'))
from pilot import Cloud, CheckError, command, event, pinned_existing_server, address

DATABASE_PROBE = r'''
import importlib.util,json,re
from narma_video.db import database
with database() as c:
 c.execute('SET TRANSACTION READ ONLY')
 tasks=c.execute("""SELECT id::text,state,attempts,error_code,runtime_revision,
  created_at::text,started_at::text,finished_at::text,
  octet_length(snapshot::text) AS snapshot_bytes,
  (SELECT count(*) FROM jsonb_object_keys(source_jobs)) AS source_jobs_count,
  review IS NOT NULL AS has_review,
  CASE WHEN snapshot->>'runtime_contract'~'^narma[.]hermes[.]review[.]v[0-9]{1,3}$' OR snapshot->>'runtime_contract'='narma.hermes.json-object.v1'
   THEN snapshot->>'runtime_contract' ELSE NULL END AS runtime_contract,
  CASE WHEN jsonb_typeof(review->'patterns')='array' THEN jsonb_array_length(review->'patterns') ELSE NULL END AS review_patterns,
  CASE WHEN jsonb_typeof(review->'goals')='array' THEN jsonb_array_length(review->'goals') ELSE NULL END AS review_goals
  FROM hermes_tasks ORDER BY created_at DESC LIMIT 10""").fetchall()
 calls=c.execute("""SELECT id,hermes_task_id::text,model,billing_status,
  reserved_microusd,charged_microusd,created_at::text,finished_at::text,
  usage->'total_input_tokens' AS total_input_tokens,
  usage->'total_output_tokens' AS total_output_tokens,
  usage->'total_thought_tokens' AS total_thought_tokens,
  usage->'total_tokens' AS total_tokens
  FROM video_provider_calls WHERE call_kind='hermes' ORDER BY id DESC LIMIT 10""").fetchall()
 budget=c.execute("SELECT enabled,model,price_policy,limit_microusd,spent_microusd,reserved_microusd,frozen_reason FROM video_ai_budget WHERE id=1").fetchone()
 unknown=c.execute("SELECT count(*) AS count,coalesce(sum(reserved_microusd),0)::bigint AS reserved_microusd FROM video_provider_calls WHERE billing_status='unknown'").fetchone()
 unknown_calls=c.execute("SELECT id,call_kind,billing_status,reserved_microusd,created_at::text,finished_at::text FROM video_provider_calls WHERE billing_status='unknown' ORDER BY id LIMIT 30").fetchall()
 coaching=c.execute("""SELECT result_payload->'coaching'->>'status' AS status,
  result_payload->'coaching'->>'failure_code' AS failure_code,
  result_payload->'coaching'->>'failure_category' AS failure_category,
  result_payload->'coaching'->>'refresh_failure_code' AS refresh_failure_code,
  result_payload->'coaching'->>'refresh_failure_category' AS refresh_failure_category,
  count(*) AS count FROM replay_jobs WHERE state='ready' GROUP BY 1,2,3,4,5""").fetchall()
 categories={'timeout','transport','rate_limited','authentication','provider_unavailable','provider_rejected','budget','configuration','lease','validation','unknown'}
 for row in coaching:
  row['status']=row['status'] if row['status'] in ('ready','unavailable',None) else 'unclassified'
  for field in ('failure_code','refresh_failure_code'):
   value=row[field]
   row[field]=value if value is None or re.fullmatch('(?:REPLAY|VIDEO|GEMINI)_[A-Z_]{1,100}',value) else 'unclassified'
  for field in ('failure_category','refresh_failure_category'):
   row[field]=row[field] if row[field] is None or row[field] in categories else 'unclassified'
 worker=c.execute("SELECT runtime_revision,automatic_tracking,last_seen::text,last_seen>now()-interval '150 seconds' AS fresh FROM hermes_workers WHERE id='scheduler'").fetchone()
 owners=c.execute('SELECT owner_id FROM portal_dota_profiles ORDER BY owner_id LIMIT 100').fetchall()
public={'available':False}
if importlib.util.find_spec('narma_video.hermes_tasks') is not None:
 from narma_video.hermes_tasks import latest_valid_review,get_runtime_status
 public={'available':True,'owners_checked':len(owners),'current_valid_reviews':0,'patterns':0,'goals':0,'connected_owners':0,'automatic_tracking_owners':0}
 for owner in owners:
  review=latest_valid_review(owner['owner_id'])
  status=get_runtime_status(owner['owner_id'])
  public['connected_owners']+=int(status.get('runtime_connected') is True)
  public['automatic_tracking_owners']+=int(status.get('automatic_tracking') is True)
  if review:
   public['current_valid_reviews']+=1
   public['patterns']+=len(review['review']['patterns'])
   public['goals']+=len(review['review']['goals'])
print(json.dumps({'tasks':tasks,'provider_calls':calls,'budget':budget,'unknown_reservations':unknown,
 'unknown_calls':unknown_calls,'replay_coaching':coaching,'worker':worker,'public_runtime':public},default=str))
'''


def host_probe():
    # The complete code runs remotely from stdin/argv. It writes no project files.
    return r'''
import json,pathlib,re,subprocess
def run(args,timeout=30):
 p=subprocess.run(args,stdin=subprocess.DEVNULL,capture_output=True,timeout=timeout)
 if p.returncode:
  raise RuntimeError('hermes_diagnostic_command_failed')
 return p.stdout
def containers(service):
 ids=run(['docker','ps','--all','--quiet','--filter','label=com.docker.compose.project=narma-video',
  '--filter','label=com.docker.compose.oneoff=False','--filter','label=com.docker.compose.service='+service]).decode().splitlines()
 assert len(ids)<=1
 return ids
current=pathlib.Path('/opt/narma/current').resolve().name
assert re.fullmatch('[0-9a-f]{40}',current)
result={'event':'hermes_readonly_diagnostic','current_release':current,'containers':[],'runtime_events':[]}
for service in ('hermes-broker','hermes-runner','replay-worker','api'):
 ids=containers(service)
 if not ids:
  result['containers'].append({'service':service,'present':False})
  continue
 identifier=ids[0]
 template='{"image":{{json .Image}},"running":{{json .State.Running}},"status":{{json .State.Status}},"exit_code":{{.State.ExitCode}},"oom_killed":{{json .State.OOMKilled}},"restarts":{{.RestartCount}},"started_at":{{json .State.StartedAt}},"finished_at":{{json .State.FinishedAt}},"health":{{if .State.Health}}{{json .State.Health.Status}}{{else}}null{{end}}}'
 state=json.loads(run(['docker','inspect','--format',template,identifier]))
 result['containers'].append({'service':service,'present':True,**state})
 if service.startswith('hermes-'):
  private=run(['docker','logs','--tail','200',identifier])[-262144:].decode(errors='replace')
  for line in private.splitlines():
   try:
    item=json.loads(line)
   except ValueError:
    continue
   kind=item.get('event')
   if kind=='hermes_broker_rejected' and re.fullmatch('(?:HERMES|VIDEO)_[A-Z_]{1,100}',str(item.get('code',''))):
    categories={'timeout','transport','rate_limited','authentication','provider_unavailable','provider_rejected','budget','configuration','lease','validation','unknown'}
    statuses={'INVALID_ARGUMENT','FAILED_PRECONDITION','OUT_OF_RANGE','UNAUTHENTICATED','PERMISSION_DENIED','NOT_FOUND','ALREADY_EXISTS','RESOURCE_EXHAUSTED','CANCELLED','DATA_LOSS','UNKNOWN','INTERNAL','UNIMPLEMENTED','UNAVAILABLE','DEADLINE_EXCEEDED'}
    category=item.get('category')
    status=item.get('provider_http_status')
    provider_status=item.get('provider_status')
    allowed_reasons={'schema_complexity','schema_keyword_unsupported','schema_reference_invalid','enum_invalid','thinking_unsupported','service_tier_unsupported','location_unsupported','permission_denied','billing_required','api_key_invalid','model_unsupported','parameter_out_of_range','unexpected_field'}
    allowed_fields={'response_json_schema','response_schema','response_format','response_mime_type','thinking_config','service_tier','max_output_tokens','temperature','top_p','contents','model'}
    reasons=item.get('reason_flags')
    fields=item.get('field_labels')
    result['runtime_events'].append({'service':service,'event':kind,'code':item['code'],
     'category':category if isinstance(category,str) and category in categories else None,
     'provider_http_status':status if type(status) is int and 100<=status<=599 else None,
     'provider_status':provider_status if isinstance(provider_status,str) and provider_status in statuses else None,
     'reason_flags':[value for value in reasons[:30] if isinstance(value,str) and value in allowed_reasons] if isinstance(reasons,list) else [],
     'field_labels':[value for value in fields[:30] if isinstance(value,str) and value in allowed_fields] if isinstance(fields,list) else []})
   elif kind=='hermes_provider_response':
    reasons={'STOP','MAX_TOKENS','SAFETY','RECITATION','OTHER','BLOCKLIST','PROHIBITED_CONTENT','SPII','MALFORMED_FUNCTION_CALL','FINISH_REASON_UNSPECIFIED','IMAGE_SAFETY','IMAGE_PROHIBITED_CONTENT','IMAGE_RECITATION','NO_IMAGE','UNEXPECTED_TOOL_CALL','TOO_MANY_TOOL_CALLS','missing','unrecognized'}
    keys={'text','thought','thoughtSignature','functionCall','functionResponse','inlineData','fileData','executableCode','codeExecutionResult','videoMetadata'}
    types={'null','boolean','string','object','array','number','other'}
    allowed={key+':'+type_ for key in keys for type_ in types}|{'invalid_part','unrecognized_key'}
    numeric={key:item[key] for key in ('candidate_count','part_count','output_bytes') if type(item.get(key)) is int and 0<=item[key]<=1048576}
    parts=item.get('part_types')
    result['runtime_events'].append({'service':service,'event':kind,**numeric,
     'finish_reason':item.get('finish_reason') if isinstance(item.get('finish_reason'),str) and item['finish_reason'] in reasons else None,
     'part_types':[part for part in parts[:100] if isinstance(part,str) and part in allowed] if isinstance(parts,list) else []})
   elif kind=='hermes_runtime_failed' and re.fullmatch('HERMES_[A-Z_]{1,100}',str(item.get('code',''))):
    result['runtime_events'].append({'service':service,'event':kind,'code':item['code']})
   elif kind=='video_provider_accounting':
    numeric={k:item[k] for k in ('call_id','charged_microusd') if k in item and (type(item[k]) is int or item[k] is None)}
    flags={k:item[k] for k in ('reservation_retained','budget_frozen') if type(item.get(k)) is bool}
    result['runtime_events'].append({'service':service,'event':kind,**numeric,**flags})
   elif kind=='hermes_runtime_ready' and re.fullmatch('[0-9a-f]{40}',str(item.get('runtime_revision',''))):
    result['runtime_events'].append({'service':service,'event':kind,'runtime_revision':item['runtime_revision']})
   elif kind=='hermes_scheduler_unavailable':
    result['runtime_events'].append({'service':service,'event':kind})
api=containers('api')
assert len(api)==1
result['database']=json.loads(run(['docker','exec',api[0],'python','-c',DATABASE_CODE]))
result['provider_requests']=0
result['generation_requests']=0
memory={}
for line in pathlib.Path('/proc/meminfo').read_text().splitlines():
 key,value=line.split(':',1)
 if key in ('MemTotal','MemAvailable'):
  memory[key]=int(value.strip().split()[0])*1024
result['memory_bytes']=memory
print(json.dumps(result))
'''.replace('DATABASE_CODE', repr(DATABASE_PROBE))


def main():
    cloud = Cloud()
    server = pinned_existing_server(cloud)
    ssh_id = None
    with tempfile.TemporaryDirectory(prefix='narma-hermes-inspect-') as directory:
        directory = Path(directory)
        key = directory / 'key'
        command(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(key)])
        try:
            created = cloud.call('POST', '/api/v1/ssh-keys', {
                'name': 'narma-hermes-readonly-inspect',
                'body': key.with_suffix('.pub').read_text().strip(), 'is_default': False})
            ssh_id = created['ssh_key']['id']
            if type(ssh_id) is not int or ssh_id <= 0:
                raise CheckError('hermes_probe_key_invalid')
            cloud.call('POST', f"/api/v1/servers/{server['id']}/ssh-keys", {'ssh_key_ids': [ssh_id]})
            ssh = ['ssh', '-i', str(key), '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes',
                '-o', 'StrictHostKeyChecking=accept-new', '-o', 'UserKnownHostsFile=' + str(directory / 'known_hosts'),
                '-o', 'ConnectTimeout=8', '-o', 'ServerAliveInterval=15', 'root@' + address(server)]
            for attempt in range(12):
                try:
                    command(ssh + ['true'], timeout=15)
                    break
                except CheckError:
                    if attempt == 11:
                        raise
                    time.sleep(5)
            value = json.loads(command(ssh + ['python3 -c ' + shlex.quote(host_probe())], timeout=200))
            if value.get('event') != 'hermes_readonly_diagnostic':
                raise CheckError('hermes_probe_invalid')
            print(json.dumps(value), flush=True)
        finally:
            if ssh_id is not None:
                try:
                    cloud.call('DELETE', f"/api/v1/servers/{server['id']}/ssh-keys/{ssh_id}")
                except CheckError:
                    event('hermes_probe_binding_cleanup_unconfirmed')
                try:
                    cloud.call('DELETE', f'/api/v1/ssh-keys/{ssh_id}')
                except CheckError:
                    event('hermes_probe_key_cleanup_unconfirmed')


if __name__ == '__main__':
    try:
        main()
    except CheckError as error:
        event('hermes_probe_failed', code=str(error))
        sys.exit(1)
    except Exception:
        event('hermes_probe_failed', code='diagnostic_unavailable')
        sys.exit(1)
