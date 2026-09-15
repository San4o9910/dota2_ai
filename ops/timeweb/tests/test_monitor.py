"""No cloud, SSH, notification or provider request is made by these tests."""
from datetime import datetime, timezone
import json
import io
from contextlib import redirect_stdout
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import monitor

NOW = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)


def run(identifier=1, created="2026-09-13T03:41:00Z", conclusion="success", **changes):
    return dict(id=identifier, created_at=created, conclusion=conclusion,
                status="completed", head_branch="main", event="schedule", **changes)


def snapshot():
    return {"schema": "narma.operations-health.v1", "status": "ok", "checks": [
        monitor.receipt(name) for name in sorted(monitor.SNAPSHOT_NAMES - {"snapshot_unavailable"})]}


class MonitorTest(unittest.TestCase):
    def test_real_event_writer_preserves_check_name_and_completion(self):
        for severity, expected in (("ok", 0), ("warning", 1), ("critical", 1)):
            output = io.StringIO()
            with patch.object(monitor, "public_health", return_value=monitor.receipt("public_https")), \
                    patch.object(monitor, "inspect_backup", return_value=monitor.receipt("backup_restore_drill")), \
                    patch.object(monitor, "Cloud"), \
                    patch.object(monitor, "private_health", return_value=[monitor.receipt("openai_budget", severity)]), \
                    redirect_stdout(output):
                self.assertEqual(monitor.main(), expected)
            events = [json.loads(line) for line in output.getvalue().splitlines() if line.startswith('{')]
            self.assertEqual(events[2]["name"], "openai_budget")
            self.assertEqual(events[2]["severity"], severity)
            self.assertEqual(events[-1]["event"], "operations_monitor_complete")
            self.assertEqual(events[-1]["status"], severity)

    def test_backup_uses_only_default_branch_restore_evidence(self):
        foreign = {**run(), "head_branch": "codex/other"}
        self.assertEqual(monitor.backup_health([foreign], now=NOW)["severity"], "critical")
        result = monitor.backup_health([run()], now=NOW)
        self.assertEqual(result["severity"], "ok")
        self.assertEqual(result["metrics"]["last_success_age_seconds"], 8 * 3600 + 19 * 60)

    def test_backup_detects_stale_failed_cancelled_and_inactive(self):
        for runs, active in (([run(created="2026-09-11T03:41:00Z")], True),
            ([run(), run(2, "2026-09-13T10:00:00Z", "failure")], True),
            ([run(), run(2, "2026-09-13T10:00:00Z", "cancelled")], True),
            ([run()], False), ([], True)):
            with self.subTest(runs=runs, active=active):
                self.assertEqual(monitor.backup_health(runs, now=NOW, active=active)["severity"], "critical")

    def test_new_running_backup_does_not_hide_previous_failure(self):
        rows = [run(), run(2, "2026-09-13T10:00:00Z", "failure"),
                {**run(3, "2026-09-13T11:00:00Z", None), "status": "in_progress"}]
        self.assertEqual(monitor.backup_health(rows, now=NOW)["severity"], "critical")
        rows = [run(), {**run(3, "2026-09-13T11:00:00Z", None), "status": "in_progress"}]
        self.assertEqual(monitor.backup_health(rows, now=NOW)["severity"], "ok")

    def test_remote_receipt_requires_complete_known_checks(self):
        self.assertEqual(len(monitor.parse_snapshot(json.dumps(snapshot()))), 10)
        value = snapshot()
        value["checks"].pop()
        with self.assertRaises(monitor.CheckError):
            monitor.parse_snapshot(json.dumps(value))

    def test_remote_arbitrary_strings_and_secret_fields_are_never_forwarded(self):
        for metrics in ({"owner_id": "private"}, {"expires_at": "private"},
                        {"queued": "private"}, {"queued": {"private": "value"}}):
            value = snapshot()
            value["checks"][0]["metrics"] = metrics
            with self.subTest(metrics=metrics), self.assertRaises(monitor.CheckError):
                monitor.parse_snapshot(json.dumps(value))

    def test_bad_remote_schema_and_forged_status_fail(self):
        for update in ({"schema": "other"}, {"status": "private"}, {"checks": []}):
            value = snapshot()
            value.update(update)
            with self.subTest(update=update), self.assertRaises(monitor.CheckError):
                monitor.parse_snapshot(json.dumps(value))
        value = snapshot()
        value["checks"][0]["severity"] = "critical"
        with self.assertRaises(monitor.CheckError):
            monitor.parse_snapshot(json.dumps(value))

    def test_public_probe_no_sensitive_response_forwarding(self):
        with patch.object(monitor, "get_json", return_value={"status": "alive"}) as get:
            self.assertEqual(monitor.public_health()["severity"], "ok")
            get.assert_called_once_with(monitor.SITE + "/livez")
        with patch.object(monitor, "get_json", side_effect=RuntimeError("private-token")):
            self.assertNotIn("private-token", str(monitor.public_health()))

    def test_ephemeral_key_removed_on_snapshot_failure(self):
        cloud = Mock()
        cloud.call.side_effect = [{"server": {}}, {"ssh_key": {"id": 321}}, {}, {}, {}]
        with patch.object(monitor, "validate_pinned_server"), \
                patch.object(monitor.Path, "read_text", return_value="synthetic-public-key"), \
                patch.object(monitor, "command", side_effect=[b"", b"", b"untrusted-output"]):
            with self.assertRaises(ValueError):
                monitor.private_health(cloud)
        deletes = [c.args for c in cloud.call.call_args_list if c.args[0] == "DELETE"]
        self.assertEqual(deletes, [("DELETE", "/api/v1/servers/9037783/ssh-keys/321"),
                                  ("DELETE", "/api/v1/ssh-keys/321")])

    def test_identity_mismatch_creates_no_ssh_key(self):
        cloud = Mock()
        cloud.call.return_value = {"server": {}}
        with self.assertRaises(monitor.CheckError):
            monitor.private_health(cloud)
        self.assertEqual(cloud.call.call_count, 1)

    def test_failed_key_cleanup_is_not_reported_healthy(self):
        cloud = Mock()
        cloud.call.side_effect = [{"server": {}}, {"ssh_key": {"id": 321}}, {},
                                 RuntimeError("private error"), {}]
        with patch.object(monitor, "validate_pinned_server"), \
                patch.object(monitor.Path, "read_text", return_value="synthetic-public-key"), \
                patch.object(monitor, "command", side_effect=[b"", b"", json.dumps(snapshot()).encode()]), \
                patch.object(monitor, "event") as event:
            with self.assertRaisesRegex(monitor.CheckError, "monitor_key_cleanup_unconfirmed"):
                monitor.private_health(cloud)
        self.assertNotIn("private error", str(event.call_args_list))
        self.assertEqual(cloud.call.call_args.args, ("DELETE", "/api/v1/ssh-keys/321"))

    def test_warning_fails_workflow_for_configured_failure_notifications(self):
        for level, status in (("ok", 0), ("warning", 1), ("critical", 1)):
            with patch.object(monitor, "public_health", return_value=monitor.receipt("public_https")), \
                    patch.object(monitor, "inspect_backup", return_value=monitor.receipt("backup_restore_drill")), \
                    patch.object(monitor, "Cloud"), \
                    patch.object(monitor, "private_health", return_value=[monitor.receipt("openai_budget", level)]), \
                    patch.object(monitor, "event"), patch("builtins.print"):
                self.assertEqual(monitor.main(), status)


if __name__ == "__main__":
    unittest.main()
