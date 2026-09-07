"""Host nginx and renewable ACME certificate. No API credentials enter nginx."""
import argparse
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import socket
import ssl
import subprocess
import sys
import time
from uuid import uuid4

IMAGE='certbot/certbot:v5.8.0@sha256:f70ad0adbb7e117f0fe42a63c553f28ea451edabc0148757b6efcd9735acaa20'
WEB=Path('/var/www/narma-acme')
STATE=Path('/opt/narma/https.json')
CERT=Path('/etc/letsencrypt/live/narma-service')

def run(args,timeout=180):
    result=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
    if result.returncode:
        # ACME debug output can contain account identifiers. Emit bounded categories only.
        diagnostic=(result.stdout+result.stderr).lower()
        code='rate_limited' if b'ratelimit' in diagnostic or b'rate limit' in diagnostic else 'dns' if b'dns problem' in diagnostic else 'challenge' if b'unauthorized' in diagnostic else 'command'
        raise RuntimeError('https_'+code+'_failed')
    return result.stdout

def atomic(path,text,mode=0o644):
    temporary=path.with_suffix('.new')
    temporary.write_text(text);temporary.chmod(mode);temporary.replace(path)

def certbot(arguments,staging=False):
    name='narma-acme-'+uuid4().hex
    args=['docker','run','--name',name,'--rm','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges',
          '--memory=256m','--cpus=0.5','--pids-limit=64','--tmpfs=/tmp:size=32m,mode=1777']
    for target in ('/etc/letsencrypt','/var/lib/letsencrypt','/var/log/letsencrypt'):
        source=Path(target+('-staging' if staging else ''));source.mkdir(parents=True,exist_ok=True,mode=0o700)
        args+=['--volume',str(source)+':'+target]
    args+=['--volume',str(WEB)+':'+str(WEB),IMAGE]+arguments
    try:
        return run(args,timeout=360)
    finally:
        subprocess.run(['docker','rm','--force',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)

def config(hostname,tls):
    challenge=f'location ^~ /.well-known/acme-challenge/ {{ root {WEB}; default_type text/plain; try_files $uri =404; }}'
    fallback=f'return 308 https://{hostname}$request_uri;' if tls else 'return 404;'
    result=f'''server {{
    listen 80 default_server;
    server_name {hostname};
    access_log off;
    {challenge}
    location / {{ {fallback} }}
}}
'''
    if tls:
        result+=f'''server {{
    listen 443 ssl default_server;
    server_name {hostname};
    ssl_certificate {CERT}/fullchain.pem;
    ssl_certificate_key {CERT}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_tickets off;
    if ($host != {hostname}) {{ return 421; }}
    access_log off;
    server_tokens off;
    client_max_body_size 6m;
    client_body_timeout 60s;
    add_header X-Content-Type-Options nosniff always;
    location = /livez {{ proxy_pass http://127.0.0.1:8080; }}
    location = /readyz {{ return 404; }}
    location /v1/ {{
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header Connection "";
        proxy_request_buffering off;
        proxy_buffering off;
        proxy_read_timeout 120s;
        proxy_send_timeout 120s;
    }}
    location / {{ return 404; }}
}}
'''
    return result

def reload_verified(hostname,ip):
    run(['nginx','-t']);run(['systemctl','reload','nginx'])
    run(['openssl','x509','-in',str(CERT/'cert.pem'),'-noout','-checkhost',hostname,'-checkend','172800'])
    # Verify trust, SAN and the certificate actually loaded by the local listener.
    context=ssl.create_default_context()
    expected=hashlib.sha256(ssl.PEM_cert_to_DER_cert((CERT/'cert.pem').read_text())).hexdigest()
    for attempt in range(10):
        with socket.create_connection(('127.0.0.1',443),timeout=15) as raw:
            with context.wrap_socket(raw,server_hostname=hostname) as connection:
                fingerprint=hashlib.sha256(connection.getpeercert(binary_form=True)).hexdigest()
        if fingerprint==expected:
            break
        time.sleep(.5)
    if fingerprint!=expected:
        raise RuntimeError('https_reload_not_observed')
    atomic(Path('/opt/narma/https-loaded-fingerprint'),fingerprint+'\n',0o600)

def prepare(hostname,ip):
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]{1,200})[a-z0-9]',hostname) or '..' in hostname:
        raise RuntimeError('https_invalid_hostname')
    address=ipaddress.ip_address(ip)
    if address.version!=4 or not address.is_global:
        raise RuntimeError('https_invalid_ip')
    addresses={x[4][0] for x in socket.getaddrinfo(hostname,80,type=socket.SOCK_STREAM)}
    if addresses!={ip}:
        raise RuntimeError('https_dns_mismatch')
    if STATE.exists() and json.loads(STATE.read_text())!={'hostname':hostname,'ip':ip}:
        raise RuntimeError('https_existing_identity_mismatch')
    run(['apt-get','update','-qq'])
    run(['apt-get','install','-y','-qq','nginx'],timeout=180)
    WEB.mkdir(parents=True,exist_ok=True,mode=0o755)
    (WEB/'.well-known/acme-challenge').mkdir(parents=True,exist_ok=True,mode=0o755)
    default=Path('/etc/nginx/sites-enabled/default')
    if default.is_symlink() and default.resolve()==Path('/etc/nginx/sites-available/default'):
        default.unlink()
    target=Path('/etc/nginx/sites-enabled/narma-service.conf')
    if target.exists() and not STATE.exists():
        raise RuntimeError('https_unmanaged_nginx_config')
    atomic(STATE,json.dumps({'hostname':hostname,'ip':ip}),0o600)
    atomic(target,config(hostname,(CERT/'fullchain.pem').exists()))
    run(['nginx','-t']);run(['systemctl','enable','--now','nginx']);run(['systemctl','reload','nginx'])
    run(['ufw','allow','80/tcp']);run(['ufw','allow','443/tcp'])
    # Public challenge probe is verified independently by the runner before issuance.
    atomic(WEB/'.well-known/acme-challenge/narma-probe','narma-acme-'+ip+'\n')

