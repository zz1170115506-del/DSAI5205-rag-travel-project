import asyncio
import pytest
from fastapi.testclient import TestClient
import app
from travel.agent import AgentEngine, Trip, extract_patch
from travel.planner import plan
from travel.trip_dates import resolve_dates
from tests.test_agent import fixture_tool

@pytest.mark.parametrize('start,end,count',[
 ('2026-10-24','2026-10-24',1),('2026-10-24','2026-10-26',3),
 ('2026-10-31','2026-11-01',2),('2026-12-31','2027-01-01',2),
 ('2028-02-28','2028-03-01',3)])
def test_inclusive_dates(start,end,count):
 assert resolve_dates(None,start,end)==count
 trip=Trip(start_date=start,end_date=end)
 assert trip.days==count
 result=plan(start_date=start,end_date=end)
 assert result['days_requested']==count
 assert result['days'][0]['date']==start
 assert result['days'][-1]['date']==end
 assert result['days'][0]['weekday'].startswith('周')

@pytest.mark.parametrize('start,end',[
 ('2026-10-24',None),(None,'2026-10-24'),('2026-10-25','2026-10-24'),
 ('2026-10-24','2027-10-25'),('2026-02-30','2026-03-01'),
 ('2026-1-01','2026-01-02'),('','')])
def test_invalid_ranges(start,end):
 with pytest.raises(ValueError):Trip(start_date=start,end_date=end)


def test_mismatch_and_legacy():
 with pytest.raises(ValueError):Trip(days=1,start_date='2026-10-24',end_date='2026-10-26')
 assert plan()['days_requested']==2
 assert plan(days=1)['start_date'] is None
 assert plan(days=1)['days'][0]['date'] is None
 assert Trip(days=2).start_date is None


def test_patch_and_followup():
 assert extract_patch('请安排2026-10-24至2026-10-26的3天行程')['end_date']=='2026-10-26'
 async def check():
  engine=AgentEngine(tool_call=fixture_tool)
  first=await engine.turn('date-test','安排2026-10-24至2026-10-26的3天行程')
  assert first['trip']['days']==3
  second=await engine.turn('date-test','改成只选室内')
  assert second['trip']['start_date']=='2026-10-24'
  assert second['trip']['end_date']=='2026-10-26'
  third=await engine.turn('date-test','改成1天')
  assert third['trip']['end_date']=='2026-10-24'
  fourth=await engine.turn('date-test','改成2026-11-01至2026-11-02')
  assert fourth['trip']['days']==2
  assert fourth['plan']['days'][0]['date']=='2026-11-01'
 asyncio.run(check())


def test_dates_api_real_stdio():
 with TestClient(app.app) as client:
  r=client.post('/api/plan',json={'start_date':'2026-10-31','end_date':'2026-11-01'})
  assert r.status_code==200,r.text
  data=r.json()
  assert data['days_requested']==2
  assert data['days'][1]['date']=='2026-11-01'
  assert data['trace'][0]['transport']=='stdio'
  assert client.post('/api/plan',json={'start_date':'2026-10-31'}).status_code==422
  assert client.post('/api/plan',json={'start_date':'2026-10-31','end_date':'2027-11-01'}).status_code==422


@pytest.mark.parametrize('count',[4,7,10,14,30,99,366])
def test_long_dates_cover_every_day_without_duplicates(count):
 from travel.trip_dates import date_for_day
 start='2026-10-24';end=date_for_day(start,count-1)
 result=plan(start_date=start,end_date=end)
 assert result['days_requested']==count==len(result['days'])
 assert [d['date'] for d in result['days']]==[date_for_day(start,i) for i in range(count)]
 ids=[s['place']['id'] for d in result['days'] for s in d['stops']]
 assert len(ids)==len(set(ids))
 assert result['coverage']['unique_places']==len(ids)
 assert result['coverage']['sightseeing_days']+result['coverage']['flex_days']==count
 assert result['days'][0]['stops'] and result['days'][-1]['stops']
 for day in result['days']:
  if day['kind']=='flex':
   assert day['activities'] and day['reason'] and day['start_guide'] is None
   assert day['stops']==day['legs']==[]
  else:assert day['stops']

@pytest.mark.parametrize('text,count',[('四天行程',4),('安排11天',11),('十天',10),('十四天',14),('三十天',30),('三百六十六天',366)])
def test_multiday_numeric_and_chinese_days(text,count):
 assert extract_patch(text)['days']==count


