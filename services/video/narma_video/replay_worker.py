"""Bounded local Source 2 parsing, factual reporting and optional metered coaching."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import signal
import subprocess
import time
from uuid import UUID

from .db import database
from .replay_jobs import (claim_replay, fail_replay, finish_replay,
    heartbeat_replay_worker, replay_directory, replay_progress)
from .replay_report import build_report, ReportError
from .replay_coach import enrich_report

WORKER_ID = 'replay'
PARSER_TIMEOUT = 300
OUTPUT_LIMIT = 50 * 1024**2


def log(event, **fields):
    print(json.dumps({'event': event, **fields}), flush=True)


def renew(job, progress):
    heartbeat_replay_worker(WORKER_ID)
    if not replay_progress(job['id'], job['lease_token'], progress):
        raise ValueError('REPLAY_LEASE_LOST')


def parser_home():
    home = Path(os.environ.get('REPLAY_PARSER_HOME', '/opt/narma/replay')).resolve()
    if not (home / 'target/classes/vision/narma/replay/ReplayProbe.class').is_file() or not shutil.which('java'):
        raise ValueError('REPLAY_PARSER_NOT_INSTALLED')
    return home


def parser_limits():
    resource.setrlimit(resource.RLIMIT_CPU, (295, 300))
    resource.setrlimit(resource.RLIMIT_FSIZE, (OUTPUT_LIMIT, OUTPUT_LIMIT))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def stop_parser(process):
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=10)


def parse(job, output):
    home = parser_home()
    source = replay_directory(job['id']) / 'source.dem'
    if not source.is_file() or source.stat().st_size != job['size_bytes']:
        raise ValueError('REPLAY_SOURCE_CHANGED')
    with source.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != job['source_sha256']:
            raise ValueError('REPLAY_SOURCE_CHANGED')
    renew(job, 5)
    command = [shutil.which('java'), '-Xms256m', '-Xmx2g', '-XX:ActiveProcessorCount=2',
        '-Dorg.slf4j.simpleLogger.defaultLogLevel=warn', '-cp',
        str(home / 'target/classes') + ':' + str(home / 'target/dependency/*'),
        'vision.narma.replay.ReplayProbe', str(source), str(output / 'events.jsonl')]
    # The parser is an offline child. In particular it never inherits the API key,
    # database credentials, cookies, or JVM option injection variables.
    environment = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'LANG': 'C.UTF-8', 'TMPDIR': '/tmp'}
    start = time.monotonic()
    with (output / 'summary.json').open('xb') as stdout, (output / 'parser.log').open('xb') as stderr:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
            env=environment, cwd=output, start_new_session=True, preexec_fn=parser_limits)
        try:
            while process.poll() is None:
                elapsed = time.monotonic() - start
                if elapsed > PARSER_TIMEOUT:
                    raise ValueError('REPLAY_PARSE_TIMEOUT')
                renew(job, 10)  # A stage marker, not an invented percentage of ticks.
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
            if process.returncode != 0:
                raise ValueError('REPLAY_PARSE_FAILED')
        finally:
            stop_parser(process)
    renew(job, 75)
    log('replay_parse_complete', job_id=str(job['id']), seconds=round(time.monotonic() - start, 2))


def run_job(job):
    # Lease-specific output prevents a stale attempt from deleting a retry's files.
    output = replay_directory(job['id']) / ('parse-' + str(UUID(str(job['lease_token']))))
    output.mkdir(mode=0o700, exist_ok=False)
    try:
        parse(job, output)
        factual = build_report(output / 'events.jsonl', output / 'summary.json', job)
        renew(job, 90)
        report = enrich_report(job, factual)
        renew(job, 99)
        if not finish_replay(job['id'], job['lease_token'], report):
            raise ValueError('REPLAY_LEASE_LOST')
        log('replay_ready', job_id=str(job['id']), final_tick=factual['coverage']['final_tick'],
            evidence_count=len(factual['evidence']), coaching=report['coaching']['status'])
        return report
    finally:
        shutil.rmtree(output, ignore_errors=True)


def cleanup():
    with database() as connection:
        deleted = connection.execute("SELECT id FROM replay_jobs WHERE state='deleted' AND storage_deleted_at IS NULL LIMIT 20").fetchall()
        # Uploads abandoned for a day still consume quota; mark failed so the
        # owner can explicitly remove them from the history.
        connection.execute("UPDATE replay_jobs SET state='failed',failure_code='REPLAY_UPLOAD_EXPIRED',updated_at=now() WHERE state='uploading' AND updated_at<now()-interval '1 day'")
    for row in deleted:
        try:
            directory = replay_directory(row['id'])
            if directory.exists():
                shutil.rmtree(directory)
            with database() as connection:
                connection.execute("UPDATE replay_jobs SET storage_deleted_at=now() WHERE id=%s AND state='deleted'", (row['id'],))
        except OSError:
            pass  # Keep its disk reservation until removal succeeds.


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--job-id', type=UUID)
    args = parser.parse_args()
    if args.job_id and not args.once:
        parser.error('--job-id requires --once')
    parser_home()  # No healthy heartbeat for a worker missing the actual parser.
    while True:
        cleanup()
        job = claim_replay(WORKER_ID, args.job_id)
        failed = False
        if job:
            try:
                run_job(job)
            except Exception as error:
                allowed = {'REPLAY_SOURCE_CHANGED', 'REPLAY_LEASE_LOST', 'REPLAY_PARSE_TIMEOUT',
                    'REPLAY_PARSE_FAILED', 'REPLAY_PARSER_NOT_INSTALLED'}
                code = str(error) if isinstance(error, ReportError) or (isinstance(error, ValueError) and str(error) in allowed) else 'REPLAY_PARSE_FAILED'
                fail_replay(job['id'], job['lease_token'], code)
                log('replay_failed', job_id=str(job['id']), code=code)
                failed = True
        if args.once:
            return 1 if failed or (args.job_id and not job) else 0
        if not job:
            time.sleep(5)


if __name__ == '__main__':
    raise SystemExit(main())
