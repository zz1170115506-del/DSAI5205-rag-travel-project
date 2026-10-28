"""Regression scenarios for relative edits, category precision and map routing.

Cloud responses are fixtures; these tests make no model or map API requests.
"""
import asyncio
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

import app
from travel import chat, retrieval, map_rag
from travel.agent import AgentEngine, Trip
from travel.config import RetrievalSettings, Settings
from travel.history import HistoryStore
from travel.knowledge import get_place
from travel.map_rag import prepare_evidence
from travel.maps import search_map
from travel.place_intent import category_search, requested_category, matches_category
from travel.place_search import search_library
from travel.trip_dates import parse_day_change
from tests.test_agent import fixture_tool
from tests.test_map_rag import external, result, model_response
from tests.test_model_conversation import call, final, engine_with


def test_relative_edits_keep_calendar_and_other_preferences():
    async def scenario():
        engine = AgentEngine(tool_call=fixture_tool)
        first = await engine.turn('relative', '安排2026-10-24至2026-10-26的3天行程',
                                  Trip(region='九龙', interests=['文化艺术'], pace='充实').model_dump())
        added = await engine.turn('relative', '再多加一天')
        assert added['trip']['days'] == len(added['plan']['days']) == 4
        assert added['trip']['start_date'] == '2026-10-24'
        assert added['trip']['end_date'] == '2026-10-27'
        assert added['trip']['region'] == first['trip']['region'] == '九龙'
        assert added['trip']['interests'] == first['trip']['interests']
        reduced = await engine.turn('relative', '少玩两天')
        assert reduced['trip']['days'] == 2 and reduced['trip']['end_date'] == '2026-10-25'
        absolute = await engine.turn('relative', '改成一天')
        assert absolute['trip']['days'] == len(absolute['plan']['days']) == 1
        assert absolute['trip']['end_date'] == '2026-10-24'
    asyncio.run(scenario())


@pytest.mark.parametrize('days,question', [(None, '再加一天'), (1, '少玩一天'), (366, '再加一天')])
def test_invalid_relative_edits_clarify_without_overwriting_trip(days, question):
    async def scenario():
        engine = AgentEngine(tool_call=fixture_tool)
        trip = Trip(days=days, region='九龙').model_dump()
        answer = await engine.turn('invalid-relative', question, trip)
        assert answer['trip'] == trip and answer['plan'] is None
        assert answer['answer']['kind'] == 'clarify'
        assert answer['stop_reason'] == 'clarify_days' and not answer['trace']
    asyncio.run(scenario())


@pytest.mark.parametrize('question', ['第二天去哪里', '第23天去哪里', '第 二十三天去哪里'])
def test_ordinal_day_is_not_a_total_duration(question):
    assert parse_day_change(question) is None


def test_model_bad_absolute_edit_is_rejected_then_relative_edit_succeeds():
    queue = [call('update_trip', changes={'days': 1}),
             call('update_trip', day_change={'operation': 'increase', 'amount': 1}),
             call('plan_itinerary'), final()]
    engine = engine_with(queue, [])
    answer = asyncio.run(engine.turn('model-relative', '再多加一天', Trip(days=3).model_dump()))
    assert answer['trip']['days'] == len(answer['plan']['days']) == 4
    assert answer['trace'][0]['status'] == 'error'
    assert '增减' in answer['trace'][0]['message']
    assert answer['trace'][1]['status'] == 'success'


def test_repeated_model_increment_does_not_add_twice():
    edit = call('update_trip', day_change={'operation': 'increase', 'amount': 1})
    engine = engine_with([deepcopy(edit), deepcopy(edit), call('plan_itinerary'), final()], [])
    answer = asyncio.run(engine.turn('repeat-relative', '再加一天', Trip(days=3).model_dump()))
    assert answer['trip']['days'] == len(answer['plan']['days']) == 4


def test_model_absolute_request_cannot_be_applied_as_an_increment():
    queue = [call('update_trip', day_change={'operation':'increase','amount':1}),
             call('update_trip', changes={'days':1}), call('plan_itinerary'), final()]
    answer = asyncio.run(engine_with(queue, []).turn('absolute', '改成一天', Trip(days=3).model_dump()))
    assert answer['trace'][0]['status'] == 'error'
    assert answer['trip']['days'] == len(answer['plan']['days']) == 1


