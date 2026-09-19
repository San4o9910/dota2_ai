"""Passive post-release check: exact public assets and anonymous access boundary."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

ASSETS=('human-coach.js','human-coach.css','portal.js','player-profile.js')

def verify(origin):
    root=Path(__file__).resolve().parents[2]/'services/video/narma_video/static'
    for name in ASSETS:
        with urlopen(origin+'/assets/'+name,timeout=30) as response:
            actual=response.read(2*1024*1024)
        if hashlib.sha256(actual).digest()!=hashlib.sha256((root/name).read_bytes()).digest():
            raise RuntimeError('Published asset does not match release: '+name)
    with urlopen(origin+'/human-coach',timeout=30) as response:
        if b'id="human-coach"' not in response.read(2*1024*1024):
            raise RuntimeError('Human coaching page missing')
    try:
        with urlopen(origin+'/api/human-coach',timeout=30):
            raise RuntimeError('Private coaching API admitted anonymous request')
    except HTTPError as error:
        if error.code!=401 or error.headers.get('Cache-Control')!='no-store':
            raise RuntimeError('Private coaching API boundary failed') from None
    return {'event':'human_coaching_release_verified','exact_assets':list(ASSETS),'anonymous_status':401,'provider_calls_created':0}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--origin',required=True)
    print(json.dumps(verify(parser.parse_args().origin.rstrip('/'))))
