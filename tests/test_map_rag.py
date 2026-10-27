"""Map evidence + generation contracts; external HTTP calls here are all fixtures."""
import asyncio
from copy import deepcopy
import json

import httpx
import pytest
from fastapi.testclient import TestClient

import app
from travel import chat, map_rag
from travel.agent import AgentEngine, ModelPolicy, Trip
from travel.config import Settings
from travel.history import HistoryStore
from travel.maps import search_map
from travel.map_rag import map_rag_answer, prepare_evidence, supplement_with_map
from tests.test_agent import fixture_tool


CFG = Settings(model_api_key='fixture-model-key', model_base_url='https://model.fixture/v1',
               amap_api_key='fixture-map-key')


def external():
    return {'provider': 'amap', 'mode': 'live', 'external_requested': True,
            'message': '高德返回地点候选，请核对同名分店。', 'results': [
                {'id': 'amap-B0TEST', 'name': '测试商场', 'address': '测试道18号', 'district': '油尖旺区',
                 'category': '购物服务', 'location': [114.17, 22.3],
                 'map_url': 'https://evil.fixture/redirect',
                 'source': {'name': 'untrusted', 'url': 'https://evil.fixture',
                            'fetched_at': '2026-10-27T12:00:00+00:00'}}]}


def evidence():
    return prepare_evidence(external(), Trip().model_dump())


def model_response(text='测试商场的地址为测试道18号，地图类别为购物服务 [map-1]。', citations=None):
    return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(
        {'answer': text, 'citations': ['map-1'] if citations is None else citations}, ensure_ascii=False)}}]})


def result():
    return {'trip': Trip().model_dump(), 'trace': [], 'sources': [], 'plan': None,
            'stop_reason': 'complete', 'answer': {},
            'metrics': {'tool_calls': 0, 'model_calls': 0, 'model_responses': 0,
                        'live_model_responses': 0, 'external_model_verified': False}}


def test_map_http_fields_become_bounded_evidence_without_credential_or_remote_link():
    def handler(request):
        assert request.url.host == 'restapi.amap.com'
        return httpx.Response(200, json={'status': '1', 'pois': [
            {'id': 'B0TEST', 'name': '测试商场', 'address': '测试道18号', 'adname': '油尖旺区',
             'cityname': '香港', 'location': '114.17,22.3', 'type': '购物服务'}]})
    lookup = asyncio.run(search_map('测试商场', CFG, httpx.MockTransport(handler)))
    found = prepare_evidence(lookup, Trip().model_dump())
    poi = found['results'][0]
    assert poi['citation_id'] == 'map-1' and poi['source']['fetched_at']
    assert poi['map_url'].startswith('https://uri.amap.com/marker?')
    assert not poi['curated_knowledge'] and 'fixture-map-key' not in json.dumps(found)
    assert evidence()['results'][0]['source']['url'].startswith('https://lbs.amap.com/')


@pytest.mark.parametrize('changes', [{'rain': True}, {'public_only': True}, {'region': '香港岛'}])
def test_map_candidates_do_not_silently_relax_preferences(changes):
    found = prepare_evidence(external(), {**Trip().model_dump(), **changes})
    assert found['mode'] == 'filtered_external' and not found['results']


def test_outside_hk_missing_source_and_duplicates_are_not_new_knowledge():
    raw = external()
    invalid = deepcopy(raw['results'][0]);invalid['location'] = [121, 31]
    missing = deepcopy(raw['results'][0]);missing['source'] = {}
    raw['results'] = [invalid, missing, *raw['results'], *raw['results']]
    assert len(prepare_evidence(raw, Trip().model_dump())['results']) == 1


def test_map_evidence_is_really_sent_to_generation_and_citations_are_accepted():
    captured = []
    def handler(request):
        body = json.loads(request.content);captured.append(body)
        context = json.loads(body['messages'][1]['content'])
        assert context['question'] == '测试商场在哪里？'
        assert context['map_evidence'][0]['address'] == '测试道18号'
        assert 'fixture-map-key' not in request.content.decode()
        assert 'tools' not in body
        assert 'citations 字符串数组' in body['messages'][0]['content']
        return model_response()
    answer, meta = asyncio.run(map_rag_answer('测试商场在哪里？', evidence(), CFG, httpx.MockTransport(handler)))
    assert len(captured) == 1 and answer['mode'] == 'model'
    assert answer['citations'] == ['map-1'] and answer['model_output_accepted']
    assert meta['output_accepted'] and meta['response_received'] and not meta['live_response']


@pytest.mark.parametrize('text,citations', [
    ('伪造编号 [map-9]', ['map-9']), ('未标正文引用', ['map-1']),
    ('正文来源不符 [map-1]', ['map-1', 'map-2']), ('未确认票价为20元 [map-1]', ['map-1']),
    ('<script>attack</script> [map-1]', ['map-1']), ('https://evil.fixture [map-1]', ['map-1']),
    ('fixture-model-key [map-1]', ['map-1']), ('模型引用本地条目 [tai-kwun]', ['tai-kwun']),
    ('测试地址 [map-1]', [{'citation_id': 'map-1', 'name': '测试商场'}])])
def test_invalid_or_reflected_model_output_falls_back_to_map_cards(text, citations):
    answer, meta = asyncio.run(map_rag_answer('测试商场在哪里？', evidence(), CFG,
        httpx.MockTransport(lambda request: model_response(text, citations))))
    assert answer['mode'] == 'map_lookup' and not answer['model_output_accepted']
    assert not meta['output_accepted'] and 'fixture-model-key' not in answer['text']


