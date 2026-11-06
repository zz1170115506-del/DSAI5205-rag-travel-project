"""Additive planning contracts. Provider/model responses are fixtures, never live."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import app
from travel.api import chat
from travel.itinerary import journey
from travel.workflows.agent import Trip
from travel.core.config import Settings
from travel.session.history import HistoryStore
from travel.rag.knowledge import places
from travel.itinerary.transit import enrich_plan
from tests.test_agent import fixture_tool
from tests.test_map_rag import external
from tests.test_anonymous_demo import anonymous


def map_result(name='K11 MUSEA', pid='amap-K11'):
    raw = external()
    raw['results'][0].update(id=pid, name=name, category='购物服务;商场')
    return raw


def ids(result):
    return [s['place']['id'] for d in result['plan']['days'] for s in d['stops']]


@pytest.fixture
def web(tmp_path, monkeypatch):
    monkeypatch.setattr(chat, 'store', HistoryStore(tmp_path/'history.sqlite3'))
    monkeypatch.setattr(chat, 'locks', {})
    monkeypatch.setattr(journey, 'local_call', fixture_tool)
    with TestClient(app.app) as client:
        yield client


def send(web, question, previous=None, **extra):
    body = {'question': question, 'workflow': 'itinerary', 'language': 'en', **extra}
    if previous:
        body.update(conversation_id=previous['conversation_id'], trip=previous['trip'])
    response = web.post('/api/chat', json=body)
    assert response.status_code == 200, response.text
    value = response.json()
    assert value['plan'] and value['answer']['kind'] == 'plan'
    return value


def test_multiple_local_additions_preserve_stops_deduplicate_and_restore_history(web, monkeypatch):
    async def forbidden(*args):pytest.fail('Known local names do not need map evidence')
    monkeypatch.setattr(chat, 'resolve_place', forbidden)
    first = send(web, 'I want to visit PMQ')
    assert ids(first) == ['pmq'] and first['trip']['days'] == 1
    assert any('one-day draft' in w for w in first['plan']['warnings'])
    second = send(web, 'What about Tai Kwun and Man Mo Temple?', first)
    assert ids(second) == ['pmq', 'tai-kwun', 'man-mo']
    duplicate = send(web, 'I want to visit PMQ', second)
    assert ids(duplicate) == ids(second)
    restored = web.post('/api/history/read', json={'id': first['conversation_id']}).json()
    assert ids(restored['turns'][-1]['result']) == ids(second)
    assert restored['checkpoint']['journey_plan'] == duplicate['plan']


@pytest.mark.parametrize('phrase', ['我想看一眼K11', 'I want to have a look on K11 muse', 'K11'])
def test_unknown_place_is_added_from_map_without_replacing_existing_plan(web, monkeypatch, phrase):
    before = deepcopy(places())
    queries = []
    async def lookup(query, settings):queries.append(query);return map_result()
    monkeypatch.setattr(chat, 'resolve_place', lookup)
    first = send(web, 'I want to visit PMQ')
    added = send(web, phrase, first)
    assert ids(added) == ['pmq', 'amap-K11']
    stop = added['plan']['days'][0]['stops'][1]
    assert stop['place']['provider'] == 'amap' and not stop['place']['curated_knowledge']
    assert stop['place']['source_evidence']['fetched_at']
    assert stop['place']['source'].startswith('https://uri.amap.com/marker?')
    assert stop['place']['lat'] is None and stop['place']['lon'] is None
    assert stop['transit_access'] is None
    leg = added['plan']['days'][0]['legs'][0]
    assert leg['minutes'] == 35 and not leg['live'] and leg['transit_guide']['mode'] == 'unverified'
    assert any('planning assumptions' in w for w in added['plan']['warnings'])
    assert len(queries) == 1
    assert places() == before  # Provider results never mutate curated sources/index.
    restored = web.post('/api/history/read', json={'id': added['conversation_id']}).json()
    assert ids(restored['turns'][-1]['result']) == ids(added)
    again = send(web, 'I want to visit K11 MUSEA', added)
    assert ids(again) == ids(added) and len(queries) == 1


def test_negation_removal_and_replacement_are_separate_from_addition(web, monkeypatch):
    first = send(web, 'PMQ and Tai Kwun')
    removed = send(web, 'Remove PMQ, but add Man Mo Temple', first)
    assert ids(removed) == ['tai-kwun', 'man-mo']
    assert 'pmq' not in removed['trip']['must_visit']
    replaced = send(web, 'Replace Man Mo Temple with PMQ', removed)
    assert ids(replaced) == ['tai-kwun', 'pmq']
    async def unavailable(*args):
        return {'provider': 'amap', 'mode': 'unavailable', 'results': []}
    monkeypatch.setattr(chat, 'resolve_place', unavailable)
    failed = send(web, 'Replace PMQ with K11 MUSEA', replaced)
    assert ids(failed) == ids(replaced)  # Failed replacement never deletes PMQ.
    assert failed['plan']['pending_places'] == ['K11 MUSEA']


@pytest.mark.parametrize('mode', ['empty', 'unavailable', 'disabled'])
def test_map_failure_preserves_previous_plan_without_unrelated_substitutes(web, monkeypatch, mode):
    async def lookup(*args):return {'provider': 'amap', 'mode': mode, 'results': []}
    monkeypatch.setattr(chat, 'resolve_place', lookup)
    first = send(web, 'PMQ')
    second = send(web, '我想看一眼K11', first)
    assert ids(second) == ['pmq'] and second['plan']['pending_places'] == ['K11']


def test_named_map_search_rejects_unrelated_provider_hits(web, monkeypatch):
    async def lookup(*args):return map_result('Avenue of Stars')
    monkeypatch.setattr(chat, 'resolve_place', lookup)
    data = send(web, 'I want to visit K11 MUSEA')
    assert not ids(data) and data['plan']['pending_places'] == ['K11 MUSEA']


def test_unlocated_requests_remain_pending_until_resolved_or_removed(web, monkeypatch):
    async def unavailable(*args):return {'provider': 'amap', 'mode': 'unavailable', 'results': []}
    monkeypatch.setattr(chat, 'resolve_place', unavailable)
    first = send(web, '我想看一眼K11')
    second = send(web, 'What about PMQ?', first)
    assert ids(second) == ['pmq'] and second['plan']['pending_places'] == ['K11']
    removed = send(web, 'Do not add K11', second)
    assert ids(removed) == ['pmq'] and not removed['plan']['pending_places']


def test_category_search_schedules_matching_map_places_not_museums(web, monkeypatch):
    queries = []
    async def lookup(query, settings):
        queries.append(query)
        result = map_result('K11 MUSEA')
        result['results'].append({**result['results'][0], 'id': 'amap-MUSEUM', 'name': '测试博物馆', 'category': '博物馆'})
        return result
    monkeypatch.setattr(chat, 'resolve_place', lookup)
    data = send(web, 'Which shopping malls can I visit in Kowloon?')
    assert queries == ['香港 九龙 商场']
    assert ids(data) == ['amap-K11']


def test_dates_and_relative_days_change_calendar_without_forgetting_places(web):
    first = send(web, 'I want to visit PMQ', trip={'start_date': '2026-11-10', 'end_date': '2026-11-12'})
    second = send(web, 'Add one more day', first)
    assert second['trip']['days'] == 4 and second['trip']['end_date'] == '2026-11-13'
    assert ids(second) == ['pmq']
    third = send(web, 'Make it one day', second)
    assert third['trip']['days'] == 1 and third['trip']['end_date'] == '2026-11-10'
    assert ids(third) == ['pmq']


def test_generic_plan_then_new_place_preserves_original_stops(web):
    first = send(web, 'Plan a two-day trip in Central', trip={'days': 2, 'region': '香港岛'})
    initial = set(ids(first))
    assert initial
    second = send(web, 'I want to visit Hong Kong Science Museum', first)
    assert initial <= set(ids(second)) and 'science-museum' in ids(second)
    assert any('preference exception' in w for w in second['plan']['warnings'])


def test_model_understands_unseen_phrasing_and_returns_all_entities_not_an_answer(web, monkeypatch):
    monkeypatch.setattr(app, 'settings', Settings(model_api_key='fixture-model'))
    captured = []
    payload = {'places': [{'query': 'PMQ'}, {'query': 'Tai Kwun'}, {'query': 'K11 MUSEA'}]}
    async def interpreted(question, selected, trip, history, settings, use_model, transport=None):
        return await original(question, selected, trip, history, settings, use_model,
            httpx.MockTransport(handler))
    original_summary = journey.generate_summary
    async def summary(*args, **kwargs):
        args = [*args]; args[6] = httpx.MockTransport(handler)
        return await original_summary(*args, **kwargs)
    def handler(request):
        obj = json.loads(request.content);captured.append(obj)
        if 'Extract the user request' in obj['messages'][0]['content']:
            assert 'Every newly mentioned place defaults to ADDING' in obj['messages'][0]['content']
            value = payload
        else:
            context = json.loads(obj['messages'][1]['content'])
            assert any(p['name'] == 'K11 MUSEA' and p['provider_fields'] for p in context['evidence'])
            assert any(p['name'] == 'PMQ' and p['summary'] for p in context['evidence'])
            value = {'text': 'Your itinerary now includes PMQ [pmq] and Tai Kwun [tai-kwun].',
                     'citations': ['pmq', 'tai-kwun']}
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(value)}}]})
    original = journey.interpret
    monkeypatch.setattr(journey, 'interpret', interpreted)
    monkeypatch.setattr(journey, 'generate_summary', summary)
    async def lookup(*args):return map_result()
    monkeypatch.setattr(chat, 'resolve_place', lookup)
    data = send(web, 'Could we squeeze in PMQ, have a wander round Tai Kwun, then swing by K11 Musea?', use_model=True)
    assert set(ids(data)) == {'pmq', 'tai-kwun', 'amap-K11'}
    assert len(captured) == 2 and data['metrics']['intent_generation']['accepted']
    assert data['answer']['model_output_accepted'] and data['metrics']['answer_generation']['accepted']
    assert data['metrics']['model_calls'] == 2


def test_malformed_model_intent_uses_offline_fallback_and_never_fakes_model_success(monkeypatch):
    monkeypatch.setattr(journey, 'local_call', fixture_tool)
    cfg = Settings(model_api_key='fixture-model')
    async def lookup(*args):pytest.fail('PMQ is local')
    data, state = asyncio.run(journey.journey_turn('I want to visit PMQ', None, None, cfg, True,
        lookup=lookup, model_transport=httpx.MockTransport(lambda request: httpx.Response(200,
            json={'choices': [{'message': {'content': '{broken'}}]}))))
    assert ids(data) == ['pmq'] and not data['metrics']['intent_generation']['accepted']


@pytest.mark.parametrize('text,citations', [
    ('Visit an invented source [made-up]', ['made-up']),
    ('PMQ ticket price is $50 [pmq]', ['pmq']),
    ('fixture-model [pmq]', ['pmq']),
])
def test_invalid_generated_summary_keeps_the_valid_itinerary(monkeypatch, text, citations):
    monkeypatch.setattr(journey, 'local_call', fixture_tool)
    cfg = Settings(model_api_key='fixture-model')
    def handler(request):
        body = json.loads(request.content)
        value = {'places': [{'query': 'PMQ'}]} if 'Extract the user request' in body['messages'][0]['content'] else {
            'text': text, 'citations': citations}
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(value)}}]})
    async def forbidden(*args):pytest.fail('PMQ is local')
    data, _ = asyncio.run(journey.journey_turn('I want to visit PMQ', None, None, cfg, True,
        lookup=forbidden, model_transport=httpx.MockTransport(handler)))
    assert ids(data) == ['pmq'] and not data['answer']['model_output_accepted']
    assert not data['metrics']['answer_generation']['accepted']
    assert text not in data['answer']['text']


def test_capacity_expands_draft_without_dropping_places_or_writing_past_midnight():
    selected = places()[:12]
    trip = Trip(days=1, start_date='2026-11-10', end_date='2026-11-10').model_dump()
    plan = journey.build_plan(selected, trip)
    assert set(ids({'plan': plan})) == {p['id'] for p in selected}
    assert plan['days_requested'] > 1 and trip['days'] == plan['days_requested']
    assert trip['end_date'] == plan['days'][-1]['date']
    assert all(day['end'] <= '23:00' for day in plan['days'] if day['stops'])
    assert any('extended' in w for w in plan['warnings'])


def test_history_enrichment_does_not_resolve_external_ids_as_curated_records():
    trip = Trip(days=1).model_dump()
    poi = journey.external_stop(journey.prepare_evidence(map_result(), trip)['results'][0], 'K11 MUSEA')
    plan = journey.build_plan([poi], trip)
    assert enrich_plan(plan) == plan


def test_main_app_requests_conditional_workflow_and_retains_native_date_inputs():
    root = Path(__file__).resolve().parents[1]
    js = (root/'static/js/app.js').read_text()
    assert "workflow:'conditional'" in js
    html = (root/'static/index.html').read_text()
    assert html.count('type="date"') == 4


def test_main_workflow_uses_actual_mcp_stdio_for_local_evidence(web, monkeypatch):
    from travel.tools.mcp_client import local_call
    monkeypatch.setattr(journey, 'local_call', local_call)
    data = send(web, 'I want to visit PMQ')
    step = next(s for s in data['trace'] if s['tool'] == 'place_detail')
    assert step['status'] == 'success' and step['protocol']['transport'] == 'stdio'
    assert 'tools/call → place_detail' in step['protocol']['steps']


def test_anonymous_visitors_keep_their_own_additive_itinerary(anonymous, monkeypatch):
    monkeypatch.setattr(journey, 'local_call', fixture_tool)
    first = send(anonymous, 'I want to visit PMQ')
    other = send(anonymous, 'I want to visit Tai Kwun')
    added = send(anonymous, 'What about Man Mo Temple?', first)
    assert ids(added) == ['pmq', 'man-mo']
    assert ids(other) == ['tai-kwun']
    assert not chat.store.path.exists()
