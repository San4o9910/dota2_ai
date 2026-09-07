"""Regression for the native decoder that failed on the production noexec mount.

Actual native loading is also verified by the hardened Docker gate.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from narma_video import replay_worker as worker


def test_parser_home_rejects_missing_native_library(monkeypatch, tmp_path):
    home = tmp_path / "parser"
    main = home / "target/classes/vision/narma/replay/ReplayProbe.class"
    main.parent.mkdir(parents=True)
    main.write_bytes(b"synthetic class existence only")
    monkeypatch.setenv("REPLAY_PARSER_HOME", str(home))
    monkeypatch.setattr(worker.shutil, "which", lambda name: "/usr/bin/java")
    with pytest.raises(ValueError, match="REPLAY_"):
        worker.parser_home()


def test_native_smoke_uses_fixed_image_library_and_sterile_child_environment(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(worker, "parser_home", lambda: tmp_path)
    monkeypatch.setattr(worker.shutil, "which", lambda name: "/usr/bin/java")
    monkeypatch.setenv("JAVA_TOOL_OPTIONS", "-Dunsafe.jvm.option=untrusted")
    monkeypatch.setenv("JDK_JAVA_OPTIONS", "-Dunsafe.jvm.option=untrusted")
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic_secret_must_not_reach_parser")
    monkeypatch.setenv("DATABASE_URL", "postgresql://synthetic_secret")
    def run(command, **options):
        calls.append((command, options))
        return SimpleNamespace(returncode=0, stdout=b"REPLAY_NATIVE_OK\n", stderr=b"")
    monkeypatch.setattr(worker.subprocess, "run", run)
    worker.verify_runtime()
    assert calls
    command, options = calls[-1]
    assert "-Dorg.xerial.snappy.lib.path=" + str(tmp_path / "native") in command
    assert "-Dorg.xerial.snappy.lib.name=libsnappyjava.so" in command
    assert "vision.narma.replay.ReplayNativeSmoke" in command
    assert "-Xmx2g" in command and "-XX:ActiveProcessorCount=2" in command
    assert options.get("shell", False) is False
    assert 0 < options["timeout"] <= 30
    assert isinstance(options.get("env"), dict)
    assert not {"JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "GEMINI_API_KEY", "DATABASE_URL"} & options["env"].keys()


def test_native_smoke_failure_cannot_mark_the_worker_healthy(monkeypatch, tmp_path):
    monkeypatch.setattr(worker, "parser_home", lambda: tmp_path)
    monkeypatch.setattr(worker.shutil, "which", lambda name: "/usr/bin/java")
    monkeypatch.setattr(worker.subprocess, "run", lambda *args, **kwargs:
        SimpleNamespace(returncode=1, stdout=b"", stderr=b"java.lang.UnsatisfiedLinkError: synthetic native failure"))
    with pytest.raises(ValueError, match="REPLAY_"):
        worker.verify_runtime()
