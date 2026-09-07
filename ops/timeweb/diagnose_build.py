"""Keep raw build logs private; report only fixed operational categories."""
import json
from pathlib import Path
import sys

PATTERNS = {
    'dependency_rate_limited': ('429', 'too many requests', 'toomanyrequests'),
    'dependency_network': ('could not resolve', 'temporary failure resolving', 'connection timed out',
                           'operation timed out', 'connection reset', 'failed to connect', '502', '503', '504'),
    'dependency_denied': ('403', '401', 'pull access denied'),
    'dependency_missing': ('404', 'no matching distribution', 'manifest unknown'),
    'dependency_integrity': ('checksum mismatch', 'replay_native_library_invalid'),
    'source_missing': ('not found in build context', 'failed to calculate checksum', 'no such file or directory'),
    'compile_error': ('compilation failed', 'syntaxerror', 'cannot be resolved', 'error in /opt/narma/replay/src'),
    'disk_full': ('no space left on device',),
    'memory_limit': ('out of memory', 'cannot allocate memory', 'exit code: 137'),
}

def categories(value):
    value = value.lower()
    return [code for code, needles in PATTERNS.items() if any(needle in value for needle in needles)] or ['unclassified']

def main():
    path = Path(sys.argv[1])
    with path.open('rb') as stream:
        stream.seek(max(0, path.stat().st_size - 512 * 1024))
        value = stream.read(512 * 1024).decode(errors='replace')
    for code in categories(value):
        print(json.dumps({'event': 'build_diagnostic', 'code': code}), flush=True)

if __name__ == '__main__':
    main()
