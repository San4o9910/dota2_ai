"""The optional schema inspector must not leak secrets or pretend a feed is ready."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_stratz as inspector


SECRET = "synthetic_secret_do_not_print"


def ref(name, kind="OBJECT"):
    return {"name": name, "kind": kind, "ofType": None}


def field(name, type_name, args=None):
    return {"name": name, "type": ref(type_name), "args": args or []}


def fixtures():
    # Names deliberately differ from any unverified production STRATZ schema.
    roots = [field("heroStats", "SyntheticHeroStats", [
        {"name": "filter", "type": ref("SyntheticFilter", "INPUT_OBJECT")}
    ]), field("player", "SyntheticPlayer"), field("collection", "SyntheticCollection"),
       field("unrelated", "SyntheticUnrelated")]
    types = [ref("SyntheticHeroStats"), ref("SyntheticFilter", "INPUT_OBJECT"),
             ref("SyntheticPlayer"), ref("SyntheticCollection"), ref("SyntheticUnrelated")]
    initial = {"data": {"__schema": {"queryType": {"name": "SyntheticRoot", "fields": roots}, "types": types}}}
    detailed = {"data": {
        "t0": {"kind": "OBJECT", "name": "SyntheticHeroStats", "fields": [field("itemCollections", "SyntheticCollection")]},
        "t1": {"kind": "INPUT_OBJECT", "name": "SyntheticFilter", "inputFields": [
            {"name": "rank", "type": ref("String", "SCALAR")}
        ]},
        "t2": {"kind": "OBJECT", "name": "SyntheticPlayer", "fields": [field("matches", "SyntheticMatch")]},
        "t3": {"kind": "OBJECT", "name": "SyntheticCollection", "fields": [field("count", "Int")]},
    }}
    return initial, detailed


def response(document, *, status=200, url=inspector.ENDPOINT, headers=None):
    result = io.BytesIO(document if isinstance(document, bytes) else json.dumps(document).encode())
    result.status = status
    result.headers = headers or {}
    result.geturl = lambda: url
    return result


class StratzPreflightTest(unittest.TestCase):
    def run_main(self, token=SECRET):
        output = io.StringIO()
        with patch.dict(inspector.os.environ, {"STRATZ_API_TOKEN": token}), redirect_stdout(output):
            status = inspector.main()
        self.assertNotIn(SECRET, output.getvalue())
        return status, json.loads(output.getvalue())

    def test_missing_secret_skips_without_request_or_false_readiness(self):
        with patch.object(inspector.urllib.request, "build_opener") as opener:
            status, output = self.run_main("")
        self.assertEqual(status, 0)
        self.assertEqual(output["event"], "source_not_configured")
        self.assertFalse(output["schema_inspected"])
        self.assertFalse(output["popular_builds_ready"])
        opener.assert_not_called()

    def test_authorized_schema_only_uses_fixed_endpoint_and_never_claims_feed_ready(self):
        opener = SimpleNamespace(open=Mock(side_effect=[response(part) for part in fixtures()]))
        with patch.object(inspector.urllib.request, "build_opener", return_value=opener) as builder:
            status, output = self.run_main()
        self.assertEqual(status, 0)
        self.assertEqual(output["event"], "stratz_schema_inspected")
        self.assertTrue(output["schema_inspected"])
        self.assertFalse(output["popular_builds_ready"])
        self.assertEqual(output["match_data_requests"], 0)
        self.assertEqual(opener.open.call_count, 2)
        for call in builder.call_args_list:
            self.assertIsInstance(call.args[0], urllib.request.ProxyHandler)
            self.assertEqual(call.args[0].proxies, {})
            self.assertIsInstance(call.args[1], inspector.NoRedirect)
        queries = []
        for call in opener.open.call_args_list:
            request = call.args[0]
            self.assertEqual(request.full_url, inspector.ENDPOINT)
            self.assertEqual(request.get_header("Authorization"), "Bearer " + SECRET)
            self.assertEqual(call.kwargs["timeout"], inspector.TIMEOUT_SECONDS)
            self.assertNotIn(SECRET, request.data.decode())
            query = json.loads(request.data)["query"]
            self.assertNotIn("mutation", query)
            queries.append(query)
        self.assertIn("__schema", queries[0])
        self.assertIn('__type(name: "SyntheticHeroStats")', queries[1])
        self.assertNotIn("unrelated", json.dumps(output))
        self.assertEqual(output["root_fields"][0]["args"], [{"name": "filter", "type": "SyntheticFilter"}])
        self.assertEqual(output["types"][1]["fields"][0]["name"], "rank")

    def test_http_and_transport_errors_do_not_print_secret_or_response_details_or_retry(self):
        for status_code, expected in [(301, "redirect_rejected"), (401, "authentication_failed"),
                                      (403, "access_denied"), (429, "rate_limited"), (500, "http_error")]:
            with self.subTest(status=status_code):
                body = Mock(read=Mock(side_effect=AssertionError("Never read error bodies")))
                failure = urllib.error.HTTPError("https://wrong.invalid/" + SECRET, status_code, SECRET, {}, body)
                opener = SimpleNamespace(open=Mock(side_effect=failure))
                with patch.object(inspector.urllib.request, "build_opener", return_value=opener):
                    status, output = self.run_main()
                self.assertEqual(status, 1)
                self.assertEqual(output["code"], expected)
                self.assertEqual(opener.open.call_count, 1)
                body.read.assert_not_called()
        for failure in (urllib.error.URLError(SECRET), RuntimeError(SECRET)):
            with patch.object(inspector.urllib.request, "build_opener", side_effect=failure):
                status, output = self.run_main()
            self.assertEqual(status, 1)
            self.assertFalse(output["schema_inspected"])

    def test_redirect_handler_never_follows_or_forwards_authorization(self):
        request = urllib.request.Request(inspector.ENDPOINT, headers={"Authorization": "Bearer " + SECRET})
        with self.assertRaisesRegex(inspector.CheckError, "^redirect_rejected$"):
            inspector.NoRedirect().redirect_request(request, None, 302, SECRET, {}, "https://wrong.invalid/")
        with patch.object(inspector.urllib.request, "build_opener", return_value=SimpleNamespace(
                open=Mock(return_value=response({}, url="https://wrong.invalid/")))):
            status, output = self.run_main()
        self.assertEqual(status, 1)
        self.assertEqual(output["code"], "redirect_rejected")

    def test_schema_errors_invalid_json_and_oversized_body_fail_safely(self):
        for document, code in [
            ({"errors": [{"message": SECRET, "extensions": {"token": SECRET}}]}, "schema_query_rejected"),
            (b"<html>" + SECRET.encode(), "invalid_json"),
            ({"data": {"__schema": None}}, "invalid_schema"),
            (b"x" * (inspector.MAX_BODY_BYTES + 1), "response_too_large"),
        ]:
            with self.subTest(code=code):
                opener = SimpleNamespace(open=Mock(return_value=response(document)))
                with patch.object(inspector.urllib.request, "build_opener", return_value=opener):
                    status, output = self.run_main()
                self.assertEqual(status, 1)
                self.assertEqual(output["code"], code)
                self.assertEqual(opener.open.call_count, 1)

    def test_invalid_selected_type_cannot_pass_partial_schema(self):
        initial, detailed = fixtures()
        detailed["data"]["t2"]["fields"] = None
        opener = SimpleNamespace(open=Mock(side_effect=[response(initial), response(detailed)]))
        with patch.object(inspector.urllib.request, "build_opener", return_value=opener):
            status, output = self.run_main()
        self.assertEqual(status, 1)
        self.assertEqual(output["code"], "invalid_schema")

    def test_invalid_token_is_not_sent_and_unexpected_exception_is_not_echoed(self):
        with patch.object(inspector, "inspect_schema") as inspect:
            status, output = self.run_main(SECRET + "\nInjected: header")
        self.assertEqual(status, 1)
        self.assertEqual(output["code"], "invalid_token_format")
        inspect.assert_not_called()
        with patch.object(inspector, "inspect_schema", side_effect=inspector.CheckError(SECRET)):
            status, output = self.run_main()
        self.assertEqual(status, 1)
        self.assertEqual(output["code"], "internal_error")

    def test_secret_reflected_in_valid_metadata_is_redacted(self):
        with patch.object(inspector, "inspect_schema", return_value={"schema_type": SECRET}):
            status, output = self.run_main()
        self.assertEqual(status, 0)
        self.assertEqual(output["schema_type"], "[redacted]")


if __name__ == "__main__":
    unittest.main()
