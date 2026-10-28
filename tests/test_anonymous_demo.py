import asyncio

from fastapi.testclient import TestClient
import pytest

import app
from travel import chat
from travel.anonymous_history import AnonymousHistory
from travel.history import HistoryStore
from travel.web_access import WebAccess, DemoRateLimit


@pytest.fixture
def anonymous(tmp_path, monkeypatch):
    monkeypatch.setattr(app, 'web_access', WebAccess(public=True, origin='https://testserver', anonymous=True))
    monkeypatch.setattr(app, 'demo_rate_limit', DemoRateLimit(limit=100))
    monkeypatch.setattr(chat, 'store', HistoryStore(tmp_path/'private.sqlite3'))
    monkeypatch.setattr(chat, 'locks', {})
    monkeypatch.setattr(chat, 'anonymous_store', AnonymousHistory(capacity=2,
                         protected=lambda: {cid for cid, lock in chat.locks.items() if lock.locked()}))
    with TestClient(app.app, base_url='https://testserver') as client:
        yield client


def test_anonymous_opt_in_needs_fixed_https_but_no_password(monkeypatch):
    monkeypatch.setenv('PUBLIC_DEMO', 'true')
    monkeypatch.setenv('PUBLIC_DEMO_ANONYMOUS', 'true')
    monkeypatch.setenv('PUBLIC_ORIGIN', 'https://demo.example')
    monkeypatch.delenv('DEMO_PASSWORD', raising=False)
    access = WebAccess.from_env()
    assert access.public and access.anonymous and access.origin == 'https://demo.example'
    monkeypatch.setenv('PUBLIC_ORIGIN', 'http://demo.example')
    with pytest.raises(ValueError): WebAccess.from_env()
    monkeypatch.setenv('PUBLIC_DEMO', 'false')
    assert not WebAccess.from_env().anonymous


def test_open_pages_and_history_disabled_status(anonymous):
    for path in ['/', '/static/app.js', '/api/status', '/api/places', '/healthz']:
        response = anonymous.get(path)
        assert response.status_code == 200
        assert 'www-authenticate' not in response.headers
    assert anonymous.get('/api/status').json()['history_enabled'] is False


def test_private_archive_cannot_be_read_or_modified_even_with_known_id(anonymous):
    cid = 'a'*32
    chat.store.save(cid, [], {'private': 'old private trip'}, False, 'old private trip')
    assert anonymous.get('/api/history').status_code == 404
    for path in ['read','delete','rename','update']:
        response = anonymous.post('/api/history/'+path, json={'id':cid,'title':'changed'})
        assert response.status_code == 404 and 'old private trip' not in response.text
    response = anonymous.post('/api/chat',json={'question':'继续之前的对话','conversation_id':cid})
    assert response.status_code == 404 and 'old private trip' not in response.text
    assert chat.store.get(cid)['title'] == 'old private trip'


def test_temporary_conversations_continue_without_crossing_visitors(anonymous):
    first = anonymous.post('/api/chat',json={'question':'安排香港行程','trip':{'region':'九龙'}}).json()
    other = anonymous.post('/api/chat',json={'question':'安排香港行程'}).json()
    assert first['conversation_id'] != other['conversation_id']
    assert first['trip']['region'] == '九龙' and other['trip']['region'] == '全部'
    continued = anonymous.post('/api/chat',json={'question':'改成两天','conversation_id':first['conversation_id']}).json()
    assert continued['trip']['region'] == '九龙' and continued['trip']['days'] == 2
    assert continued['plan']
    assert not chat.store.path.exists()
    assert len(chat.anonymous_store.entries) == 2


def test_full_temporary_store_evicts_idle_instead_of_blocking_public_access(anonymous):
    first = anonymous.post('/api/chat',json={'question':'安排香港行程'}).json()['conversation_id']
    for _ in range(2):
        assert anonymous.post('/api/chat',json={'question':'安排香港行程'}).status_code == 200
    assert len(chat.anonymous_store.entries) == 2
    assert anonymous.post('/api/chat',json={'question':'继续','conversation_id':first}).status_code == 404


def test_expiry_and_active_conversation_protection(monkeypatch):
    import travel.anonymous_history as module
    now=[100.]
    monkeypatch.setattr(module.time, 'monotonic', lambda: now[0])
    protected={'a'}
    archive=AnonymousHistory(capacity=2,ttl=30,protected=lambda:protected)
    for cid in ['a','b']: archive.save(cid,[],{},False,cid)
    archive.save('c',[],{},False,'c')
    assert set(archive.entries)=={'a','c'}
    now[0]+=31
    # The route locks a requested ID before reading it; that cannot defeat expiry.
    with pytest.raises(KeyError): archive.get('a')
    archive.prune()
    assert not archive.entries


def test_limits_and_foreign_origin_still_apply_without_password(anonymous, monkeypatch):
    assert anonymous.post('/api/chat',json={},headers={'Origin':'https://evil.example'}).status_code == 403
    monkeypatch.setattr(app,'demo_rate_limit',DemoRateLimit(limit=1))
    assert anonymous.post('/api/chat',json={}).status_code == 422
    for path in ['/api/chat','/api/amap/search','/api/places/resolve']:
        assert anonymous.post(path,json={}).status_code == 429
    assert anonymous.get('/api/places?q=文化').status_code == 429
