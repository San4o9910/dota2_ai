"""Bounded provider-free rehearsal of the actual browser and queue boundary.

Only a newly created isolated PostgreSQL schema and temporary synthetic media
are changed. This is not a full-match parser benchmark or a live-server test.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import os
from pathlib import Path
import secrets
import socket
import sys
import tempfile
import time
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import psycopg
from psycopg import sql

# The script is mounted read-only into CI alongside the exact candidate source.
# Production runtime images need only pilot_evidence, not a mutation rehearsal.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def validate_target(dsn, *, ci_container=False):
    """No service/hostaddr/options escape to another server or schema."""
    try:
        parsed = urlsplit(dsn)
        params = parse_qsl(parsed.query, strict_parsing=True)
        valid = (parsed.scheme in ('postgres', 'postgresql') and parsed.path not in ('', '/')
                 and not parsed.fragment and parsed.hostname in ('127.0.0.1', '::1', 'localhost', 'db')
                 and all(key in ('sslmode', 'connect_timeout') for key, _ in params))
        if parsed.hostname == 'db':
            valid = valid and ci_container and os.environ.get('NARMA_PILOT_CI_ISOLATED') == '1'
        if not valid:
            raise ValueError()
        # Force validation of the port without exposing connection information.
        parsed.port
    except (ValueError, TypeError, AttributeError):
        raise ValueError('PILOT_LOCAL_TEST_DATABASE_REQUIRED') from None
    return parsed


@contextmanager
def isolated_libpq_environment():
    # PGHOSTADDR/PGSERVICE can override where an otherwise local DSN connects.
    # Remove inherited libpq settings for admin *and* all app/test connections.
    previous = {name: value for name, value in os.environ.items() if name.startswith('PG')}
    try:
        for name in previous:
            os.environ.pop(name, None)
        yield
    finally:
        for name in list(os.environ):
            if name.startswith('PG'):
                os.environ.pop(name, None)
        os.environ.update(previous)


@contextmanager
def isolated_database(dsn, *, ci_container=False):
    parsed = validate_target(dsn, ci_container=ci_container)
    schema = 'pilot_rehearsal_' + uuid4().hex
    with isolated_libpq_environment():
        with psycopg.connect(dsn, autocommit=True, connect_timeout=5) as admin:
            admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
            prior = os.environ.get('DATABASE_URL')
            try:
                params = parse_qsl(parsed.query)
                params.extend([('application_name', 'narma-pilot-rehearsal'),
                    ('options', f'-csearch_path={schema} -cstatement_timeout=8000 -clock_timeout=4000')])
                # libpq URI decoding preserves '+'; option separators must be
                # percent-encoded spaces, not HTML form encoding's plus signs.
                os.environ['DATABASE_URL'] = urlunsplit(parsed._replace(query=urlencode(params, quote_via=quote)))
                from narma_video.db import migrate, database
                migrate()
                with database() as connection:
                    actual = connection.execute('SELECT current_schema() AS name').fetchone()['name']
                    if actual != schema:
                        raise RuntimeError('PILOT_SCHEMA_ISOLATION_FAILED')
                yield schema
            finally:
                if prior is None:
                    os.environ.pop('DATABASE_URL', None)
                else:
                    os.environ['DATABASE_URL'] = prior
                admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


def metadata_fixture():
    """Minimal synthetic Source 2 metadata, deliberately no gameplay packets."""
    def varint(value):
        result = bytearray()
        while True:
            byte = value & 127
            value >>= 7
            result.append(byte | (128 if value else 0))
            if not value:
                return bytes(result)

    def integer(field, value):
        return varint(field * 8) + varint(value)

    def message(field, value):
        return varint(field * 8 + 2) + varint(len(value)) + value

    dota = integer(1, 8963624400)
    for index in range(10):
        dota += message(4, b''.join([
            message(1, b'npc_dota_hero_necrolyte'), message(2, f'Player_{index}'.encode()),
            integer(3, 0), integer(4, 76561197960265728 + 1000 + index),
            integer(5, 2 if index < 5 else 3)]))
    info = message(4, message(4, dota))
    return b'PBDEMS2\0' + (64).to_bytes(4, 'little') + bytes(52) + varint(2) + varint(152653) + varint(len(info)) + info


def distribution(values):
    ordered = sorted(values)
    if not ordered:
        return {'samples': 0, 'p50_ms': None, 'p95_ms': None}
    def percentile(p):
        position = (len(ordered)-1)*p
        left = int(position)
        return round(ordered[left] + (ordered[min(left+1, len(ordered)-1)]-ordered[left])*(position-left), 3)
    return {'samples': len(ordered), 'p50_ms': percentile(.5), 'p95_ms': percentile(.95)}


def rehearse(*, users=4, concurrency=8):
    if not 2 <= users <= 8 or not 2 <= concurrency <= 16:
        raise ValueError('PILOT_REHEARSAL_BOUND_INVALID')
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from narma_video.db import database
    from narma_video import replay_jobs, web

    app = FastAPI()
    web.attach_web(app)
    replay_jobs.attach_replays(app)
    origin = os.environ['APP_ORIGIN']
    password = secrets.token_urlsafe(24)
    hashed = web.password_hash(password)
    accounts = [('pilot_' + uuid4().hex, f'pilot{index}@example.test') for index in range(users)]
    with database() as connection:
        for owner, email in accounts:
            connection.execute('INSERT INTO portal_accounts(owner_id,email,password_hash) VALUES (%s,%s,%s)',
                               (owner, email, hashed))
        before = connection.execute('SELECT count(*) AS n FROM openai_api_calls').fetchone()['n']
        before += connection.execute('SELECT count(*) AS n FROM video_provider_calls').fetchone()['n']
        if before:
            raise RuntimeError('PILOT_SCHEMA_NOT_EMPTY')

    def timed(client, method, path, expected, **kwargs):
        start = time.monotonic()
        response = client.request(method, path, **kwargs)
        duration = (time.monotonic()-start)*1000
        if response.status_code != expected:
            raise RuntimeError('PILOT_UNEXPECTED_HTTP_STATUS')
        return response, duration

    def user_flow(account):
        _, email = account
        durations = {'login': [], 'session': [], 'admission': [], 'upload': [], 'complete': []}
        jobs = []
        with TestClient(app, base_url=origin, headers={'Origin': origin}) as client:
            _, duration = timed(client, 'POST', '/api/auth/login', 200, json={'email': email, 'password': password})
            durations['login'].append(duration)
            response, duration = timed(client, 'GET', '/api/session', 200)
            durations['session'].append(duration)
            if not response.json()['authenticated']:
                raise RuntimeError('PILOT_SESSION_FAILED')
            content = metadata_fixture()
            for _ in range(2):
                job_id = str(uuid4())
                _, duration = timed(client, 'POST', '/api/replays', 201,
                    json={'id': job_id, 'filename': 'synthetic.dem', 'size_bytes': len(content), 'nickname': 'Player_0'})
                durations['admission'].append(duration)
                _, duration = timed(client, 'PUT', f'/api/replays/{job_id}/parts/1', 200, content=content)
                durations['upload'].append(duration)
                _, duration = timed(client, 'POST', f'/api/replays/{job_id}/complete', 200)
                durations['complete'].append(duration)
                jobs.append(job_id)
            # Real owner active-job admission rejects a third in-flight job.
            response, _ = timed(client, 'POST', '/api/replays', 429,
                json={'id': str(uuid4()), 'filename': 'third.dem', 'size_bytes': len(content), 'nickname': 'Player_0'})
            if response.headers.get('X-Narma-Error') != 'REPLAY_QUOTA':
                raise RuntimeError('PILOT_ADMISSION_CHECK_FAILED')
            token = client.cookies.get(web.COOKIE)
        return durations, jobs, token

    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=min(users, concurrency)) as pool:
        results = list(pool.map(user_flow, accounts))
    totals = {key: [] for key in results[0][0]}
    job_ids = []
    for durations, jobs, _ in results:
        for key, values in durations.items():
            totals[key].extend(values)
        job_ids.extend(jobs)
    # Same real cookie boundary must not disclose the other owner's job.
    with TestClient(app, base_url=origin, headers={'Origin': origin}) as client:
        client.cookies.set(web.COOKIE, results[0][2])
        timed(client, 'GET', f'/api/replays/{results[1][1][0]}', 404)
    with TestClient(app, base_url=origin) as client:
        timed(client, 'GET', '/api/replays', 401)

    # Every queued job is contested twice. Only one claim can own each lease.
    contested = job_ids + job_ids
    def claim(job_id):
        start = time.monotonic()
        row = replay_jobs.claim_replay('pilot-rehearsal', job_id)
        return row, (time.monotonic()-start)*1000
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        claims = list(pool.map(claim, contested))
    claimed = [row for row, _ in claims if row]
    if len(claimed) != len(job_ids) or len({str(row['id']) for row in claimed}) != len(job_ids):
        raise RuntimeError('PILOT_DUPLICATE_QUEUE_CLAIM')
    for row in claimed:
        if not replay_jobs.fail_replay(row['id'], row['lease_token'], 'REPLAY_SYNTHETIC_REHEARSAL_END'):
            raise RuntimeError('PILOT_LEASE_FENCING_FAILED')
    with database() as connection:
        after = connection.execute('SELECT count(*) AS n FROM openai_api_calls').fetchone()['n']
        after += connection.execute('SELECT count(*) AS n FROM video_provider_calls').fetchone()['n']
        ready = connection.execute("SELECT count(*) AS n FROM replay_jobs WHERE state='ready'").fetchone()['n']
    if after or ready:
        raise RuntimeError('PILOT_PROVIDER_OR_SYNTHETIC_REPORT_CREATED')
    return {'schema_version': 1, 'scope': 'local_asgi_postgresql_synthetic_metadata_only',
        'users': users, 'max_concurrency': concurrency, 'queued_jobs': len(job_ids),
        'owner_quota_rejections': users, 'distinct_fenced_claims': len(claimed),
        'cross_owner_read_rejected': True, 'anonymous_read_rejected': True,
        'provider_calls_created': after, 'gameplay_reports_created': ready,
        'elapsed_seconds': round(time.monotonic()-start, 3),
        'http_timings': {key: distribution(values) for key, values in totals.items()},
        'queue_claim_timings': distribution([duration for _, duration in claims]),
        'limitations': ['In-process ASGI; excludes internet, nginx and TLS latency.',
            'Synthetic metadata only; excludes full-match Java parsing, video decoding and model latency.',
            'No inference of production concurrency, model quality or paid per-match cost.']}


@contextmanager
def offline_environment(media):
    values = {'APP_ORIGIN': 'https://pilot.example.test', 'VIDEO_STORAGE_PATH': media,
        'VIDEO_SERVICE_TOKEN': secrets.token_urlsafe(32), 'OPENAI_API_KEY': '',
        'GEMINI_API_KEY': '', 'GOOGLE_API_KEY': '', 'REPLAY_COACH_PROVIDER': 'disabled',
        'CHATGPT_PROVIDER_ENABLED': 'false', 'HERMES_ENABLED': 'false',
        'NARMA_EXPLORE_REFRESH_ENABLED': '0', 'NARMA_WORKSHOP_REFRESH_ENABLED': '0'}
    previous = {name: os.environ.get(name) for name in values}
    original_connect = socket.create_connection
    def no_network(*args, **kwargs):
        raise RuntimeError('PILOT_EXTERNAL_NETWORK_FORBIDDEN')
    try:
        os.environ.update(values)
        # Psycopg uses libpq; HTTP clients use this Python socket helper. The
        # rehearsal never starts a worker or calls a provider implementation.
        socket.create_connection = no_network
        yield
    finally:
        socket.create_connection = original_connect
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ci-container', action='store_true')
    parser.add_argument('--users', type=int, choices=range(2, 9), default=4)
    parser.add_argument('--concurrency', type=int, choices=range(2, 17), default=8)
    args = parser.parse_args()
    # Never fall back to DATABASE_URL: it may be the real application database.
    dsn = os.environ.get('TEST_DATABASE_URL', '')
    try:
        with isolated_database(dsn, ci_container=args.ci_container):
            with tempfile.TemporaryDirectory(prefix='narma-pilot-rehearsal-') as media:
                with offline_environment(media):
                    result = rehearse(users=args.users, concurrency=args.concurrency)
        result['isolated_schema_removed'] = True
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as error:
        # Connection errors can contain DSNs; only constant codes reach logs.
        known = str(error)
        code = known if known.startswith('PILOT_') and known.replace('_', '').isalnum() else 'PILOT_REHEARSAL_FAILED'
        print(json.dumps({'status': 'failed', 'code': code}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
