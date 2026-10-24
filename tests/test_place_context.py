import asyncio
import pytest
from fastapi.testclient import TestClient
import app
from travel import chat
from travel.agent import AgentEngine,Trip
from travel.history import HistoryStore
from travel.knowledge import get_place
from travel.place_context import clean_context,hydrate_context,resolve_reference,visible_ids
from travel.planner import plan
from tests.test_agent import fixture_tool

@pytest.fixture
def web(tmp_path,monkeypatch):
 monkeypatch.setattr(chat,'store',HistoryStore(tmp_path/'history.sqlite3'))
 monkeypatch.setattr(chat,'locks',{})
 async def forbidden(*args,**kwargs):pytest.fail('a local follow-up must never query AMap')
 monkeypatch.setattr(chat,'resolve_place',forbidden)
 with TestClient(app.app) as client:yield client

def stops(value):return [s['place']['id'] for d in value['plan']['days'] for s in d['stops']]

def first_turn(web):
 r=web.post('/api/chat',json={'question':'我想去海边玩','trip':{'start_date':'2026-10-22','end_date':'2026-10-23'}})
 assert r.status_code==200,r.text
 a=r.json();assert set(a['answer']['citations'])=={'avenue-stars','art-park'}
 return a

@pytest.mark.parametrize('question',['那我就去这两个地方','我就要去这两个地方','就选这俩','安排这两个地方','安排两天行程'])
def test_screenshot_chain_selects_exact_visible_places(web,question):
 first=first_turn(web)
 r=web.post('/api/chat',json={'question':question,'conversation_id':first['conversation_id'],'trip':first['trip']})
 assert r.status_code==200,r.text
 answer=r.json()
 assert set(stops(answer))==set(first['answer']['citations']) and len(stops(answer))==2
 assert answer['trip']['only_selected'] and answer['plan']['only_selected']
 assert answer['trip']['start_date']=='2026-10-22' and answer['trip']['end_date']=='2026-10-23'
 assert len(answer['plan']['days'])==2 and all(day['stops'] for day in answer['plan']['days'])
 assert 'external_lookup' not in answer and '已确认' in answer['answer']['text']
 assert answer['metrics']['model_calls']==0


def test_ordinals_keep_original_list_after_detail_and_new_engine(web):
 first=first_turn(web);cid=first['conversation_id'];ids=first['answer']['citations']
 for index,text in [(1,'第二个有什么特色'),(0,'那第一个呢')]:
  with TestClient(app.app) as resumed:r=resumed.post('/api/chat',json={'question':text,'conversation_id':cid})
  assert r.status_code==200,r.text
  result=r.json()
  assert result['answer']['citations']==[ids[index]]
  assert result['place_context']['listed_ids']==ids
  assert 'external_lookup' not in result
 chosen=web.post('/api/chat',json={'question':'我就去这两个地方','conversation_id':cid}).json()
 assert set(stops(chosen))==set(ids)


def test_followup_route_is_transport_not_new_search(web):
 first=first_turn(web)
 route=web.post('/api/chat',json={'question':'这两个地方之间怎么走','conversation_id':first['conversation_id']}).json()
 assert route['trace'][0]['tool']=='transfer_estimate'
 assert '屯马线' in route['answer']['text'] and 'external_lookup' not in route

@pytest.mark.parametrize('question',['我就去这两个地方','第二个呢','那几个怎么走','安排这两个地方'])
def test_reference_without_context_asks_instead_of_map_lookup(web,question):
 result=web.post('/api/chat',json={'question':question}).json()
 assert result['stop_reason']=='reference_clarify' and not result['plan']
 assert result['metrics']['tool_calls']==0 and 'external_lookup' not in result


def test_selection_before_dates_is_remembered(web):
 first=web.post('/api/chat',json={'question':'我想去海边玩'}).json()
 cid=first['conversation_id']
 selected=web.post('/api/chat',json={'question':'那就去这两个地方','conversation_id':cid}).json()
 assert selected['stop_reason']=='clarify' and selected['trip']['only_selected']
 assert set(selected['trip']['must_visit'])==set(first['answer']['citations'])
 planned=web.post('/api/chat',json={'question':'安排1天行程','conversation_id':cid}).json()
 assert set(stops(planned))==set(first['answer']['citations'])


