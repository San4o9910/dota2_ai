"""Prepare server-only API configuration without invoking providers or budgets."""
import fcntl
import json
import os
from pathlib import Path
import re
import sys
import tempfile

ENV_FILE = Path('/opt/narma/secrets/video.env')
CURRENT = Path('/opt/narma/current')
MODEL = 'gpt-5.6-sol'
SETTINGS = ('REPLAY_COACH_PROVIDER', 'HERMES_PROVIDER', 'HERMES_RUNTIME_ENABLED',
            'VIDEO_ANALYSIS_MODE', 'OPENAI_MODEL', 'OPENAI_MAX_DAILY_CALLS')


def validate_release(release):
    if not isinstance(release, str) or not re.fullmatch('[0-9a-f]{40}', release):
        raise RuntimeError('openai_release_invalid')


def validate_key(key):
    # Reject newline/Compose expansion/quoting before any env-file mutation.
    # This validates transport syntax only, not provider access or account credit.
    if not isinstance(key, str) or not re.fullmatch(r'sk-[A-Za-z0-9_-]{16,500}', key):
        raise RuntimeError('openai_key_format_invalid')


def install_key(values, key):
    """First installation or identical retry; never silently rotate a live key."""
    validate_key(key)
    existing = values.get('OPENAI_API_KEY')
    if existing and existing != key:
        raise RuntimeError('openai_existing_key_preserved')
    values['OPENAI_API_KEY'] = key


def prepare_openai_settings(values, release, *, enable_runtime=False):
    """Explicit deployment selection; caller persists non-secret rollback first.

    The existing runtime enabled flag is preserved. Credentials, monetary limits,
    accounting and outstanding reservations are not changed by this function.
    A newly migrated OpenAI allowance is disabled and cannot generate calls.
    """
    validate_release(release)
    validate_key(values.get('OPENAI_API_KEY'))
    daily = values.get('OPENAI_MAX_DAILY_CALLS', '20')
    if not re.fullmatch(r'[0-9]{1,3}', daily) or not 1 <= int(daily) <= 250:
        raise RuntimeError('openai_daily_cap_invalid')
    previous = {name: values.get(name) for name in SETTINGS}
    values.update(REPLAY_COACH_PROVIDER='openai_api', HERMES_PROVIDER='openai_api',
                  VIDEO_ANALYSIS_MODE='selective_v1', OPENAI_MODEL=MODEL,
                  OPENAI_MAX_DAILY_CALLS=daily)
    if enable_runtime:
        values['HERMES_RUNTIME_ENABLED'] = '1'
    return {'release': release, 'settings': previous}


def restore_openai_settings(values, snapshot, release):
    validate_release(release)
    previous = snapshot.get('settings') if isinstance(snapshot, dict) else None
    if (not isinstance(snapshot, dict) or snapshot.get('release') != release
            or not isinstance(previous, dict) or set(previous) != set(SETTINGS)
            or any(value is not None and (not isinstance(value, str)
                   or '\n' in value or '\r' in value) for value in previous.values())):
        raise RuntimeError('openai_settings_snapshot_invalid')
    for name, value in previous.items():
        if value is None:
            values.pop(name, None)
        else:
            values[name] = value


def settings_path(release):
    validate_release(release)
    return Path('/opt/narma/checks') / ('openai-settings-before-' + release + '.json')


def restore_settings(release, path=ENV_FILE):
    saved = settings_path(release)
    if not saved.is_file():
        return False
    values = read_values(Path(path))
    restore_openai_settings(values, json.loads(saved.read_text()), release)
    write_values(Path(path), values)
    return True


def read_values(path):
    if path.is_symlink() or not path.is_file():
        raise RuntimeError('openai_existing_settings_required')
    values = {}
    for line in path.read_text().splitlines():
        if '=' not in line:
            raise RuntimeError('openai_existing_settings_invalid')
        name, value = line.split('=', 1)
        if not re.fullmatch('[A-Z][A-Z0-9_]*', name) or name in values:
            raise RuntimeError('openai_existing_settings_invalid')
        values[name] = value
    if not all(values.get(name) for name in ('DATABASE_URL', 'POSTGRES_PASSWORD', 'VIDEO_SERVICE_TOKEN')):
        raise RuntimeError('openai_existing_settings_invalid')
    return values


def write_values(path, values):
    fd, temporary = tempfile.mkstemp(prefix='.openai-settings-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(''.join(name + '=' + value + '\n' for name, value in values.items()))
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def safe_status(values, release):
    valid_key = False
    try:
        validate_key(values.get('OPENAI_API_KEY'))
        valid_key = True
    except RuntimeError:
        pass
    providers = {'gemini', 'chatgpt_subscription', 'openai_api'}
    modes = {'full_frames_v1', 'selective_v1'}
    return {'event': 'openai_server_configuration', 'release': release,
            'key_present': bool(values.get('OPENAI_API_KEY')), 'key_format_valid': valid_key,
            'model_supported': values.get('OPENAI_MODEL', MODEL) == MODEL,
            'replay_provider': values.get('REPLAY_COACH_PROVIDER')
                if values.get('REPLAY_COACH_PROVIDER') in providers else 'unset_or_unknown',
            'hermes_provider': values.get('HERMES_PROVIDER')
                if values.get('HERMES_PROVIDER') in providers else 'unset_or_unknown',
            'video_mode': values.get('VIDEO_ANALYSIS_MODE', 'full_frames_v1')
                if values.get('VIDEO_ANALYSIS_MODE', 'full_frames_v1') in modes else 'unknown',
            'provider_access_verified': False, 'generation_requests': 0,
            'services_changed': False, 'budgets_changed': False}


def process(payload, *, path=ENV_FILE, current=CURRENT):
    if not isinstance(payload, dict) or payload.get('mode') not in ('inspect', 'install-key'):
        raise RuntimeError('openai_support_mode_invalid')
    expected = payload.get('expected_release')
    validate_release(expected)
    actual = current.resolve().name
    if actual != expected:
        raise RuntimeError('openai_installed_release_mismatch')
    values = read_values(path)
    before = dict(values)
    if payload['mode'] == 'install-key':
        install_key(values, payload.get('key'))
        if values != before:
            write_values(path, values)
    elif 'key' in payload:
        raise RuntimeError('openai_inspect_cannot_receive_key')
    return safe_status(values, actual)


def main():
    os.umask(0o077)
    try:
        raw = sys.stdin.buffer.read(16385)
        if len(raw) > 16384:
            raise RuntimeError('openai_support_payload_too_large')
        payload = json.loads(raw)
        # Serializes with existing deploy secret writes; no service is paused.
        with open('/var/lock/narma-deploy.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = process(payload)
        print(json.dumps(result))
    except Exception as error:
        code = str(error) if isinstance(error, RuntimeError) and re.fullmatch('openai_[a-z_]{1,100}', str(error)) else 'openai_support_failed'
        print(json.dumps({'event': 'openai_support_failure', 'code': code}))
        sys.exit(1)


if __name__ == '__main__':
    main()
