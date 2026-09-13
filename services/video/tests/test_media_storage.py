"""Shared storage admission, real PostgreSQL races and filesystem failures.

Sources are tiny synthetic byte strings; these tests never parse gameplay or
make provider calls. Database cases run only against an explicit isolated URL.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import errno
import hashlib
import os
import threading
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
import pytest
from pydantic import ValidationError

from narma_video import api, media_storage as storage, replay_jobs, web
from narma_video.config import PART_BYTES, job_directory
from narma_video.db import database, migrate
from test_replay_metadata import metadata_fixture

OWNERS = ('storage_owner_a', 'storage_owner_b')
VIDEO = b'\x00\x00\x00\x18ftyp' + bytes(16)


@pytest.fixture
def db(monkeypatch, tmp_path):
    url = os.environ.get('TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set an isolated TEST_DATABASE_URL')
    monkeypatch.setenv('DATABASE_URL', url)
    monkeypatch.setenv('VIDEO_STORAGE_PATH', str(tmp_path / 'media'))
    monkeypatch.setenv('VIDEO_ANALYSIS_MODE', 'full_frames_v1')
    monkeypatch.setattr(api.budget, 'status', lambda *args: {
        'enabled': True, 'available_microusd': 10000000})
    monkeypatch.setattr(storage.shutil, 'disk_usage', lambda root: SimpleNamespace(free=10**12))
    migrate()
    with database() as connection:
        connection.execute('TRUNCATE video_jobs CASCADE')
        connection.execute('TRUNCATE portal_accounts CASCADE')
        for owner in OWNERS:
            connection.execute('INSERT INTO portal_accounts(owner_id,email,password_hash) VALUES (%s,%s,%s)',
                               (owner, owner + '@example.test', 'synthetic-unused'))
    yield
    with database() as connection:
        connection.execute('TRUNCATE video_jobs CASCADE')
        connection.execute('TRUNCATE portal_accounts CASCADE')


def create(kind, size=40, owner=OWNERS[0], job_id=None):
    job_id = job_id or uuid4()
    if kind == 'video':
        api.create_video(api.CreateVideo(id=job_id, filename='synthetic.mp4', size_bytes=size,
                                        account_id=1000, nickname='Player_0'), owner)
    else:
        replay_jobs.create_replay(replay_jobs.CreateReplay(id=job_id, filename='synthetic.dem',
                                  size_bytes=size, nickname='Player_0'), owner)
    return job_id


def state(kind, job_id):
    with database() as connection:
        # The table name is selected by the test, never request input.
        return connection.execute(f'SELECT state FROM {kind}_jobs WHERE id=%s', (job_id,)).fetchone()['state']


@pytest.mark.parametrize('value', ['24', 24.0, True])
@pytest.mark.parametrize('kind', ['video', 'replay'])
def test_declared_size_requires_an_integer(value, kind):
    with pytest.raises(ValidationError):
        create(kind, value)


@pytest.mark.parametrize('error_number', [errno.ENOSPC, errno.EDQUOT])
def test_disk_exhaustion_is_retryable(error_number):
    with pytest.raises(HTTPException) as rejected:
        with storage.storage_errors():
            raise OSError(error_number, 'synthetic storage fault')
    assert rejected.value.status_code == 507
    assert 'synthetic' not in rejected.value.detail


def test_unrelated_filesystem_errors_are_not_mislabelled_as_disk_exhaustion():
    with pytest.raises(PermissionError):
        with storage.storage_errors():
            raise PermissionError(errno.EACCES, 'synthetic permission fault')


def test_headroom_includes_all_remaining_sources_and_retry_chunk(monkeypatch, tmp_path):
    monkeypatch.setenv('VIDEO_STORAGE_PATH', str(tmp_path))
    monkeypatch.setattr(storage, 'reservations', lambda connection: {'stored': 100, 'remaining': 80})
    threshold = 80 + 40 + PART_BYTES + storage.FREE_HEADROOM_BYTES
    monkeypatch.setattr(storage.shutil, 'disk_usage', lambda root: SimpleNamespace(free=threshold-1))
    with pytest.raises(HTTPException) as rejected:
        storage.check_space(None, new_bytes=40)
    assert rejected.value.status_code == 507
    monkeypatch.setattr(storage.shutil, 'disk_usage', lambda root: SimpleNamespace(free=threshold))
    storage.check_space(None, new_bytes=40)


def test_video_foreign_job_rejected_before_reading_body(monkeypatch):
    def foreign(*args):
        raise HTTPException(404, 'Synthetic foreign job')
    monkeypatch.setattr(api, 'video_part_size', foreign)
    class Request:
        headers = {}
        async def stream(self):
            pytest.fail('A foreign owner upload body was consumed')
            yield b''
    with pytest.raises(HTTPException) as rejected:
        asyncio.run(api.upload_part(uuid4(), 1, Request(), OWNERS[1]))
    assert rejected.value.status_code == 404


def test_video_oversized_body_rejected_before_storage(monkeypatch):
    monkeypatch.setattr(api, 'video_part_size', lambda *args: 24)
    monkeypatch.setattr(api, 'store_video_part', lambda *args: pytest.fail('Oversized body reached storage'))
    class Request:
        headers = {}
        async def stream(self):
            yield VIDEO
            yield b'oversized'
    with pytest.raises(HTTPException) as rejected:
        asyncio.run(api.upload_part(uuid4(), 1, Request(), OWNERS[0]))
    assert rejected.value.status_code == 413


@pytest.mark.parametrize('kinds', [('video', 'video'), ('replay', 'replay'), ('video', 'replay')])
def test_concurrent_admission_never_oversubscribes_shared_quota(db, monkeypatch, kinds):
    monkeypatch.setattr(storage, 'GLOBAL_STORAGE_BYTES', 79)
    start = threading.Barrier(2)
    def attempt(index):
        start.wait(timeout=5)
        try:
            create(kinds[index], owner=OWNERS[index])
            return 201
        except HTTPException as error:
            return error.status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(attempt, range(2))) == [201, 429]
    with database() as connection:
        assert storage.reservations(connection) == {'stored': 40, 'remaining': 80}


def test_existing_failed_and_pending_deleted_files_hold_reservations(db, monkeypatch):
    job = create('video')
    with database() as connection:
        connection.execute("UPDATE video_jobs SET state='failed' WHERE id=%s", (job,))
        assert storage.reservations(connection) == {'stored': 40, 'remaining': 0}
        connection.execute("UPDATE video_jobs SET state='deleted' WHERE id=%s", (job,))
        assert storage.reservations(connection)['stored'] == 40
    monkeypatch.setattr(storage, 'GLOBAL_STORAGE_BYTES', 79)
    with pytest.raises(HTTPException) as rejected:
        create('replay')
    assert rejected.value.status_code == 429
    # Only confirmed filesystem removal releases the durable source reservation.
    api.delete_video(job, OWNERS[0])
    create('replay')


def test_profile_uploads_share_global_quota_and_future_disk_demand(db, monkeypatch):
    job = create('video')
    with database() as connection:
        connection.execute("INSERT INTO portal_replay_uploads(id,owner_id,reserved_bytes,expires_at) VALUES (%s,%s,512,now()+interval '20 minutes')",
                           (uuid4(), OWNERS[1]))
        assert storage.reservations(connection) == {'stored': 552, 'remaining': 592}
    monkeypatch.setattr(storage, 'GLOBAL_STORAGE_BYTES', 591)
    with pytest.raises(HTTPException) as rejected:
        create('replay')
    assert rejected.value.status_code == 429
    assert state('video', job) == 'uploading'


@pytest.mark.parametrize('kind', ['video', 'replay'])
def test_disk_pressure_rejects_admission_without_creating_job(db, monkeypatch, kind):
    monkeypatch.setattr(storage.shutil, 'disk_usage', lambda root: SimpleNamespace(free=storage.FREE_HEADROOM_BYTES))
    job = uuid4()
    with pytest.raises(HTTPException) as rejected:
        create(kind, job_id=job)
    assert rejected.value.status_code == 507
    with database() as connection:
        assert connection.execute(f'SELECT count(*) AS n FROM {kind}_jobs').fetchone()['n'] == 0


@pytest.mark.parametrize('kind', ['video', 'replay'])
def test_disk_pressure_at_chunk_and_assembly_preserves_retry(db, monkeypatch, kind):
    data = VIDEO if kind == 'video' else metadata_fixture()[0]
    job = create(kind, len(data))
    store = api.store_video_part if kind == 'video' else replay_jobs.store_part
    complete = api.complete_video if kind == 'video' else replay_jobs.complete_replay
    directory = job_directory(job) if kind == 'video' else replay_jobs.replay_directory(job)
    monkeypatch.setattr(storage.shutil, 'disk_usage', lambda root: SimpleNamespace(free=storage.FREE_HEADROOM_BYTES))
    with pytest.raises(HTTPException) as rejected:
        store(job, 1, data, OWNERS[0])
    assert rejected.value.status_code == 507
    assert not (directory / 'part-1').exists()
    monkeypatch.setattr(storage.shutil, 'disk_usage', lambda root: SimpleNamespace(free=10**12))
    store(job, 1, data, OWNERS[0])
    with database() as connection:
        assert storage.reservations(connection) == {'stored': len(data), 'remaining': len(data)}
    monkeypatch.setattr(storage.shutil, 'disk_usage', lambda root: SimpleNamespace(free=storage.FREE_HEADROOM_BYTES + PART_BYTES + len(data) - 1))
    with pytest.raises(HTTPException) as rejected:
        complete(job, OWNERS[0])
    assert rejected.value.status_code == 507
    assert state(kind, job) == 'uploading'
    assert (directory / 'part-1').read_bytes() == data
    assert not (directory / 'source.pending').exists()
    monkeypatch.setattr(storage.shutil, 'disk_usage', lambda root: SimpleNamespace(free=10**12))
    complete(job, OWNERS[0])
    assert state(kind, job) == 'queued'


@pytest.mark.parametrize('kind', ['video', 'replay'])
@pytest.mark.parametrize('phase', ['chunk', 'assembly'])
def test_external_disk_full_during_fsync_rolls_back_and_can_retry(db, monkeypatch, kind, phase):
    data = VIDEO if kind == 'video' else metadata_fixture()[0]
    job = create(kind, len(data))
    store = api.store_video_part if kind == 'video' else replay_jobs.store_part
    complete = api.complete_video if kind == 'video' else replay_jobs.complete_replay
    directory = job_directory(job) if kind == 'video' else replay_jobs.replay_directory(job)
    if phase == 'assembly':
        store(job, 1, data, OWNERS[0])
    def full(fd):
        raise OSError(errno.ENOSPC, 'synthetic post-admission exhaustion')
    with monkeypatch.context() as fault:
        fault.setattr(os, 'fsync', full)
        with pytest.raises(HTTPException) as rejected:
            if phase == 'chunk':
                store(job, 1, data, OWNERS[0])
            else:
                complete(job, OWNERS[0])
        assert rejected.value.status_code == 507
    assert state(kind, job) == 'uploading'
    assert not (directory / 'source.pending').exists()
    assert not (directory / ('source' if kind == 'video' else 'source.dem')).exists()
    with database() as connection:
        assert connection.execute(f'SELECT count(*) AS n FROM {kind}_parts WHERE job_id=%s', (job,)).fetchone()['n'] == (0 if phase == 'chunk' else 1)
    if phase == 'chunk':
        assert not list(directory.iterdir())
        store(job, 1, data, OWNERS[0])
    else:
        assert (directory / 'part-1').read_bytes() == data
        complete(job, OWNERS[0])


def test_concurrent_video_part_changes_cannot_replace_accepted_bytes(db):
    job = create('video', len(VIDEO))
    start = threading.Barrier(2)
    payloads = [VIDEO, VIDEO[:-1] + b'x']
    def attempt(index):
        start.wait(timeout=5)
        try:
            api.store_video_part(job, 1, payloads[index], OWNERS[0])
            return 200
        except HTTPException as error:
            return error.status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(attempt, range(2))) == [200, 409]
    data = (job_directory(job) / 'part-1').read_bytes()
    with database() as connection:
        part = connection.execute('SELECT sha256,size_bytes FROM video_parts WHERE job_id=%s', (job,)).fetchone()
    assert part == {'sha256': hashlib.sha256(data).hexdigest(), 'size_bytes': len(data)}


@pytest.mark.parametrize('content', [VIDEO[:-1], VIDEO + b'x', b'x' * len(VIDEO)])
def test_corrupt_or_oversized_video_part_never_queues(db, content):
    job = create('video', len(VIDEO))
    api.store_video_part(job, 1, VIDEO, OWNERS[0])
    (job_directory(job) / 'part-1').write_bytes(content)
    with pytest.raises(HTTPException) as rejected:
        api.complete_video(job, OWNERS[0])
    assert rejected.value.status_code == 409
    assert state('video', job) == 'uploading'
    assert not (job_directory(job) / 'source').exists()
