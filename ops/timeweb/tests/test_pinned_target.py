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
                cloud.list.assert_called_once_with("/api/v1/presets/servers", "server_presets")
                project.assert_not_called(); bundle.assert_not_called()

    def test_preflight_is_read_only_and_does_not_require_gemini_or_release(self):
        cloud = SimpleNamespace(call=Mock(return_value={"server": server()}), list=Mock(return_value=presets()))
        with patch.object(pilot, "Cloud", return_value=cloud), \
                patch.object(pilot, "event") as event, \
                patch.dict(pilot.os.environ, {}, clear=True):
            pilot.target_preflight()
        cloud.call.assert_called_once_with("GET", "/api/v1/servers/9037783")
        cloud.list.assert_called_once_with("/api/v1/presets/servers", "server_presets")
        self.assertTrue(event.call_args.kwargs["read_only"])

    def test_pinned_target_keeps_price_guard_before_image_preparation(self):
        expensive = presets(); expensive[0]["price"] = pilot.MAX_VM_MONTH_EQUIVALENT + 1
        cloud = SimpleNamespace(call=Mock(return_value={"server": server()}), list=Mock(return_value=expensive))
        with patch.object(pilot, "Cloud", return_value=cloud), patch.object(pilot, "prepare_bundle") as bundle, \
                patch.dict(pilot.os.environ, {"GEMINI_API_KEY": "synthetic_key_long_enough", "GITHUB_SHA": "a" * 40}):
            with self.assertRaisesRegex(pilot.CheckError, "pilot_price_exceeds_authorized_target"):
                pilot.main()
        bundle.assert_not_called()


if __name__ == "__main__":
    unittest.main()
