"""Transient reads may retry; resource mutations and unrelated failures may not."""
import io
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pilot


def response(data=b'{"ok":true}'):
    return io.BytesIO(data)


def http_error(status):
    return urllib.error.HTTPError("https://synthetic.invalid/private", status,
        "private error text must stay private", {}, io.BytesIO(b"private body must stay private"))


class CloudReadsTest(unittest.TestCase):
    def setUp(self):
        self.cloud = pilot.Cloud.__new__(pilot.Cloud)
        self.cloud.token = "synthetic_token_never_printed"

    def test_transient_get_http_statuses_retry_with_bounded_backoff(self):
        for status in (429, 500, 502, 503, 504):
            with self.subTest(status=status):
                opener = SimpleNamespace(open=Mock(side_effect=[http_error(status), http_error(status), response()]))
                with patch.object(pilot.urllib.request, "build_opener", return_value=opener), \
                        patch.object(pilot.time, "sleep") as sleep:
                    self.assertEqual(self.cloud.call("GET", "/api/v1/servers"), {"ok": True})
                self.assertEqual(opener.open.call_count, 3)
                self.assertEqual(sleep.call_args_list, [call(2), call(4)])

    def test_get_transport_failures_retry_and_http_exhaustion_stops_at_three(self):
        opener = SimpleNamespace(open=Mock(side_effect=[urllib.error.URLError("private detail"), TimeoutError(), response()]))
        with patch.object(pilot.urllib.request, "build_opener", return_value=opener), patch.object(pilot.time, "sleep") as sleep:
            self.assertEqual(self.cloud.call("GET", "/api/v1/servers"), {"ok": True})
            self.assertEqual(sleep.call_args_list, [call(2), call(4)])
        opener.open = Mock(side_effect=[http_error(500), http_error(500), http_error(500)])
        with patch.object(pilot.urllib.request, "build_opener", return_value=opener), patch.object(pilot.time, "sleep"):
            with self.assertRaisesRegex(pilot.CheckError, r"^cloud_http_500_GET_/api/v1/servers$"):
                self.cloud.call("GET", "/api/v1/servers?limit=100")
        self.assertEqual(opener.open.call_count, 3)

    def test_post_and_delete_never_retry_even_transient_failures(self):
        for method in ("POST", "DELETE"):
            for kind in (429, 500, 502, 503, 504, "url", "timeout"):
                with self.subTest(method=method, failure=kind):
                    error = (urllib.error.URLError("private detail") if kind == "url" else
                             TimeoutError() if kind == "timeout" else http_error(kind))
                    opener = SimpleNamespace(open=Mock(side_effect=error))
                    with patch.object(pilot.urllib.request, "build_opener", return_value=opener), \
                            patch.object(pilot.time, "sleep") as sleep:
                        with self.assertRaises(pilot.CheckError) as caught:
                            self.cloud.call(method, "/api/v1/servers")
                    self.assertNotIn("private", str(caught.exception))
                    self.assertEqual(opener.open.call_count, 1)
                    sleep.assert_not_called()

    def test_get_auth_schema_and_oversize_failures_do_not_retry(self):
        for failure in (http_error(401), http_error(404), response(b"not json"), response(b"x" * (2 * 1024**2 + 1))):
            opener = SimpleNamespace(open=Mock(side_effect=failure) if isinstance(failure, Exception) else Mock(return_value=failure))
            with patch.object(pilot.urllib.request, "build_opener", return_value=opener), patch.object(pilot.time, "sleep") as sleep:
                with self.assertRaises(pilot.CheckError):
                    self.cloud.call("GET", "/api/v1/servers")
            self.assertEqual(opener.open.call_count, 1)
            sleep.assert_not_called()

    def test_existing_checked_server_skips_os_catalog_but_new_server_requires_it(self):
        for existing in (True, False):
            with self.subTest(existing=existing):
                paths = []
                def listing(path, key):
                    paths.append(path)
                    if path == "/api/v1/presets/servers":
                        return [{"id": pilot.PRESET, "location": "nl-1", "cpu": 4, "ram": 8192, "price": 2000}]
                    if path == "/api/v1/servers?limit=100":
                        return ([{"id": 9037783, "name": pilot.NAME, "comment": pilot.MARKER,
                                  "project_id": 2655641, "preset_id": pilot.PRESET}] if existing else [])
                    if path == "/api/v1/os/servers":
                        if existing: raise AssertionError("Existing server must not query the OS catalog")
                        return [{"id": 1, "name": "Ubuntu", "version": "24.04"}]
                    raise AssertionError("Unexpected API read")
                cloud = SimpleNamespace(list=listing, call=Mock())
                with patch.object(pilot, "Cloud", return_value=cloud), \
                        patch.object(pilot, "PINNED_TARGET", None), \
                        patch.object(pilot, "selected_project", return_value=2655641), \
                        patch.object(pilot, "event"), \
                        patch.dict(pilot.os.environ, {"GEMINI_API_KEY": "synthetic_key_long_enough", "GITHUB_SHA": "a" * 40}), \
                        patch.object(pilot, "prepare_bundle", side_effect=pilot.ImageError("prebuilt_test_stop")):
                    with self.assertRaisesRegex(pilot.CheckError, "prebuilt_test_stop"):
                        pilot.main()
                self.assertEqual("/api/v1/os/servers" in paths, not existing)
                cloud.call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
