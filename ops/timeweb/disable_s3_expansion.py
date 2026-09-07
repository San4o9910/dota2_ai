"""Use the documented Terraform resource; allow only disabling S3 auto expansion."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
from preflight import CheckError

def disable_expansion(bucket,token):
    executable='/tmp/narma-terraform/terraform'
    if not Path(executable).is_file():
        raise CheckError('backup_terraform_not_prepared')
    with tempfile.TemporaryDirectory(prefix='narma-storage-config-') as temp:
        directory=Path(temp)
        configuration={'terraform':{'required_providers':{'twc':{'source':'timeweb-cloud/timeweb-cloud','version':'= 1.8.2'}}},
            'provider':{'twc':{}},'resource':{'twc_s3_bucket':{'backup':{
                'name':bucket['name'],'type':bucket['type'],'preset_id':bucket['preset_id'],
                'project_id':bucket['project_id'],'description':bucket['description'],
                'is_allow_auto_upgrade':False,'lifecycle':{'prevent_destroy':True}}}}}
        (directory/'main.tf.json').write_text(json.dumps(configuration))
        env={**os.environ,'TWC_TOKEN':token,'TF_IN_AUTOMATION':'1'}
        def run(*args):
            result=subprocess.run([executable,*args],cwd=directory,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=180)
            if result.returncode: raise CheckError('backup_terraform_operation_failed')
            return result.stdout
        run('init','-input=false')
        lock=(directory/'.terraform.lock.hcl').read_text()
        if 'zh:3ba47ace275a8a0bc28381db598282d6e2d860762e045624ea3b146d14e9b05e' not in lock:
            raise CheckError('backup_provider_checksum_mismatch')
        run('import','-input=false','twc_s3_bucket.backup',str(bucket['id']))
        run('plan','-input=false','-out=approved.tfplan')
        plan=json.loads(run('show','-json','approved.tfplan'))
        changes=[r for r in plan.get('resource_changes',[]) if r['change']['actions']!=['no-op']]
        if len(changes)!=1 or changes[0]['address']!='twc_s3_bucket.backup' or changes[0]['change']['actions']!=['update']:
            raise CheckError('backup_terraform_unexpected_operations')
        before=changes[0]['change']['before'];after=changes[0]['change']['after']
        different={k for k in set(before)|set(after) if before.get(k)!=after.get(k)}
        if different!={'is_allow_auto_upgrade'} or before['is_allow_auto_upgrade'] is not True or after['is_allow_auto_upgrade'] is not False:
            raise CheckError('backup_terraform_unexpected_change')
        run('apply','-input=false','approved.tfplan')
