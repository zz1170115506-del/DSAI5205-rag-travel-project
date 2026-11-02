"""Named lookups cannot be replaced by nearby or semantically similar sights.

Model and map responses are fixtures; no credentials or live HTTP are used.
"""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

import app
from travel import chat, map_rag, retrieval
from travel.agent import AgentEngine, ModelPolicy, Trip
from travel.config import RetrievalSettings, Settings
from travel.history import HistoryStore
from travel.knowledge import get_place
from travel.place_intent import explicit_name
from tests.test_agent import fixture_tool
from tests.test_intent_fixes import routed_web
from tests.test_map_rag import external, model_response
from tests.test_model_conversation import call, final


@pytest.mark.parametrize('question,target', [
    ('我想看一眼K11', 'K11'), ('我想去看看 K11', 'K11'),
    ('想逛一下K11', 'K11'), ('K11', 'K11'), ('Where is K11?', 'K11'),
    ('I want to have a look on K11 muse', 'K11 MUSEA'),
    ('I want to have a look at K11 MUSEA', 'K11 MUSEA'),
    ("I'd like to visit K11 MUSEA, please.", 'K11 MUSEA'),
    ('I want to visit K11 MUSEA in Tsim Sha Tsui', 'K11 MUSEA'),
    ('I want to see PMQ', 'PMQ'), ('我想看一下香港艺术馆', '香港艺术馆'),
    ('Tell me about Avenue of Stars', 'Avenue of Stars'),
])
def test_conversational_lookup_extracts_the_target(question, target):
    assert explicit_name(question) == target


@pytest.mark.parametrize('question', [
    '推荐一些商场', '我想去逛逛商场', '想去九龙', '我想去海边玩',
    'I want to visit some shopping malls', 'I want to see a museum',
    'I want to see culture', 'I want to visit Hong Kong',
    '第二个有什么特色', '那第一个呢', 'I want to see it',
    'I want to visit K11 and PMQ', 'I want to see day 2',
    '我不想去K11', 'I do not want to visit K11',
    '把K11加入行程', 'Add K11 to my itinerary',
])
def test_categories_regions_negations_and_itinerary_edits_are_not_single_names(question):
    assert explicit_name(question) is None