def test_model_relative_edit_without_baseline_cannot_create_a_one_day_trip():
    engine = engine_with([call('update_trip', day_change={'operation': 'increase', 'amount': 1}),
                          final('原本打算玩几天？', 'clarify')], [])
    answer = asyncio.run(engine.turn('missing-baseline', '再加一天'))
    assert answer['trip']['days'] is None and not answer['plan']
    assert answer['trace'][0]['status'] == 'error' and answer['answer']['kind'] == 'clarify'


def mall(name='测试商场'):
    return {**get_place('pmq'), 'name': name, 'category': 'mall'}


def test_hybrid_similarity_cannot_turn_museums_or_shopping_streets_into_malls(monkeypatch):
    monkeypatch.setattr(retrieval, 'semantic_search', lambda *a, **kw: [
        {**get_place('science-museum'), 'semantic_score': .99},
        {**get_place('pmq'), 'semantic_score': .98}])
    found = retrieval.retrieve('香港有哪些商场', settings=RetrievalSettings(mode='hybrid'))
    assert found['retrieval']['embedding_used'] and found['results'] == []


def test_model_cannot_reuse_museum_from_previous_plan_as_a_mall():
    queue = [call('search_places', query='文化艺术'),
             final('推荐科学馆 [science-museum]。', 'answer', ['science-museum'])]
    engine = engine_with(queue, [])
    async def scenario():
        await engine.graph.aupdate_state({'configurable': {'thread_id': 'category'}},
            {'trip': Trip(days=3, must_visit=['science-museum']).model_dump()}, as_node='finish')
        answer = await engine.turn('category', '推荐商场')
        assert not answer['sources'] and not answer['answer']['citations']
        assert not answer['answer']['model_output_accepted']
        assert answer['trace'][0]['arguments']['query'] == '推荐商场'
        assert answer['trace'][0]['status'] == 'empty'
    asyncio.run(scenario())


@pytest.mark.parametrize('question,category,broad', [
    ('香港有哪些商场', 'mall', True), ('九龍有哪些購物中心', 'mall', True),
    ('recommend shopping malls', 'mall', True), ('K11商场在哪', 'mall', False),
    ('K11商场', 'mall', False), ('不要博物馆，推荐商场', 'mall', True),
    ('不要商场', None, False)])
def test_category_intent_preserves_named_queries_and_negation(question, category, broad):
    assert requested_category(question) == category
    assert category_search(question) == broad


@pytest.fixture
def routed_web(tmp_path, monkeypatch):
    monkeypatch.setattr(app, 'settings', Settings(amap_api_key='fixture-map-key'))
    monkeypatch.setattr(chat, 'store', HistoryStore(tmp_path/'history.sqlite3'))
    monkeypatch.setattr(chat, 'locks', {})
    def seed(sources, intent='search', kind='answer', stop='complete'):
        async def turn(*args):
            obj = result()
            obj['stop_reason'] = stop
            obj['sources'] = deepcopy(sources)
            obj['trace'] = [{'tool': 'search_places', 'status': 'success', 'arguments': {'query': '商场'}}] if intent == 'search' else []
            obj['answer'] = {'text': '本地候选。', 'citations': [p['id'] for p in sources],
                             'notice': '本地资料', 'mode': 'local_demo', 'kind': kind}
            return obj
        async def state(*args):
            return SimpleNamespace(values={'intent': intent})
        monkeypatch.setattr(chat, 'AgentEngine', lambda *a: SimpleNamespace(
            turn=turn, graph=SimpleNamespace(aget_state=state)))
    with TestClient(app.app) as web:
        yield web, seed


@pytest.mark.parametrize('sources', [[], [get_place('science-museum')], [mall()]])
@pytest.mark.parametrize('question', ['九龙有哪些商场', '九龍有哪些購物中心'])
def test_broad_mall_query_routes_on_missing_wrong_or_insufficient_local_results(routed_web, monkeypatch, sources, question):
    web, seed = routed_web
    seed(sources)
    queries = []
    async def lookup(query, settings):
        queries.append(query)
        return external()
    monkeypatch.setattr(chat, 'resolve_place', lookup)
    response = web.post('/api/chat', json={'question': question})
    assert response.status_code == 200, response.text
    data = response.json()
    assert queries == ['香港 九龙 商场']
    assert data['external_lookup']['results'][0]['name'] == '测试商场'
    assert all(matches_category(p, 'mall') for p in data['sources'])
    assert '科学馆' not in data['answer']['text']
    assert data['external_lookup']['coverage']['exhaustive'] is False


