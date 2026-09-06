#!/usr/bin/env python3
"""Reproducible JRE17-only research build. Download pinned artifacts from Maven Central."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
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
                    item["url"], "-o", str(temporary)], check=True)
    if temporary.stat().st_size != item["bytes"] or digest(temporary) != item["sha256"]:
        temporary.unlink()
        raise ValueError("Dependency checksum mismatch")
    temporary.replace(target)
    return target

with ThreadPoolExecutor(max_workers=8) as executor:
    paths = list(executor.map(download, artifacts))
classpath = ":".join(str(path) for path, item in zip(paths, artifacts) if not item.get("buildOnly"))
output = root / "target/classes"
output.mkdir(parents=True, exist_ok=True)
subprocess.run(["java", "-jar", str(root / "tooling/ecj-3.37.0.jar"), "-17", "-proc:none", "-cp", classpath,
                "-d", str(output), str(root / "src/main/java/vision/narma/replay/ReplayProbe.java")], check=True)
print("Clarity probe compiled; dependency checksums verified.")
