"""Read-only image identity diagnostics on the explicitly owned existing pilot."""
import json
from pathlib import Path
import shlex
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).parent / 'timeweb'))
from pilot import Cloud, CheckError, command, event, pinned_existing_server, address

PROBE = r'''
import hashlib,json,pathlib,re,subprocess,tarfile
root=pathlib.Path('/opt/narma/releases/1218e93b604f4a8b006198b1f6502dc51ca18851')
assert pathlib.Path('/opt/narma/current').resolve().name=='c8a15da3eb9983466ec43817f78c0191eced302b'
manifest=json.loads((root/'images-manifest.json').read_text())
archive=root/'images.tar.gz'
assert archive.stat().st_size==manifest['archive_bytes']
with archive.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==manifest['archive_sha256']
def docker(args):
 p=subprocess.run(['docker']+args,stdin=subprocess.DEVNULL,capture_output=True,timeout=30)
 if p.returncode:return None
 return json.loads(p.stdout)
def member_json(t,name):
 m=t.getmember(name)
 assert m.isfile() and m.size<=1024*1024
 with t.extractfile(m) as f:data=f.read()
 return json.loads(data),hashlib.sha256(data).hexdigest()
result={'event':'image_identity_diagnostic','archive_integrity_verified':True,
 'engine_version':docker(['version','--format','{{json .Server.Version}}']),
 'storage_driver':docker(['info','--format','{{json .Driver}}']),
 'driver_status':docker(['info','--format','{{json .DriverStatus}}']),
 'images':[]}
with tarfile.open(archive,'r:gz') as t:
 entries,_=member_json(t,'manifest.json')
 for entry in entries:
  tags=[tag.removesuffix(':latest') for tag in entry.get('RepoTags',[])]
  if not any(tag in manifest['images'] for tag in tags):continue
  assert all(tag in manifest['images'] for tag in tags)
  config,digest=member_json(t,entry['Config'])
  identifier='sha256:'+digest
  fmt='{"id":{{json .Id}},"os":{{json .Os}},"architecture":{{json .Architecture}},"layers":{{json .RootFS.Layers}}}'
  result['images'].append({'tags':tags,'ci_ids':sorted({manifest['images'][tag]['id'] for tag in tags}),
   'archive_config_id':identifier,'archive_os':config.get('os'),'archive_architecture':config.get('architecture'),
   'archive_layers':config.get('rootfs',{}).get('diff_ids',[]),
   'loaded_lookup_by_config':docker(['image','inspect','--format',fmt,identifier])})
print(json.dumps(result))
'''


def main():
    cloud=Cloud()
    server=pinned_existing_server(cloud)
    ssh_id=None
    with tempfile.TemporaryDirectory(prefix='narma-image-inspect-') as directory:
        directory=Path(directory);key=directory/'key'
        command(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(key)])
        try:
            created=cloud.call('POST','/api/v1/ssh-keys',{'name':'narma-image-identity-inspect',
                'body':key.with_suffix('.pub').read_text().strip(),'is_default':False})
            ssh_id=created['ssh_key']['id']
            if type(ssh_id) is not int or ssh_id<=0:raise CheckError('image_probe_key_invalid')
            cloud.call('POST',f"/api/v1/servers/{server['id']}/ssh-keys",{'ssh_key_ids':[ssh_id]})
            ssh=['ssh','-i',str(key),'-o','BatchMode=yes','-o','IdentitiesOnly=yes',
                '-o','StrictHostKeyChecking=accept-new','-o','UserKnownHostsFile='+str(directory/'known_hosts'),
                '-o','ConnectTimeout=8','-o','ServerAliveInterval=15','root@'+address(server)]
            for attempt in range(12):
                try:command(ssh+['true'],timeout=15);break
                except CheckError:
                    if attempt==11:raise
                    time.sleep(5)
            value=json.loads(command(ssh+['python3 -c '+shlex.quote(PROBE)],timeout=200))
            if value.get('event')!='image_identity_diagnostic':raise CheckError('image_probe_invalid')
            print(json.dumps(value),flush=True)
        finally:
            if ssh_id is not None:
                try:cloud.call('DELETE',f"/api/v1/servers/{server['id']}/ssh-keys/{ssh_id}")
                except CheckError:event('image_probe_binding_cleanup_unconfirmed')
                try:cloud.call('DELETE',f'/api/v1/ssh-keys/{ssh_id}')
                except CheckError:event('image_probe_key_cleanup_unconfirmed')


if __name__=='__main__':
    try:main()
    except CheckError as error:
        event('image_probe_failed',code=str(error));sys.exit(1)
    except Exception:
        event('image_probe_failed',code='diagnostic_unavailable');sys.exit(1)
