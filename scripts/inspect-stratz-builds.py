#!/usr/bin/env python3
"""Bounded read-only schema discovery for the build adapter; no match queries."""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ops" / "timeweb"))
import check_stratz as check


def inspect(token):
    initial = check.graphql(token, check.ROOT_QUERY)["__schema"]
    roots = check.fields(initial["queryType"]["fields"])
    catalog = {check.name(t["name"]): t["kind"] for t in initial["types"]}
    # Names below were observed in the authorized 2026-09-09 schema inspection.
    pending = ["HeroStatsQuery", "HeroItemPurchaseType", "HeroGuideListType",
               "RankBracketBasicEnum", "MatchPlayerPositionType", "HeroPositionTimeDetailType",
               "RankBracket", "HeroWinGameVersionType", "FilterHeroWinRequestGroupBy",
               "MatchPlayerType", "PlayerMatchesRequestType"]
    for field in roots:
        if field["name"] in {"constants", "live", "league", "leagues"}:
            pending.append(check.base_type(field["type"]))
    seen = set()
    output = []
    requests = 1
    for _ in range(3):
        selected = list(dict.fromkeys(n for n in pending if n not in seen
                        and catalog.get(n) in {"OBJECT", "INPUT_OBJECT", "ENUM"}))[:24]
        if not selected:
            break
        selection = ("kind name fields(includeDeprecated: false) { " + check.FIELD_SELECTION
                     + " } inputFields { name type { " + check.TYPE_REF + " } } enumValues { name }")
        query = "query NarmaSchemaInspection { " + " ".join(
            f't{i}: __type(name: "{name}") {{ {selection} }}' for i, name in enumerate(selected)) + " }"
        data = check.graphql(token, query)
        requests += 1
        pending = []
        for i, expected in enumerate(selected):
            row = data[f"t{i}"]
            if row["name"] != expected or row["kind"] != catalog[expected]:
                raise check.CheckError("invalid_schema")
            seen.add(expected)
            fields = check.fields(row.get("fields") or row.get("inputFields") or [])
            enums = [check.name(e["name"]) for e in row.get("enumValues") or []]
            output.append({"name": expected, "kind": row["kind"], "fields": fields[:160],
                           "fields_omitted": max(0, len(fields)-160), "enum_values": enums[:96]})
            if expected != "MatchPlayerType":
                for field in fields:
                    base = check.base_type(field["type"])
                    if catalog.get(base) in {"INPUT_OBJECT", "ENUM"} or any(
                            s in base for s in ("ItemPurchase", "Guide", "GameVersion", "Constants", "Live")):
                        pending.append(base)
                    pending.extend(check.base_type(a["type"]) for a in field["args"])
    return {"event": "stratz_build_schema", "root_fields": roots, "types": output,
            "schema_requests": requests, "match_data_requests": 0}


if __name__ == "__main__":
    token = os.environ.get("STRATZ_API_TOKEN", "").strip()
    try:
        if not token or len(token) > 8192 or not check.TOKEN.fullmatch(token):
            raise check.CheckError("invalid_token_format")
        result = inspect(token)
    except Exception as exc:
        code = str(exc) if isinstance(exc, check.CheckError) and str(exc) in check.ERROR_CODES else "internal_error"
        print(json.dumps({"event": "stratz_build_schema_failed", "code": code}))
        sys.exit(1)
    print(json.dumps(result, separators=(",", ":")).replace(token, "[redacted]"))
