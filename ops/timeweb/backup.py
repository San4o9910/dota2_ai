"""Runner-only off-server PostgreSQL backup and restore drill. Never installs S3 keys on VPS."""
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import subprocess
import tempfile
import time
from uuid import uuid4

from pilot import Cloud,CheckError,MARKER,NAME,address,command,event

SERVER=9037783
PROJECT=2655641
PRESET=4621
DESCRIPTION='NARMA PostgreSQL backups VPS 9037783 project 2655641'
PREFIX='postgres/9037783/'
MAX_DUMP=1024**3-16*1024**2  # Seven retained copies + next copy + manifests fit within 8 GiB.

# Conditional queries preserve the ability to restore earlier pilot snapshots.
REPLAY_RESTORE_SQL="""SELECT json_build_object(
    'tables',(SELECT count(*) FROM information_schema.tables WHERE table_schema=current_schema() AND table_name IN ('replay_jobs','replay_parts','replay_workers')),
    'jobs',(SELECT count(*) FROM replay_jobs),
    'orphan_jobs',(SELECT count(*) FROM replay_jobs j LEFT JOIN portal_accounts a ON a.owner_id=j.owner_id WHERE a.owner_id IS NULL),
    'orphan_parts',(SELECT count(*) FROM replay_parts p LEFT JOIN replay_jobs j ON j.id=p.job_id WHERE j.id IS NULL),
    'invalid_ready_identity',(SELECT count(*) FROM replay_jobs j WHERE j.state='ready' AND (
        j.result_payload->>'match_id' IS DISTINCT FROM j.match_id
        OR j.result_payload->'player'->>'account_id' IS DISTINCT FROM j.account_id::text))
);"""

PROVIDER_RESTORE_SQL="""SELECT json_build_object(
    'invalid_call_jobs',(SELECT count(*) FROM video_provider_calls c
        LEFT JOIN video_jobs v ON v.id=c.job_id
        LEFT JOIN replay_jobs r ON r.id=c.replay_job_id
        WHERE CASE c.call_kind
            WHEN 'video' THEN c.job_id IS NULL OR c.replay_job_id IS NOT NULL
                OR v.id IS NULL OR c.owner_id IS DISTINCT FROM v.owner_id
                OR c.first_frame<0 OR c.last_frame<c.first_frame
            WHEN 'replay' THEN c.job_id IS NOT NULL OR c.replay_job_id IS NULL
                OR r.id IS NULL OR c.owner_id IS DISTINCT FROM r.owner_id
                OR c.first_frame<>0 OR c.last_frame<>0
            ELSE true END)
);"""


def provider_restore_sql(migrations):
    """Use the source schema's legal targets; never accept unknown call kinds."""
    if '011_hermes_runtime.sql' not in migrations:
        return PROVIDER_RESTORE_SQL
    provider_check = (" OR h.provider IS DISTINCT FROM 'gemini' OR h.model IS DISTINCT FROM c.model"
                      if '015_hermes_chatgpt_provider.sql' in migrations else '')
    return """SELECT json_build_object('invalid_call_jobs',count(*) FILTER (WHERE invalid),
        'invalid_video',count(*) FILTER (WHERE invalid AND call_kind='video'),
        'invalid_replay',count(*) FILTER (WHERE invalid AND call_kind='replay'),
        'invalid_hermes',count(*) FILTER (WHERE invalid AND call_kind='hermes'))
        FROM (SELECT c.call_kind,CASE c.call_kind
            WHEN 'video' THEN c.job_id IS NULL OR c.replay_job_id IS NOT NULL
                OR c.hermes_task_id IS NOT NULL OR v.id IS NULL
                OR c.owner_id IS DISTINCT FROM v.owner_id
                OR c.first_frame<0 OR c.last_frame<c.first_frame
            WHEN 'replay' THEN c.job_id IS NOT NULL OR c.replay_job_id IS NULL
                OR c.hermes_task_id IS NOT NULL OR r.id IS NULL
                OR c.owner_id IS DISTINCT FROM r.owner_id OR c.first_frame<>0 OR c.last_frame<>0
            WHEN 'hermes' THEN c.job_id IS NOT NULL OR c.replay_job_id IS NOT NULL
                OR c.hermes_task_id IS NULL OR h.id IS NULL
                OR c.owner_id IS DISTINCT FROM h.owner_id OR c.first_frame<>0 OR c.last_frame<>0
                """ + provider_check + """
            ELSE true END AS invalid
        FROM video_provider_calls c LEFT JOIN video_jobs v ON v.id=c.job_id
        LEFT JOIN replay_jobs r ON r.id=c.replay_job_id
        LEFT JOIN hermes_tasks h ON h.id=c.hermes_task_id) checks;"""


