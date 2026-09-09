"""Runs on the VPS; read secret JSON over SSH stdin and preserve database identity."""
import json
import fcntl
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
from chatgpt_secrets import prepare_settings
from stratz_secrets import install_stratz

os.umask(0o077)
lock = open("/var/lock/narma-deploy.lock", "a")
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
incoming = json.load(sys.stdin)
key = incoming["gemini_key"]
if not re.fullmatch(r"[A-Za-z0-9_./+=:-]{20,16384}", key):
    raise SystemExit(2)
directory = Path("/opt/narma/secrets")
directory.mkdir(parents=True, exist_ok=True, mode=0o700)
path = directory/"video.env"
values = {}
established = path.exists()
if path.exists():
    for line in path.read_text().splitlines():
        name, value = line.split("=", 1)
        values[name] = value
    if not all(values.get(name) for name in ("POSTGRES_PASSWORD", "VIDEO_SERVICE_TOKEN", "DATABASE_URL")):
        raise SystemExit(3)
else:
    existing_volume = Path("/var/lib/docker/volumes/narma-video_database").exists()
    if shutil.which("docker"):
        existing_volume = existing_volume or subprocess.run(
            ["docker","volume","inspect","narma-video_database"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20).returncode == 0
    if existing_volume:
        raise SystemExit(4)  # Restore the original credentials; never reset this DB.
    values["POSTGRES_PASSWORD"] = secrets.token_hex(32)
    values["VIDEO_SERVICE_TOKEN"] = secrets.token_hex(32)
    values["DATABASE_URL"] = "postgresql://narma:" + values["POSTGRES_PASSWORD"] + "@db:5432/narma"
values.update(GEMINI_API_KEY=key, GEMINI_MODEL="gemini-3.8-flash",
    VIDEO_FRAME_BUDGET="3600", VIDEO_REQUEST_BUDGET="250",
    VIDEO_OWNER_DAILY_REQUEST_BUDGET="250")
install_stratz(values, incoming.get("stratz_token"))
portal=json.loads((Path(__file__).parent/'portal-setup.json').read_text())
if portal['server_id']!=9037783 or portal['project_id']!=2655641 or portal['origin']!='https://narma-72-56-98-68.sslip.io':
    raise SystemExit(5)
if not re.fullmatch('[0-9a-f]{64}',portal['setup_token_sha256']):
    raise SystemExit(6)
values.update(APP_ORIGIN=portal['origin'],PORTAL_SETUP_TOKEN_SHA256=portal['setup_token_sha256'],PORTAL_SETUP_EXPIRES_AT=portal['setup_expires_at'])
if incoming.get('prepare_chatgpt_auth') is True:
    prepare_settings(values, incoming['release'], established=established)
temporary = path.with_suffix(".new")
temporary.write_text("".join(name+"="+value+"\n" for name,value in values.items()))
temporary.chmod(0o600)
temporary.replace(path)
