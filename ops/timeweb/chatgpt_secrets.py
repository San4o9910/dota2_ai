"""Server-only OAuth encryption setup; never prints keys, tokens or env files."""
import base64
import json
import os
from pathlib import Path
import re
import secrets

from snapshot_worker_state import ENV_FILE, run, write_private

SETTINGS = ('REPLAY_COACH_PROVIDER', 'HERMES_PROVIDER', 'HERMES_RUNTIME_ENABLED')


def settings_path(release):
    if not re.fullmatch('[0-9a-f]{40}', release):
        raise RuntimeError('chatgpt_release_invalid')
    return Path('/opt/narma/checks') / ('chatgpt-settings-before-' + release + '.json')


def validate_key(key):
    try:
        raw = base64.b64decode(key, altchars=b'-_', validate=True)
    except (ValueError, TypeError):
        raise RuntimeError('chatgpt_encryption_key_invalid') from None
    if len(raw) != 32 or base64.urlsafe_b64encode(raw).decode() != key:
        raise RuntimeError('chatgpt_encryption_key_invalid')


def existing_connections():
    """Fail closed if a durable installation cannot rule out encrypted tokens."""
    ids = run(['docker', 'ps', '--quiet', '--filter', 'label=com.docker.compose.project=narma-video',
               '--filter', 'label=com.docker.compose.service=api']).splitlines()
    if len(ids) != 1:
        raise RuntimeError('chatgpt_existing_credentials_unverified')
    identifier = ids[0].decode()
    if not re.fullmatch('[0-9a-f]{12,64}', identifier):
        raise RuntimeError('chatgpt_existing_credentials_unverified')
    code = '''from narma_video.db import database
with database() as c:
 c.execute('SET TRANSACTION READ ONLY')
 present=c.execute("SELECT to_regclass('public.chatgpt_connections') AS r").fetchone()['r']
 print(c.execute('SELECT count(*) AS n FROM chatgpt_connections').fetchone()['n'] if present else 0)
'''
    output = run(['docker', 'exec', identifier, 'python', '-c', code]).strip()
    if not re.fullmatch(rb'[0-9]{1,12}', output):
        raise RuntimeError('chatgpt_existing_credentials_unverified')
    return int(output)


def prepare_settings(values, release, *, established=True):
    key = values.get('NARMA_CHATGPT_ENCRYPTION_KEY')
    if key:
        validate_key(key)
    else:
        if established and existing_connections():
            raise RuntimeError('chatgpt_existing_encryption_key_required')
        key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
    # Only non-secret provider settings enter rollback metadata. The encryption
    # key must survive every release rollback and every database restoration.
    write_private(settings_path(release), {'release': release,
        'settings': {name: values.get(name) for name in SETTINGS}})
    values['NARMA_CHATGPT_ENCRYPTION_KEY'] = key
    values.update(REPLAY_COACH_PROVIDER='chatgpt_subscription',
                  HERMES_PROVIDER='chatgpt_subscription', HERMES_RUNTIME_ENABLED='1')
    return values


def restore_settings(release, path=None):
    saved = settings_path(release)
    if not saved.exists():
        return False
    snapshot = json.loads(saved.read_text())
    settings = snapshot.get('settings')
    if snapshot.get('release') != release or not isinstance(settings, dict) or set(settings) != set(SETTINGS):
        raise RuntimeError('chatgpt_settings_snapshot_invalid')
    if any(value is not None and (not isinstance(value, str) or '\n' in value or '\r' in value)
           for value in settings.values()):
        raise RuntimeError('chatgpt_settings_snapshot_invalid')
    path = Path(path or ENV_FILE)
    values = dict(line.split('=', 1) for line in path.read_text().splitlines())
    for name, value in settings.items():
        if value is None:
            values.pop(name, None)
        else:
            values[name] = value
    temporary = path.with_suffix('.rollback')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        stream.write(''.join(name + '=' + value + '\n' for name, value in values.items()))
        stream.flush(); os.fsync(stream.fileno())
    temporary.chmod(0o600)
    temporary.replace(path)
    return True
