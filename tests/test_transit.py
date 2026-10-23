"""Curated topology regression: not a real-time navigation accuracy benchmark."""
import copy
import json

import pytest
from fastapi.testclient import TestClient

import app
from travel import chat
from travel.agent import Trip, extract_patch
from travel.history import HistoryStore
from travel.knowledge import places
from travel.planner import estimate_transfer, plan
from travel.transit import access_for, enrich_plan, from_station, rail_path, rail_steps, transit_data


def test_all_local_places_have_source_backed_exit_or_connector():
    assert set(transit_data()['access'])=={p['id'] for p in places()}
    for p in places():
        access=access_for(p['id'])
        assert access['options'] and access['checked']=='2026-10-22'
        assert all(o['exit'] and o['station'] and o['sources'] for o in access['options'])
        assert all(s['url'].startswith('https://') for s in access['sources'])


def test_direct_cross_harbour_route_has_correct_direction_and_stop_count():
    guide=from_station('尖沙咀','tai-kwun')
    rides=[s for s in guide['steps'] if s['kind']=='ride']
    assert len(rides)==1
    assert rides[0]['line_id']=='TWL' and rides[0]['direction']=='中环'
    assert rides[0]['stations']==['尖沙咀','金钟','中环'] and rides[0]['stop_count']==2
    assert any(s['kind']=='exit' and s['station']=='中环' and s['exit']=='D1' for s in guide['steps'])
    assert not guide['live']


def test_interchange_route_includes_transfer_direction_and_destination_exit():
    guide=from_station('尖沙咀','nan-lian')
    transfers=[s for s in guide['steps'] if s['kind']=='transfer']
    assert len(transfers)==1 and transfers[0]['station'] in {'太子','旺角'}
    rides=[s for s in guide['steps'] if s['kind']=='ride']
    assert [s['line_id'] for s in rides]==['TWL','KTL']
    assert rides[-1]['direction']=='调景岭' and rides[-1]['to']=='钻石山'
    assert any(s['kind']=='exit' and s['exit']=='C2' for s in guide['steps'])


def test_return_direction_and_last_mile_are_not_reused_from_outbound():
    steps=rail_steps(rail_path('钻石山','尖沙咀'))
    rides=[s for s in steps if s['kind']=='ride']
    assert rides[0]['direction']=='黄埔' and rides[-1]['direction']=='中环'
    assert rides[0]['from']=='钻石山' and rides[-1]['to']=='尖沙咀'


def test_walk_interchanges_explicitly_describe_gate_difference():
    steps=rail_steps(rail_path('尖沙咀','尖东'))
    assert len(steps)==1 and steps[0]['kind']=='station_walk'
    assert '出入闸' in steps[0]['text']
    central=rail_steps(rail_path('中环','香港'))
    assert any(s['kind']=='station_walk' for s in central)


def test_peak_and_lantau_do_not_fabricate_mtr_stations():
    peak=estimate_transfer('pmq','peak')['transit_guide']
    assert any(s['kind']=='tram' for s in peak['steps']) and not any(s['kind']=='ride' for s in peak['steps'])
    for a,b in [('tai-o','big-buddha'),('ngong-ping','tai-o')]:
        guide=estimate_transfer(a,b)['transit_guide']
        assert any(s.get('number')=='21' for s in guide['steps'])
        assert not any(s['kind']=='ride' for s in guide['steps'])
    arrival=from_station('中环','big-buddha')
    assert any(s.get('number')=='23' for s in arrival['steps'])
    assert any(s['kind']=='exit' and s['station']=='东涌' and s['exit']=='B' for s in arrival['steps'])


def test_nearby_walk_and_same_station_do_not_force_train():
    guide=estimate_transfer('hkmoa','avenue-stars')['transit_guide']
    assert guide['mode']=='walk' and not any(s['kind']=='ride' for s in guide['steps'])
    direct=from_station('钻石山','nan-lian')
    assert not any(s['kind']=='ride' for s in direct['steps'])
    assert any(s['kind']=='exit' for s in direct['steps'])


def test_first_stop_preserves_missing_origin_and_validates_input():
    guide=from_station('','nan-lian')
    assert guide['missing_origin'] and guide['estimated_minutes'] is None
    with pytest.raises(ValueError):from_station('不存在的地铁站','nan-lian')
    with pytest.raises(ValueError):Trip(start_station='../../.env')
    assert extract_patch('从九龙站出发，安排行程')=={'start_station':'九龙'}


def test_old_plan_enriched_on_read_without_changing_old_times_or_disk(tmp_path,monkeypatch):
    original=plan(days=1)
    for d in original['days']:
        d.pop('start_guide')
        for stop in d['stops']:stop.pop('transit_access')
        for leg in d['legs']:leg.pop('transit_guide')
    original.pop('transit_version');original.pop('start_station')
    before=copy.deepcopy(original)
    fixed=enrich_plan(original)
    assert original==before and fixed['history_transport_refreshed']
    assert fixed['days'][0]['stops'][0]['start']==before['days'][0]['stops'][0]['start']
    store=HistoryStore(tmp_path/'history.sqlite3');monkeypatch.setattr(chat,'store',store)
    cid=store.save(None,[{'question':'旧行程','result':{'plan':before,'trip':{}}}],{'trip':{}},False,'旧行程')
    with TestClient(app.app) as web:
        saved=web.post('/api/history/read',json={'id':cid}).json()
    assert saved['turns'][0]['result']['plan']['days'][0]['start_guide']
    assert 'transit_version' not in store.get(cid)['turns'][0]['result']['plan']


def test_transport_api_and_unified_plan_keep_selected_departure(tmp_path,monkeypatch):
    monkeypatch.setattr(chat,'store',HistoryStore(tmp_path/'history.sqlite3'));monkeypatch.setattr(chat,'locks',{})
    with TestClient(app.app) as web:
        result=web.post('/api/transit/route',json={'origin_station':'尖沙咀','destination_id':'nan-lian'}).json()
        assert any(s['kind']=='transfer' for s in result['steps'])
        assert web.post('/api/transit/route',json={'origin_station':'fake','destination_id':'nan-lian'}).status_code==422
        assert web.post('/api/transit/route',json={'origin_id':'pmq','origin_station':'中环','destination_id':'peak'}).status_code==422
        response=web.post('/api/chat',json={'question':'九龙一天行程','trip':{'days':1,'start_station':'中环'}}).json()
        assert response['plan']['start_station']=='中环'
        assert response['plan']['days'][0]['start_guide']['origin_station']=='中环'
        next_turn=web.post('/api/chat',json={'question':'改成从旺角站出发','conversation_id':response['conversation_id']}).json()
        assert next_turn['trip']['start_station']=='旺角' and next_turn['trip']['region']=='九龙'
        assert next_turn['plan']['days'][0]['start_guide']['origin_station']=='旺角'
