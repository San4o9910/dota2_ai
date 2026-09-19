import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from release_gate import BRANCH, WORKFLOWS, checks, current, verify

SHA = 'a' * 40

def run(path, **values):
    return dict(head_sha=SHA, head_branch=BRANCH, event='push', path=path,
                run_number=1, run_attempt=1, status='completed', conclusion='success') | values

class ReleaseGateTest(unittest.TestCase):
    def test_both_exact_commit_push_checks_required(self):
        runs = [run(path) for path in WORKFLOWS]
        self.assertTrue(checks(runs, SHA))
        self.assertFalse(checks(runs[:1], SHA))
        for change in ({'head_sha':'b'*40}, {'head_branch':'main'}, {'event':'pull_request'}, {'status':'in_progress'}):
            self.assertFalse(checks([run(path, **change) for path in WORKFLOWS], SHA))
        for conclusion in ('failure','skipped','cancelled','neutral'):
            with self.assertRaises(RuntimeError):
                checks([run(path, conclusion=conclusion) for path in WORKFLOWS], SHA)

    def test_latest_attempt_overrides_older_success(self):
        runs = [run(path) for path in WORKFLOWS]
        self.assertFalse(checks(runs+[run(WORKFLOWS[0],run_attempt=2,status='in_progress')], SHA))
        with self.assertRaises(RuntimeError):
            checks(runs+[run(WORKFLOWS[0],run_number=2,conclusion='failure')], SHA)

    def test_superseded_commit_and_wait_timeout_fail_closed(self):
        with self.assertRaises(RuntimeError):
            current(SHA, lambda _: {'commit':{'sha':'b'*40}})
        times=iter([0,1501])
        def get(path):
            return {'commit':{'sha':SHA}} if path.startswith('/branches/') else {'workflow_runs':[]}
        with self.assertRaisesRegex(RuntimeError,'timed out'):
            verify(SHA,get=get,clock=lambda:next(times),wait=lambda _:None)
