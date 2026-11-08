"""Public environment API never exports entered values, including validation failures."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from quickquip.app.web import auth
from quickquip.app.web.routes import environment as routes
from quickquip.app.web.session_store import WebAdminSessionStore
from quickquip.environment.store import Store


@pytest.fixture
def client(tmp_path, monkeypatch):
    (tmp_path / '.env').write_text('EXISTING_KEY=old-secret\n')
    store = Store(tmp_path)
    monkeypatch.setattr(routes, 'call', store.execute)
    monkeypatch.setattr(auth, 'get_web_admin_password', lambda: 'admin-password')
    monkeypatch.setattr(routes, 'get_web_admin_password', lambda: 'admin-password')
    monkeypatch.setattr(auth, '_session_store', lambda: sessions)
    monkeypatch.setattr(routes.audit_logger, 'log', lambda *a, **k: None)
    sessions = WebAdminSessionStore(tmp_path / 'sessions.db')
    app = FastAPI()
    app.include_router(auth.router, prefix='/ops/api')
    app.include_router(routes.router, prefix='/ops/api', dependencies=auth.protected_dependencies)
    with TestClient(app, headers={'origin': 'http://testserver'}) as client:
        yield client, store


def test_session_origin_reauthentication_and_no_secret_errors(client):
    client, store = client
    assert client.get('/ops/api/environment').status_code == 401
    client.post('/ops/api/auth/login', json={'password': 'admin-password'})
    listing = client.get('/ops/api/environment')
    assert 'old-secret' not in listing.text
    body = {'expected_version': listing.json()['version'], 'request_id': 'api-test',
            'password': 'wrong', 'changes': [
                {'name': 'NEW_KEY', 'action': 'create', 'value': 'new-secret'}]}
    assert client.post('/ops/api/environment/changes', json=body).status_code == 403
    body['password'] = 'admin-password'
    assert client.post('/ops/api/environment/changes', json=body,
                       headers={'origin': 'https://evil.test'}).status_code == 403
    response = client.post('/ops/api/environment/changes', json=body)
    assert response.status_code == 200 and 'new-secret' not in response.text
    assert store.execute('snapshot')['values']['NEW_KEY'] == 'new-secret'
    body['changes'][0]['action'] = 'invalid-new-secret'
    response = client.post('/ops/api/environment/changes', json=body)
    assert response.status_code == 422 and 'new-secret' not in response.text
