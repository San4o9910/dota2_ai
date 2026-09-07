"""Offline acceptance gate inside the final replay-worker container."""
import os
from pathlib import Path
from .replay_worker import parser_home, verify_runtime


def check_runtime():
    assert os.geteuid() == 10001, 'REPLAY_GATE_WRONG_UID'
    mounts = {line.split()[1]: set(line.split()[3].split(','))
        for line in Path('/proc/mounts').read_text().splitlines()}
    assert 'ro' in mounts.get('/', set()), 'REPLAY_GATE_ROOT_WRITABLE'
    assert {'noexec', 'nosuid', 'nodev'} <= mounts.get('/tmp', set()), 'REPLAY_GATE_TMP_NOT_HARDENED'
    library = parser_home() / 'native/libsnappyjava.so'
    assert library.stat().st_uid == 0 and not library.stat().st_mode & 0o222, 'REPLAY_GATE_NATIVE_WRITABLE'
    verify_runtime()


if __name__ == '__main__':
    check_runtime()
    print('REPLAY_NATIVE_WORKER_RUNTIME_OK')
