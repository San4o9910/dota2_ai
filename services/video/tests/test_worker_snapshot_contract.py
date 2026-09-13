"""Run the deployment probe against real runtime modules without model or DB I/O."""
import hashlib
import json
from pathlib import Path
import runpy
import sys

import pytest

from narma_video import db, replay_worker, resource_lock, video_analysis, worker

PROBE = runpy.run_path(str(Path(__file__).resolve().parents[3]
    / 'ops/timeweb/snapshot_worker_state.py'))['DUAL_WORKER_PROBE']
DATABASE = 'postgresql://narma:synthetic-secret@db:5432/narma'


def execute_probe(monkeypatch, capsys, service):
    monkeypatch.setattr(sys, 'argv', ['-c', service, 'challenge'])
    exec(PROBE, {})
    return json.loads(capsys.readouterr().out)


@pytest.fixture(autouse=True)
def configuration(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', DATABASE)
    monkeypatch.setenv('REPLAY_COACH_PROVIDER', 'openai_api')
    monkeypatch.setenv('VIDEO_ANALYSIS_MODE', 'selective_v1')


def test_real_worker_contracts_match_without_connecting_or_claiming_work(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError('Probe must not connect to PostgreSQL')
    monkeypatch.setattr(db.psycopg, 'connect', forbidden)
    replay = execute_probe(monkeypatch, capsys, 'replay-worker')
    video = execute_probe(monkeypatch, capsys, 'worker')
    assert replay == video == {'contract': 'openai-selective-media-lock-v1', 'lock': 643847215,
        'database': hashlib.sha256(('challenge\0' + DATABASE).encode()).hexdigest()}
    assert 'synthetic-secret' not in json.dumps(video)


@pytest.mark.parametrize('provider', ['gemini', 'chatgpt_subscription', 'unknown'])
@pytest.mark.parametrize('service', ['worker', 'replay-worker'])
def test_legacy_or_unknown_runtime_cannot_claim_the_dual_contract(monkeypatch, capsys, provider, service):
    monkeypatch.setenv('REPLAY_COACH_PROVIDER', provider)
    with pytest.raises(AssertionError):
        execute_probe(monkeypatch, capsys, service)


def test_full_frame_video_cannot_claim_selective_contract(monkeypatch, capsys):
    monkeypatch.setenv('VIDEO_ANALYSIS_MODE', 'full_frames_v1')
    with pytest.raises(AssertionError):
        execute_probe(monkeypatch, capsys, 'worker')


@pytest.mark.parametrize('module,service', [(worker, 'worker'), (video_analysis, 'worker'),
                                           (replay_worker, 'replay-worker')])
def test_missing_shared_lock_binding_is_rejected(monkeypatch, capsys, module, service):
    monkeypatch.setattr(module, 'media_slot', lambda: None)
    with pytest.raises(AssertionError):
        execute_probe(monkeypatch, capsys, service)


def test_changed_lock_key_is_rejected(monkeypatch, capsys):
    monkeypatch.setattr(resource_lock, 'MEDIA_LOCK', 643847216)
    with pytest.raises(AssertionError):
        execute_probe(monkeypatch, capsys, 'replay-worker')