def openai_restore_sql(migrations):
    hermes_check = ("c.job_id IS NOT NULL OR c.video_job_id IS NOT NULL OR c.task_id IS NULL "
        "OR h.id IS NULL OR c.owner_id IS DISTINCT FROM h.owner_id "
        "OR c.source_sha256 IS DISTINCT FROM h.snapshot_sha256 "
        "OR h.provider IS DISTINCT FROM 'openai_api' OR h.model IS DISTINCT FROM c.model"
        if '020_hermes_openai.sql' in migrations else 'true')
    return """SELECT json_build_object(
        'tables',(SELECT count(*) FROM information_schema.tables WHERE table_schema=current_schema()
            AND table_name IN ('openai_api_budget','openai_api_calls')),
        'budget_rows',(SELECT count(*) FROM openai_api_budget),
        'invalid_call_jobs',(SELECT count(*) FROM openai_api_calls c
            LEFT JOIN replay_jobs r ON r.id=c.job_id
            LEFT JOIN video_jobs v ON v.id=c.video_job_id
            LEFT JOIN hermes_tasks h ON h.id=c.task_id
            WHERE CASE c.kind
                WHEN 'replay' THEN c.job_id IS NULL OR c.video_job_id IS NOT NULL OR c.task_id IS NOT NULL
                    OR r.id IS NULL OR c.owner_id IS DISTINCT FROM r.owner_id
                    OR c.source_sha256 IS DISTINCT FROM r.source_sha256
                WHEN 'video' THEN c.video_job_id IS NULL OR c.job_id IS NOT NULL OR c.task_id IS NOT NULL
                    OR v.id IS NULL OR c.owner_id IS DISTINCT FROM v.owner_id
                    OR c.source_sha256 IS DISTINCT FROM v.source_sha256
                WHEN 'hermes' THEN """ + hermes_check + """ ELSE true END),
        'invalid_call_accounting',(SELECT count(*) FROM openai_api_calls c
            LEFT JOIN openai_api_budget b ON b.id=c.budget_id
            WHERE b.id IS NULL OR c.model IS DISTINCT FROM b.model OR CASE c.billing_status
                WHEN 'reserved' THEN c.state NOT IN ('reserved','calling') OR c.charged_microusd IS NOT NULL
                WHEN 'unknown' THEN c.state<>'unknown' OR c.charged_microusd IS NOT NULL
                WHEN 'settled' THEN c.state NOT IN ('succeeded','failed') OR c.charged_microusd IS NULL
                WHEN 'breach' THEN c.state<>'failed' OR c.charged_microusd IS NULL
                ELSE true END),
        'invalid_budget',(SELECT count(*) FROM openai_api_budget b WHERE b.id<>1
            OR b.limit_microusd NOT BETWEEN 0 AND 10000000
            OR b.spent_microusd IS DISTINCT FROM (SELECT coalesce(sum(c.charged_microusd),0)
                FROM openai_api_calls c WHERE c.budget_id=b.id)
            OR b.reserved_microusd IS DISTINCT FROM (SELECT coalesce(sum(c.reserved_microusd),0)
                FROM openai_api_calls c WHERE c.budget_id=b.id AND c.billing_status IN ('reserved','unknown'))));"""


