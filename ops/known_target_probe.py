"""Explicit incident probe for a previously verified, owner-authorized VM.

Not a deployment fallback. No application writes or provider GET requests.
The only provider mutations are creating/binding an ephemeral SSH key and cleanup.
Verifies private on-host identity before reporting diagnostic success.
"""
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent / 'timeweb'))
from pilot import Cloud, CheckError, command, event

SERVER = 9037783
PROJECT = 2655641
HOST = "72.56.98.68"
RELEASE = "c8a15da3eb9983466ec43817f78c0191eced302b"
JOB = "354d95b9-2bb7-4700-923d-796566a7cc01"
SOURCE = "db9df23273bdac450a027ff11992428e6610403de78301c86e9adbe26320e0bc"

DATABASE_PROBE = r'''
import hashlib,json,pathlib,sys
from narma_video.db import database
request=json.loads(sys.stdin.read())
with database() as c:
 c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
 row=c.execute("SELECT id,owner_id,account_id,match_id,source_sha256,size_bytes,state FROM replay_jobs WHERE id=%s AND state<>'deleted'",('354d95b9-2bb7-4700-923d-796566a7cc01',)).fetchone()
 assert row and row['account_id']==435842051 and row['match_id']=='8984479726'
 assert row['source_sha256']=='db9df23273bdac450a027ff11992428e6610403de78301c86e9adbe26320e0bc' and row['size_bytes']==169982117
 profile=c.execute('SELECT account_id FROM portal_dota_profiles WHERE owner_id=%s',(row['owner_id'],)).fetchone()
 assert profile and profile['account_id']==row['account_id']
 assert c.execute('SELECT 1 FROM portal_accounts WHERE owner_id=%s',(row['owner_id'],)).fetchone()
 owners=c.execute('SELECT owner_id FROM portal_accounts ORDER BY owner_id').fetchall()
 bindings=c.execute('SELECT owner_id,account_id FROM portal_dota_profiles ORDER BY owner_id').fetchall()
 fingerprint=hashlib.sha256(json.dumps({'owners':owners,'bindings':bindings},sort_keys=True).encode()).hexdigest()
 assert fingerprint==request['expected_owner_identity']
 source=pathlib.Path('/var/lib/narma/video/replays/354d95b9-2bb7-4700-923d-796566a7cc01/source.dem')
 assert source.is_file() and not source.is_symlink() and source.stat().st_size==row['size_bytes']
 with source.open('rb') as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==row['source_sha256']
 assert row['state'] in ('uploading','queued','processing','ready','failed')
 print(json.dumps({'event':'known_target_readonly_probe_passed','release_verified':True,'target_configuration_verified':True,'source_verified':True,'owner_profile_verified':True,'prior_owner_fingerprint_verified':True,'job_state':row['state']}))
'''


def host_probe():
    # The host verifies its old release and the private identity checkpoint before
    # executing only SELECTs in the existing API container. No new image is loaded.
    return """import json,pathlib,re,subprocess,sys
release=%r
root=pathlib.Path('/opt/narma/releases')/release
assert pathlib.Path('/opt/narma/current').resolve()==root
target=json.loads((root/'ops/timeweb/portal-setup.json').read_text())
assert target['server_id']==9037783 and target['project_id']==2655641
assert target['origin']=='https://narma-72-56-98-68.sslip.io'
snapshot=json.loads((pathlib.Path('/opt/narma/checks')/('workers-before-'+release+'.json')).read_text())
assert snapshot['release']==release
identity=snapshot['before']['owner_identity']
assert re.fullmatch('[0-9a-f]{64}',identity)
compose=['docker','compose','--project-name','narma-video','--env-file','/opt/narma/secrets/video.env','--file',str(root/'services/video/compose.yaml')]
result=subprocess.run(compose+['exec','-T','api','python','-c',%r],input=json.dumps({'expected_owner_identity':identity}).encode(),capture_output=True,timeout=60)
assert result.returncode==0
value=json.loads(result.stdout)
assert value.get('event')=='known_target_readonly_probe_passed'
print(json.dumps(value))
""" % (RELEASE, DATABASE_PROBE)


def main():
    cloud = Cloud()
    ssh_id = None
    binding_attempted = False
    with tempfile.TemporaryDirectory(prefix="narma-known-target-probe-") as folder:
        folder = Path(folder)
        key = folder / "key"
        command(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)])
        try:
            # POST is never retried by Cloud.call. An ambiguous result stops here.
            created = cloud.call("POST", "/api/v1/ssh-keys", {
                "name": "narma-known-target-readonly-probe",
                "body": key.with_suffix(".pub").read_text().strip(), "is_default": False})
            ssh_id = created.get("ssh_key", {}).get("id")
            if type(ssh_id) is not int or ssh_id <= 0:
                raise CheckError("known_target_probe_key_outcome_unknown")
            binding_attempted = True
            cloud.call("POST", f"/api/v1/servers/{SERVER}/ssh-keys", {"ssh_key_ids": [ssh_id]})
            ssh = ["ssh", "-i", str(key), "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
                "-o", "StrictHostKeyChecking=accept-new", "-o", "UserKnownHostsFile=" + str(folder / "known_hosts"),
                "-o", "ConnectTimeout=8", "-o", "ServerAliveInterval=15", "root@" + HOST]
            # Only harmless SSH authentication probes may repeat while binding propagates.
            for attempt in range(6):
                try:
                    command(ssh + ["true"], timeout=12)
                    break
                except CheckError:
                    if attempt == 5: raise
                    time.sleep(2)
            result = command(ssh + ["python3 -c " + shlex.quote(host_probe())], timeout=80)
            value = json.loads(result)
            expected = {"event", "release_verified", "target_configuration_verified", "source_verified", "owner_profile_verified",
                "prior_owner_fingerprint_verified", "job_state"}
            if set(value) != expected or value["event"] != "known_target_readonly_probe_passed" or any(
                    value[key] is not True for key in expected - {"event", "job_state"}):
                raise CheckError("known_target_probe_not_verified")
            if value["job_state"] not in {"uploading", "queued", "processing", "ready", "failed"}:
                raise CheckError("known_target_probe_not_verified")
            # No private path, roster, email, prompt, session or key is logged.
            print(json.dumps(value), flush=True)
        finally:
            if ssh_id is not None:
                if binding_attempted:
                    try: cloud.call("DELETE", f"/api/v1/servers/{SERVER}/ssh-keys/{ssh_id}")
                    except CheckError: event("known_target_probe_binding_cleanup_unconfirmed")
                try: cloud.call("DELETE", f"/api/v1/ssh-keys/{ssh_id}")
                except CheckError: event("known_target_probe_key_cleanup_unconfirmed")


if __name__ == "__main__":
    try: main()
    except CheckError as error:
        event("known_target_probe_failed", code=str(error)); sys.exit(1)
    except Exception:
        event("known_target_probe_failed", code="probe_unverified_no_sensitive_details_logged"); sys.exit(1)
