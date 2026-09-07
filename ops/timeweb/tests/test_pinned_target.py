"""A pinned production target can never silently become a provisioning request."""
from copy import deepcopy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pilot


def server():
    return {"id": 9037783, "project_id": 2655641, "name": pilot.NAME,
        "comment": pilot.MARKER, "preset_id": pilot.PRESET, "status": "on",
        "networks": [{"type": "public", "ips": [{"type": "ipv4", "ip": "72.56.98.68"}]}]}


def presets():
    return [{"id": pilot.PRESET, "location": "nl-1", "cpu": 4, "ram": 8192, "price": 2000}]


class PinnedTargetTest(unittest.TestCase):
    def test_direct_lookup_uses_only_explicit_id_and_accepts_exact_target(self):
        cloud = SimpleNamespace(call=Mock(return_value={"server": server()}), list=Mock())
        self.assertEqual(pilot.pinned_existing_server(cloud), server())
        cloud.call.assert_called_once_with("GET", "/api/v1/servers/9037783")
        cloud.list.assert_not_called()

    def test_every_target_identity_field_and_public_ip_are_checked(self):
        changes = {"id": 123, "project_id": 123, "name": "different", "comment": "different",
                   "preset_id": 123, "networks": [{"type": "public", "ips": [{"type": "ipv4", "ip": "8.8.8.8"}]}]}
        for field, value in changes.items():
            with self.subTest(field=field):
                changed = deepcopy(server()); changed[field] = value
                cloud = SimpleNamespace(call=Mock(return_value={"server": changed}), list=Mock())
                with self.assertRaises(pilot.CheckError):
                    pilot.pinned_existing_server(cloud)
                cloud.call.assert_called_once_with("GET", "/api/v1/servers/9037783")
                cloud.list.assert_not_called()

    def test_missing_or_unreachable_pinned_server_cannot_fall_back_to_creation(self):
        for code in ("cloud_http_404_GET_/api/v1/servers/9037783", "cloud_http_500_GET_/api/v1/servers/9037783"):
            with self.subTest(code=code):
                cloud = SimpleNamespace(call=Mock(side_effect=pilot.CheckError(code)), list=Mock(return_value=presets()))
                with patch.object(pilot, "Cloud", return_value=cloud), \
                        patch.object(pilot, "selected_project") as project, \
                        patch.object(pilot, "prepare_bundle") as bundle, \
                        patch.dict(pilot.os.environ, {"GEMINI_API_KEY": "synthetic_key_long_enough", "GITHUB_SHA": "a" * 40}):
                    with self.assertRaisesRegex(pilot.CheckError, code):
                        pilot.main()
                cloud.call.assert_called_once_with("GET", "/api/v1/servers/9037783")
                cloud.list.assert_not_called()
                project.assert_not_called(); bundle.assert_not_called()

    def test_preflight_is_read_only_and_does_not_require_gemini_or_release(self):
        cloud = SimpleNamespace(call=Mock(return_value={"server": server()}), list=Mock(return_value=presets()))
        with patch.object(pilot, "Cloud", return_value=cloud), \
                patch.object(pilot, "event") as event, \
                patch.dict(pilot.os.environ, {}, clear=True):
            pilot.target_preflight()
        cloud.call.assert_called_once_with("GET", "/api/v1/servers/9037783")
        cloud.list.assert_not_called()
        self.assertTrue(event.call_args.kwargs["read_only"])
        self.assertTrue(event.call_args.kwargs["approved_preset_id_verified"])
        self.assertFalse(event.call_args.kwargs["infrastructure_change_requested"])
        self.assertNotIn("preset_and_budget_verified", event.call_args.kwargs)

    def test_explicit_unpinned_provisioning_keeps_price_guard_before_image_preparation(self):
        expensive = presets(); expensive[0]["price"] = pilot.MAX_VM_MONTH_EQUIVALENT + 1
        cloud = SimpleNamespace(call=Mock(return_value={"server": server()}), list=Mock(return_value=expensive))
        with patch.object(pilot, "Cloud", return_value=cloud), patch.object(pilot, "PINNED_TARGET", None), \
                patch.object(pilot, "prepare_bundle") as bundle, \
                patch.dict(pilot.os.environ, {"GEMINI_API_KEY": "synthetic_key_long_enough", "GITHUB_SHA": "a" * 40}):
            with self.assertRaisesRegex(pilot.CheckError, "pilot_price_exceeds_authorized_target"):
                pilot.main()
        bundle.assert_not_called()

    def test_pinned_update_uses_one_identity_read_and_no_catalog_or_domain_lists(self):
        calls = []
        def call(method, path, payload=None):
            calls.append((method, path))
            if method == "GET":
                self.assertEqual(path, "/api/v1/servers/9037783")
                self.assertEqual(sum(m == "GET" for m, _ in calls), 1)
                return {"server": server()}
            if method == "POST" and path == "/api/v1/ssh-keys":
                return {"ssh_key": {"id": 777}}
            self.assertIn((method, path), {
                ("POST", "/api/v1/servers/9037783/ssh-keys"),
                ("DELETE", "/api/v1/servers/9037783/ssh-keys/777"),
                ("DELETE", "/api/v1/ssh-keys/777")})
            return {}
        def command(argv, **options):
            if argv[0] == "ssh-keygen":
                Path(argv[-1]).with_suffix(".pub").write_text("synthetic public key")
                return b""
            self.assertIn("root@72.56.98.68", argv)
            if argv[-1] == "true": return b""
            self.assertTrue(argv[-1].startswith("mkdir -p /opt/narma/releases/"))
            raise pilot.CheckError("synthetic_stop_before_host_mutation")
        def bundle(sha, directory):
            return directory / "archive", directory / "manifest", {"archive_bytes": 1, "source_tree": "b" * 40}
        cloud = SimpleNamespace(call=call, list=Mock(side_effect=AssertionError("No catalog needed for code-only update")))
        with patch.object(pilot, "Cloud", return_value=cloud), patch.object(pilot, "command", side_effect=command), \
                patch.object(pilot, "prepare_bundle", side_effect=bundle), patch.object(pilot, "event") as event, \
                patch.dict(pilot.os.environ, {"GEMINI_API_KEY": "synthetic_key_long_enough", "GITHUB_SHA": "a" * 40}):
            with self.assertRaisesRegex(pilot.CheckError, "synthetic_stop_before_host_mutation"):
                pilot.main()
        cloud.list.assert_not_called()
        plan = next(item for item in event.call_args_list if item.args == ("pilot_plan",))
        self.assertEqual(plan.kwargs["action"], "update_existing_server")
        self.assertFalse(plan.kwargs["infrastructure_change_requested"])
        self.assertNotIn("vm_month_equivalent_rub", plan.kwargs)


if __name__ == "__main__":
    unittest.main()
