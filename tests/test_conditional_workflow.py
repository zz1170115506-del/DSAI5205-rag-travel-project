import asyncio
from copy import deepcopy
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app import app
from travel.api import chat
from travel.core.config import Settings, RetrievalSettings
from travel.session.history import HistoryStore
from travel.workflows.conditional import RouteDecision, conditional_turn
from travel.workflows.rag import Assessment, GroundedAnswer, Verification, agentic_answer
from travel.rag.documents import documents, retrieve_documents
from travel.rag.knowledge import get_place
from travel.rag.place_intent import matches_category


async def no_lookup(*args):
    return {'mode':'empty','results':[]}


class ModelStub:
    def __init__(self,responses=None):
        self.responses=responses or {};self.calls=0;self.trace=[];self.payloads=[]
    async def ask(self,role,instructions,payload,schema):
        self.calls+=1;self.payloads.append((role,payload))
        response=self.responses.get(role)
        return response(payload) if callable(response) else response


async def initial():
    result,checkpoint=await conditional_turn('Plan my trip',
        {'days':2,'must_visit':['pmq','hkmoa'],'only_selected':True},None,Settings(),False,
        lookup=no_lookup,action='create_plan',model=ModelStub())
    assert result['plan_changed'] and result['plan_version']==1
    return {'checkpoint':checkpoint,'turns':[{'question':'Plan my trip','result':result}]}


def test_named_questions_and_general_chat_leave_the_committed_itinerary_unchanged():
    async def scenario():
        saved=await initial();before=deepcopy(saved['checkpoint'])
        answer,cp=await conditional_turn('大馆以前是什么地方？',{'days':10},saved,Settings(),False,
                                        lookup=no_lookup,model=ModelStub())
        assert answer['route']=='travel_question' and not answer['plan_changed'] and answer['plan'] is None
        assert cp['journey_plan']==before['journey_plan'] and cp['trip']==before['trip']
        assert answer['plan_version']==1 and answer['evidence']
        general,cp=await conditional_turn('讲个笑话',None,saved,Settings(),False,
                                         lookup=no_lookup,model=ModelStub({'general_conversation':GroundedAnswer(text='A joke.')}))
        assert general['route']=='general_chat' and general['answer']['text']=='A joke.'
        assert cp['journey_plan']==before['journey_plan'] and not general['evidence']
    asyncio.run(scenario())


def test_local_replacement_commits_once_and_preserves_the_other_day():
    async def scenario():
        saved=await initial();before=deepcopy(saved['checkpoint']['journey_plan'])
        result,cp=await conditional_turn('把元创方换成大馆',None,saved,Settings(),False,lookup=no_lookup,model=ModelStub())
        assert result['plan_changed'] and result['plan_version']==2
        assert cp['journey_plan']['days'][1]==before['days'][1]
        ids=[s['place']['id'] for d in result['plan']['days'] for s in d['stops']]
        assert set(ids)=={'tai-kwun','hkmoa'} and 'pmq' in cp['trip']['excluded_places']
        assert 'price_summary' in result['plan']
    asyncio.run(scenario())


def test_ambiguous_and_stale_edits_do_not_commit():
    async def scenario():
        saved=await initial()
        for question,version in [('换一个',1),('把元创方换成大馆',0)]:
            result,cp=await conditional_turn(question,None,saved,Settings(),False,lookup=no_lookup,
                                            expected_version=version,model=ModelStub())
            assert result['answer']['kind']=='clarify' and not result['plan_changed']
            assert cp['journey_plan']==saved['checkpoint']['journey_plan'] and result['plan_version']==1
    asyncio.run(scenario())


def test_discussed_place_reference_is_resolved_without_adding_it():
    async def scenario():
        saved=await initial();saved['checkpoint']['discussed_place_ids']=['tai-kwun']
        result,cp=await conditional_turn('它以前是什么？',None,saved,Settings(),False,lookup=no_lookup,model=ModelStub())
        queries=[t.get('query','') for t in result['trace'] if t['tool'].startswith('retrieve_')]
        assert any('大馆' in q for q in queries)
        assert not result['plan_changed'] and cp['journey_plan']==saved['checkpoint']['journey_plan']
    asyncio.run(scenario())


