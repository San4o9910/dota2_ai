"""Fetch the pinned upstream with ephemeral GitHub auth and a verified Git cache.

No token appears in arguments, repository configuration, image ENV or output.
Only authenticated reads of one official repository are retried. There is no
alternate URL or anonymous fallback after throttling.
"""
import argparse
import base64
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tarfile
import tempfile
import time

REVISION = '9fd44b4dfc44138b9e5d5689acb56c438364ff7b'
TREE = '69a0ed6baa95d4e6af7b3c8c6147f193d29d48f7'
ORIGIN = 'https://github.com/NousResearch/hermes-agent.git'
MAX_ATTEMPTS = 2
FETCH_TIMEOUT = 90
TOTAL_FETCH_SECONDS = 240


class SourceError(RuntimeError):
    pass


def clean_environment():
    environment = {name: value for name, value in os.environ.items()
                   if not name.startswith('GIT_') and name not in ('GITHUB_TOKEN', 'GH_TOKEN', 'HERMES_SOURCE_GITHUB_TOKEN')}
    environment.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_SYSTEM='/dev/null',
        GIT_CONFIG_GLOBAL='/dev/null', GIT_TERMINAL_PROMPT='0', GIT_TRACE='0',
        GIT_TRACE_CURL='0', GIT_CURL_VERBOSE='0', GIT_NO_REPLACE_OBJECTS='1')
    return environment


def git(cache, arguments, *, environment=None, timeout=90):
    # These -c values are public. Authorization is supplied only in the child
    # process environment and therefore is never written into the cache.
    return subprocess.run(['git', '-c', 'credential.helper=', '-c', 'core.hooksPath=/dev/null',
        '-c', 'http.followRedirects=false', '--git-dir', str(cache), *arguments],
        env=environment or clean_environment(), stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, timeout=timeout)


def identity(cache):
    commit = git(cache, ['rev-parse', '--verify', REVISION + '^{commit}'])
    if commit.returncode:
        return False
    tree = git(cache, ['rev-parse', '--verify', REVISION + '^{tree}'])
    if commit.stdout.strip() != REVISION.encode() or tree.returncode or tree.stdout.strip() != TREE.encode():
        raise SourceError('HERMES_SOURCE_IDENTITY_MISMATCH')
    if git(cache, ['fsck', '--strict', '--no-reflogs', '--no-dangling', REVISION]).returncode:
        raise SourceError('HERMES_SOURCE_CACHE_CORRUPT')
    return True


def retry_delay(stderr):
    """Honor Retry-After when Git exposes it; otherwise wait at least 60s."""
    match = re.search(rb'(?im)retry-after:\s*([^\r\n]+)', stderr[:65536])
    if not match:
        return 60
    value = match[1].decode('ascii', errors='ignore').strip()
    if value.isdigit():
        return max(60, int(value))
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(60, int((parsed - datetime.now(timezone.utc)).total_seconds()) + 1)
    except (ValueError, TypeError, OverflowError):
        return 60


def sanitize_cache(cache):
    """The dedicated bare cache stores objects, never executable configuration."""
    if cache.is_symlink() or (cache / 'commondir').exists() or (cache / 'commondir').is_symlink():
        raise SourceError('HERMES_SOURCE_CACHE_INVALID')
    cache.mkdir(parents=True, exist_ok=True)
    for relative in ('config', 'config.worktree', 'info/attributes', 'info/grafts'):
        path = cache / relative
        if path.parent.is_symlink() or (path.exists() and path.is_dir()):
            raise SourceError('HERMES_SOURCE_CACHE_INVALID')
        path.unlink(missing_ok=True)
    with (cache / 'config').open('x') as config:
        config.write('[core]\nrepositoryformatversion = 0\nbare = true\n')


