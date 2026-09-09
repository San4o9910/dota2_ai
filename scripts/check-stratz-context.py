#!/usr/bin/env python3
"""Compare three narrow public purchase cohorts; log only validated context/counts."""
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'ops/timeweb'))
import check_stratz as check

token=os.environ.get('STRATZ_API_TOKEN','').strip()
try:
    if not token or not check.TOKEN.fullmatch(token):
        raise check.CheckError('invalid_token_format')
    requests=[('low','POSITION_2','HERALD_GUARDIAN'),('high','POSITION_2','DIVINE_IMMORTAL'),('offlane','POSITION_3','HERALD_GUARDIAN')]
    fields='heroId week position bracketBasicIds itemId instance matchCount winCount'
    selections=' '.join(f'{alias}:itemFullPurchase(heroId:47,positionIds:[{position}],bracketBasicIds:[{rank}],minTime:10,maxTime:10,matchLimit:1) {{ {fields} }}' for alias,position,rank in requests)
    data=check.graphql(token,'query NarmaSchemaInspection { heroStats { '+selections+' } }')['heroStats']
    result=[]
    for alias,position,rank in requests:
        rows=data[alias] or []
        contexts=set();sample=[]
        for row in rows:
            contexts.add((row['heroId'],check.name(row['position']) if row.get('position') else None,check.name(row['bracketBasicIds']) if row.get('bracketBasicIds') else None))
            if row['instance']==0 and len(sample)<8:
                if not all(type(row[k]) is int for k in ('itemId','matchCount','winCount')):
                    raise check.CheckError('invalid_schema')
                sample.append({k:row[k] for k in ('itemId','matchCount','winCount')})
        result.append({'requested':{'position':position,'rank':rank},'rows':len(rows),'returned_contexts':sorted(contexts,key=str),'sample':sample})
    print(json.dumps({'event':'stratz_cohort_context_checked','cohorts':result,'provider_requests':1},separators=(',',':')).replace(token,'[redacted]'))
except Exception as exc:
    code=str(exc) if isinstance(exc,check.CheckError) and str(exc) in check.ERROR_CODES else 'internal_error'
    print(json.dumps({'event':'stratz_context_failed','code':code}))
    sys.exit(1)