def test_enough_matching_local_candidates_do_not_request_map(routed_web, monkeypatch):
    web, seed = routed_web
    seed([{**mall(str(i)+'商场'), 'id': str(i)} for i in range(3)])
    async def forbidden(*args):
        pytest.fail('sufficient category matches must not request the map')
    monkeypatch.setattr(chat, 'resolve_place', forbidden)
    data = web.post('/api/chat', json={'question': '有哪些商场'}).json()
    assert 'external_lookup' not in data and len(data['sources']) == 3


def test_explicit_category_request_does_not_depend_on_model_search_decision(routed_web, monkeypatch):
    web, seed = routed_web
    seed([], intent='conversation', kind='clarify')
    async def lookup(query, cfg):
        assert query == '香港 商场'
        return external()
    monkeypatch.setattr(chat, 'resolve_place', lookup)
    data = web.post('/api/chat', json={'question':'香港有哪些商场'}).json()
    assert data['external_lookup']['mode'] == 'live'


def test_failed_supplement_keeps_verified_local_candidates(routed_web, monkeypatch):
    web, seed = routed_web
    seed([mall()])
    async def lookup(*args):
        return {'provider':'amap','mode':'unavailable','results':[],
                'external_requested':True,'message':'地图暂不可用'}
    monkeypatch.setattr(chat, 'resolve_place', lookup)
    data = web.post('/api/chat', json={'question': '推荐几个商场'}).json()
    assert data['sources'][0]['name'] == '测试商场'
    assert data['answer']['text'] == '本地候选。'
    assert data['external_lookup']['mode'] == 'unavailable'


def test_map_category_filter_excludes_museum_and_mall_parking():
    def handler(request):
        assert request.url.params['keywords'] == '香港 九龙 商场'
        return httpx.Response(200, json={'status':'1','pois':[
            {'id':'1','name':'测试商场','cityname':'香港','adname':'油尖旺区',
             'location':'114.17,22.3','type':'购物服务;商场;购物中心'},
            {'id':'2','name':'测试博物馆','cityname':'香港','location':'114.17,22.3','type':'科教文化服务;博物馆'},
            {'id':'3','name':'测试商场停车场','cityname':'香港','location':'114.17,22.3','type':'停车场'}]})
    found = asyncio.run(search_map('香港 九龙 商场', Settings(amap_api_key='fixture'), httpx.MockTransport(handler)))
    assert [p['name'] for p in found['results']] == ['测试商场']
    # Repeat validation at the evidence boundary, even if a lookup bypassed search_map.
    raw = external()
    raw['results'].append({**raw['results'][0], 'id':'amap-MUSEUM', 'name':'博物馆', 'category':'博物馆'})
    assert len(prepare_evidence(raw, Trip().model_dump(), 'mall')['results']) == 1


def test_library_category_query_is_normalized_and_rejects_wrong_provider_category():
    queries = []
    def handler(request):
        queries.append(request.url.params['keywords'])
        return httpx.Response(200, json={'status':'1','pois':[
            {'id':'1','name':'博物馆','cityname':'香港','location':'114.17,22.3','type':'博物馆'}]})
    found = asyncio.run(search_library('旺角有哪些商场', '九龙', Settings(amap_api_key='fixture'),
                                       httpx.MockTransport(handler)))
    assert queries == ['香港 旺角 商场'] and found['results'] == []


def test_explicit_neighbourhood_overrides_old_trip_region_for_maps(routed_web, monkeypatch):
    web, _ = routed_web
    def engine(*args):
        async def turn(*args):
            obj = result()
            obj['trip']['region'] = '香港岛'
            obj['answer'] = {'text':'暂无本地商场资料。','notice':'本地资料','kind':'answer','citations':[]}
            return obj
        async def state(*args):
            return SimpleNamespace(values={'intent':'search'})
        return SimpleNamespace(turn=turn,graph=SimpleNamespace(aget_state=state))
    monkeypatch.setattr(chat, 'AgentEngine', engine)
    async def lookup(query, cfg):
        assert query == '香港 旺角 商场'
        return external()  # Oil Tsim Mong is in Kowloon, not the old Hong Kong Island trip.
    monkeypatch.setattr(chat, 'resolve_place', lookup)
    data = web.post('/api/chat',json={'question':'旺角有哪些商场'}).json()
    assert data['external_lookup']['mode'] == 'live' and data['external_lookup']['results']
    assert data['trip']['region'] == '香港岛'


