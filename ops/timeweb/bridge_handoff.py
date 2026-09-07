"""Encrypt only the site-to-video credential for the authorized Sites secret store."""
import base64
import hashlib
import json
import re
from pathlib import Path
import subprocess
import sys
import tempfile

def main():
    release,run_id=sys.argv[1:]
    if not re.fullmatch('[0-9a-f]{40}',release) or not re.fullmatch('[0-9]{1,20}',run_id):
        raise ValueError()
    config=json.loads((Path(__file__).parent/'bridge-handoff.json').read_text())
    if config['server_id']!=9037783 or config['project_id']!=2655641:
        raise ValueError()
    public=config['public_key'].encode()
    values=dict(line.split('=',1) for line in Path('/opt/narma/secrets/video.env').read_text().splitlines())
    token=values['VIDEO_SERVICE_TOKEN']
    if not re.fullmatch('[a-f0-9]{64}',token):
        raise ValueError()
    origin='https://'+json.loads(Path('/opt/narma/https.json').read_text())['hostname']
    context={'token':token,'origin':origin,'vm':9037783,'sha':release,'run':run_id,
        'nonce':config['nonce'],'key':hashlib.sha256(public).hexdigest()}
    with tempfile.TemporaryDirectory(prefix='narma-handoff-') as directory:
        key=Path(directory)/'public.pem';key.write_bytes(public)
        result=subprocess.run(['openssl','pkeyutl','-encrypt','-pubin','-inkey',str(key),
            '-pkeyopt','rsa_padding_mode:oaep','-pkeyopt','rsa_oaep_md:sha256','-pkeyopt','rsa_mgf1_md:sha256'],
            input=json.dumps(context,separators=(',',':')).encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=15)
        if result.returncode or len(result.stdout)!=512:
            raise ValueError()
    print(json.dumps({'event':'encrypted_site_bridge','ciphertext':base64.b64encode(result.stdout).decode(),
        'key_fingerprint':context['key'],'release':release,'run_id':run_id,'server_id':9037783}),flush=True)

if __name__=='__main__':
    try:
        main()
    except Exception:
        print('{"event":"encrypted_site_bridge_failed"}',flush=True);sys.exit(1)
