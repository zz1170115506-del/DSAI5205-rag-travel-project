import asyncio
import json
from itertools import product

import httpx
import pytest
from fastapi.testclient import TestClient

from app import app
from travel.answers import demo_answer, rag_answer
from travel.config import ROOT, Settings
from travel.knowledge import dataset, places, search
from travel.mcp_client import ToolError, amap_search, local_call, local_session, unpack
from travel.planner import estimate_transfer, plan


def test_dataset_is_linked_and_unique():
    assert len(places()) == len({p['id'] for p in places()}) == 33
    for p in places():
        assert p['source'].startswith('https://')
        assert 'discoverhongkong.com/' in p['source']
        assert p['checked'] in {'2026-10-19','2026-10-22'}
        assert 22 < p['lat'] < 23 and 113 < p['lon'] < 115
        assert p['duration'] > 0
    assert sum(p['checked']=='2026-10-22' for p in places())==12


CASES = json.loads((ROOT/'data/eval_cases.json').read_text())


@pytest.mark.parametrize('case', CASES, ids=[c['question'] for c in CASES])
def test_retrieval_cases(case):
    hits = search(case['question'], limit=3, kind=case.get('kind', 'all'), indoor_only=case.get('indoor_only', False))
    found = {p['id'] for p in hits}
    if case['expected']:
        assert found & set(case['expected'])
    else:
        assert not found


def test_filters_and_empty():
    assert search('   ') == []
    assert all(p['region'] == '九龙' for p in search('博物馆', region='九龙'))
    assert all(p['indoor'] for p in search('雨天', indoor_only=True))
    assert all(p['kind'] == 'food' for p in search('美食', kind='food'))


@pytest.mark.parametrize('days,region,rain,public', list(product([1,2,3], ['全部','香港岛','九龙','大屿山'], [False,True],[False,True])))
def test_plan_constraints(days,region,rain,public):
    try:
        result = plan(days=days,region=region,rain=rain,public_only=public)
    except ValueError:
        assert not any(p['kind'] == 'attraction' and (region == '全部' or p['region'] == region) and (not rain or p['indoor']) and (not public or p['cost'] == 'public') for p in places())
        return
    stops = [s for d in result['days'] for s in d['stops']]
    assert stops
    assert len({s['place']['id'] for s in stops}) == len(stops)
    assert len(result['days']) == days
    for day in result['days']:
        if day['kind']=='flex':
            assert day['stops']==day['legs']==[] and day['activities'] and day['reason']
            continue
        assert len(day['legs']) == len(day['stops'])-1
        assert len({s['place']['cluster'] for s in day['stops']}) == 1
        assert day['end'] <= '23:00'
        for i,s in enumerate(day['stops']):
            assert s['start'] < s['end']
            if i: assert day['stops'][i-1]['end'] <= s['start']
            p=s['place']
            assert region == '全部' or p['region'] == region
            assert not rain or p['indoor']
            assert not public or p['cost'] == 'public' or p['kind'] == 'food'


def test_required_places_and_conflicts():
    result=plan(days=2,must_visit=['peak','tai-o'])
    assert {'peak','tai-o'} <= {s['place']['id'] for d in result['days'] for s in d['stops']}
    with pytest.raises(ValueError, match='冲突'):plan(region='九龙',must_visit=['peak'])
    with pytest.raises(ValueError, match='冲突'):plan(rain=True,must_visit=['peak'])
    with pytest.raises(ValueError, match='天数不足'):plan(days=1,must_visit=['peak','tai-o'])
    with pytest.raises(ValueError):plan(must_visit=['missing'])


def test_transfer_is_honest_about_mountains():
    near=estimate_transfer('hkmoa','avenue-stars')
    far=estimate_transfer('tai-o','big-buddha')
    assert near['mode'] == '步行估算'
    assert far['minutes'] >= 60 and far['mode'] == '山区交通待查'
    assert not far['live']