def verify_restored_database(query):
    """Check only the isolated restored database supplied by verify_restore.

    query never receives a source/VPS connection. Migration names select schema
    features; counts alone cannot identify whether a particular feature exists.
    """
    migrations=set(query("SELECT json_build_object('names',coalesce(json_agg(name),'[]'::json)) FROM video_schema_migrations;")['names'])
    state=query("""SELECT json_build_object('tables',(SELECT count(*) FROM information_schema.tables
        WHERE table_schema=current_schema() AND table_name IN ('video_schema_migrations','video_jobs','video_parts',
        'video_batches','video_workers','video_provider_calls','video_ai_budget','video_budget_operations')),
        'migrations',(SELECT count(*) FROM video_schema_migrations),'jobs',(SELECT count(*) FROM video_jobs),
        'calls',(SELECT count(*) FROM video_provider_calls),'allowance',(SELECT limit_microusd FROM video_ai_budget WHERE id=1),
        'orphans',(SELECT count(*) FROM video_batches b LEFT JOIN video_jobs j ON j.id=b.job_id WHERE j.id IS NULL));""")
    expected_tables=8 if '003_record_generate_content_cutover.sql' in migrations else 7
    if state['tables']!=expected_tables or '002_global_ai_budget.sql' not in migrations or state['orphans']!=0 or state['allowance']>10000000:
        raise CheckError('backup_restore_invariants_failed')
    if '004_standalone_portal.sql' in migrations:
        portal=query("""SELECT json_build_object('tables',(SELECT count(*) FROM information_schema.tables
            WHERE table_schema=current_schema() AND table_name IN ('portal_accounts','portal_sessions','portal_auth_limits','portal_dota_profiles','portal_replay_uploads')),
            'accounts',(SELECT count(*) FROM portal_accounts),
            'orphan_sessions',(SELECT count(*) FROM portal_sessions s LEFT JOIN portal_accounts a ON a.owner_id=s.owner_id WHERE a.owner_id IS NULL),
            'orphan_profiles',(SELECT count(*) FROM portal_dota_profiles p LEFT JOIN portal_accounts a ON a.owner_id=p.owner_id WHERE a.owner_id IS NULL));""")
        singleton='021_portal_multiple_accounts.sql' not in migrations
        if portal['tables']!=5 or (singleton and portal['accounts']>1) or portal['orphan_sessions'] or portal['orphan_profiles']:
            raise CheckError('backup_portal_restore_invariants_failed')
        state['portal']=portal
    if '005_replay_analysis.sql' in migrations:
        replay=query(REPLAY_RESTORE_SQL)
        if replay['tables']!=3 or replay['orphan_jobs'] or replay['orphan_parts'] or replay['invalid_ready_identity']:
            raise CheckError('backup_replay_restore_invariants_failed')
        state['replay']=replay
    if '006_replay_shared_ai_budget.sql' in migrations:
        provider=query(provider_restore_sql(migrations))
        if provider['invalid_call_jobs']:
            event('backup_provider_restore_diagnostics',**provider)
            raise CheckError('backup_provider_restore_invariants_failed')
        state['provider']=provider
    if '018_openai_api.sql' in migrations:
        openai=query(openai_restore_sql(migrations))
        if (openai['tables']!=2 or openai['budget_rows']!=1 or openai['invalid_call_jobs']
                or openai['invalid_call_accounting'] or openai['invalid_budget']):
            event('backup_openai_restore_diagnostics',**openai)
            raise CheckError('backup_openai_restore_invariants_failed')
        state['openai']=openai
    # Both writes target the disconnected drill copy. Never reset money, holds,
    # expiry or a prior accounting freeze, and never enable either provider.
    query("""UPDATE video_ai_budget SET enabled=false,
        frozen_reason=coalesce(frozen_reason,'RESTORE_REQUIRES_SPEND_RECONCILIATION') WHERE id=1
        RETURNING json_build_object('disabled',NOT enabled);""")
    if '018_openai_api.sql' in migrations:
        query("""UPDATE openai_api_budget SET enabled=false,
            frozen_reason=coalesce(frozen_reason,'RESTORE_REQUIRES_SPEND_RECONCILIATION') WHERE id=1
            RETURNING json_build_object('disabled',NOT enabled);""")
    return state


def bucket(cloud):
    plans=cloud.list('/api/v1/presets/storages','storages_presets')
    plan=next((p for p in plans if p.get('id')==PRESET),None)
    if not plan or type(plan.get('price')) not in (int,float) or not 0<plan['price']<=79 or plan.get('storage_class')!='standard' or plan.get('disk')!=10240:
        event('backup_plan_unverified',plan={k:(plan or {}).get(k) for k in ('id','price','disk','storage_class')})
        raise CheckError('backup_plan_changed')
    existing=cloud.list('/api/v1/storages/buckets','buckets')
    matches=[b for b in existing if b.get('description')==DESCRIPTION]
    if len(matches)>1:
        raise CheckError('backup_bucket_ambiguous')
    if matches:
        result=matches[0]
    else:
        if any('narma-pg-backups-9037783' in str(b.get('name','')) for b in existing):
            raise CheckError('backup_bucket_ownership_mismatch')
        result=cloud.call('POST','/api/v1/storages/buckets',{'name':'narma-pg-backups-9037783',
            'type':'private','preset_id':PRESET,'project_id':PROJECT,'description':DESCRIPTION})['bucket']
        event('backup_bucket_created',bucket_id=result['id'],month_equivalent_rub=plan['price'])
    for attempt in range(12):
        result=cloud.call('GET',f"/api/v1/storages/buckets/{int(result['id'])}")['bucket']
        if result.get('access_key') and result.get('secret_key') and result.get('status')=='created':
            break
        time.sleep(5)
    if result.get('project_id')!=PROJECT or result.get('preset_id')!=PRESET or result.get('type')!='private':
        raise CheckError('backup_bucket_configuration_mismatch')
    if result.get('status')!='created':
        raise CheckError('backup_bucket_not_ready')
    if result.get('is_allow_auto_upgrade') is not False:
        if result.get('is_allow_auto_upgrade') is not True:
            raise CheckError('backup_auto_upgrade_state_unknown')
        from disable_s3_expansion import disable_expansion
        disable_expansion(result,cloud.token)
        result=cloud.call('GET',f"/api/v1/storages/buckets/{int(result['id'])}")['bucket']
        if result.get('is_allow_auto_upgrade') is not False:
            raise CheckError('backup_auto_upgrade_must_be_disabled')
        event('backup_auto_upgrade_status',bucket_id=result['id'],disabled=True)
    return result

