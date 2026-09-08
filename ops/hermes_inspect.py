"""Read-only runtime and accounting diagnostic on the existing Narma server.

Only allowlisted status fields leave the host. No worker is started, task
requeued, model called, allowance changed or provider credential read.
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
import json
from narma_video.db import database
with database() as c:
 c.execute('SET TRANSACTION READ ONLY')
 tasks=c.execute("""SELECT id::text,state,attempts,error_code,runtime_revision,
  created_at::text,started_at::text,finished_at::text,
  octet_length(snapshot::text) AS snapshot_bytes,
  (SELECT count(*) FROM jsonb_object_keys(source_jobs)) AS source_jobs_count,
  review IS NOT NULL AS has_review
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
 worker=c.execute("SELECT runtime_revision,automatic_tracking,last_seen::text FROM hermes_workers WHERE id='scheduler'").fetchone()
 print(json.dumps({'tasks':tasks,'provider_calls':calls,'budget':budget,'unknown_reservations':unknown,'worker':worker},default=str))
'''


def host_probe():
    # The complete code runs remotely from stdin/argv. It writes no project files.
    return r'''
import json,pathlib,re,subprocess
def run(args):
 p=subprocess.run(args,stdin=subprocess.DEVNULL,capture_output=True,timeout=30)
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