@pytest.mark.parametrize('mode', ['empty', 'unavailable', 'disabled', 'not_configured', 'filtered_external'])
def test_no_map_evidence_never_calls_model(mode):
    def forbidden(request):pytest.fail('no evidence must not request the model')
    answer, meta = asyncio.run(map_rag_answer('地点在哪？', {**external(), 'mode': mode, 'results': []}, CFG,
                                             httpx.MockTransport(forbidden)))
    assert answer['mode'] == 'map_lookup' and not meta['requested']


def test_dynamic_questions_remain_unanswered_by_poi_name_and_address():
    def forbidden(request):pytest.fail('POI data cannot answer live opening hours')
    answer, meta = asyncio.run(map_rag_answer('测试商场营业时间？', evidence(), CFG, httpx.MockTransport(forbidden)))
    assert not meta['requested'] and meta['reason'] == 'unsupported_live_question'
    assert '不能确认' in answer['text']


def test_supplement_records_actual_generation_and_preserves_planner_state():
    async def lookup(query, cfg):return external()
    obj = result();before = deepcopy(obj['trip'])
    asyncio.run(supplement_with_map(obj, '测试商场在哪里？', '测试商场', CFG, True, lookup=lookup,
                                   model_transport=httpx.MockTransport(lambda request: model_response())))
    assert obj['trip'] == before and obj['plan'] is None and not obj['sources']
    assert obj['metrics']['map_rag_used'] and obj['metrics']['model_calls'] == 1
    assert not obj['metrics']['external_model_verified']
    assert [step['tool'] for step in obj['trace']] == ['map_search', 'map_rag_answer']
    assert obj['trace'][0]['retrieval']['embedding_used'] is False


def test_local_mode_never_sends_map_evidence_to_a_model():
    async def lookup(query, cfg):return external()
    def forbidden(request):pytest.fail('local mode must not request a model')
    obj = result()
    asyncio.run(supplement_with_map(obj, '测试商场在哪里？', '测试商场', CFG, False, lookup=lookup,
                                   model_transport=httpx.MockTransport(forbidden)))
    assert obj['answer']['mode'] == 'map_lookup'
    assert obj['metrics']['model_calls'] == 0 and not obj['metrics']['map_rag_used']


def test_map_timeout_is_bounded_and_not_reported_as_a_success():
    async def lookup(query, cfg):await asyncio.sleep(1)
    obj = result()
    asyncio.run(supplement_with_map(obj, '地点在哪？', '地点', CFG, True, lookup=lookup, time_budget=.01))
    assert obj['external_lookup']['mode'] == 'unavailable'
    assert obj['metrics']['model_calls'] == 0 and not obj['metrics']['map_rag_used']


def test_model_timeout_preserves_evidence_and_reports_failure():
    def handler(request):raise httpx.ReadTimeout('fixture-model-key must not leak')
    answer, meta = asyncio.run(map_rag_answer('地点在哪？', evidence(), CFG, httpx.MockTransport(handler)))
    assert answer['mode'] == 'map_lookup' and meta['requested'] and not meta['response_received']
    assert 'fixture-model-key' not in json.dumps(answer)


def test_web_unknown_named_place_generates_from_map_and_survives_history_reload(tmp_path, monkeypatch):
    monkeypatch.setattr(app, 'settings', CFG)
    monkeypatch.setattr(chat, 'store', HistoryStore(tmp_path/'history.sqlite3'))
    monkeypatch.setattr(chat, 'locks', {})
    queries = []
    async def lookup(query, cfg):queries.append(query);return external()
    monkeypatch.setattr(chat, 'resolve_place', lookup)
    def engine(*args):
        created = AgentEngine(CFG, tool_call=fixture_tool)
        queue = [
            {'tool_calls': [{'type': 'function', 'function': {'name': 'search_places', 'arguments': '{"query":"虚构测试商场"}'}}]},
            {'content': '{"kind":"clarify","text":"请核对地点名称。","citations":[]}'}]
        created.policy = ModelPolicy(CFG, httpx.MockTransport(lambda request: httpx.Response(200,
            json={'choices': [{'message': queue.pop(0)}]})))
        return created
    monkeypatch.setattr(chat, 'AgentEngine', engine)
    actual_generation = map_rag.map_rag_answer
    async def generate(question, found, cfg, transport=None, **kwargs):
        return await actual_generation(question, found, cfg, httpx.MockTransport(lambda request: model_response()), **kwargs)
    monkeypatch.setattr(map_rag, 'map_rag_answer', generate)
    with TestClient(app.app) as web:
        r = web.post('/api/chat', json={'question': '介绍虚构测试商场', 'use_model': True})
        assert r.status_code == 200
        data = r.json()
        assert queries == ['虚构测试商场']
        assert data['answer']['retrieval_source'] == 'amap' and data['metrics']['map_rag_used']
        assert data['sources'] == [] and data['answer']['citations'] == ['map-1']
        saved = web.post('/api/history/read', json={'id': data['conversation_id']}).json()
        assert saved['turns'][0]['result']['external_lookup']['results'][0]['citation_id'] == 'map-1'
        assert saved['checkpoint']['place_context']['listed_ids'] == []
        assert saved['checkpoint']['history'][-1]['content'] == data['answer']['text']
        assert 'fixture-model-key' not in json.dumps(saved) and 'fixture-map-key' not in json.dumps(saved)
