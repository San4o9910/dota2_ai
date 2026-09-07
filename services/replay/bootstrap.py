#!/usr/bin/env python3
"""Reproducible JRE17-only research build. Download pinned artifacts from Maven Central."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import platform
import zipfile
from pathlib import Path
import subprocess
from urllib.parse import urlsplit

root = Path(__file__).resolve().parent
artifacts = json.loads((root / "dependencies.lock.json").read_text())

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def download(item):
    url = urlsplit(item["url"])
    if url.scheme != "https" or url.netloc != "repo.maven.apache.org" or not url.path.startswith("/maven2/"):
        raise ValueError("Only pinned Maven Central artifacts are supported")
    directory = root / ("tooling" if item.get("buildOnly") else "target/dependency")
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (item["artifact"] + ".jar")
    if target.exists() and digest(target) == item["sha256"]:
        return target
    temporary = target.with_suffix(".download")
    subprocess.run(["curl", "-fsSL", "--proto", "=https", "--connect-timeout", "10", "--max-time", "120",
                    "--retry", "3", "--retry-delay", "2", "--retry-max-time", "45",
                    item["url"], "-o", str(temporary)], check=True)
    if temporary.stat().st_size != item["bytes"] or digest(temporary) != item["sha256"]:
        temporary.unlink()
        raise ValueError("Dependency checksum mismatch")
    temporary.replace(target)
    return target

with ThreadPoolExecutor(max_workers=8) as executor:
    paths = list(executor.map(download, artifacts))
# Snappy normally extracts native code into java.io.tmpdir at first packet.
# Our runtime intentionally mounts /tmp noexec. Install the native library from
# the SHA-256-verified JAR during the image build instead of making /tmp executable.
architecture = {"x86_64": "x86_64", "aarch64": "aarch64"}.get(platform.machine())
if platform.system() != "Linux" or architecture is None:
    raise RuntimeError("REPLAY_NATIVE_ARCH_UNSUPPORTED")
snappy = next(path for path, item in zip(paths, artifacts) if item["artifact"].startswith("snappy-java-"))
with zipfile.ZipFile(snappy) as archive:
    native_data = archive.read("org/xerial/snappy/native/Linux/" + architecture + "/libsnappyjava.so")
if not native_data.startswith(b"\x7fELF") or not 0 < len(native_data) < 5 * 1024**2:
    raise RuntimeError("REPLAY_NATIVE_LIBRARY_INVALID")
native = root / "native"
native.mkdir(mode=0o755, exist_ok=True)
native_library = native / "libsnappyjava.so"
if native_library.exists():
    if native_library.read_bytes() != native_data:
        raise RuntimeError("REPLAY_NATIVE_LIBRARY_INVALID")
else:
    native_library.write_bytes(native_data)
native_library.chmod(0o444)

classpath = ":".join(str(path) for path, item in zip(paths, artifacts) if not item.get("buildOnly"))
output = root / "target/classes"
output.mkdir(parents=True, exist_ok=True)
subprocess.run(["java", "-jar", str(root / "tooling/ecj-3.37.0.jar"), "-17", "-proc:none", "-cp", classpath,
                "-d", str(output), str(root / "src/main/java/vision/narma/replay/ReplayProbe.java"),
                str(root / "src/main/java/vision/narma/replay/ReplayNativeSmoke.java")], check=True)
subprocess.run(["java", "-Xms256m", "-Xmx2g", "-XX:ActiveProcessorCount=2",
                "-Dorg.xerial.snappy.lib.path=" + str(native),
                "-Dorg.xerial.snappy.lib.name=libsnappyjava.so", "-cp", str(output) + ":" + classpath,
                "vision.narma.replay.ReplayNativeSmoke"], check=True, timeout=15)
print("Clarity probe compiled; dependency checksums and native compression verified.")