def test_rag_retries_and_never_returns_an_unverified_model_claim():
    model=ModelStub({'assess_evidence':Assessment(sufficient=True),
        'generate_grounded_answer':lambda p:GroundedAnswer(text='Unsupported claim ['+p['evidence'][0]['id']+']',
                                                           citations=[p['evidence'][0]['id']]),
        'verify_grounded_answer':Verification(supported=False,covers_question=False,missing='Architectural history')})
    result=asyncio.run(agentic_answer('PMQ history',['pmq'],model,Settings(),no_lookup))
    assert result['round']==3
    assert 'Unsupported claim' not in result['answer']['text']
    assert not result['answer']['model_output_accepted']
    assert len([t for t in result['trace'] if t['tool'].startswith('retrieve_')])<=3


def test_approved_paragraph_retrieval_keeps_page_and_source_metadata():
    records=documents()
    assert not any(r.get('review_required') for r in records)
    evidence,meta=retrieve_documents('PMQ heritage impact assessment',['pmq'])
    assert evidence and all(r['place_id']=='pmq' and r['source_url'] for r in evidence)
    assert any(r.get('page_number') for r in evidence)
    assert meta['embedding_used'] is False


def test_mixed_question_and_edit_returns_evidence_and_updates_one_version():
    async def scenario():
        saved=await initial()
        result,cp=await conditional_turn('大馆是什么地方？顺便把大馆加到第二天',None,saved,Settings(),False,
                                        lookup=no_lookup,model=ModelStub())
        assert result['plan_changed'] and result['plan_version']==2 and result['evidence']
        assert 'tai-kwun' in [stop['place']['id'] for stop in cp['journey_plan']['days'][1]['stops']]
    asyncio.run(scenario())


def test_recall_of_current_schedule_uses_state_without_changing_it():
    async def scenario():
        saved=await initial()
        result,cp=await conditional_turn('当前行程第二天去哪？',None,saved,Settings(),False,
                                        lookup=no_lookup,model=ModelStub())
        assert any(row.get('evidence_type')=='current_itinerary' for row in result['evidence'])
        assert not result['plan_changed'] and cp['journey_plan']==saved['checkpoint']['journey_plan']
    asyncio.run(scenario())


def test_unlocated_external_addition_keeps_the_existing_plan():
    async def scenario():
        saved=await initial()
        result,cp=await conditional_turn('Add K11 MUSEA',None,saved,Settings(),False,
                                        lookup=no_lookup,model=ModelStub())
        assert not result['plan_changed'] and result['plan_version']==1
        assert cp['journey_plan']==saved['checkpoint']['journey_plan']
    asyncio.run(scenario())


def test_api_restores_current_plan_after_a_read_only_turn(tmp_path,monkeypatch):
    monkeypatch.setattr(chat,'store',HistoryStore(tmp_path/'conversations.sqlite3'))
    with TestClient(app) as client:
        initial_response=client.post('/api/chat',json={'question':'Plan my trip','workflow':'conditional',
            'action':'create_plan','trip':{'days':1,'must_visit':['pmq'],'only_selected':True}})
        assert initial_response.status_code==200
        first=initial_response.json();cid=first['conversation_id']
        result=client.post('/api/chat',json={'question':'PMQ的历史是什么？','workflow':'conditional',
            'conversation_id':cid,'expected_plan_version':1}).json()
        assert result['route']=='travel_question' and result['plan'] is None
        restored=client.post('/api/history/read',json={'id':cid}).json()
        assert restored['checkpoint']['journey_plan']==first['plan']
        assert restored['checkpoint']['plan_version']==1


