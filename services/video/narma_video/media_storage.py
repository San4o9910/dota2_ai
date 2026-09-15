"""Shared, durable admission and disk headroom for every local media upload.

Jobs reserve their declared source size until storage_deleted_at is committed;
failed/deleted jobs still reserve space until their files are actually removed.
The existing job/part rows are the reservation ledger, including pre-upgrade
uploads. All admission, chunk writes and assembly use one transaction lock.
"""
from contextlib import contextmanager
import errno
import shutil

from fastapi import HTTPException

from .config import PART_BYTES, media_root
from .db import database

# Keep the replay admission lock number so mixed old/new replay processes share
# it during a rollout. The deployed API must nevertheless be a single release.
QUOTA_LOCK = 643847219
GLOBAL_STORAGE_BYTES = 16 * 1024**3
FREE_HEADROOM_BYTES = 2 * 1024**3
SOURCE_POLICY = {
    "source_backup": False,
    "source_removal": "owner_managed",
    "keep_local_copy": True,
    "report_backup": "postgresql",
}


def lock(connection):
    """Acquire before owner/job locks; retain through filesystem writes."""
    connection.execute("SELECT pg_advisory_xact_lock(%s)", (QUOTA_LOCK,))


def reservations(connection):
    # Parts already written consume measured free space. Reserve only still
    # unwritten bytes plus one full assembly copy for each incomplete source.
    # Profile uploads have no part ledger, so conservatively reserve their full
    # size until the streamed temporary file has been removed.
    return connection.execute("""
        WITH media AS (
            SELECT j.size_bytes, j.state,
                coalesce((SELECT sum(p.size_bytes) FROM video_parts p WHERE p.job_id=j.id),0) AS uploaded
            FROM video_jobs j WHERE j.storage_deleted_at IS NULL
            UNION ALL
            SELECT j.size_bytes, j.state,
                coalesce((SELECT sum(p.size_bytes) FROM replay_parts p WHERE p.job_id=j.id),0) AS uploaded
            FROM replay_jobs j WHERE j.storage_deleted_at IS NULL
        ), sources AS (
            SELECT coalesce(sum(size_bytes),0) AS stored,
                coalesce(sum(size_bytes + greatest(size_bytes-uploaded,0))
                    FILTER (WHERE state='uploading'),0) AS remaining
            FROM media
        ), profiles AS (
            SELECT coalesce(sum(reserved_bytes),0) AS reserved FROM portal_replay_uploads
        )
        SELECT stored + reserved AS stored, remaining + reserved AS remaining
        FROM sources CROSS JOIN profiles
    """).fetchone()


def check_space(connection, *, new_bytes=0):
    remaining = int(reservations(connection)["remaining"])
    # A repeated chunk uses a second, temporary chunk before os.replace. Keep
    # this allowance even when the earlier part is already in the part ledger.
    required = remaining + new_bytes + PART_BYTES + FREE_HEADROOM_BYTES
    if shutil.disk_usage(media_root()).free < required:
        raise HTTPException(507, "На сервере недостаточно места. Загрузка сохранена; повторите позже или удалите ненужные исходные файлы.")


def check_admission(connection, owner_id, size_bytes, *, assembly=True):
    # owner_id intentionally remains server-supplied; per-owner/type quotas are
    # checked by the calling API while holding this same global lock.
    if int(reservations(connection)["stored"]) + size_bytes > GLOBAL_STORAGE_BYTES:
        raise HTTPException(429, "Общее хранилище заполнено. Удалите ненужные исходные файлы или повторите позже.")
    check_space(connection, new_bytes=size_bytes * (2 if assembly else 1))


@contextmanager
def storage_errors():
    """A race with external disk consumers must not queue an incomplete file."""
    try:
        yield
    except OSError as error:
        if error.errno in {errno.ENOSPC, errno.EDQUOT}:
            raise HTTPException(507, "На сервере закончилось место. Загрузка не завершена; повторите позже.") from None
        raise


def write_profile_chunk(destination, chunk):
    """Bound legacy profile streaming to the same reservation/headroom gate."""
    with database() as connection:
        lock(connection)
        check_space(connection)
        with storage_errors():
            destination.write(chunk)
            destination.flush()
