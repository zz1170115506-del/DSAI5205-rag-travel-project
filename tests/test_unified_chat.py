"""Local history + real stdio; maps are HTTP fixtures, never real AMap verification."""
import asyncio
import base64
import json

import httpx
import pytest
from fastapi.testclient import TestClient

import app
from travel import chat
from travel.config import Settings
from travel.history import HistoryStore
from travel.maps import resolve_place, route_map, search_map
from travel.retrieval import retrieve


@pytest.fixture
def web(tmp_path, monkeypatch):
    monkeypatch.setattr(chat, 'store', HistoryStore(tmp_path/'history.sqlite3'))
    monkeypatch.setattr(chat, 'locks', {})
    with TestClient(app.app) as client:
        yield client


def test_unified_plan_followup_persists_across_client_restart(web):
    first=web.post('/api/chat',json={'question':'带父母九龙一天，少走路，安排行程'}).json()
    cid=first['conversation_id']
    assert first['plan'] and first['trip']['region']=='九龙'
    # New HTTP client / new AgentEngine: only the SQLite checkpoint can carry memory.
    with TestClient(app.app) as other:
        second=other.post('/api/chat',json={'question':'改成只选室内','conversation_id':cid}).json()
    assert second['trip']['days']==1 and second['trip']['region']=='九龙' and second['trip']['rain']
    assert second['plan'] and all(s['place']['indoor'] for d in second['plan']['days'] for s in d['stops'])
    saved=web.post('/api/history/read',json={'id':cid}).json()
    assert len(saved['turns'])==2 and 'session_id' not in json.dumps(saved)
    assert web.get('/api/history').json()['conversations'][0]['id']==cid
    assert web.post('/api/history/delete',json={'id':cid}).json()['deleted']
    assert web.post('/api/history/read',json={'id':cid}).status_code==404


def test_question_after_plan_is_search_and_has_retrieval_trace(web):
    first=web.post('/api/chat',json={'question':'九龙一天行程'}).json()
    second=web.post('/api/chat',json={'question':'香港科学馆有什么特色？','conversation_id':first['conversation_id']}).json()
    assert second['plan'] is None
    assert 'science-museum' in {p['id'] for p in second['sources']}
    assert second['trace'][0]['retrieval']['recall']=='SQLite FTS5 BM25'


def test_trip_form_and_text_revision_share_one_conversation(web):
    r=web.post('/api/chat',json={'question':'请按偏好安排行程','trip':{'days':2,'region':'香港岛','pace':'充实','interests':['文化艺术'],'rain':False,'public_only':False,'must_visit':['blue-house']}})
    assert r.status_code==200
    obj=r.json()
    assert obj['trip']['days']==2 and 'blue-house' in {s['place']['id'] for d in obj['plan']['days'] for s in d['stops']}


def test_unknown_place_is_explicit_not_configured_not_fake(web):
    r=web.post('/api/places/resolve',json={'query':'虚构的测试犄角巷'}).json()
    assert r['mode']=='not_configured' and not r['external_requested'] and r['results']==[]
    result=web.post('/api/chat',json={'question':'虚构的测试犄角巷在哪里？'}).json()
    assert result['external_lookup']['mode']=='not_configured'
    assert not result['sources'] and result['answer']['mode']=='map_lookup'
    route=web.post('/api/amap/route',json={'place_ids':['tai-kwun','pmq']}).json()
    assert route['mode']=='not_configured' and route['map_image'] is None


def test_local_resolve_never_calls_map(monkeypatch):
    def forbidden(req):pytest.fail('local hit must not call AMap')
    result=asyncio.run(resolve_place('蓝屋',Settings(amap_api_key='fixture'),httpx.MockTransport(forbidden)))
    assert result['mode']=='local' and not result['external_requested']


def test_external_poi_schema_provenance_and_hk_filter():
    def handler(req):
        assert req.url.host=='restapi.amap.com' and req.url.params['citylimit']=='true'
        return httpx.Response(200,json={'status':'1','pois':[
            {'id':'A1','name':'小巷公园','location':'114.17,22.3','address':'测试街1号','cityname':'香港','type':'公园'},
            {'id':'A2','name':'同名外地公园','location':'114.17,22.3','cityname':'深圳'},
            {'id':'A3','name':'错误坐标','location':'NaN,NaN','cityname':'香港'}]})
    result=asyncio.run(resolve_place('小巷公园',Settings(amap_api_key='fixture-secret'),httpx.MockTransport(handler)))
    assert result['mode']=='live' and len(result['results'])==1
    p=result['results'][0]
    assert p['provider']=='amap' and p['source']['fetched_at'] and not p['curated_knowledge']
    assert p['review_status']=='external_unreviewed' and p['coordinate_system'].startswith('GCJ')
    assert 'fixture-secret' not in json.dumps(result)