def test_new_topic_replaces_reference_list(web):
 first=first_turn(web);cid=first['conversation_id']
 changed=web.post('/api/chat',json={'question':'香港科学馆有什么特色？','conversation_id':cid}).json()
 assert changed['place_context']['listed_ids']==['science-museum']
 selected=web.post('/api/chat',json={'question':'我就去这两个地方','conversation_id':cid}).json()
 assert selected['stop_reason']=='reference_clarify' and 'external_lookup' not in selected


def test_legacy_history_recovers_refs_after_old_pronoun_map_bug(web):
 ids=['avenue-stars','art-park']
 first={'answer':{'citations':ids,'text':'推荐两个地方'},'sources':[get_place(pid) for pid in ids],'plan':None}
 bad={'answer':{'citations':[],'text':'地图未找到'},'sources':[],'plan':None,'external_lookup':{'provider':'amap','query':'那我就去这两个地方'}}
 cid=chat.store.save(None,[{'question':'我想去海边玩','result':first},{'question':'那我就去这两个地方','result':bad}],{'trip':Trip(days=2).model_dump(),'history':[],'intent':'search'},False,'synthetic old history')
 result=web.post('/api/chat',json={'question':'我就去这两个地方','conversation_id':cid}).json()
 assert set(stops(result))==set(ids)
 assert chat.store.get(cid)['checkpoint']['place_context']['listed_ids']==ids


def test_ambiguous_subset_asks_then_ordinal_selection():
 ctx=clean_context({'listed_ids':['avenue-stars','art-park','tai-kwun','pmq']})
 assert resolve_reference('我去这两个地方',ctx)['kind']=='clarify'
 selected=resolve_reference('我选第一个和第三个',ctx)
 assert selected['ids']==['avenue-stars','tai-kwun'] and selected['kind']=='select'

def test_ordinals_follow_visible_prose_order_not_citation_array():
 ids=['avenue-stars','art-park']
 shown={'answer':{'citations':list(reversed(ids)),'text':'1. 星光大道 [avenue-stars]\n2. 西九艺术公园 [art-park]'},'sources':[get_place(pid) for pid in ids]}
 assert visible_ids(shown)==ids

def test_negative_reference_does_not_confirm_the_rejected_place():
 ctx=clean_context({'listed_ids':['avenue-stars','art-park']})
 assert resolve_reference('不要第二个',ctx)['kind']=='clarify'

@pytest.mark.parametrize('days',[1,2,5])
def test_only_selected_never_pads_and_preserves_days(days):
 result=plan(days=days,must_visit=['avenue-stars','art-park'],only_selected=True)
 assert len(result['days'])==days
 assert [s['place']['id'] for d in result['days'] for s in d['stops']]==['avenue-stars','art-park']
 for day in result['days']:
  if day['kind']=='flex':assert '未额外添加' in day['reason']


def test_selected_foods_work_without_adding_attractions():
 result=plan(days=2,must_visit=['lan-fong-yuen','hing-kee'],only_selected=True)
 assert len(result['days'])==2
 assert {s['place']['id'] for d in result['days'] for s in d['stops']}=={'lan-fong-yuen','hing-kee'}


def test_context_rejects_unknown_ids_and_never_leaks_between_sessions():
 assert clean_context({'listed_ids':['.env','unknown','avenue-stars']})['listed_ids']==['avenue-stars']
 async def check():
  engine=AgentEngine(tool_call=fixture_tool)
  await engine.turn('first','我想去海边玩')
  result=await engine.turn('second','我就去这两个地方')
  assert result['stop_reason']=='reference_clarify' and not result['trip']['must_visit']
 asyncio.run(check())


def test_explicit_choice_uses_names_and_exact_only_mode(web):
 result=web.post('/api/chat',json={'question':'我就去星光大道和西九艺术公园，安排一天'}).json()
 assert set(stops(result))=={'avenue-stars','art-park'} and len(stops(result))==2


def test_selected_constraints_do_not_silently_relax(web):
 first=first_turn(web);cid=first['conversation_id']
 selected=web.post('/api/chat',json={'question':'就去这两个地方','conversation_id':cid}).json()
 result=web.post('/api/chat',json={'question':'改成只选室内','conversation_id':cid}).json()
 assert result['plan'] is None and result['stop_reason']=='tool_error'
 assert result['trip']['must_visit']==selected['trip']['must_visit'] and result['trip']['only_selected']
 assert 'external_lookup' not in result