def verify_restore(dump):
    name='narma-restore-'+uuid4().hex
    image='postgres:17-bookworm'
    # No cloud credentials, public ports, production volumes or network in the drill.
    try:
        command(['docker','run','-d','--name',name,'--network','none','--memory','1g','--cpus','1',
            '--pids-limit','128','--env','POSTGRES_USER=drill','--env','POSTGRES_DB=narma_restore_drill',
            '--env','POSTGRES_HOST_AUTH_METHOD=trust',image])
        for attempt in range(30):
            result=subprocess.run(['docker','exec',name,'pg_isready','-h','127.0.0.1','-U','drill'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
            if result.returncode==0: break
            time.sleep(1)
        else: raise CheckError('backup_restore_database_unavailable')
        with dump.open('rb') as source:
            result=subprocess.run(['docker','exec','-i',name,'pg_restore','--username=drill','--dbname=narma_restore_drill',
                '--no-owner','--no-acl','--single-transaction','--exit-on-error','--no-password'],stdin=source,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=300)
        if result.returncode: raise CheckError('backup_restore_failed')
        def restored_query(sql):
            output=command(['docker','exec','-i',name,'psql','-U','drill','-d','narma_restore_drill',
                '-v','ON_ERROR_STOP=1','-At'],input=sql.encode())
            return json.loads(output.decode().splitlines()[0])
        state=verify_restored_database(restored_query)
        event('backup_restore_verified',**state)
        return state
    finally:
        subprocess.run(['docker','rm','--force','--volumes',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)

def backup(cloud,ssh,temporary):
    # Cloud-only dependencies are unnecessary for isolated SQL verification.
    import boto3
    from botocore.config import Config
    destination=bucket(cloud)
    dump=temporary/'database.dump'
    # Enforce the output cap in the SSH process; an oversized dump cannot fill the runner.
    def bound(): resource.setrlimit(resource.RLIMIT_FSIZE,(MAX_DUMP,MAX_DUMP))
    remote='cd /opt/narma/current/services/video && docker compose --project-name narma-video --env-file /opt/narma/secrets/video.env exec -T db pg_dump --username=narma --dbname=narma --format=custom --compress=gzip:6 --lock-wait-timeout=5s --no-password'
    with dump.open('wb') as output:
        result=subprocess.run(ssh+[remote],stdout=output,stderr=subprocess.DEVNULL,timeout=600,preexec_fn=bound)
    if result.returncode or not 16<dump.stat().st_size<=MAX_DUMP:
        raise CheckError('backup_dump_failed_or_oversized')
    with dump.open('rb') as file: digest=hashlib.file_digest(file,'sha256').hexdigest()
    # Timeweb's documented regional SDK endpoint, independent of display hostname formatting.
    client=boto3.client('s3',endpoint_url='https://s3.twcstorage.ru',region_name='ru-1',
        aws_access_key_id=destination['access_key'],aws_secret_access_key=destination['secret_key'],
        config=Config(connect_timeout=15,read_timeout=60,retries={'total_max_attempts':2},s3={'addressing_style':'path'}))
    name=destination['name']
    objects=[]
    for page in client.get_paginator('list_objects_v2').paginate(Bucket=name):
        objects.extend(page.get('Contents',[]))
        if len(objects)>1000: raise CheckError('backup_bucket_inventory_exceeded')
    if sum(o['Size'] for o in objects)+dump.stat().st_size+4096>8*1024**3:
        raise CheckError('backup_capacity_limit')
    key=PREFIX+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex+'.dump'
    verified_success=False
    try:
        # Single PUT avoids abandoned multipart uploads; the dump cap is below S3's limit.
        with dump.open('rb') as file:
            client.put_object(Bucket=name,Key=key,Body=file,ContentLength=dump.stat().st_size,
                ContentType='application/octet-stream',Metadata={'sha256':digest})
        restored=temporary/'downloaded.dump'
        response=client.get_object(Bucket=name,Key=key)
        body=response['Body']; downloaded=0;download_hash=hashlib.sha256()
        try:
            if response['ContentLength']!=dump.stat().st_size:
                raise CheckError('backup_download_size_mismatch')
            with restored.open('wb') as file:
                while chunk:=body.read(1024*1024):
                    downloaded+=len(chunk)
                    if downloaded>dump.stat().st_size: raise CheckError('backup_download_oversized')
                    file.write(chunk);download_hash.update(chunk)
        finally: body.close()
        if downloaded!=dump.stat().st_size or download_hash.hexdigest()!=digest:
            raise CheckError('backup_download_hash_mismatch')
        verified=verify_restore(restored)
        manifest={'sha256':digest,'bytes':dump.stat().st_size,'source_vm':SERVER,'created_at':datetime.now(timezone.utc).isoformat(),
            'restore_verified':True,'schema':verified,'restore_budget_action':'disable until provider spend reconciled'}
        client.put_object(Bucket=name,Key=key+'.json',Body=json.dumps(manifest).encode(),ContentType='application/json')
        verified_success=True
    finally:
        if not verified_success:
            try:
                client.delete_object(Bucket=name,Key=key);client.delete_object(Bucket=name,Key=key+'.json')
            except Exception: event('backup_failed_object_cleanup_unconfirmed')
    # Prune only this script's pairs, after the new upload/download/restore succeeds.
    previous=sorted([o['Key'] for o in objects if re.fullmatch(re.escape(PREFIX)+r'[0-9]{8}T[0-9]{6}Z-[0-9a-f]{32}\.dump',o['Key'])
        and any(m['Key']==o['Key']+'.json' for m in objects)])
    for old in previous[:-6]:
        client.delete_object(Bucket=name,Key=old);client.delete_object(Bucket=name,Key=old+'.json')
    event('backup_complete',bucket_id=destination['id'],bytes=dump.stat().st_size,sha256=digest,
        off_server=True,download_verified=True,restore_verified=True,retained=min(7,len(previous)+1))

def main():
    os.umask(0o077);cloud=Cloud();key_id=None
    server=cloud.call('GET',f'/api/v1/servers/{SERVER}')['server']
    if server.get('project_id')!=PROJECT or server.get('name')!=NAME or server.get('comment')!=MARKER:
        raise CheckError('backup_server_ownership_mismatch')
    host=address(server)
    if not host: raise CheckError('backup_server_address_missing')
    with tempfile.TemporaryDirectory(prefix='narma-backup-') as tmp:
        temporary=Path(tmp);private=temporary/'ssh-key'
        command(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(private)])
        try:
            key_id=int(cloud.call('POST','/api/v1/ssh-keys',{'name':'narma-backup-'+os.environ.get('GITHUB_RUN_ID','manual'),
                'body':private.with_suffix('.pub').read_text().strip(),'is_default':False})['ssh_key']['id'])
            cloud.call('POST',f'/api/v1/servers/{SERVER}/ssh-keys',{'ssh_key_ids':[key_id]})
            ssh=['ssh','-i',str(private),'-o','BatchMode=yes','-o','IdentitiesOnly=yes','-o','StrictHostKeyChecking=accept-new',
                '-o','UserKnownHostsFile='+str(temporary/'known_hosts'),'-o','ConnectTimeout=8','root@'+host]
            for attempt in range(20):
                try: command(ssh+['true'],timeout=15);break
                except (CheckError,subprocess.TimeoutExpired):
                    if attempt==19: raise CheckError('backup_ssh_unavailable') from None
                    time.sleep(5)
            backup(cloud,ssh,temporary)
        finally:
            if key_id is not None:
                try: cloud.call('DELETE',f'/api/v1/servers/{SERVER}/ssh-keys/{key_id}')
                except CheckError: event('backup_key_binding_cleanup_unconfirmed')
                try: cloud.call('DELETE',f'/api/v1/ssh-keys/{key_id}')
                except CheckError: event('backup_key_cleanup_unconfirmed')

if __name__=='__main__':
    try: main()
    except Exception as error:
        event('backup_failed',code=str(error) if isinstance(error,CheckError) else 'backup_failure_no_sensitive_details_logged');raise SystemExit(1)
