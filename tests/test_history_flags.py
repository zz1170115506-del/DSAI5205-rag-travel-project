"""Local-only archive metadata; preserve old payloads and ongoing chat checkpoints."""
import json
import sqlite3
import pytest
from fastapi.testclient import TestClient
import app
from travel import chat
from travel.history import HistoryStore


@pytest.fixture
def web(tmp_path,monkeypatch):
    store=HistoryStore(tmp_path/'history.sqlite3')
    monkeypatch.setattr(chat,'store',store)
    monkeypatch.setattr(chat,'locks',{})
    with TestClient(app.app) as client:yield client,store


def seed(store,title='合成测试对话'):
    return store.save(None,[],{'trip':{}},False,title)


def test_migrate_legacy_db_without_changing_payload(tmp_path):
    path=tmp_path/'legacy.sqlite3';cid='a'*32
    payload=json.dumps({'id':cid,'title':'旧对话','turns':[{'question':'测试'}],'checkpoint':{'place_context':{'listed_ids':['avenue-stars']}}},ensure_ascii=False)
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE conversations(id TEXT PRIMARY KEY,title TEXT NOT NULL,updated TEXT NOT NULL,payload TEXT NOT NULL)')
        db.execute('INSERT INTO conversations VALUES(?,?,?,?)',(cid,'旧对话','2026-10-21',payload))
    store=HistoryStore(path)
    assert store.list()[0]['favorite'] is False and store.list()[0]['pinned'] is False
    store.update_flags(cid,favorite=True,pinned=True)
    assert HistoryStore(path).get(cid)['pinned'] is True
    with sqlite3.connect(path) as db:assert db.execute('SELECT payload FROM conversations').fetchone()[0]==payload
    assert store.get(cid)['checkpoint']['place_context']['listed_ids']==['avenue-stars']


def test_pin_sort_and_flags_do_not_change_recency(tmp_path):
    store=HistoryStore(tmp_path/'db');older=seed(store,'较早');newer=seed(store,'较新')
    before={c['id']:c['updated'] for c in store.list()}
    store.update_flags(older,pinned=True)
    assert [c['id'] for c in store.list()]==[older,newer]
    store.update_flags(newer,favorite=True)
    assert {c['id']:c['updated'] for c in store.list()}==before
    store.update_flags(older,pinned=False)
    assert [c['id'] for c in store.list()]==[newer,older]


def test_partial_updates_survive_save_and_reopen(tmp_path):
    store=HistoryStore(tmp_path/'db');cid=seed(store)
    store.update_flags(cid,favorite=True,pinned=True)
    store.update_flags(cid,favorite=False)
    store.save(cid,[{'question':'继续提问'}],{'trip':{'days':2}},False,'原标题')
    saved=HistoryStore(store.path).get(cid)
    assert saved['pinned'] and not saved['favorite']
    assert saved['turns'][0]['question']=='继续提问' and saved['checkpoint']['trip']['days']==2


def test_flag_api_read_toggle_delete_and_unknown(web):
    client,store=web;cid=seed(store)
    r=client.post('/api/history/update',json={'id':cid,'favorite':True,'pinned':True})
    assert r.status_code==200 and r.json()=={'id':cid,'favorite':True,'pinned':True}
    assert client.post('/api/history/read',json={'id':cid}).json()['favorite']
    assert client.get('/api/history').json()['conversations'][0]['pinned']
    client.post('/api/history/update',json={'id':cid,'favorite':False})
    assert not store.get(cid)['favorite'] and store.get(cid)['pinned']
    assert client.post('/api/history/delete',json={'id':cid}).json()['deleted']
    assert client.get('/api/history').json()['conversations']==[]
    assert client.post('/api/history/update',json={'id':cid,'pinned':False}).status_code==404


@pytest.mark.parametrize('body',[{'id':'../../.env','favorite':True},{'id':'a'*32},{'id':'a'*32,'favorite':'true'},{'id':'a'*32,'pinned':1},{'id':'a'*32,'title':'覆盖标题'}])
def test_flag_api_rejects_invalid_requests(web,body):
    assert web[0].post('/api/history/update',json=body).status_code==422


def test_continuing_real_chat_preserves_favorites_and_context(web):
    client,store=web
    first=client.post('/api/chat',json={'question':'我想去海边玩','trip':{'days':2}}).json();cid=first['conversation_id']
    client.post('/api/history/update',json={'id':cid,'favorite':True,'pinned':True})
    second=client.post('/api/chat',json={'question':'就去这两个地方','conversation_id':cid}).json()
    assert second['plan'] and second['trip']['only_selected']
    assert store.get(cid)['favorite'] and store.get(cid)['pinned']
    assert len(store.get(cid)['turns'])==2
