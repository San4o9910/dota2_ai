"""Serialize memory-heavy media work across containers on the pilot VPS."""
from contextlib import contextmanager
import time

from .db import database

MEDIA_LOCK = 643847215


@contextmanager
def media_slot(heartbeat=None, timeout=600):
    # A session lock survives the short renewal transactions, is released by a
    # lost connection/process, and is shared by replay and video containers.
    with database() as connection:
        deadline = time.monotonic() + timeout
        acquired = False
        try:
            while not acquired:
                row = connection.execute('SELECT pg_try_advisory_lock(%s) AS acquired', (MEDIA_LOCK,)).fetchone()
                acquired = bool(row and row['acquired'])
                connection.commit()
                if acquired:
                    break
                if heartbeat:
                    heartbeat()
                if time.monotonic() >= deadline:
                    raise ValueError('VIDEO_MEDIA_SLOT_TIMEOUT')
                time.sleep(2)
            if heartbeat:
                heartbeat()
            yield
        finally:
            if acquired:
                connection.execute('SELECT pg_advisory_unlock(%s)', (MEDIA_LOCK,))
                connection.commit()