def test_narrow_filter_keeps_all_dates_without_relaxing():
 result=plan(start_date='2026-10-24',end_date='2026-11-06',region='大屿山',must_visit=['tai-o'])
 assert len(result['days'])==14
 stops=[s for d in result['days'] for s in d['stops']]
 assert all(s['place']['region']=='大屿山' for s in stops)
 assert 'tai-o' in {s['place']['id'] for s in stops}
 assert result['coverage']['flex_days']>0


def test_long_range_real_stdio_and_capacity():
 with TestClient(app.app) as client:
  r=client.post('/api/plan',json={'start_date':'2026-10-24','end_date':'2026-11-06'})
  assert r.status_code==200,r.text
  assert len(r.json()['days'])==14
  assert r.json()['days'][-1]['date']=='2026-11-06'
  assert r.json()['trace'][0]['transport']=='stdio'
  assert client.post('/api/plan',json={'days':367}).status_code==422
  assert client.get('/api/status').json()['max_trip_days']==366


def test_long_chat_history_and_date_followup(tmp_path,monkeypatch):
 from travel import chat
 from travel.history import HistoryStore
 monkeypatch.setattr(chat,'store',HistoryStore(tmp_path/'history.sqlite3'))
 monkeypatch.setattr(chat,'locks',{})
 with TestClient(app.app) as client:
  r=client.post('/api/chat',json={'question':'请安排2026-10-24至2026-11-06的14天行程'})
  assert r.status_code==200,r.text
  first=r.json();cid=first['conversation_id']
  assert len(first['plan']['days'])==14
  r=client.post('/api/chat',json={'question':'改成只选室内','conversation_id':cid})
  assert r.status_code==200,r.text
  second=r.json()
  assert second['trip']['end_date']=='2026-11-06'
  assert len(second['plan']['days'])==14
  assert all(s['place']['indoor'] for d in second['plan']['days'] for s in d['stops'])
  saved=client.post('/api/history/read',json={'id':cid}).json()
  assert len(saved['turns'][-1]['result']['plan']['days'])==14
  assert saved['turns'][-1]['result']['plan']['days'][-1]['date']=='2026-11-06'
  r=client.post('/api/chat',json={'question':'改成10天','conversation_id':cid})
  assert r.status_code==200,r.text
  assert r.json()['trip']['end_date']=='2026-11-02'
  assert len(r.json()['plan']['days'])==10


def test_long_tool_observation_is_valid_bounded_json():
 import json
 async def check():
  observations=[]
  async def policy(state):
   if state['tool_calls']:
    observations.extend(m['content'] for m in state['messages'] if m['role']=='tool')
    return {'final':{'text':'','citations':[]}}
   return {'tool':'plan_itinerary','args':{}}
  engine=AgentEngine(policy=policy,tool_call=fixture_tool)
  result=await engine.turn('long-model-observation','安排366天行程')
  assert len(result['plan']['days'])==366
  payload=observations[0]
  value=json.loads(payload)
  assert len(payload)<16000 and len(value['day_preview'])==7
  assert value['coverage']['calendar_days']==366
 asyncio.run(check())


def test_plan_conflict_never_falls_back_to_external_map(tmp_path,monkeypatch):
 from travel import chat
 from travel.history import HistoryStore
 monkeypatch.setattr(chat,'store',HistoryStore(tmp_path/'history.sqlite3'))
 monkeypatch.setattr(chat,'locks',{})
 async def forbidden(*args,**kwargs):pytest.fail('a failed plan must not trigger POI search')
 monkeypatch.setattr(chat,'resolve_place',forbidden)
 with TestClient(app.app) as client:
  first=client.post('/api/chat',json={'question':'安排2026-10-24至2026-11-06的14天行程',
       'trip':{'must_visit':['nan-lian']}})
  assert first.status_code==200,first.text
  second=client.post('/api/chat',json={'question':'改成只选室内','conversation_id':first.json()['conversation_id']})
  assert second.status_code==200,second.text
  result=second.json()
  assert result['plan'] is None and result['stop_reason']=='tool_error'
  assert 'external_lookup' not in result
  assert '调整' in result['answer']['text']
  assert result['trip']['must_visit']==['nan-lian']
  assert result['trip']['end_date']=='2026-11-06'
