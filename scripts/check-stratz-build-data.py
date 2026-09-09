#!/usr/bin/env python3
"""Check bounded public aggregate samples. Never request account identities."""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ops" / "timeweb"))
import check_stratz as check


def inspect(token):
    # All selected fields and enum values were confirmed through authorized introspection.
    query = '''query NarmaSchemaInspection {
      constants { gameVersions { id name asOfDateTime }
        items(language:ENGLISH) { id name displayName shortName stat { cost isRecipe isPurchasable } components { componentId } }
      }
      heroStats { itemFullPurchase(heroId:47,positionIds:[POSITION_2],bracketBasicIds:[HERALD_GUARDIAN],minTime:0,maxTime:75,matchLimit:1) {
        heroId week bracketBasicIds position itemId instance time matchCount winCount winsAverage
      } }
      live { matches(request:{isCompleted:true,isLeague:false,take:5,skip:0,orderBy:MATCH_ID}) {
        matchId completed averageRank
      } }
      itemSchema: __type(name:"ItemType") { name fields { name type { %s } } }
      statsSchema: __type(name:"HeroStatsQuery") { fields { name description args { name description defaultValue } } }
      itemStatSchema: __type(name:"ItemStatType") { fields { name type { %s } } }
      itemLanguageSchema: __type(name:"ItemLanguageType") { fields { name type { %s } } }
      itemComponentSchema: __type(name:"ItemComponentType") { fields { name type { %s } } }
      purchaseSchema: __type(name:"HeroItemPurchaseType") { fields { name description } }
    }''' % (check.TYPE_REF, check.TYPE_REF, check.TYPE_REF, check.TYPE_REF)
    data = check.graphql(token, query)
    rows = data["heroStats"]["itemFullPurchase"] or []
    if not isinstance(rows, list) or len(rows) > 10000:
        raise check.CheckError("invalid_schema")
    clean = []
    for r in rows:
        if any(not isinstance(r.get(k), (int, float)) or isinstance(r.get(k), bool)
               for k in ("heroId", "week", "itemId", "instance", "matchCount", "winCount")):
            raise check.CheckError("invalid_schema")
        clean.append({k:r[k] for k in ("heroId","week","itemId","instance","time","matchCount","winCount")})
    versions = []
    for v in data["constants"]["gameVersions"] or []:
        if isinstance(v.get("name"), str) and len(v["name"]) < 40 and all(
                isinstance(v.get(k), int) for k in ("id","asOfDateTime")):
            versions.append({k:v[k] for k in ("id","name","asOfDateTime")})
    matches = []
    for r in data["live"]["matches"] or []:
        if isinstance(r.get("matchId"), int) and r.get("completed") is True:
            matches.append({k:r[k] for k in ("matchId","completed","averageRank")})
    return {"event":"stratz_build_data_checked", "aggregate_rows":len(clean),
            "weeks":sorted({r["week"] for r in clean}), "instances":sorted({r["instance"] for r in clean}),
            "top_rows":sorted(clean,key=lambda r:r["matchCount"],reverse=True)[:20],
            "recent_versions":sorted(versions,key=lambda v:v["asOfDateTime"],reverse=True)[:8],
            "completed_public_matches":matches, "item_fields":check.fields(data["itemSchema"]["fields"]),
            "item_stat_fields":check.fields(data["itemStatSchema"]["fields"]),
            "item_language_fields":check.fields(data["itemLanguageSchema"]["fields"]),
            "item_component_fields":check.fields(data["itemComponentSchema"]["fields"]),
            "purchase_documentation":[r for r in data["statsSchema"]["fields"] if r["name"] in {"stats","itemFullPurchase"}],
            "purchase_field_documentation":data["purchaseSchema"]["fields"],
            "item_examples":[r for r in data["constants"]["items"] if r["id"] in {63,75,108,236}],
            "provider_requests":1, "private_account_requests":0}


if __name__ == "__main__":
    token = os.environ.get("STRATZ_API_TOKEN", "").strip()
    try:
        if not token or len(token)>8192 or not check.TOKEN.fullmatch(token):
            raise check.CheckError("invalid_token_format")
        result=inspect(token)
    except Exception as exc:
        code=str(exc) if isinstance(exc,check.CheckError) and str(exc) in check.ERROR_CODES else "internal_error"
        print(json.dumps({"event":"stratz_build_data_failed","code":code}))
        sys.exit(1)
    print(json.dumps(result,separators=(",",":")).replace(token,"[redacted]"))
