"""Check the Gemini key by listing models; no inference or media uploads."""
import json
import os
import re
import sys
import urllib.error
import urllib.request
from preflight import CheckError, NoRedirect


def main():
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    result = {"mode": "models_only", "generation_requests": 0}
    if not 20 <= len(key) <= 16384 or any(c.isspace() for c in key):
        result["error"] = "missing_or_invalid_GEMINI_API_KEY_secret"
    else:
        request = urllib.request.Request(
            "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000",
            method="GET", headers={"x-goog-api-key": key, "Accept": "application/json"},
        )
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=25) as response:
                data = response.read(2 * 1024 * 1024 + 1)
            if len(data) > 2 * 1024 * 1024:
                raise CheckError("response_too_large")
            models = json.loads(data)
            if not isinstance(models, dict) or not isinstance(models.get("models"), list):
                raise CheckError("unexpected_schema")
            names = sorted({m["name"] for m in models["models"] if isinstance(m, dict)
                and isinstance(m.get("name"), str)
                and re.fullmatch(r"models/gemini-[A-Za-z0-9._-]{1,80}", m["name"])})
            result.update(key_access="ok", models=names,
                preferred_model_listed="models/gemini-3.8-flash" in names,
                list_truncated=bool(models.get("nextPageToken")))
        except urllib.error.HTTPError as error:
            result["error"] = "http_" + str(error.code)
        except (urllib.error.URLError, TimeoutError, OSError):
            result["error"] = "connection_failed"
        except (ValueError, UnicodeError):
            result["error"] = "invalid_json"
        except CheckError as error:
            result["error"] = str(error)
    output = json.dumps(result, ensure_ascii=True, indent=2)
    if key:
        output = output.replace(key, "[REDACTED]")
    print(output)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as handle:
            handle.write("## Gemini key check (no inference)\n\n```json\n" + output + "\n```\n")
    return int("error" in result)


if __name__ == "__main__":
    sys.exit(main())