@pytest.mark.parametrize('question,proposed,expected',[
    ('把我的行程改成3天，出发日期不变。',{'days':3,'end_date':'2026-11-13'},3),
    ('再多玩两天，出发日期不变。',{'days':2,'end_date':'2026-11-11'},4),
])
def test_explicit_duration_uses_server_arithmetic_instead_of_model_calendar(question,proposed,expected):
    async def scenario():
        first,cp=await conditional_turn('Plan my trip',{'days':2,'start_date':'2026-11-10','end_date':'2026-11-11'},
            None,Settings(),False,lookup=no_lookup,action='create_plan',model=ModelStub())
        model=ModelStub({'route_message':RouteDecision(route='modify_itinerary',standalone_question=question,changes=proposed)})
        result,cp=await conditional_turn(question,None,{'checkpoint':cp,'turns':[{'question':'Plan my trip','result':first}]},
            Settings(),True,lookup=no_lookup,model=model)
        assert result['plan_changed'] and len(result['plan']['days'])==expected
        assert cp['trip']['days']==expected and cp['trip']['start_date']=='2026-11-10'
        assert cp['trip']['end_date']==f'2026-11-{9+expected:02d}'
    asyncio.run(scenario())


def test_category_retrieval_never_substitutes_streets_for_malls():
    malls,_=retrieve_documents('香港商场',settings=RetrievalSettings(),category='mall')
    assert malls==[]
    museums,_=retrieve_documents('香港博物馆',settings=RetrievalSettings(),category='museum')
    assert museums and all(matches_category(get_place(row['place_id']),'museum') for row in museums)


def test_mall_recommendation_uses_map_and_filters_non_malls_before_limiting():
    calls=[]
    async def lookup(query,settings):
        calls.append(query)
        rows=[{'name':name,'category':category,'map_url':'https://example.org/map',
               'address':'香港','source':{'name':'Fixture map'}} for name,category in
              [('女人街','购物街'),('商场停车场','停车场'),('甲购物中心','商场'),('乙购物中心','商场'),('丙购物中心','商场')]]
        return {'mode':'live','results':rows}
    model=ModelStub({'assess_evidence':Assessment(sufficient=True),
        'generate_grounded_answer':lambda payload:GroundedAnswer(
            text='\n'.join(row['title']+' ['+row['id']+']' for row in payload['evidence']),
            citations=[row['id'] for row in payload['evidence']]),
        'verify_grounded_answer':Verification(supported=True,covers_question=True)})
    result=asyncio.run(agentic_answer('推荐香港三个商场，告诉我名称和地区',[],model,
        Settings(amap_api_key='fixture-only'),lookup))
    assert calls==['香港 商场']
    assert result['answer']['model_output_accepted'] and len(result['evidence'])==3
    assert all('购物中心' in row['title'] for row in result['evidence'])


@pytest.mark.parametrize('explicit_mode', [None, True, False])
def test_configured_model_is_automatic_even_for_an_old_offline_conversation(tmp_path,monkeypatch,explicit_mode):
    import app as application
    from travel.core.model import WorkflowModel
    from travel.workflows import conditional

    archive=HistoryStore(tmp_path/'conversations.sqlite3')
    saved=asyncio.run(initial())
    cid=archive.save(None,saved['turns'],saved['checkpoint'],False,'Old local conversation')
    monkeypatch.setattr(chat,'store',archive)
    monkeypatch.setattr(application,'settings',Settings(model_api_key='fixture-only'))
    requests=[]

    def provider(request):
        messages=json.loads(request.content)['messages']
        requests.append(messages)
        if 'Classify intent' in messages[0]['content']:
            content={'route':'general_chat','standalone_question':'Tell me a joke'}
        else:
            content={'text':'A fixture joke from the model.','citations':[]}
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(content)}}]})

    monkeypatch.setattr(conditional,'WorkflowModel',lambda settings,enabled:
        WorkflowModel(settings,enabled,httpx.MockTransport(provider)))
    payload={'question':'Tell me a joke','workflow':'conditional','language':'en','conversation_id':cid}
    if explicit_mode is not None:
        payload['use_model']=explicit_mode
    with TestClient(app) as client:
        response=client.post('/api/chat',json=payload)
    assert response.status_code==200
    result=response.json()
    assert result['route']=='general_chat' and not result['plan_changed']
    assert archive.get(cid)['checkpoint']['journey_plan']==saved['checkpoint']['journey_plan']
    if explicit_mode is False:
        assert not requests and archive.get(cid)['use_model'] is False
    else:
        assert len(requests)==2
        assert result['answer']['text']=='A fixture joke from the model.'
        assert archive.get(cid)['use_model'] is True
