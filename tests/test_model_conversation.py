"""Mock model semantics + real state/tool execution; not a model accuracy benchmark."""
import asyncio,json
import httpx,pytest
from fastapi.testclient import TestClient
import app
from travel import agent,chat
from travel.agent import AgentEngine,ModelPolicy,Trip
from travel.config import Settings
from travel.conversation_memory import plan_snapshot,restore_memory,bounded_history
from travel.itinerary_edits import revise_plan
from travel.planner import plan
from travel.history import HistoryStore
from tests.test_agent import fixture_tool

def call(name,**args):return {'tool_calls':[{'type':'function','function':{'name':name,'arguments':json.dumps(args,ensure_ascii=False)}}]}
def final(text='已完成本轮修改。',kind='ack',citations=None):return {'content':json.dumps({'kind':kind,'text':text,'citations':citations or []},ensure_ascii=False)}

def engine_with(queue,payloads):
    def handler(req):
        payloads.append(json.loads(req.content))
        return httpx.Response(200,json={'choices':[{'message':queue.pop(0)}]})
    settings=Settings(model_api_key='fixture-only')
    engine=AgentEngine(settings,tool_call=fixture_tool)
    engine.policy=ModelPolicy(settings,httpx.MockTransport(handler))
    return engine

def test_model_uses_history_and_edits_without_keyword_parser(monkeypatch):
    def forbidden(*args):pytest.fail('model mode must not use keyword interpretation')
    monkeypatch.setattr(agent,'extract_patch',forbidden);monkeypatch.setattr(agent,'resolve_reference',forbidden)
    queue=[];payloads=[];engine=engine_with(queue,payloads)
    async def scenario():
        queue.extend([call('search_places',query='海边'),final('星光大道可看海港 [avenue-stars]，西九艺术公园可散步 [art-park]。','answer',['avenue-stars','art-park'])])
        first=await engine.turn('s','想吹吹海风，有什么选择')
        queue.extend([call('update_trip',changes={'days':3,'must_visit':['avenue-stars','art-park'],'only_selected':True},notes=['与父母同行，偏好轻松']),call('plan_itinerary'),final()])
        second=await engine.turn('s','挑你讲的两处，爸妈同行，分成三天慢慢来')
        assert second['trip']['days']==3 and second['plan']['days'][0]['stops'] and second['plan']['days'][2]['stops']
        queue.extend([call('revise_itinerary',edits=[{'action':'move','place_id':pid,'day':2} for pid in ['avenue-stars','art-park']]),final()])
        third=await engine.turn('s','其余不动，把它们都挪到中间那天')
        assert len(third['plan']['days'][1]['stops'])==2 and not third['plan']['days'][0]['stops'] and not third['plan']['days'][2]['stops']
        assert len(third['plan']['days'][1]['legs'])==1
        queue.extend([call('update_trip',changes={'must_visit':['avenue-stars','hkmoa'],'excluded_places':['art-park']}),call('revise_itinerary',edits=[{'action':'replace','place_id':'art-park','replacement_id':'hkmoa'}]),final()])
        fourth=await engine.turn('s','后面那个换成香港艺术馆，别再把公园加回来')
        assert [stop['place']['id'] for stop in fourth['plan']['days'][1]['stops']]==['avenue-stars','hkmoa']
        checkpoint=(await engine.graph.aget_state({'configurable':{'thread_id':'s'}})).values
        resumed=engine_with(queue,payloads)
        await resumed.graph.aupdate_state({'configurable':{'thread_id':'s'}},checkpoint,as_node='finish')
        queue.extend([call('revise_itinerary',edits=[{'action':'swap_days','day':1,'other_day':2}]),final()])
        fifth=await resumed.turn('s','前两天互换，剩下的照旧')
        assert len(fifth['plan']['days'][0]['stops'])==2 and not fifth['plan']['days'][1]['stops']
        assert fifth['memory_notes']==['与父母同行，偏好轻松'] and fifth['trip']['excluded_places']==['art-park']
        system=payloads[-2]['messages'][0]['content']
        assert '与父母同行' in system and 'hkmoa' in system and 'place_ids' in system
        assert any('吹吹海风' in str(message) for message in payloads[-1]['messages'])
        assert first['answer']['model_output_accepted'] and all(row['status']=='success' for row in fourth['trace'])
    asyncio.run(scenario())