def fetch(cache, token_path):
    sanitize_cache(cache)
    if not (cache / 'HEAD').is_file():
        initialized = subprocess.run(['git', 'init', '--bare', '--quiet', str(cache)],
            env=clean_environment(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        if initialized.returncode:
            raise SourceError('HERMES_SOURCE_CACHE_INIT_FAILED')
    if identity(cache):
        return
    token = token_path.read_text().strip()
    if not re.fullmatch('[A-Za-z0-9_]{20,16384}', token):
        raise SourceError('HERMES_SOURCE_AUTH_REQUIRED')
    environment = clean_environment()
    authorization = base64.b64encode(('x-access-token:' + token).encode()).decode()
    environment.update(GIT_CONFIG_COUNT='1',
        GIT_CONFIG_KEY_0='http.https://github.com/.extraheader',
        GIT_CONFIG_VALUE_0='AUTHORIZATION: basic ' + authorization)
    deadline = time.monotonic() + TOTAL_FETCH_SECONDS
    for attempt in range(MAX_ATTEMPTS):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SourceError('HERMES_SOURCE_FETCH_TIMEOUT')
        try:
            result = git(cache, ['fetch', '--quiet', '--no-tags', '--depth=1', ORIGIN, REVISION],
                environment=environment, timeout=min(FETCH_TIMEOUT, remaining))
            if result.returncode == 0:
                if not identity(cache):
                    raise SourceError('HERMES_SOURCE_REVISION_MISSING')
                return
            # Raw transport output is neither logged nor persisted. Other
            # authentication/permission errors fail immediately.
            transient = bool(re.search(rb'(?i)(\b429\b|\b50[234]\b|rate limit|timed out|connection reset)', result.stderr[:65536]))
            delay = retry_delay(result.stderr)
        except subprocess.TimeoutExpired:
            transient, delay = True, 60
        if not transient or attempt + 1 == MAX_ATTEMPTS:
            raise SourceError('HERMES_SOURCE_FETCH_FAILED')
        if delay + 1 > deadline - time.monotonic():
            raise SourceError('HERMES_SOURCE_RETRY_AFTER_EXCEEDS_BUILD_BUDGET')
        print('HERMES_SOURCE_WAIT retry=1 delay_seconds=' + str(delay), flush=True)
        time.sleep(delay)
    raise SourceError('HERMES_SOURCE_FETCH_FAILED')


def extract(cache, destination):
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise SourceError('HERMES_SOURCE_DESTINATION_NOT_EMPTY')
    with tempfile.TemporaryDirectory(prefix='narma-hermes-source-') as directory:
        archive = Path(directory) / 'source.tar'
        result = git(cache, ['archive', '--format=tar', '--output=' + str(archive), REVISION])
        if result.returncode:
            raise SourceError('HERMES_SOURCE_ARCHIVE_FAILED')
        seen = set(); expanded = 0
        with tarfile.open(archive, 'r:') as source:
            for member in source:
                name = PurePosixPath(member.name)
                if (name.is_absolute() or '..' in name.parts or not name.parts
                        or '.git' in name.parts or member.name in seen
                        or not (member.isdir() or member.isfile())):
                    raise SourceError('HERMES_SOURCE_ARCHIVE_INVALID')
                seen.add(member.name); expanded += member.size
                if len(seen) > 30000 or expanded > 512 * 1024**2:
                    raise SourceError('HERMES_SOURCE_ARCHIVE_TOO_LARGE')
                target = destination.joinpath(*name.parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(member) as incoming, target.open('xb') as output:
                    while block := incoming.read(1024 * 1024):
                        output.write(block)
                target.chmod(0o755 if member.mode & 0o111 else 0o644)
    (destination / '.narma-upstream-revision').write_text(REVISION + '\n')
    print('HERMES_SOURCE_VERIFIED revision=' + REVISION + ' tree=' + TREE, flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--token-file', type=Path, default=Path('/run/secrets/github_token'))
    args = parser.parse_args()
    try:
        fetch(args.cache, args.token_file)
        extract(args.cache, args.destination)
    except Exception as error:
        code = str(error) if isinstance(error, SourceError) else 'HERMES_SOURCE_PREPARATION_FAILED'
        print(code, file=sys.stderr, flush=True)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
