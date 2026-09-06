#!/usr/bin/env python3
"""Run a compiled probe with explicit resource budgets. Linux worker prototype."""
import argparse
import json
from pathlib import Path
import resource
import subprocess
import time

parser = argparse.ArgumentParser()
parser.add_argument("replay", type=Path)
parser.add_argument("new_output_directory", type=Path)
args = parser.parse_args()
args.new_output_directory.mkdir(parents=True, exist_ok=False)
root = Path(__file__).resolve().parent
output = args.new_output_directory.resolve()
command = ["java", "-Xms256m", "-Xmx2g", "-Dorg.slf4j.simpleLogger.defaultLogLevel=warn", "-cp",
           str(root / "target/classes") + ":" + str(root / "target/dependency/*"),
           "vision.narma.replay.ReplayProbe", str(args.replay.resolve()), str(output / "events.jsonl")]

def limits():
    resource.setrlimit(resource.RLIMIT_CPU, (295, 300))
    resource.setrlimit(resource.RLIMIT_FSIZE, (50 * 1024 * 1024, 50 * 1024 * 1024))

start = time.monotonic()
with (output / "summary.json").open("w") as stdout, (output / "run.log").open("w") as stderr:
    try:
        code = subprocess.run(command, stdout=stdout, stderr=stderr, timeout=300, preexec_fn=limits).returncode
    except subprocess.TimeoutExpired:
        code = 124
usage = resource.getrusage(resource.RUSAGE_CHILDREN)
metrics = {"exitCode": code, "wallSeconds": round(time.monotonic() - start, 3),
           "maxRssKiB": usage.ru_maxrss, "userCpuSeconds": usage.ru_utime, "systemCpuSeconds": usage.ru_stime}
(output / "run-metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
print(json.dumps(metrics))
raise SystemExit(code)