def issue(hostname,ip):
    args=['certonly','--non-interactive','--agree-tos','--register-unsafely-without-email',
          '--webroot','--webroot-path',str(WEB),'--preferred-challenges','http',
          '--cert-name','narma-service','--domain',hostname,'--keep-until-expiring']
    if not (CERT/'fullchain.pem').exists():
        certbot(args+['--staging'],staging=True)
    certbot(args)
    atomic(Path('/etc/nginx/sites-enabled/narma-service.conf'),config(hostname,True))
    reload_verified(hostname,ip)
    current=Path(__file__).resolve()
    installed=Path('/usr/local/lib/narma-https.py');installed.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(current,installed);installed.chmod(0o644)
    atomic(Path('/etc/systemd/system/narma-https-renew.service'),'''[Unit]
Description=Renew NARMA HTTPS and verify loaded certificate
After=network-online.target docker.service nginx.service
[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /usr/local/lib/narma-https.py renew
TimeoutStartSec=480
UMask=0077
''')
    atomic(Path('/etc/systemd/system/narma-https-renew.timer'),'''[Unit]
Description=Hourly NARMA certificate renewal check
[Timer]
OnCalendar=hourly
RandomizedDelaySec=15m
Persistent=true
[Install]
WantedBy=timers.target
''')
    run(['systemctl','daemon-reload']);run(['systemctl','enable','--now','narma-https-renew.timer'])
    marker=Path('/opt/narma/checks/https-renewal-passed')
    marker.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if not marker.exists():
        certbot(['renew','--cert-name','narma-service','--dry-run','--non-interactive','--no-random-sleep-on-renew'])
        atomic(marker,'passed\n',0o600)
    (WEB/'.well-known/acme-challenge/narma-probe').unlink(missing_ok=True)

def main():
    os.environ['DEBIAN_FRONTEND']='noninteractive'
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','issue','renew']);parser.add_argument('hostname',nargs='?');parser.add_argument('ip',nargs='?');args=parser.parse_args()
    with open('/var/lock/narma-https.lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if args.action=='prepare':
            prepare(args.hostname,args.ip)
        else:
            state=json.loads(STATE.read_text())
            if args.action=='issue':
                issue(**state)
            else:
                certbot(['renew','--cert-name','narma-service','--non-interactive','--quiet','--no-random-sleep-on-renew'])
                reload_verified(**state)
    print(json.dumps({'event':'https_'+args.action,'state':'passed'}),flush=True)

if __name__=='__main__':
    try:
        main()
    except Exception as error:
        code=str(error) if isinstance(error,RuntimeError) and re.fullmatch('https_[a-z_]+',str(error)) else 'https_operation_failed'
        print(json.dumps({'event':'https_failure','code':code}),flush=True);sys.exit(1)