@pytest.mark.parametrize('status,body',[(200,{'status':'0','info':'fixture-secret'}),(401,{}),(200,{'status':'1','pois':[]})])
def test_map_errors_and_empty_are_distinct(status,body):
    def handler(req):return httpx.Response(status,json=body)
    result=asyncio.run(search_map('小巷',Settings(amap_api_key='fixture-secret'),httpx.MockTransport(handler)))
    assert result['mode']==('empty' if body.get('status')=='1' else 'unavailable')
    assert 'fixture-secret' not in json.dumps(result)


def test_real_route_contract_uses_resolved_coordinates_not_local_sketch():
    names=['大馆','元创方 PMQ']
    poi_count=0
    image=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j4l8AAAAASUVORK5CYII=')
    def handler(req):
        nonlocal poi_count
        if req.url.path=='/v3/place/text':
            i=poi_count;poi_count+=1
            return httpx.Response(200,json={'status':'1','pois':[{'id':str(i),'name':names[i],'cityname':'香港','location':['114.16,22.28','114.15,22.29'][i]}]})
        if req.url.path=='/v3/direction/walking':
            assert req.url.params['origin']=='114.16,22.28'
            return httpx.Response(200,json={'status':'1','route':{'paths':[{'distance':'900','duration':'700','steps':[{'polyline':'114.16,22.28;114.155,22.285;114.15,22.29'}]}]}})
        assert req.url.path=='/v3/staticmap'
        return httpx.Response(200,content=image,headers={'Content-Type':'image/png'})
    result=asyncio.run(route_map(['tai-kwun','pmq'],Settings(amap_api_key='fixture-secret'),httpx.MockTransport(handler)))
    assert result['mode']=='live' and result['distance_m']==900 and result['duration_s']==700
    assert result['map_image'].startswith('data:image/png;base64,') and result['polylines'][0][0]==[114.16,22.28]
    assert 'fixture-secret' not in json.dumps(result)


def test_ambiguous_map_location_does_not_guess_route():
    def handler(req):return httpx.Response(200,json={'status':'1','pois':[]})
    result=asyncio.run(route_map(['tai-kwun','pmq'],Settings(amap_api_key='fixture'),httpx.MockTransport(handler)))
    assert result['mode']=='ambiguous_location' and not result['polylines']


def test_history_capacity_and_no_arbitrary_file_paths(tmp_path):
    store=HistoryStore(tmp_path/'local.sqlite3',capacity=1)
    cid=store.save(None,[],{},False,'安全标题')
    assert HistoryStore(store.path).get(cid)['title']=='安全标题'
    with pytest.raises(ValueError):store.save(None,[],{},False,'第二段')
    store.delete(cid)
    assert store.list()==[]


def test_history_and_chat_validate_ids(web):
    assert web.post('/api/history/read',json={'id':'../../.env'}).status_code==422
    assert web.post('/api/chat',json={'question':'香港','conversation_id':'a'*32}).status_code==404
    assert web.post('/api/chat',json={'question':'香港','use_model':True}).status_code==422
    assert web.get('/api/history').headers['cache-control']=='no-store'


def test_explicit_amap_disable_switch_overrides_available_key(monkeypatch):
    monkeypatch.setenv('AMAP_API_KEY','fixture-present-but-disabled')
    monkeypatch.setenv('AMAP_ENABLED','false')
    assert not Settings.from_env().amap_api_key
    assert not Settings.from_env().amap_enabled
    assert Settings.from_env().amap_key_present


def test_disabled_map_is_distinct_and_offers_safe_search_links():
    def forbidden(req):pytest.fail('disabled must never call provider')
    settings=Settings(amap_enabled=False,amap_api_key='fixture-disabled-secret')
    result=asyncio.run(resolve_place('鹤咀海岸保护区',settings,httpx.MockTransport(forbidden)))
    assert result['mode']=='disabled' and not result['external_requested']
    assert result['results']==[] and '未启用' in result['message']
    assert result['search_links'][0]['url'].startswith('https://uri.amap.com/search?')
    assert 'fixture-disabled-secret' not in json.dumps(result)
    route=asyncio.run(route_map(['tai-kwun','pmq'],settings,httpx.MockTransport(forbidden)))
    assert route['mode']=='disabled' and not route['polylines']


def test_map_headers_allow_tiles_keep_private_default_referrer(web):
    response=web.get('/')
    assert 'https://tile.openstreetmap.org' in response.headers['content-security-policy']
    assert "script-src 'self';" in response.headers['content-security-policy']
    assert response.headers['referrer-policy']=='no-referrer'
    assert '/static/vendor/leaflet/leaflet.js' in response.text


def test_rerank_filters_and_feature_explanation():
    result=retrieve('蓝屋',5)
    assert result['results'][0]['id']=='blue-house'
    assert result['results'][0]['ranking_features']['name_match']
    assert result['retrieval']['candidate_count']>=result['retrieval']['returned_count']
    assert not retrieve('qzxy987无匹配',5)['results']
    assert all(p['region']=='九龙' and p['indoor'] for p in retrieve('博物馆',5,'九龙',True)['results'])