def test_model_clarification_is_not_discarded_or_sent_to_maps(tmp_path,monkeypatch):
    queue=[final('你指哪两个地点？请告诉我名称。','clarify')];payloads=[]
    monkeypatch.setattr(app,'settings',Settings(model_api_key='fixture-only'))
    monkeypatch.setattr(chat,'store',HistoryStore(tmp_path/'db'));monkeypatch.setattr(chat,'locks',{})
    monkeypatch.setattr(chat,'AgentEngine',lambda *args:engine_with(queue,payloads))
    async def forbidden(*args):pytest.fail('a clarification must not query AMap')
    monkeypatch.setattr(chat,'resolve_place',forbidden)
    with TestClient(app.app) as client:r=client.post('/api/chat',json={'question':'照之前那样吧','use_model':True})
    assert r.status_code==200
    assert r.json()['answer']['kind']=='clarify' and '哪两个' in r.json()['answer']['text']
    assert not r.json()['plan'] and len(payloads)==1

def test_model_updates_calendar_and_rejects_invalid_changes():
    queue=[call('update_trip',changes={'days':4}),call('plan_itinerary'),final()];engine=engine_with(queue,[])
    async def scenario():
        r=await engine.turn('s','多留一阵子',Trip(start_date='2026-10-24',end_date='2026-10-25').model_dump())
        assert r['trip']['end_date']=='2026-10-27' and len(r['plan']['days'])==4
        queue.extend([call('update_trip',changes={'must_visit':['unknown-id']}),final('地点尚未识别，请明确名称。','clarify')])
        bad=await engine.turn('s','换个没收录的地方')
        assert bad['trip']==r['trip'] and bad['trace'][0]['status']=='error'
        assert bad['answer']['kind']=='clarify'
    asyncio.run(scenario())


@pytest.mark.parametrize('question',['明天开始，照刚才的排','天气不好就把公园换掉','第二天几点出门比较好'])
def test_contextual_date_weather_and_time_questions_reach_model(question):
    queue=[final('请先确认想调整的日期和地点。','clarify')];payloads=[]
    result=asyncio.run(engine_with(queue,payloads).turn('s',question))
    assert len(payloads)==1 and result['answer']['kind']=='clarify'


def test_model_can_recall_preferences_without_making_new_changes():
    queue=[call('read_itinerary'),final('你之前说与父母同行，第二天保留休息。')];payloads=[];engine=engine_with(queue,payloads)
    async def scenario():
        trip=Trip(days=2,must_visit=['avenue-stars'],only_selected=True).model_dump()
        await engine.graph.aupdate_state({'configurable':{'thread_id':'s'}},{'trip':trip,'plan_context':plan_snapshot(plan(**trip)),'memory_notes':['与父母同行']},as_node='finish')
        result=await engine.turn('s','我忘了第二天怎么安排，还跟谁去？')
        assert result['answer']['model_output_accepted'] and '父母' in result['answer']['text']
        assert not result['plan'] and result['trip']==trip
    asyncio.run(scenario())


def test_model_can_reference_excluded_places_when_recalling_preferences():
    queue=[call('read_itinerary'),final('之前说与父母同行，不再去西九艺术公园 [art-park]。',citations=['art-park'])];engine=engine_with(queue,[])
    async def scenario():
        trip=Trip(days=2,excluded_places=['art-park']).model_dump()
        await engine.graph.aupdate_state({'configurable':{'thread_id':'s'}},{'trip':trip,'memory_notes':['与父母同行']},as_node='finish')
        result=await engine.turn('s','我说过不去哪里？')
        assert result['answer']['model_output_accepted'] and result['answer']['citations']==['art-park']
    asyncio.run(scenario())


def test_model_json_mode_and_fenced_output_are_validated():
    message=final('请确认是哪一处。','clarify');message['content']='```json\n'+message['content']+'\n```'
    queue=[message];payloads=[]
    result=asyncio.run(engine_with(queue,payloads).turn('s','那边呢'))
    assert payloads[0]['response_format']=={'type':'json_object'} and result['answer']['kind']=='clarify'


def test_plain_text_final_has_one_format_retry_without_repeating_tools():
    queue=[call('update_trip',changes={'days':2}),{'content':'已记下两天。'},final('已记下两天。')];payloads=[]
    result=asyncio.run(engine_with(queue,payloads).turn('s','留两天'))
    assert result['answer']['model_output_accepted'] and result['trip']['days']==2
    assert result['metrics']['format_repairs']==1 and result['metrics']['model_calls']==3
    assert 'tools' not in payloads[-1] and len(result['trace'])==1


