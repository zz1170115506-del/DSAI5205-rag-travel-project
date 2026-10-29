"""English presentation behaviour with canonical tool values kept compatible."""
import asyncio
from dataclasses import replace
from html.parser import HTMLParser
import json
from pathlib import Path
import re

import httpx
import pytest
from fastapi.testclient import TestClient

import app
from travel import chat
from travel.agent import AgentEngine, ModelPolicy, Trip
from travel.config import Settings
from travel.english import place_texts
from travel.history import HistoryStore
from travel.knowledge import places
from travel.map_rag import map_rag_answer
from travel.place_intent import category_search, map_category_query
from travel.retrieval import retrieve
from travel.trip_dates import parse_day_change
from tests.test_agent import fixture_tool
from tests.test_map_rag import CFG, evidence, model_response

ROOT=Path(__file__).resolve().parents[1]
CJK=re.compile(r'[\u3400-\u9fff]')


def test_all_curated_places_have_complete_english_presentations():
    translated=place_texts()
    assert set(translated)=={p['id'] for p in places()}
    for item in translated.values():
        assert all(item.get(key) and not CJK.search(item[key]) for key in ('name','area','summary','tip'))


def test_visible_html_is_english_and_form_values_remain_canonical():
    class Page(HTMLParser):
        def __init__(self):super().__init__();self.visible=[];self.values=[]
        def handle_data(self,text):self.visible.append(text)
        def handle_starttag(self,tag,attrs):
            attrs=dict(attrs)
            for key in ('aria-label','placeholder','title','data-prompt'):
                assert not CJK.search(attrs.get(key,''))
            if 'value' in attrs:self.values.append(attrs['value'])
    page=Page();page.feed((ROOT/'static/index.html').read_text())
    assert not CJK.search(''.join(page.visible))
    assert {'全部','香港岛','九龙','大屿山','轻松','充实'}<=set(page.values)


@pytest.mark.parametrize('text,operation,amount',[
    ('Plan three days','set',3),('Plan a 3-day trip','set',3),('Plan a three-day itinerary','set',3),
    ('Add one more day','increase',1),('Add another day','increase',1),
    ('Extend the trip by 2 days','increase',2),('Make it one day','set',1),
    ('Remove two days','decrease',2),('One fewer day','decrease',1)])
def test_english_duration_operations(text,operation,amount):
    change=parse_day_change(text)
    assert change.operation==operation and change.amount==amount


def test_english_local_retrieval_and_category_constraints():
    assert retrieve('What cultural places can I visit in Central?')['results']
    assert not retrieve('Recommend shopping malls in Hong Kong')['results']
    assert category_search('Which shopping malls can I visit in Mong Kok?')
    assert map_category_query('Which shopping malls can I visit in Mong Kok?')=='香港 旺角 商场'


def test_english_conversation_keeps_dates_preferences_and_local_citations(tmp_path,monkeypatch):
    monkeypatch.setattr(chat,'store',HistoryStore(tmp_path/'history.sqlite3'))
    monkeypatch.setattr(chat,'locks',{})
    with TestClient(app.app) as web:
        first=web.post('/api/chat',json={'question':'Plan a 3 day relaxed itinerary in Kowloon from 2026-11-01 to 2026-11-03','language':'en'}).json()
        assert first['trip']['region']=='九龙' and first['trip']['pace']=='轻松'
        assert first['trip']['days']==len(first['plan']['days'])==3
        second=web.post('/api/chat',json={'question':'Add one more day','language':'en','conversation_id':first['conversation_id']}).json()
        assert second['trip']['days']==len(second['plan']['days'])==4
        assert second['trip']['start_date']=='2026-11-01' and second['trip']['end_date']=='2026-11-04'
        third=web.post('/api/chat',json={'question':'Make it one day','language':'en','conversation_id':first['conversation_id']}).json()
        assert third['trip']['days']==len(third['plan']['days'])==1
        for result in (first,second,third):assert not CJK.search(result['answer']['text']+result['answer']['notice'])
        source=web.post('/api/chat',json={'question':'What cultural places can I visit in Central?','language':'en'}).json()
        assert source['answer']['citations'] and not CJK.search(source['answer']['text'])


def test_english_model_prompt_preserves_canonical_tool_enums():
    config=Settings(model_api_key='fixture-only',response_language='en')
    payloads=[]
    queue=[{'tool_calls':[{'type':'function','function':{'name':'update_trip','arguments':'{"changes":{"days":3,"pace":"轻松"}}'}}]},
           {'content':'{"kind":"ack","text":"Your three-day relaxed trip is saved.","citations":[]}'}]
    def handler(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200,json={'choices':[{'message':queue.pop(0)}]})
    engine=AgentEngine(config,tool_call=fixture_tool)
    engine.policy=ModelPolicy(config,httpx.MockTransport(handler))
    result=asyncio.run(engine.turn('english','Save a three day relaxed trip'))
    assert result['trip']['days']==3 and result['trip']['pace']=='轻松'
    assert result['answer']['model_output_accepted']
    assert 'ALL user-facing answers must be in English' in payloads[0]['messages'][0]['content']


def test_map_generation_uses_english_and_rejects_chinese_model_prose():
    config=replace(CFG,response_language='en')
    def handler(request):
        assert 'Answer in English' in json.loads(request.content)['messages'][0]['content']
        return model_response('The test mall is at 18 Test Road [map-1].')
    answer,meta=asyncio.run(map_rag_answer('Where is the test mall?',evidence(),config,httpx.MockTransport(handler)))
    assert meta['output_accepted'] and not CJK.search(answer['text'])
    bad,meta=asyncio.run(map_rag_answer('Where is the test mall?',evidence(),config,
                         httpx.MockTransport(lambda request:model_response())))
    assert not meta['output_accepted'] and not CJK.search(bad['text'])
