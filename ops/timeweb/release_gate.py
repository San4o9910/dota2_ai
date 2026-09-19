"""Read-only exact-commit gates for ordinary automatic releases; no cloud writes."""
import argparse
import json
import os
import re
import time
from urllib.request import Request, urlopen

REPOSITORY = 'San4o9910/dota2_ai'
BRANCH = 'codex/openai-video-coach'
WORKFLOWS = ('.github/workflows/ci.yml', '.github/workflows/deep-learning-ci.yml')


def fetch(path):
    request = Request('https://api.github.com/repos/' + REPOSITORY + path,
        headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
                 'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def current(sha, get=fetch):
    if not re.fullmatch('[0-9a-f]{40}', sha):
        raise RuntimeError('Invalid release commit')
    if get('/branches/' + BRANCH)['commit']['sha'] != sha:
        raise RuntimeError('Release superseded: this job cannot replace a newer release')


def checks(runs, sha):
    for path in WORKFLOWS:
        candidates = [r for r in runs if r['head_sha'] == sha and r['head_branch'] == BRANCH
                      and r['event'] == 'push' and r['path'] == path]
        if not candidates:
            return False
        latest = max(candidates, key=lambda r: (r['run_number'], r.get('run_attempt', 1)))
        if latest['status'] != 'completed':
            return False
        if latest['conclusion'] != 'success':
            raise RuntimeError('Release verification failed: ' + path)
    return True


def verify(sha, *, current_only=False, get=fetch, clock=time.monotonic, wait=time.sleep):
    deadline = clock() + 25 * 60
    while True:
        current(sha, get)
        if current_only or checks(get('/actions/runs?head_sha=' + sha + '&per_page=100')['workflow_runs'], sha):
            print('Exact release verified; no provider or cloud mutations.')
            return
        if clock() >= deadline:
            raise RuntimeError('Release verification timed out; server was not changed')
        print('Waiting for CI and application verification of this commit.', flush=True)
        wait(20)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--current-only', action='store_true')
    args = parser.parse_args()
    if os.environ.get('GITHUB_REPOSITORY') != REPOSITORY or os.environ.get('GITHUB_REF') != 'refs/heads/' + BRANCH:
        raise SystemExit('Unsupported release target')
    verify(os.environ['GITHUB_SHA'], current_only=args.current_only)
