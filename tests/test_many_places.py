"""Selection coverage and stateful edits; fixtures are not model accuracy claims."""
import asyncio
from collections import Counter
import pytest
from fastapi.testclient import TestClient
import app
from travel.agent import Trip,TripPatch,validate_trip,AgentEngine
from travel.knowledge import places
from travel.mcp_client import local_call
from travel.planner import plan
from travel.place_context import resolve_reference,clean_ids
from tests.test_agent import fixture_tool
from tests.test_model_conversation import engine_with,call,final

FOUR=['escalator','pmq','lan-fong-yuen','zoological-gardens']
def ids(result):return [s['place']['id'] for d in result['days'] for s in d['stops']]

@pytest.mark.parametrize('only',[True,False])
def test_four_places_are_never_dropped(only):
 result=plan(days=2,must_visit=FOUR,only_selected=only)
 assert set(FOUR)<=set(ids(result)) and len(ids(result))==len(set(ids(result)))
 if only:assert Counter(ids(result))==Counter(FOUR)

@pytest.mark.parametrize('pace,days',[('轻松',14),('充实',12)])
def test_all_catalog_places_can_be_selected_and_spread(pace,days):
 selected=[p['id'] for p in places()]
 trip=validate_trip(Trip(days=days,pace=pace,must_visit=selected,only_selected=True).model_dump())
 assert TripPatch(must_visit=selected).must_visit==selected
 assert clean_ids(selected)==selected
 result=plan(**trip)
 assert Counter(ids(result))==Counter(selected)
 assert all(len(d['stops'])<=(3 if pace=='轻松' else 4) for d in result['days'])


def test_short_calendar_reports_capacity_without_truncating():
 with pytest.raises(ValueError,match='至少需要'):
  plan(days=1,must_visit=FOUR,only_selected=True)


def test_reference_selection_accepts_four_and_explicit_names():
 context={'listed_ids':FOUR,'focus_ids':FOUR,'kind':'recommendation'}
 assert resolve_reference('就去这四个地方',context)['ids']==FOUR
 assert set(resolve_reference('只去中环至半山自动扶梯、元创方 PMQ、兰芳园、香港动植物公园',{})['ids'])==set(FOUR)


def test_api_and_real_stdio_accept_four_selected_places():
 with TestClient(app.app) as web:
  response=web.post('/api/plan',json={'days':2,'must_visit':FOUR,'only_selected':True})
 assert response.status_code==200 and Counter(ids(response.json()))==Counter(FOUR)
 result,trace=asyncio.run(local_call('plan_itinerary',Trip(days=2,must_visit=FOUR,only_selected=True).model_dump()))
 assert Counter(ids(result))==Counter(FOUR) and trace['transport']=='stdio'


def test_four_place_model_selection_modify_and_restore():
 queue=[call('update_trip',changes={'must_visit':FOUR,'only_selected':True},notes=['与爸妈同行，轻松']),final('已记下四处，请问玩几天？','clarify')]
 engine=engine_with(queue,[])
 async def scenario():
  first=await engine.turn('many','先选这四个，和爸妈一起')
  queue.extend([call('update_trip',changes={'days':2}),call('plan_itinerary'),final()])
  planned=await engine.turn('many','玩两天')
  assert planned['stop_reason']=='complete' and Counter(ids(planned['plan']))==Counter(FOUR)
  updated=['tai-kwun' if p=='pmq' else p for p in FOUR]
  queue.extend([call('update_trip',changes={'must_visit':updated,'excluded_places':['pmq']}),call('revise_itinerary',edits=[{'action':'replace','place_id':'pmq','replacement_id':'tai-kwun'}]),final()])
  changed=await engine.turn('many','元创方换成大馆，旧的不要再排')
  assert Counter(ids(changed['plan']))==Counter(updated)
  checkpoint=(await engine.graph.aget_state({'configurable':{'thread_id':'many'}})).values
  resumed=engine_with(queue,[])
  await resumed.graph.aupdate_state({'configurable':{'thread_id':'many'}},checkpoint,as_node='finish')
  queue.extend([call('revise_itinerary',edits=[{'action':'swap_days','day':1,'other_day':2}]),final()])
  swapped=await resumed.turn('many','前后两天互换，其他不动')
  assert ids({'days':[swapped['plan']['days'][0]]})==ids({'days':[changed['plan']['days'][1]]})
  assert swapped['trip']['excluded_places']==['pmq'] and len(swapped['trip']['must_visit'])==4
  assert all(t['status']=='success' for t in swapped['trace'])
 asyncio.run(scenario())


def test_invalid_model_clarification_keeps_selection_and_asks_duration():
 queue=[final('请确认营业时间。','clarify')]
 result=asyncio.run(engine_with(queue,[]).turn('missing-days','把它们串起来',Trip(must_visit=FOUR,only_selected=True).model_dump()))
 assert '4 个地点' in result['answer']['text'] and '几天' in result['answer']['text']
 assert '可以先考虑' not in result['answer']['text'] and not result['plan']
