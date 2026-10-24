"""Unified library fallback; provider behavior here uses HTTP fixtures only."""
import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

import app
from travel.config import Settings
from travel.place_search import search_library, poi_region
from travel import place_search


def test_local_hit_and_empty_browse_never_request_amap():
    def forbidden(req):pytest.fail('local results must not request AMap')
    for q in ['蓝屋','文化艺术','']:
        result=asyncio.run(search_library(q,'全部',Settings(amap_api_key='fixture'),httpx.MockTransport(forbidden)))
        assert result['mode']=='local' and result['results']
        assert not result['external_requested'] and not result['local_miss']


def test_local_result_outside_selected_region_does_not_mean_database_miss():
    def forbidden(req):pytest.fail('region filter must not cause unnecessary external fallback')
    result=asyncio.run(search_library('蓝屋','九龙',Settings(amap_api_key='fixture'),httpx.MockTransport(forbidden)))
    assert result['mode']=='filtered_local' and not result['results']
    assert result['local_match'] and not result['local_miss'] and not result['external_requested']


def test_unknown_query_automatically_calls_provider_once_and_preserves_json_source():
    calls=[]
    def handler(req):
        calls.append(req)
        assert req.url.host=='restapi.amap.com' and req.url.params['keywords']=='COA'
        return httpx.Response(200,json={'status':'1','pois':[{'id':'A1','name':'COA','location':'114.15,22.28','cityname':'香港','adname':'中西区','address':'测试地址','type':'餐饮服务'}]})
    result=asyncio.run(search_library('COA','全部',Settings(amap_api_key='fixture-secret'),httpx.MockTransport(handler)))
    assert len(calls)==1 and result['mode']=='live' and result['local_miss']
    assert result['external_requested'] and result['local_count']==0
    p=result['results'][0]
    assert p['source']['fetched_at'] and p['provider']=='amap' and not p['curated_knowledge']
    assert p['review_status']=='external_unreviewed' and 'fixture-secret' not in json.dumps(result)


@pytest.mark.parametrize('region,expected',[('香港岛','live'),('九龙','filtered_external'),('大屿山','filtered_external')])
def test_external_results_obey_region_without_mislabelling_islands(region,expected):
    def handler(req):return httpx.Response(200,json={'status':'1','pois':[{'id':'A1','name':'COA','location':'114.15,22.28','cityname':'香港','adname':'中西区'}]})
    result=asyncio.run(search_library('COA',region,Settings(amap_api_key='fixture'),httpx.MockTransport(handler)))
    assert result['mode']==expected
    assert bool(result['results'])==(expected=='live')
    assert poi_region({'district':'离岛区','name':'长洲某店'}) is None
    assert poi_region({'district':'離島區','name':'东涌某店'})=='大屿山'


@pytest.mark.parametrize('mode',['empty','unavailable','disabled','not_configured'])
def test_miss_with_provider_failure_never_fakes_local_or_map_results(mode):
    def handler(req):
        return httpx.Response(200,json={'status':'1','pois':[]} if mode=='empty' else {'status':'0','info':'fixture-secret'})
    cfg=Settings(amap_api_key='' if mode=='not_configured' else 'fixture-secret',amap_enabled=mode!='disabled')
    result=asyncio.run(search_library('COA','全部',cfg,httpx.MockTransport(handler)))
    assert result['mode']==mode and result['local_miss'] and result['results']==[]
    assert 'fixture-secret' not in json.dumps(result)
    assert result['external_requested']==(mode in {'empty','unavailable'})


def test_single_search_api_fallback_and_input_validation(monkeypatch):
    calls=[]
    async def fake_resolve(query,cfg,http_transport=None):
        calls.append(query)
        return {'mode':'empty','provider':'amap','results':[],'query':query,'external_requested':True,'message':'高德暂无结果'}
    monkeypatch.setattr(place_search,'resolve_place',fake_resolve)
    with TestClient(app.app) as web:
        assert web.post('/api/places/search',json={'query':'蓝屋'}).json()['mode']=='local'
        r=web.post('/api/places/search',json={'query':'COA'}).json()
        assert r['local_miss'] and r['external_requested'] and calls==['COA']
        assert web.post('/api/places/search',json={'query':'c'}).status_code==422
        assert web.post('/api/places/search',json={'query':'a'*101}).status_code==422
        assert web.post('/api/places/search',json={'query':'COA','region':'深圳'}).status_code==422
        html=web.get('/').text
        assert 'id="library-search-form"' in html and 'id="resolve-form"' not in html