def test_library_query_enforces_explicit_region_even_with_all_selected():
    def handler(request):
        return httpx.Response(200,json={'status':'1','pois':[
            {'id':'1','name':'香港岛测试商场','cityname':'香港','adname':'中西区',
             'location':'114.15,22.28','type':'购物服务;商场'}]})
    data = asyncio.run(search_library('九龙有哪些商场','全部', Settings(amap_api_key='fixture'),
                                       httpx.MockTransport(handler)))
    assert data['mode'] == 'filtered_external' and not data['results']


def test_repeated_model_search_hands_off_after_first_empty_result(tmp_path, monkeypatch):
    monkeypatch.setattr(app, 'settings', Settings(model_api_key='fixture-model-key', amap_api_key='fixture-map-key'))
    monkeypatch.setattr(chat, 'store', HistoryStore(tmp_path/'history.sqlite3'))
    monkeypatch.setattr(chat, 'locks', {})
    # Simulate a provider that keeps asking to search the same empty local category.
    queue = [call('search_places', query='购物中心') for _ in range(3)]
    payloads = []
    monkeypatch.setattr(chat, 'AgentEngine', lambda *args: engine_with(queue, payloads))
    queries = []
    async def lookup(query, cfg):
        queries.append(query)
        return external()
    monkeypatch.setattr(chat, 'resolve_place', lookup)
    actual_generation = map_rag.map_rag_answer
    async def generate(question, evidence, cfg, transport=None, **kwargs):
        return await actual_generation(question, evidence, cfg,
            httpx.MockTransport(lambda request: model_response()), **kwargs)
    monkeypatch.setattr(map_rag, 'map_rag_answer', generate)
    with TestClient(app.app) as web:
        response = web.post('/api/chat', json={'question':'推荐一些商场', 'use_model':True})
        assert response.status_code == 200, response.text
        data = response.json()
        assert queries == ['香港 商场'] and len(payloads) == 1
        assert data['stop_reason'] == 'complete' and data['metrics']['map_rag_used']
        assert data['metrics']['agent_stop_reason'] == 'map_needed'
        assert data['answer']['citations'] == ['map-1']
        assert '重复' not in data['answer']['text']
        saved = web.post('/api/history/read', json={'id':data['conversation_id']}).json()
        assert saved['checkpoint']['history'][-1]['content'] == data['answer']['text']


@pytest.mark.parametrize('stop', ['repeat', 'limit'])
@pytest.mark.parametrize('map_mode', ['live', 'not_configured'])
def test_search_loop_can_still_reach_map_or_show_explicit_map_failure(routed_web, monkeypatch, stop, map_mode):
    web, seed = routed_web
    seed([], stop=stop)
    calls = []
    async def lookup(query, cfg):
        calls.append(query)
        raw = external()
        if map_mode != 'live':
            raw.update(mode=map_mode, results=[], external_requested=False, message='地图未配置，暂无商场候选。')
        return raw
    monkeypatch.setattr(chat, 'resolve_place', lookup)
    data = web.post('/api/chat', json={'question':'推荐一些商场'}).json()
    assert calls == ['香港 商场']
    assert data['external_lookup']['mode'] == map_mode
    assert data['stop_reason'] == 'complete' and data['metrics']['agent_stop_reason'] == stop
    assert not data['metrics']['map_rag_used']


@pytest.mark.parametrize('stop', ['timeout', 'tool_error', 'clarify_days'])
def test_other_failures_do_not_bypass_constraints_to_query_maps(routed_web, monkeypatch, stop):
    web, seed = routed_web
    seed([], stop=stop)
    async def forbidden(*args):
        pytest.fail('time limits and failed constraints must remain stopped')
    monkeypatch.setattr(chat, 'resolve_place', forbidden)
    data = web.post('/api/chat', json={'question':'推荐一些商场'}).json()
    assert data['stop_reason'] == stop and 'external_lookup' not in data