def test_real_mcp_subprocess_tools():
    async def run():
        async with local_session() as session:
            names={t.name for t in (await session.list_tools()).tools}
            assert names == {'search_places','place_detail','transfer_estimate','plan_itinerary'}
            found=unpack(await session.call_tool('search_places',{'query':'兰芳园'}))
            assert found['results'][0]['id']=='lan-fong-yuen'
            detail=unpack(await session.call_tool('place_detail',{'place_id':'peak'}))
            assert detail['name']=='太平山顶'
            transfer=unpack(await session.call_tool('transfer_estimate',{'origin_id':'hkmoa','destination_id':'avenue-stars'}))
            assert transfer['live'] is False
            result=unpack(await session.call_tool('plan_itinerary',{'days':1,'region':'九龙'}))
            assert result['days']
        with pytest.raises(ToolError,match='冲突'):
            await local_call('plan_itinerary',{'region':'九龙','must_visit':['peak']})
    asyncio.run(run())


def test_model_adapter_and_safe_fallback():
    hits=search('太平山顶',1)
    settings=Settings(model_api_key='test-secret')
    def response(request):
        body=json.loads(request.content)
        assert body['messages'][0]['role']=='system'
        assert 'reference_data' in body['messages'][1]['content']
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'answer':'可从山顶欣赏海港。[peak]','citations':['peak']})}}]})
    result=asyncio.run(rag_answer('山顶能看什么',hits,settings,httpx.MockTransport(response)))
    assert result['mode']=='model' and result['citations']==['peak']
    def invalid(request):
        return httpx.Response(200,json={'choices':[{'message':{'content':'{"answer":"胡编票价 [missing]","citations":["missing"]}'}}]})
    # 此题专测模型返回非法引用；动态信息拦截由独立检查覆盖。
    fallback=asyncio.run(rag_answer('山顶特色',hits,settings,httpx.MockTransport(invalid)))
    assert fallback['mode']=='fallback' and '胡编' not in fallback['text']
    def fails(request):return httpx.Response(429,json={'error':'rate limit'})
    fallback=asyncio.run(rag_answer('山顶',hits,settings,httpx.MockTransport(fails)))
    assert fallback['mode']=='fallback' and 'test-secret' not in json.dumps(fallback)


def test_missing_keys_and_unknown_question():
    result=asyncio.run(amap_search('香港大馆',Settings()))
    assert result['mode']=='not_configured' and result['results'] is None
    assert demo_answer('量子纠缠',[])['citations']==[]
    assert '无法确认' in demo_answer('山顶今天几点开门',search('太平山顶',1))['text']


def test_http_end_to_end():
    with TestClient(app) as client:
        status=client.get('/api/status')
        assert status.status_code==200 and status.json()['place_count']==33
        assert 'api_key' not in status.text
        for url in ['/','/static/style.css','/static/app.js','/static/harbour.svg','/static/icon.svg','/openapi.json']:
            assert client.get(url).status_code==200
        assert client.get('/').headers.get('content-security-policy')
        result=client.post('/api/ask',json={'question':'深水埗有什么小吃？'})
        assert result.status_code==200
        data=result.json()
        assert data['answer']['mode']=='local' and data['sources'][0]['id']=='hop-yik-tai'
        assert data['trace'][0]['transport']=='stdio'
        result=client.post('/api/plan',json={'days':2})
        assert result.status_code==200 and len(result.json()['days'])==2
        assert client.post('/api/plan',json={'region':'九龙','must_visit':['peak']}).status_code==422
        assert client.post('/api/plan',json={'days':367}).status_code==422
        assert client.post('/api/ask',json={'question':'  '}).status_code==422
        assert client.post('/api/ask',json={'question':'香港去哪玩'},headers={'Origin':'https://example.org'}).status_code==403
        assert client.post('/api/amap/search',json={'place_id':'peak'}).json()['mode']=='not_configured'
