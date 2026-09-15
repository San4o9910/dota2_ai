"""Stop an idle installed worker set while PostgreSQL prevents new claims.

This is a fail-fast maintenance boundary, not graceful draining: an active job
or unfinished provider attempt aborts the upgrade with all workers still live.
The probe runs in the old API container, so it also works on the first upgrade
from workers that do not implement a deployment/drain protocol themselves.
"""
from contextlib import contextmanager
import json
import os
import re
import secrets
import selectors
import subprocess
import sys
import time

from snapshot_worker_state import SERVICES, inspect_service, run


PROBE = r'''
import hashlib,json,select,sys,time
from narma_video.db import database,database_url
try:
 with database() as c:
  c.execute("SET LOCAL statement_timeout='5s'")
  c.execute("LOCK TABLE replay_jobs,video_jobs,hermes_tasks,openai_api_calls,chatgpt_calls,video_provider_calls IN SHARE MODE NOWAIT")
  counts=c.execute("""SELECT
    (SELECT count(*) FROM replay_jobs WHERE state='processing') AS replays,
    (SELECT count(*) FROM video_jobs WHERE state='processing') AS videos,
    (SELECT count(*) FROM hermes_tasks WHERE state='running') AS hermes,
    (SELECT count(*) FROM openai_api_calls WHERE state IN ('reserved','calling')) AS openai,
    (SELECT count(*) FROM chatgpt_calls WHERE state IN ('reserved','calling')) AS chatgpt,
    (SELECT count(*) FROM video_provider_calls WHERE billing_status='reserved') AS gemini
  """).fetchone()
  if any(counts.values()):
   print(json.dumps({'status':'busy'}),flush=True)
   raise SystemExit(2)
  identity=hashlib.sha256((sys.argv[1]+'\0'+database_url()).encode()).hexdigest()
  print(json.dumps({'status':'locked','database':identity}),flush=True)
  deadline=time.monotonic()+90
  while time.monotonic()<deadline:
   readable,_,_=select.select([sys.stdin],[],[],min(1,deadline-time.monotonic()))
   c.execute('SELECT 1')
   if not readable:
    continue
   command=sys.stdin.readline()
   if command=='ping\n':
    print(json.dumps({'status':'locked','database':identity}),flush=True)
   elif command=='release\n':
    break
   else:
    raise RuntimeError('guard_closed')
  else:
   raise RuntimeError('guard_expired')
except Exception:
 print(json.dumps({'status':'failed'}),flush=True)
 raise SystemExit(1)
'''

DATABASE_PROBE = """import hashlib,sys
from narma_video.db import database_url
print(hashlib.sha256((sys.argv[1]+'\\0'+database_url()).encode()).hexdigest())
"""


def receive(process, timeout=10):
    """Read one bounded probe receipt without indefinitely blocking bootstrap."""
    deadline = time.monotonic() + timeout
    data = bytearray()
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        while len(data) < 256:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                raise RuntimeError('deployment_idle_guard_timeout')
            chunk = os.read(process.stdout.fileno(), 1)
            if not chunk:
                raise RuntimeError('deployment_idle_guard_lost')
            data.extend(chunk)
            if chunk == b'\n':
                try:
                    return json.loads(data)
                except (ValueError, UnicodeError):
                    break
    raise RuntimeError('deployment_idle_guard_invalid')


def validate_receipt(receipt, expected=None):
    if receipt == {'status': 'busy'}:
        raise RuntimeError('deployment_workers_busy')
    if (not isinstance(receipt, dict) or set(receipt) != {'status', 'database'}
            or receipt['status'] != 'locked' or not isinstance(receipt['database'], str)
            or len(receipt['database']) != 64
            or any(char not in '0123456789abcdef' for char in receipt['database'])
            or (expected is not None and receipt['database'] != expected)):
        raise RuntimeError('deployment_idle_guard_invalid')
    return receipt['database']


@contextmanager
def idle_guard(api, challenge):
    process = subprocess.Popen(['docker', 'exec', '-i', api['id'], 'python', '-u', '-c', PROBE, challenge],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
    try:
        identity = validate_receipt(receive(process, 15))

        def confirm():
            if process.poll() is not None:
                raise RuntimeError('deployment_idle_guard_lost')
            process.stdin.write(b'ping\n')
            process.stdin.flush()
            validate_receipt(receive(process, 6), identity)

        yield identity, confirm
    finally:
        try:
            if process.poll() is None:
                process.stdin.write(b'release\n')
                process.stdin.flush()
            process.stdin.close()
            process.wait(timeout=7)
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
            process.wait(timeout=5)
        finally:
            process.stdout.close()


def stop_idle_workers(*, on_stop_start=lambda: None):
    current = [item for service in SERVICES if (item := inspect_service(service))]
    active = [item for item in current if item['running']]
    if not active:
        # Initial installation has no old consumers to interrupt or fence.
        return {'event': 'deployment_workers_quiesced', 'stopped_services': [], 'idle_guard_verified': False}
    api = inspect_service('api')
    if not api or not api['running'] or any(item['config'] != api['config'] for item in active):
        raise RuntimeError('deployment_idle_api_unavailable')
    challenge = secrets.token_hex(32)
    with idle_guard(api, challenge) as (identity, confirm):
        # The same compose file alone does not prove that manually changed
        # containers still connect to the same database. Compare only in memory.
        for item in active:
            if item['service'] == 'hermes-runner':
                # The isolated runner has no database credentials; its broker
                # owns all claims and dispatches covered by the table locks.
                continue
            proof = run(['docker', 'exec', item['id'], 'python', '-c', DATABASE_PROBE, challenge], timeout=5)
            if proof.decode().strip() != identity:
                raise RuntimeError('deployment_worker_database_mismatch')
        if inspect_service('api') != api or any(inspect_service(item['service']) != item for item in current):
            raise RuntimeError('deployment_worker_changed')
        confirm()
        # Stop the exact verified old containers concurrently. New claims and
        # provider-state transitions remain blocked until this command finishes.
        on_stop_start()
        run(['docker', 'stop', '--time', '15', *[item['id'] for item in active]], timeout=35)
        confirm()
        for item in current:
            stopped = inspect_service(item['service'])
            if not stopped or stopped['id'] != item['id'] or stopped['running']:
                raise RuntimeError('deployment_worker_stop_unconfirmed')
    return {'event': 'deployment_workers_quiesced',
        'stopped_services': [item['service'] for item in active], 'idle_guard_verified': True}


if __name__ == '__main__':
    stopping = [False]
    try:
        if len(sys.argv) != 2 or not re.fullmatch('[0-9a-f]{32}', sys.argv[1]):
            raise RuntimeError('deployment_attempt_invalid')
        print(json.dumps(stop_idle_workers(on_stop_start=lambda: stopping.__setitem__(0, True))), flush=True)
    except Exception as error:
        allowed = {'deployment_workers_busy', 'deployment_idle_guard_timeout', 'deployment_idle_guard_lost',
            'deployment_idle_guard_invalid', 'deployment_idle_api_unavailable', 'deployment_worker_database_mismatch',
            'deployment_worker_changed', 'deployment_worker_stop_unconfirmed'}
        code = str(error) if str(error) in allowed else 'deployment_idle_guard_failed'
        deferred = not stopping[0] and len(sys.argv) == 2 and bool(re.fullmatch('[0-9a-f]{32}', sys.argv[1]))
        receipt = {'event': 'deployment_quiescence_failed', 'code': code}
        if deferred:
            receipt.update(disposition='deferred_before_stop', attempt=sys.argv[1])
        print(json.dumps(receipt), flush=True)
        sys.exit(75 if deferred else 1)