def test_successful_model_updates_survive_later_timeout(monkeypatch):
    queue=[call('update_trip',changes={'days':2},notes=['与父母同行'])];engine=engine_with(queue,[])
    policy=engine.policy
    async def choose(state):
        if state['tool_calls']:await asyncio.sleep(10)
        return await policy(state)
    engine.policy=choose;monkeypatch.setattr(agent,'TURN_TIMEOUT',.1)
    result=asyncio.run(engine.turn('s','爸妈想慢慢逛'))
    assert result['stop_reason']=='timeout' and result['trip']['days']==2 and result['memory_notes']==['与父母同行']


def test_restore_memory_keeps_latest_plan_after_detail_and_bounds_history():
    saved={'checkpoint':{'memory_notes':['与父母同行']},'turns':[{'question':'安排行程','result':{'plan':plan(days=2),'answer':{'text':'草案'}}},{'question':'第二个有什么特色','result':{'answer':{'text':'介绍'}}}]}
    memory=restore_memory(saved)
    assert memory['plan_context']['days_requested']==2 and memory['memory_notes']==['与父母同行']
    assert len(bounded_history([{'role':'user','content':'字'*4000}]*100))==6
    assert plan_snapshot({'days':[{'place_ids':['not-local']} ]}) is None


@pytest.mark.parametrize('edits',[[{'action':'move','place_id':'art-park','day':3}],[{'action':'remove','place_id':'art-park'}],[{'action':'replace','place_id':'art-park','replacement_id':'avenue-stars'}],[{'action':'remove','place_id':'art-park','day':1}]])
def test_edits_reject_out_of_range_missing_must_duplicate_and_wrong_day(edits):
    trip=Trip(days=2,must_visit=['avenue-stars','art-park'],only_selected=True).model_dump()
    with pytest.raises(ValueError):revise_plan(plan(**trip),trip,edits)


def test_edit_remove_and_add_keeps_other_days_and_recalculates():
    trip=Trip(days=2,must_visit=['avenue-stars','art-park'],only_selected=True).model_dump();previous=plan(**trip)
    trip.update(must_visit=['avenue-stars'],only_selected=False,excluded_places=['art-park'])
    revised=revise_plan(previous,trip,[{'action':'remove','place_id':'art-park'},{'action':'add','place_id':'hkmoa','day':1}])
    assert [stop['place']['id'] for stop in revised['days'][0]['stops']]==['avenue-stars','hkmoa']
    assert len(revised['days'])==2 and revised['days'][1]['kind']=='flex'
    assert revised['days'][0]['transfer_minutes']>0 and revised['days'][0]['end']!='11:00'
    assert all('art-park'!=stop['place']['id'] for day in plan(**trip)['days'] for stop in day['stops'])


def test_rename_survives_stale_save_and_preserves_flags(tmp_path):
    store=HistoryStore(tmp_path/'db');cid=store.save(None,[],{},False,'旧名称')
    before=store.list()[0]['updated'];store.update_flags(cid,pinned=True,favorite=True)
    store.rename(cid,'  周末和爸妈看海  ')
    assert store.list()[0]['updated']==before
    store.save(cid,[{'question':'继续'}],{},False,'旧名称')
    restored=HistoryStore(store.path).get(cid)
    assert restored['title']=='周末和爸妈看海' and restored['title_is_custom']
    assert restored['pinned'] and restored['favorite']


@pytest.mark.parametrize('name',['','   ','字'*61,'含\n换行','含\x00字符'])
def test_rename_validation(tmp_path,name):
    store=HistoryStore(tmp_path/'db');cid=store.save(None,[],{},False,'原名')
    with pytest.raises(ValueError):store.rename(cid,name)
    assert store.get(cid)['title']=='原名'


def test_rename_api_missing_and_escaped_title(tmp_path,monkeypatch):
    store=HistoryStore(tmp_path/'db');monkeypatch.setattr(chat,'store',store)
    cid=store.save(None,[],{},False,'原名')
    with TestClient(app.app) as client:
        assert client.post('/api/history/rename',json={'id':'a'*32,'title':'新名'}).status_code==404
        assert client.post('/api/history/rename',json={'id':cid,'title':'<旅行 & 周末>'}).status_code==200
        assert client.get('/api/history').json()['conversations'][0]['title']=='<旅行 & 周末>'
