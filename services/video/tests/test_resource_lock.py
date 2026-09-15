"""Native PostgreSQL gates for cross-worker media exclusion and cleanup."""
from concurrent.futures import ThreadPoolExecutor
import os
from threading import Event

import pytest

from narma_video import replay_worker, video_analysis, worker
from narma_video.db import database


@pytest.fixture(autouse=True)
def native_database(monkeypatch):
    if os.environ.get('NARMA_SYNTHETIC_PGLITE') == '1':
        pytest.skip('Native PostgreSQL session/advisory-lock gate; PGlite multiplexes sessions')
    url = os.environ.get('TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set isolated TEST_DATABASE_URL')
    monkeypatch.setenv('DATABASE_URL', url)
    with database() as connection:
        version = connection.execute('SELECT version() AS version').fetchone()['version'].lower()
    if any(word in version for word in ('pglite', 'emscripten', 'wasm')):
        pytest.skip('Native PostgreSQL session/advisory-lock gate runs in CI')


def test_replay_excludes_both_video_workers_and_waiter_keeps_heartbeat():
    waiting_heartbeat, entered = Event(), Event()

    def second_job():
        try:
            # Immediate timeout keeps this gate fast; the contender still uses
            # its own real PostgreSQL session and performs the normal heartbeat.
            with video_analysis.media_slot(waiting_heartbeat.set, timeout=0):
                entered.set()
            return 'entered'
        except ValueError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=1) as pool:
        with replay_worker.media_slot(timeout=0):
            contender = pool.submit(second_job)
            assert contender.result(timeout=2) == 'VIDEO_MEDIA_SLOT_TIMEOUT'
            assert waiting_heartbeat.is_set() and not entered.is_set()
            # A failed waiter must not unlock the replay's still-held session
            # lock. The legacy full-frame worker shares this same boundary.
            with pytest.raises(ValueError, match='VIDEO_MEDIA_SLOT_TIMEOUT'):
                with worker.media_slot(timeout=0):
                    pytest.fail('Legacy video overlapped the active replay')
        assert pool.submit(second_job).result(timeout=2) == 'entered'
    assert entered.is_set()
    with worker.media_slot(timeout=0):
        pass


@pytest.mark.parametrize('failure_phase', ['body', 'heartbeat'])
def test_exception_releases_the_acquired_session_lock(failure_phase):
    class SyntheticFailure(Exception):
        pass

    def heartbeat():
        if failure_phase == 'heartbeat':
            raise SyntheticFailure('Synthetic lease renewal failure')

    with pytest.raises(SyntheticFailure):
        with video_analysis.media_slot(heartbeat, timeout=0):
            raise SyntheticFailure('Synthetic media processing failure')
    # Independent replay acquisition proves that cleanup released the lock,
    # including an exception raised after acquisition but before entering body.
    with replay_worker.media_slot(timeout=0):
        pass
