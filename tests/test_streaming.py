import asyncio
import json

from fastapi import HTTPException
from fastapi.testclient import TestClient

import app
from travel import chat, streaming
from travel.history import HistoryStore
from travel.web_access import WebAccess


def test_pending_arrives_before_work_and_disconnect_cancels_task():
    async def scenario():
        started, cancelled = asyncio.Event(), asyncio.Event()
        async def run():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        events = streaming.chat_events(run)
        assert (await anext(events)).strip() == b''
        await started.wait()
        await events.aclose()
        assert cancelled.is_set()
    asyncio.run(scenario())


def test_heartbeat_keeps_slow_result_alive(monkeypatch):
    monkeypatch.setattr(streaming, 'HEARTBEAT_SECONDS', .001)
    async def scenario():
        async def run():
            await asyncio.sleep(.015)
            return {'answer': {'text': '大馆'}}
        chunks = [event async for event in streaming.chat_events(run)]
        events = [json.loads(event) for event in chunks if event.strip()]
        assert len(chunks) > 2
        assert all(not chunk.strip() for chunk in chunks[:-1])
        assert events[-1] == {'type': 'result', 'status': 200, 'data': {'answer': {'text': '大馆'}}}
    asyncio.run(scenario())


def test_errors_and_queue_deadline_never_leak_exception_text(monkeypatch):
    monkeypatch.setattr(streaming, 'REQUEST_SECONDS', .01)
    async def scenario():
        async def missing(): raise HTTPException(404, '历史不存在')
        async def provider(): raise RuntimeError('secret-api-key')
        cancelled = asyncio.Event()
        async def queued():
            try: await asyncio.sleep(10)
            finally: cancelled.set()
        for run, code in [(missing,404), (provider,500), (queued,504)]:
            events = [json.loads(event) async for event in streaming.chat_events(run) if event.strip()]
            assert events[-1]['status'] == code
            assert 'secret-api-key' not in json.dumps(events)
        assert cancelled.is_set()
    asyncio.run(scenario())


def test_negotiated_stream_uses_existing_chat_history_and_access_guards(tmp_path, monkeypatch):
    monkeypatch.setattr(chat, 'store', HistoryStore(tmp_path/'history.sqlite3'))
    monkeypatch.setattr(chat, 'locks', {})
    headers = {'Accept': 'application/x-ndjson'}
    with TestClient(app.app) as client:
        response = client.post('/api/chat',json={'question':'安排香港行程'},headers=headers)
        assert response.headers['content-type'].startswith('application/x-ndjson')
        final = json.loads(response.text.splitlines()[-1])
        assert final['status'] == 200
        cid = final['data']['conversation_id']
        assert client.post('/api/history/read',json={'id':cid}).json()['turns']
        query_stream = client.post('/api/chat?stream=true', json={'question':'安排香港行程'})
        assert query_stream.headers['content-type'].startswith('application/x-ndjson')
        assert query_stream.json()['status'] == 200
        missing = client.post('/api/chat',json={'question':'继续','conversation_id':'a'*32},headers=headers)
        assert json.loads(missing.text.splitlines()[-1])['status'] == 404
        monkeypatch.setattr(app, 'web_access', WebAccess(public=True,origin='https://demo.example',password='test-only-password'))
        assert client.post('/api/chat',json={'question':'安排香港行程'},headers=headers).status_code == 401
        assert client.post('/api/chat',json={'question':'安排香港行程'},headers={**headers,'Origin':'https://evil.example'},auth=('team','test-only-password')).status_code == 403
