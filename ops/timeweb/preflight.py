"""Read-only Timeweb access check. No provisioning or raw response logging."""

import json
import math
import os
import re
import sys
import urllib.error
import urllib.request

ORIGIN = "https://api.timeweb.cloud"
ENDPOINTS = {
    "servers": "/api/v1/servers?limit=100",
    "server_presets": "/api/v1/presets/servers",
    "storages_presets": "/api/v1/presets/storages",
}
MAX_BYTES = 2 * 1024 * 1024
NUMERIC_FIELDS = ("id", "price", "cpu", "cpu_frequency", "ram", "disk", "bandwidth")
CODE_FIELDS = ("location", "disk_type", "storage_class")


class CheckError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise CheckError("unexpected_redirect")


def get_resource(name, token):
    # No user-provided origin, paths, HTTP method, or redirect target.
    request = urllib.request.Request(
        ORIGIN + ENDPOINTS[name], method="GET",
        headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
    )
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=20) as response:
            if response.status != 200:
                raise CheckError("unexpected_status")
            raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise CheckError("response_too_large")
        data = json.loads(raw)
        if not isinstance(data, dict) or not isinstance(data.get(name), list):
            raise CheckError("unexpected_schema")
        return data[name]
    except urllib.error.HTTPError as error:
        # Provider bodies and exception messages may contain sensitive data.
        raise CheckError("http_" + str(error.code)) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise CheckError("connection_failed") from None
    except (ValueError, UnicodeError):
        raise CheckError("invalid_json") from None


def safe_preset(item):
    if not isinstance(item, dict):
        raise CheckError("invalid_preset")
    safe = {}
    for field in NUMERIC_FIELDS:
        value = item.get(field)
        if type(value) in (int, float) and 0 <= value <= 10**12 and math.isfinite(value):
            safe[field] = value
    for field in CODE_FIELDS:
        value = item.get(field)
        if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,32}", value):
            safe[field] = value
    return safe


def main():
    token = os.environ.get("TIMEWEB_CLOUD_TOKEN", "").strip()
    report = {
        "mode": "read_only", "budget_target_rub_per_day": 100,
        "provisioning_performed": False,
        "notes": [
            "Preset prices are raw API values, not a verified final monthly quote.",
            "Include IPv4, offserver backups, egress and existing services before ordering.",
            "Server ram/disk are MB; storage disk units require confirmation.",
            "Verify the selected region against Gemini availability before ordering.",
        ],
    }
    if not 20 <= len(token) <= 16384 or any(c.isspace() for c in token):
        report["error"] = "missing_or_invalid_TIMEWEB_CLOUD_TOKEN_secret"
        print(json.dumps(report, ensure_ascii=True))
        return 1
    errors = False
    for name in ENDPOINTS:
        try:
            items = get_resource(name, token)
            if name == "servers":
                # This authenticated endpoint confirms server read access only.
                # No names, IPs, IDs, balances, credentials or customer data leave it.
                report["server_read_access"] = "ok"
                pilot = [item for item in items if item.get("name") == "narma-vision-pilot-01"]
                if len(pilot) == 1:
                    item = pilot[0]
                    report["narma_pilot"] = {
                        "id":item.get("id"), "preset_id":item.get("preset_id"),
                        "availability_zone":item.get("availability_zone") if re.fullmatch(r"[a-z0-9-]{1,64}", str(item.get("availability_zone", ""))) else None,
                        "project_id":item.get("project_id"),
                        "public_ipv4_present":any(ip.get("type") == "ipv4"
                            for network in item.get("networks", []) if network.get("type") == "public"
                            for ip in (network.get("ips") or [])),
                        "status":item.get("status") if re.fullmatch(r"[A-Za-z_-]{1,40}", str(item.get("status", ""))) else "unknown",
                        "schema_fields":sorted(item.keys()),
                    }
            else:
                report[name] = [safe_preset(item) for item in items[:500]]
                report[name + "_truncated"] = len(items) > 500
        except CheckError as error:
            report[name + "_error"] = str(error)
            errors = True
    output = json.dumps(report, ensure_ascii=True, indent=2)
    # Defence in depth, even if a provider unexpectedly echoes the token.
    output = output.replace(token, "[REDACTED]")
    print(output)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("## Timeweb preflight (read only)\n\n```json\n" + output + "\n```\n")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
