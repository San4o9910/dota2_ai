#!/usr/bin/env python3
"""Inspect STRATZ schema metadata; never fetch player/match data or enable a feed."""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request


ENDPOINT = "https://api.stratz.com/graphql"
TIMEOUT_SECONDS = 12
MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_TYPES = 16
MAX_FIELDS = 48
NAME = re.compile(r"[_A-Za-z][_0-9A-Za-z]{0,95}\Z")
TOKEN = re.compile(r"[A-Za-z0-9._~+/-]+={0,2}\Z")
RELEVANT = re.compile(r"match|player|herostats|collection", re.IGNORECASE)
KINDS = {"SCALAR", "OBJECT", "INTERFACE", "UNION", "ENUM", "INPUT_OBJECT", "LIST", "NON_NULL"}
ERROR_CODES = {"redirect_rejected", "http_error", "response_too_large", "network_timeout",
               "authentication_failed", "access_denied", "rate_limited", "network_error",
               "invalid_json", "schema_query_rejected", "invalid_schema",
               "relevant_schema_not_found", "invalid_token_format", "internal_error"}


class CheckError(Exception):
    """Only fixed, non-sensitive error codes may cross the CLI boundary."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise CheckError("redirect_rejected")


def graphql(token: str, query: str) -> dict:
    """One bounded request, no retries and no environmental HTTP proxies."""
    request = urllib.request.Request(
        ENDPOINT,
        data=json.dumps({"query": query, "operationName": "NarmaSchemaInspection"}).encode(),
        method="POST",
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json",
                 "Accept": "application/json", "User-Agent": "STRATZ_API"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            if response.geturl() != ENDPOINT:
                raise CheckError("redirect_rejected")
            if response.status != 200:
                raise CheckError("http_error")
            length = response.headers.get("Content-Length")
            if length is not None and (not length.isdecimal() or int(length) > MAX_BODY_BYTES):
                raise CheckError("response_too_large")
            body = bytearray()
            deadline = time.monotonic() + TIMEOUT_SECONDS
            while True:
                if time.monotonic() >= deadline:
                    raise CheckError("network_timeout")
                chunk = response.read1(min(65536, MAX_BODY_BYTES + 1 - len(body)))
                if not chunk:
                    break
                body.extend(chunk)
                if len(body) > MAX_BODY_BYTES:
                    raise CheckError("response_too_large")
    except urllib.error.HTTPError as error:
        # Do not read or stringify error bodies, reasons, headers, or URLs.
        status = error.code
        error.close()
        code = ({401: "authentication_failed", 403: "access_denied", 429: "rate_limited"}
                .get(status, "redirect_rejected" if 300 <= status < 400 else "http_error"))
        raise CheckError(code) from None
    except (TimeoutError, ConnectionError, urllib.error.URLError, OSError):
        raise CheckError("network_error") from None
    try:
        document = json.loads(body)
    except (ValueError, UnicodeError):
        raise CheckError("invalid_json") from None
    if not isinstance(document, dict) or document.get("errors"):
        raise CheckError("schema_query_rejected")
    if not isinstance(document.get("data"), dict):
        raise CheckError("invalid_schema")
    return document["data"]


def name(value: object) -> str:
    if not isinstance(value, str) or not NAME.fullmatch(value):
        raise CheckError("invalid_schema")
    return value


def type_ref(value: object, depth: int = 0) -> tuple[str, str]:
    """Validate and format GraphQL names and wrappers, never free-form descriptions."""
    if not isinstance(value, dict) or depth > 6 or value.get("kind") not in KINDS:
        raise CheckError("invalid_schema")
    kind = value["kind"]
    if kind in {"LIST", "NON_NULL"}:
        formatted, base = type_ref(value.get("ofType"), depth + 1)
        return (("[" + formatted + "]") if kind == "LIST" else formatted + "!", base)
    base = name(value.get("name"))
    return base, base


def fields(values: object) -> list[dict]:
    if not isinstance(values, list) or len(values) > 2048:
        raise CheckError("invalid_schema")
    output = []
    for value in values:
        if not isinstance(value, dict):
            raise CheckError("invalid_schema")
        arguments = value.get("args", [])
        if not isinstance(arguments, list) or len(arguments) > 128:
            raise CheckError("invalid_schema")
        args = []
        for argument in arguments:
            if not isinstance(argument, dict):
                raise CheckError("invalid_schema")
            args.append({"name": name(argument.get("name")), "type": type_ref(argument.get("type"))[0]})
        output.append({"name": name(value.get("name")), "type": type_ref(value.get("type"))[0], "args": args})
    return output


def base_type(formatted: str) -> str:
    return formatted.translate(str.maketrans("", "", "[]!"))


TYPE_REF = "kind name"
for _ in range(6):
    TYPE_REF = "kind name ofType { " + TYPE_REF + " }"
FIELD_SELECTION = "name args { name type { " + TYPE_REF + " } } type { " + TYPE_REF + " }"
ROOT_QUERY = ("query NarmaSchemaInspection { __schema { queryType { name fields(includeDeprecated: false) { "
              + FIELD_SELECTION + " } } types { kind name } } }")


def inspect_schema(token: str) -> dict:
    # These are introspection queries only. No root match/player resolver is called.
    initial = graphql(token, ROOT_QUERY)
    schema = initial.get("__schema")
    if not isinstance(schema, dict) or not isinstance(schema.get("queryType"), dict):
        raise CheckError("invalid_schema")
    query_type = schema["queryType"]
    query_name = name(query_type.get("name"))
    root_fields = [field for field in fields(query_type.get("fields")) if RELEVANT.search(field["name"])]
    if not root_fields:
        raise CheckError("relevant_schema_not_found")
    catalog = schema.get("types")
    if not isinstance(catalog, list) or len(catalog) > 10000:
        raise CheckError("invalid_schema")
    named_types = {}
    for entry in catalog:
        if not isinstance(entry, dict) or entry.get("kind") not in KINDS - {"LIST", "NON_NULL"}:
            raise CheckError("invalid_schema")
        named_types[name(entry.get("name"))] = entry["kind"]
    # Root return/argument types first, then related catalog names. Never guess field names.
    candidates = []
    for field in root_fields:
        candidates.append(base_type(field["type"]))
        candidates.extend(base_type(arg["type"]) for arg in field["args"])
    candidates.extend(sorted(entry for entry in named_types if RELEVANT.search(entry)))
    candidates = list(dict.fromkeys(entry for entry in candidates
                                   if named_types.get(entry) in {"OBJECT", "INTERFACE", "INPUT_OBJECT", "ENUM"}))
    selected = candidates[:MAX_TYPES]
    if not selected:
        raise CheckError("relevant_schema_not_found")
    selection = ("kind name fields(includeDeprecated: false) { " + FIELD_SELECTION
                 + " } inputFields { name type { " + TYPE_REF + " } } enumValues { name }")
    query = "query NarmaSchemaInspection { " + " ".join(
        f't{index}: __type(name: "{entry}") {{ {selection} }}' for index, entry in enumerate(selected)
    ) + " }"
    detail = graphql(token, query)
    inspected = []
    for index, expected in enumerate(selected):
        entry = detail.get(f"t{index}")
        if (not isinstance(entry, dict) or entry.get("name") != expected
                or entry.get("kind") != named_types[expected]):
            raise CheckError("invalid_schema")
        kind = entry["kind"]
        type_fields = (fields(entry.get("fields")) if kind in {"OBJECT", "INTERFACE"} else
                       fields(entry.get("inputFields")) if kind == "INPUT_OBJECT" else [])
        enums = entry.get("enumValues") if kind == "ENUM" else []
        if not isinstance(enums, list) or len(enums) > 2048:
            raise CheckError("invalid_schema")
        enum_names = []
        for value in enums:
            if not isinstance(value, dict):
                raise CheckError("invalid_schema")
            enum_names.append(name(value.get("name")))
        inspected.append({"name": expected, "kind": entry["kind"], "fields": type_fields[:MAX_FIELDS],
                          "fields_omitted": max(0, len(type_fields) - MAX_FIELDS),
                          "enum_values": enum_names[:MAX_FIELDS],
                          "enum_values_omitted": max(0, len(enum_names) - MAX_FIELDS)})
    return {"event": "stratz_schema_inspected", "source": "stratz", "configured": True,
            "schema_inspected": True, "popular_builds_ready": False, "match_data_requests": 0,
            "schema_requests": 2, "query_type": query_name, "root_fields": root_fields[:MAX_FIELDS],
            "root_fields_omitted": max(0, len(root_fields) - MAX_FIELDS),
            "types": inspected, "related_types_omitted": max(0, len(candidates) - len(selected))}


def main() -> int:
    token = os.environ.get("STRATZ_API_TOKEN", "").strip()
    if not token:
        print(json.dumps({"event": "source_not_configured", "source": "stratz", "configured": False,
                          "schema_inspected": False, "popular_builds_ready": False}))
        return 0
    try:
        if len(token) > 8192 or not TOKEN.fullmatch(token):
            raise CheckError("invalid_token_format")
        result = inspect_schema(token)
    except CheckError as error:
        code = str(error) if str(error) in ERROR_CODES else "internal_error"
        print(json.dumps({"event": "stratz_preflight_failed", "source": "stratz", "code": code,
                          "schema_inspected": False, "popular_builds_ready": False}).replace(token, "[redacted]"))
        return 1
    except Exception:
        # No traceback: even an unexpected transport exception may contain credentials.
        print(json.dumps({"event": "stratz_preflight_failed", "source": "stratz", "code": "internal_error",
                          "schema_inspected": False, "popular_builds_ready": False}).replace(token, "[redacted]"))
        return 1
    print(json.dumps(result, separators=(",", ":")).replace(token, "[redacted]"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
