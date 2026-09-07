"""No paid or network calls: parser boundaries and publication fencing."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4

import pytest

from narma_video import replay_worker as worker
from narma_video.replay_report import ReportError


@pytest.fixture
def replay(tmp_path, monkeypatch):
    directory = tmp_path / "replay"
    directory.mkdir()
    source = b"PBDEMS2\x00bounded synthetic source"
    (directory / "source.dem").write_bytes(source)
    home = tmp_path / "parser"
    home.mkdir()
    job = {"id": uuid4(), "lease_token": uuid4(), "source_sha256": hashlib.sha256(source).hexdigest(),
           "size_bytes": len(source), "match_id": "8984479726", "account_id": 123, "nickname": "Selected"}
    monkeypatch.setattr(worker, "replay_directory", lambda job_id: directory)
    monkeypatch.setattr(worker, "parser_home", lambda: home)
    monkeypatch.setattr(worker.shutil, "which", lambda name: "/usr/bin/java")
    monkeypatch.setattr(worker, "heartbeat_replay_worker", lambda _: None)
    monkeypatch.setattr(worker, "replay_progress", lambda *args: True)
    return directory, home, job


class CompletedProcess:
    returncode = 0
    pid = 23456

    def poll(self):
        return self.returncode


@pytest.mark.parametrize("change", ["size", "hash", "missing"])
def test_changed_source_never_launches_parser(replay, monkeypatch, change):
    directory, home, job = replay
    if change == "size": job["size_bytes"] += 1
    elif change == "hash": job["source_sha256"] = "0" * 64
    else: (directory / "source.dem").unlink()
    monkeypatch.setattr(worker.subprocess, "Popen", lambda *a, **k: pytest.fail("Changed source reached parser"))
    output = directory / "output"
    output.mkdir()
    with pytest.raises(ValueError, match="REPLAY_SOURCE_CHANGED"):
        worker.parse(job, output)


def test_parser_child_has_sterile_environment_and_bounded_launch(replay, monkeypatch):
    directory, home, job = replay
    monkeypatch.setenv("GEMINI_API_KEY", "must-not-inherit")
    monkeypatch.setenv("DATABASE_URL", "postgresql://private")
    monkeypatch.setenv("JAVA_TOOL_OPTIONS", "-javaagent:/evil.jar")
    monkeypatch.setenv("JDK_JAVA_OPTIONS", "-Xmx20g")
    calls = []
    def launch(command, **kwargs):
        calls.append((command, kwargs))
        return CompletedProcess()
    monkeypatch.setattr(worker.subprocess, "Popen", launch)
    output = directory / "output"
    output.mkdir()
    worker.parse(job, output)
    command, options = calls[0]
    assert len(calls) == 1
    assert command[0] == "/usr/bin/java" and "-Xmx2g" in command and "-XX:ActiveProcessorCount=2" in command
    assert command[-2:] == [str(directory / "source.dem"), str(output / "events.jsonl")]
    assert options["env"] == {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8", "TMPDIR": "/tmp"}
    assert options["stdin"] == subprocess.DEVNULL and options["start_new_session"] is True
    assert options["preexec_fn"] is worker.parser_limits and not options.get("shell")
    assert options["cwd"] == output


def test_parser_resource_limits_are_applied(monkeypatch):
    calls = []
    monkeypatch.setattr(worker.resource, "setrlimit", lambda kind, value: calls.append((kind, value)))
    worker.parser_limits()
    assert (worker.resource.RLIMIT_CPU, (295, 300)) in calls
    assert (worker.resource.RLIMIT_FSIZE, (50 * 1024**2, 50 * 1024**2)) in calls
    assert (worker.resource.RLIMIT_CORE, (0, 0)) in calls


@pytest.mark.parametrize("failure", ["timeout", "lease"])
def test_parser_timeout_or_lost_lease_kills_child_group(replay, monkeypatch, failure):
    directory, home, job = replay
    killed, waited = [], []
    class RunningProcess:
        pid = 34567
        returncode = None
        def poll(self): return None
        def wait(self, timeout):
            waited.append(timeout)
            if not killed: raise subprocess.TimeoutExpired("java", timeout)
            return -9
    monkeypatch.setattr(worker.subprocess, "Popen", lambda *a, **k: RunningProcess())
    monkeypatch.setattr(worker.os, "killpg", lambda pid, sig: killed.append((pid, sig)))
    times = iter([0, 301] if failure == "timeout" else [0, 1])
    monkeypatch.setattr(worker.time, "monotonic", lambda: next(times))
    if failure == "lease":
        progresses = iter([True, False])
        monkeypatch.setattr(worker, "replay_progress", lambda *a: next(progresses))
    output = directory / "output"
    output.mkdir()
    with pytest.raises(ValueError, match="REPLAY_PARSE_TIMEOUT" if failure == "timeout" else "REPLAY_LEASE_LOST"):
        worker.parse(job, output)
    assert killed == [(34567, worker.signal.SIGKILL)] and waited == [10]


def test_failed_parser_exit_does_not_advance_to_completed_stage(replay, monkeypatch):
    directory, home, job = replay
    stages = []
    monkeypatch.setattr(worker, "renew", lambda job, stage: stages.append(stage))
    process = CompletedProcess()
    process.returncode = 1
    monkeypatch.setattr(worker.subprocess, "Popen", lambda *a, **k: process)
    output = directory / "output"
    output.mkdir()
    with pytest.raises(ValueError, match="REPLAY_PARSE_FAILED"):
        worker.parse(job, output)
    assert stages == [5]


def test_missing_eof_never_reaches_coaching_or_persistence(replay, monkeypatch):
    directory, home, job = replay
    summary = {"complete": True, "sha256": job["source_sha256"], "matchId": job["match_id"],
        "lastTick": 100, "playbackTicks": 100, "gameStartTimeRaw": 10, "gameEndTimeRaw": 100,
        "players": [{"steamId": str(76561197960265728 + 123), "name": "Selected", "hero": "npc_dota_hero_necrolyte", "team": 2}]}
    def incomplete(job, output):
        (output / "summary.json").write_text(json.dumps(summary))
        (output / "events.jsonl").write_text(json.dumps({"type": "source", "eventId": 1, "metadata": summary}) + "\n")
    monkeypatch.setattr(worker, "parse", incomplete)
    monkeypatch.setattr(worker, "enrich_report", lambda *a: pytest.fail("Incomplete replay reached coaching"))
    monkeypatch.setattr(worker, "finish_replay", lambda *a: pytest.fail("Incomplete replay reached publication"))
    with pytest.raises(ReportError, match="INCOMPLETE_PLAYER_DATA"):
        worker.run_job(job)
    assert not (directory / ("parse-" + str(job["lease_token"]))).exists()
    assert (directory / "source.dem").exists()


FACTUAL = {"coverage": {"complete": True, "final_tick": 42}, "evidence": [{"id": "event-1"}],
           "match_id": "8984479726", "player": {"account_id": 123}, "metrics": {"kills": 2}}


def mock_successful_analysis(monkeypatch):
    monkeypatch.setattr(worker, "parse", lambda *a: None)
    monkeypatch.setattr(worker, "build_report", lambda *a: FACTUAL)
    monkeypatch.setattr(worker, "enrich_report", lambda job, facts: dict(facts, coaching={"status": "unavailable"}))


@pytest.mark.parametrize("stage", ["before_coach", "after_coach", "finish"])
def test_stale_lease_cannot_publish_ready(replay, monkeypatch, stage):
    directory, home, job = replay
    mock_successful_analysis(monkeypatch)
    renewals, finishes = [], []
    def renew(job, progress):
        renewals.append(progress)
        if progress == (90 if stage == "before_coach" else 99) and stage != "finish":
            raise ValueError("REPLAY_LEASE_LOST")
    monkeypatch.setattr(worker, "renew", renew)
    def finish(*args):
        finishes.append(args)
        return False
    monkeypatch.setattr(worker, "finish_replay", finish)
    with pytest.raises(ValueError, match="REPLAY_LEASE_LOST"):
        worker.run_job(job)
    assert len(finishes) == (1 if stage == "finish" else 0)
    assert not (directory / ("parse-" + str(job["lease_token"]))).exists()


def test_success_persists_with_exact_lease_and_preserves_other_attempt_files(replay, monkeypatch):
    directory, home, job = replay
    mock_successful_analysis(monkeypatch)
    monkeypatch.setattr(worker, "renew", lambda *a: None)
    finishes = []
    monkeypatch.setattr(worker, "finish_replay", lambda *args: finishes.append(args) or True)
    other_attempt = directory / ("parse-" + str(uuid4()))
    other_attempt.mkdir()
    (other_attempt / "events.jsonl").write_text("retry's private events")
    result = worker.run_job(job)
    assert finishes == [(job["id"], job["lease_token"], result)]
    assert result["metrics"] == FACTUAL["metrics"]
    assert other_attempt.exists() and (other_attempt / "events.jsonl").exists()
    assert (directory / "source.dem").exists()
    assert not (directory / ("parse-" + str(job["lease_token"]))).exists()


def test_main_logs_only_safe_failure_code(replay, monkeypatch, capsys):
    directory, home, job = replay
    monkeypatch.setattr(worker, "cleanup", lambda: None)
    monkeypatch.setattr(worker, "claim_replay", lambda *a: job)
    monkeypatch.setattr("sys.argv", ["replay_worker", "--once", "--job-id", str(job["id"])])
    def fail(*args): raise RuntimeError("secret provider credentials must never appear")
    monkeypatch.setattr(worker, "run_job", fail)
    failed = []
    monkeypatch.setattr(worker, "fail_replay", lambda *args: failed.append(args))
    assert worker.main() == 1
    assert failed == [(job["id"], job["lease_token"], "REPLAY_PARSE_FAILED")]
    log = capsys.readouterr().out
    assert "secret provider" not in log and "REPLAY_PARSE_FAILED" in log
