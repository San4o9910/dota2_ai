"""Offline endpoint/cache tests; no provider calls or accounts."""
from copy import deepcopy
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from narma_video import build_meta, explore
from narma_video.build_statistics import GUIDES, SourceError

NOW=datetime(2026,9,9,12,tzinfo=timezone.utc).timestamp()
KEY=('viper-mid-pressure','HERALD_GUARDIAN')


@pytest.fixture
def setup(monkeypatch,tmp_path):
    monkeypatch.setenv('NARMA_BUILD_STATS_SOURCE','stratz')
    monkeypatch.setenv('STRATZ_API_TOKEN','synthetic.test')
    monkeypatch.setenv('NARMA_STRATZ_REFRESH_ENABLED','0')
    monkeypatch.setattr(explore,'get_payload',lambda kind:{'stale':False,'errors':[],
        'latest_patch':{'version':'7.41e','published_at':'2026-07-30T07:00:00Z'}})
    guide=GUIDES[KEY[0]]
    slugs=list(dict.fromkeys(i['id'] for k in ('core_items','situational_items','final_items') for i in guide[k]))
    raw_items=[{'id':i,'name':'item_'+slug,'displayName':slug,'stat':{'cost':2000,'isRecipe':False,'isPurchasable':True},'components':None} for i,slug in enumerate(slugs,1)]
    rows=[{'heroId':47,'week':2957,'position':'POSITION_2','bracketBasicIds':KEY[1],
        'itemId':i,'instance':0,'time':20,'matchCount':200,'winCount':120} for i in range(1,len(slugs)+1)]
    calls=[]
    def fetch(token,query,operation,variables=None):
        calls.append(operation)
        if operation=='NarmaBuildCatalog':
            return {'constants':{'items':raw_items,'gameVersions':[{'name':'7.40b','asOfDateTime':1766534400}]}}
        return {'heroStats':{'itemFullPurchase':deepcopy(rows)}}
    cache=build_meta.BuildCache(tmp_path/'snapshot.json',fetch=fetch,now=lambda:NOW)
    return cache,calls


def test_refresh_normalizes_public_evidence_and_persists_without_credentials(setup):
    cache,calls=setup
    cache.refresh(KEY)
    result=cache.get(*KEY)
    assert result['status']=='ready'
    assert result['joint_build_winrate'] is None
    assert len(result['plans']['popular'])==6
    assert len(result['plans']['winrate'])==6
    assert 'synthetic.test' not in cache.path.read_text()
    assert calls==['NarmaBuildCatalog','NarmaBuildPurchases']
    restored=build_meta.BuildCache(cache.path,now=lambda:NOW)
    assert restored.get(*KEY)['items']==result['items']


def test_source_failure_and_expiry_preserve_dated_evidence(setup):
    cache,_=setup;cache.refresh(KEY)
    before=deepcopy(cache.data[KEY])
    def fail(*args):raise SourceError('source_unavailable')
    cache.fetch=fail
    with pytest.raises(SourceError):cache.refresh(KEY)
    assert cache.data[KEY]==before
    cache.now=lambda:NOW+7201
    result=cache.get(*KEY)
    assert result['status']=='stale'
    assert result['items'] and result['checked_at']
    assert not result['plans']


@pytest.mark.parametrize('patch,when,status',[
    ('7.42','2026-09-09T10:00:00Z','transition'),
    ('7.42','2026-08-20T10:00:00Z','pool_review')])
def test_new_patch_withholds_old_suggestions(setup,monkeypatch,patch,when,status):
    cache,_=setup;cache.refresh(KEY)
    monkeypatch.setattr(explore,'get_payload',lambda kind:{'stale':False,'errors':[],
        'latest_patch':{'version':patch,'published_at':when}})
    result=cache.get(*KEY)
    assert result['patch_status']==status
    assert not result['plans']
    assert result['items']


def test_public_endpoint_cannot_create_arbitrary_upstream_queries(setup,monkeypatch):
    cache,calls=setup
    monkeypatch.setattr(build_meta,'cache',cache)
    app=FastAPI();app.include_router(build_meta.router)
    with TestClient(app) as client:
        assert client.get('/api/explore/builds',params={'guide':KEY[0],'rank':KEY[1]}).status_code==200
        for query in ({'guide':'https://evil.test','rank':KEY[1]}, {'guide':KEY[0],'rank':'IMMORTAL) { secret }'}):
            assert client.get('/api/explore/builds',params=query).status_code==422
    assert calls==[]


def test_disabled_worker_has_no_network_side_effects(setup,monkeypatch):
    cache,calls=setup
    monkeypatch.delenv('STRATZ_API_TOKEN')
    cache.start()
    assert cache.thread is None
    assert not calls
    assert cache.get(*KEY)['status']=='unavailable'


def test_authored_mode_never_uses_credential_or_saved_provider_evidence(setup,monkeypatch):
    cache,calls=setup
    cache.refresh(KEY)
    calls.clear()
    monkeypatch.setenv('NARMA_BUILD_STATS_SOURCE','authored')
    monkeypatch.setenv('NARMA_STRATZ_REFRESH_ENABLED','1')
    cache.start()
    assert cache.thread is None
    result=cache.get(*KEY)
    assert result['source']==result['status']=='authored'
    assert result['items']==result['plans']=={}
    assert result['joint_build_winrate'] is None
    assert 'checked_at' not in result and 'source_url' not in result
    with pytest.raises(SourceError,match='configuration'):
        cache.refresh(KEY)
    assert calls==[]


def test_authored_is_default_even_with_a_provider_token(setup,monkeypatch):
    cache,calls=setup
    monkeypatch.delenv('NARMA_BUILD_STATS_SOURCE')
    monkeypatch.setenv('NARMA_STRATZ_REFRESH_ENABLED','1')
    cache.start()
    assert cache.thread is None
    assert cache.get(*KEY)['status']=='authored'
    assert calls==[]


@pytest.mark.parametrize('code',['access_denied','authentication_failed','configuration'])
def test_permission_failure_stops_the_worker_without_automatic_retry(setup,code):
    cache,_=setup
    calls=[]
    def reject(*args):
        calls.append(True)
        raise SourceError(code)
    cache.fetch=reject
    cache.run()
    assert len(calls)==1
    assert cache.blocked
    assert cache.get(*KEY)['status']=='unavailable'


@pytest.mark.parametrize('status',[200,403])
def test_documented_client_header_and_no_retry_on_access_denial(monkeypatch,status):
    calls=[]
    original=httpx.Client
    def handler(request):
        calls.append(request)
        assert str(request.url)=='https://api.stratz.com/graphql'
        assert request.headers['User-Agent']=='STRATZ_API'
        assert request.headers['Authorization']=='Bearer synthetic.test'
        return httpx.Response(status,json={'data':{'ok':True}})
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return original(transport=httpx.MockTransport(handler),**kwargs)
    monkeypatch.setattr(build_meta.httpx,'Client',client)
    if status==200:
        assert build_meta.graphql('synthetic.test','query NarmaTest { __typename }','NarmaTest')=={'ok':True}
    else:
        with pytest.raises(SourceError,match='^access_denied$'):
            build_meta.graphql('synthetic.test','query NarmaTest { __typename }','NarmaTest')
    assert len(calls)==1
