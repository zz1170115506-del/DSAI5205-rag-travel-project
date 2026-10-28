"""Public-demo authentication and origin contracts; no cloud services are called."""
import base64
import importlib.util
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
import yaml

import app
from travel.web_access import WebAccess, DemoRateLimit


PASSWORD = 'fixture-demo-password-123'


@pytest.fixture
def public(monkeypatch):
    monkeypatch.setattr(app, 'web_access', WebAccess(True, 'https://testserver', 'team', PASSWORD))
    monkeypatch.setattr(app, 'demo_rate_limit', DemoRateLimit())
    with TestClient(app.app, base_url='https://testserver') as client:
        yield client


@pytest.mark.parametrize('path', ['/', '/static/app.js', '/api/status', '/api/history', '/openapi.json'])
def test_public_pages_and_apis_require_password(public, path):
    r = public.get(path)
    assert r.status_code == 401 and r.headers['www-authenticate'].startswith('Basic ')
    assert r.headers['cache-control'] == 'no-store'
    assert public.get(path, auth=('team', PASSWORD)).status_code == 200


@pytest.mark.parametrize('header', ['', 'Bearer token', 'Basic !!!', 'Basic Zm9v',
                                   'Basic '+base64.b64encode(b'team:wrong').decode()])
def test_bad_credentials_fail_closed(public, header):
    r = public.get('/api/status', headers={'Authorization': header})
    assert r.status_code == 401 and PASSWORD not in r.text


def test_health_check_never_returns_private_state(public):
    r = public.get('/healthz')
    assert r.status_code == 200 and r.json() == {'status': 'ok'}


def test_history_mutations_are_also_protected(public):
    for path in ['/api/history/delete', '/api/history/rename', '/api/agent/reset']:
        assert public.post(path, json={}).status_code == 401


def test_public_fixed_origin_works_behind_http_proxy_and_blocks_foreign_origin(public):
    auth = ('team', PASSWORD)
    # Empty body intentionally reaches route validation, without an external API call.
    r = public.post('/api/chat', auth=auth, headers={'Origin': 'https://testserver'}, json={})
    assert r.status_code == 422
    for origin in ['https://evil.fixture', 'null', 'http://testserver']:
        assert public.post('/api/chat', auth=auth, headers={'Origin': origin}, json={}).status_code == 403
    with TestClient(app.app, base_url='http://testserver') as internal:
        assert internal.post('/api/chat', auth=auth, headers={'Origin': 'https://testserver'}, json={}).status_code == 422


def test_public_limit_covers_expensive_compatibility_routes_and_is_not_bypassed(public, monkeypatch):
    monkeypatch.setattr(app, 'demo_rate_limit', DemoRateLimit(limit=2))
    for _ in range(2):
        assert public.post('/api/chat', auth=('team', PASSWORD), json={}).status_code == 422
    for path in ['/api/chat', '/api/agent', '/api/amap/search', '/api/places/resolve']:
        r = public.post(path, auth=('team', PASSWORD), json={})
        assert r.status_code == 429 and r.headers['retry-after'] == '60'
    assert public.get('/api/status', auth=('team', PASSWORD)).status_code == 200


def test_unauthorized_requests_do_not_consume_group_budget(public, monkeypatch):
    monkeypatch.setattr(app, 'demo_rate_limit', DemoRateLimit(limit=1))
    assert public.post('/api/chat', json={}).status_code == 401
    assert public.post('/api/chat', auth=('team', PASSWORD), json={}).status_code == 422


def test_rate_window_resets(monkeypatch):
    import travel.web_access as module
    now = [100.]
    monkeypatch.setattr(module.time, 'monotonic', lambda: now[0])
    limit = DemoRateLimit(limit=1)
    assert limit.allow() and not limit.allow()
    now[0] += 60
    assert limit.allow()


@pytest.mark.parametrize('origin', ['', 'http://testserver', 'https://user:pass@testserver',
                                  'https://*.example.com', 'https://example.com/path',
                                  'https://example.com?x=1', 'https://bad host'])
def test_public_configuration_rejects_invalid_origin(monkeypatch, origin):
    monkeypatch.setenv('PUBLIC_DEMO', 'true');monkeypatch.setenv('PUBLIC_ORIGIN', origin)
    monkeypatch.delenv('RENDER_EXTERNAL_URL', raising=False)
    monkeypatch.setenv('DEMO_PASSWORD', PASSWORD)
    with pytest.raises(ValueError):WebAccess.from_env()


@pytest.mark.parametrize('password', ['', 'short'])
def test_public_mode_refuses_missing_or_short_password(monkeypatch, password):
    monkeypatch.setenv('PUBLIC_DEMO', 'true');monkeypatch.setenv('PUBLIC_ORIGIN', 'https://example.com')
    monkeypatch.setenv('DEMO_PASSWORD', password)
    with pytest.raises(ValueError):WebAccess.from_env()


def test_render_origin_is_exact_and_password_is_not_in_config_repr(monkeypatch):
    monkeypatch.setenv('PUBLIC_DEMO', 'true');monkeypatch.delenv('PUBLIC_ORIGIN', raising=False)
    monkeypatch.setenv('RENDER_EXTERNAL_URL', 'https://demo.onrender.com')
    monkeypatch.setenv('DEMO_PASSWORD', PASSWORD)
    settings = WebAccess.from_env()
    assert settings.origin == 'https://demo.onrender.com'
    assert 'demo.onrender.com' in settings.allowed_hosts and '*' not in settings.allowed_hosts
    assert PASSWORD not in repr(settings)


def test_cloud_entry_refuses_to_bind_without_public_mode(monkeypatch):
    spec = importlib.util.spec_from_file_location('public_entry', 'scripts/serve_public.py')
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setenv('PUBLIC_DEMO', 'false')
    monkeypatch.setattr(module.uvicorn, 'run', lambda *args, **kwargs: pytest.fail('must not bind'))
    with pytest.raises(SystemExit):module.main()


def test_blueprint_uses_free_plan_single_service_and_secret_placeholders():
    blueprint = yaml.safe_load(Path('render.yaml').read_text())
    assert len(blueprint['services']) == 1
    service = blueprint['services'][0]
    assert service['plan'] == 'free' and service['autoDeployTrigger'] == 'off'
    assert service['startCommand'] == 'python scripts/serve_public.py'
    env = {item['key']: item for item in service['envVars']}
    for name in ['MODEL_API_KEY', 'AMAP_API_KEY', 'DEMO_PASSWORD']:
        assert env[name] == {'key': name, 'sync': False}
    assert env['RETRIEVAL_MODE']['value'] == 'hybrid'