@pytest.mark.parametrize('mode', ['local_hybrid', 'model_hybrid', 'model_no_search'])
@pytest.mark.parametrize('question,target', [
    ('我想看一眼K11', 'K11'),
    ('I want to have a look on K11 muse', 'K11 MUSEA'),
])
def test_web_named_miss_ignores_similar_sights_and_old_selections_then_queries_map(
        tmp_path, monkeypatch, mode, question, target):
    cfg = Settings(model_api_key='fixture-model', model_base_url='https://model.fixture/v1',
                   amap_api_key='fixture-map')
    monkeypatch.setattr(app, 'settings', cfg)
    monkeypatch.setattr(chat, 'store', HistoryStore(tmp_path/'history.sqlite3'))
    monkeypatch.setattr(chat, 'locks', {})
    # Reproduce the screenshot: dense search happily returns unrelated HK sights.
    monkeypatch.setattr(retrieval, 'semantic_search', lambda *a, **kw: [
        {**get_place(pid), 'semantic_score': .99}
        for pid in ['avenue-stars', 'knutsford', 'star-ferry', 'art-park']])
    async def tool(name, args):
        assert name == 'search_places'
        assert args['query'] == target
        found = retrieval.retrieve(**args, settings=RetrievalSettings(mode='hybrid'))
        return found, {'transport': 'in_process_fixture'}
    payloads = []
    def create(settings):
        engine = AgentEngine(settings, tool_call=tool)
        if mode.startswith('model'):
            queue = ([final('Which place do you mean?', 'clarify')] if mode == 'model_no_search'
                     else [call('search_places', query='Places in Kowloon')])
            def handler(request):
                payloads.append(json.loads(request.content))
                return httpx.Response(200, json={'choices': [{'message': queue.pop(0)}]})
            engine.policy = ModelPolicy(settings, httpx.MockTransport(handler))
        return engine
    monkeypatch.setattr(chat, 'AgentEngine', create)
    queries = []
    async def lookup(query, settings):
        queries.append(query)
        found = external()
        found['results'][0]['name'] = 'K11 MUSEA'
        return found
    monkeypatch.setattr(chat, 'resolve_place', lookup)
    generate = map_rag.map_rag_answer
    async def generation(question, evidence, settings, transport=None, **kwargs):
        return await generate(question, evidence, settings,
            httpx.MockTransport(lambda request: model_response('K11 MUSEA is listed at the provider address [map-1].')),
            **kwargs)
    monkeypatch.setattr(map_rag, 'map_rag_answer', generation)
    with TestClient(app.app) as web:
        response = web.post('/api/chat', json={
            'question': question, 'language': 'en', 'use_model': mode.startswith('model'),
            'trip': Trip(days=3, must_visit=['avenue-stars']).model_dump()})
        assert response.status_code == 200, response.text
        data = response.json()
        assert queries == [target], data
        assert data['sources'] == [] and data['plan'] is None
        assert data['trip']['must_visit'] == ['avenue-stars']  # Lookup doesn't edit the trip.
        assert data['answer']['retrieval_source'] == 'amap'
        assert data['external_lookup']['results'][0]['name'] == 'K11 MUSEA'
        assert 'Avenue of Stars' not in data['answer']['text']
        assert data['stop_reason'] == 'complete'
        if mode == 'model_hybrid':
            assert len(payloads) == 1  # First local miss hands off; no search loop.
            assert data['metrics']['agent_stop_reason'] == 'map_needed'
        saved = web.post('/api/history/read', json={'id': data['conversation_id']}).json()
        assert saved['checkpoint']['history'][-1]['content'] == data['answer']['text']


def test_known_named_place_keeps_local_evidence_and_does_not_query_map(tmp_path, monkeypatch):
    monkeypatch.setattr(app, 'settings', Settings())
    monkeypatch.setattr(chat, 'store', HistoryStore(tmp_path/'history.sqlite3'))
    monkeypatch.setattr(chat, 'locks', {})
    monkeypatch.setattr(chat, 'AgentEngine', lambda cfg: AgentEngine(cfg, tool_call=fixture_tool))
    async def forbidden(*args):
        pytest.fail('Known local place should not request an external lookup')
    monkeypatch.setattr(chat, 'resolve_place', forbidden)
    with TestClient(app.app) as web:
        data = web.post('/api/chat', json={'question': 'I want to see PMQ', 'language': 'en'}).json()
        assert [p['id'] for p in data['sources']] == ['pmq']
        assert 'external_lookup' not in data and 'PMQ' in data['answer']['text']


@pytest.mark.parametrize('stop', ['timeout', 'tool_error', 'clarify_days'])
def test_named_lookup_does_not_bypass_other_failure_stops(routed_web, monkeypatch, stop):
    web, seed = routed_web
    seed([], stop=stop)
    async def forbidden(*args):
        pytest.fail('Named lookup must respect deadlines and constraint failures')
    monkeypatch.setattr(chat, 'resolve_place', forbidden)
    data = web.post('/api/chat', json={'question': '我想看一眼K11'}).json()
    assert data['stop_reason'] == stop and 'external_lookup' not in data


def test_unavailable_map_does_not_fall_back_to_unrelated_local_sights(routed_web, monkeypatch):
    web, seed = routed_web
    seed([get_place('avenue-stars')])
    async def lookup(query, settings):
        return {'provider': 'amap', 'mode': 'unavailable', 'results': [],
                'external_requested': True, 'message': '地图暂不可用'}
    monkeypatch.setattr(chat, 'resolve_place', lookup)
    data = web.post('/api/chat', json={'question': '我想看一眼K11'}).json()
    assert not data['sources'] and not data['answer']['citations']
    assert data['answer']['retrieval_source'] == 'amap'
    assert data['external_lookup']['mode'] == 'unavailable'
