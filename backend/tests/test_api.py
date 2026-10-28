from fastapi.testclient import TestClient

from app.main import create_app


def test_auth_scope_memory_deletion_and_csrf(stack):
    app=create_app(stack[0])
    with TestClient(app) as a, TestClient(app) as b:
        assert a.get('/api/v1/health/ready').status_code==200
        assert a.get('/api/v1/me/preferences').status_code==401
        a.post('/api/v1/auth/guest',json={}); b.post('/api/v1/auth/guest',json={})
        session=a.post('/api/v1/sessions',json={}).json()['session_id']
        assert b.get('/api/v1/sessions/'+session).status_code==404
        assert a.post('/api/v1/sessions',json={},headers={'Origin':'https://evil.invalid'}).status_code==403
        assert a.post('/api/v1/sessions',data='anything').status_code==415
        assert a.patch('/api/v1/me/preferences',json={'enabled':True,'values':{'interests':['历史文化']}}).status_code==200
        assert b.get('/api/v1/me/preferences').json()['values']=={}
        a.delete('/api/v1/me/preferences/interests',headers={'Content-Type':'application/json'})
        assert a.get('/api/v1/me/preferences').json()['values']=={}


def test_api_search_details_and_missing_price(stack):
    with TestClient(create_app(stack[0])) as client:
        client.post('/api/v1/auth/guest',json={})
        response=client.post('/api/v1/search',json={'query':'演示历史馆'})
        assert response.status_code==200
        assert response.json()['results'][0]['attraction_id']=='attr_history'
        assert client.get('/api/v1/attractions?setting=indoor').json()['total']==3
        assert client.get('/api/v1/attractions/attr_history').json()['images']==[]
        assert client.get('/api/v1/attractions?limit=1000').status_code==422


def test_sse_final_state_and_cancellation(stack):
    with TestClient(create_app(stack[0])) as c:
        c.post('/api/v1/auth/guest',json={})
        sid=c.post('/api/v1/sessions',json={}).json()['session_id']
        run=c.post(f'/api/v1/sessions/{sid}/runs',json={'message':'介绍演示科学馆','request_id':'api1'}).json()['run_id']
        with c.stream('GET',f'/api/v1/runs/{run}/events') as stream:
            content=''.join(stream.iter_text())
        assert 'citation' in content and 'token' in content and 'done' in content
        assert c.get('/api/v1/runs/'+run).json()['status']=='completed'
        assert c.post(f'/api/v1/runs/{run}/cancel',json={}).json()['status']=='completed'
