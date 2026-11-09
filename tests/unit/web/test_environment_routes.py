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
    monkeypatch.setattr(routes, 'environment_management_enabled', lambda: True)
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


def test_disabled_capabilities_and_mutations_do_not_access_store(client, monkeypatch):
    client, store = client
    monkeypatch.setattr(routes, 'environment_management_enabled', lambda: False)
    def unexpected(*args, **kwargs):
        pytest.fail('Disabled management accessed its backend')
    monkeypatch.setattr(routes, 'call', unexpected)
    client.post('/ops/api/auth/login', json={'password': 'admin-password'})
    response = client.get('/ops/api/environment')
    assert response.status_code == 200
    assert response.json() == {
        'enabled': False, 'restart_required': True, 'backend_available': False,
        'reason': 'environment_management_disabled', 'variables': [], 'version': '',
        'suggestions': [], 'consumers': {},
    }
    response = client.post('/ops/api/environment/changes', json={
        'expected_version': '', 'request_id': 'disabled', 'password': 'admin-password',
        'changes': [{'name': 'NEW_KEY', 'action': 'create', 'value': 'sentinel'}],
    })
    assert response.status_code == 409
    assert response.json()['code'] == 'environment_management_disabled'
    assert 'sentinel' not in response.text
    assert not store.directory.exists()
    assert store.path.read_text() == 'EXISTING_KEY=old-secret\n'


def test_enabled_unavailable_backend_exposes_capabilities_without_values(client, monkeypatch):
    client, _ = client
    def unavailable(*args, **kwargs):
        raise OSError('private socket/path must not be echoed')
    monkeypatch.setattr(routes, 'call', unavailable)
    client.post('/ops/api/auth/login', json={'password': 'admin-password'})
    response = client.get('/ops/api/environment')
    assert response.json()['enabled'] is True
    assert response.json()['backend_available'] is False
    assert response.json()['reason'] == 'environment_backend_unavailable'
    assert 'private socket' not in response.text


def test_directory_is_opt_in_and_disabled_directory_does_not_touch_backend(client, monkeypatch):
    client, store = client
    client.post('/ops/api/auth/login', json={'password': 'admin-password'})
    baseline = client.get('/ops/api/environment')
    assert 'directory' not in baseline.json()
    response = client.get('/ops/api/environment?include_directory=true')
    assert response.status_code == 200
    names = {row['name'] for row in response.json()['directory']}
    assert 'EXISTING_KEY' in names
    assert 'PIP_INDEX_URL' in names
    assert response.json()['directory_errors'] == []
    assert 'old-secret' not in response.text

    monkeypatch.setattr(routes, 'environment_management_enabled', lambda: False)
    def unexpected(*args, **kwargs):
        pytest.fail('Disabled directory accessed its backend')
    monkeypatch.setattr(routes, 'call', unexpected)
    disabled = client.get('/ops/api/environment?include_directory=true')
    assert disabled.json()['directory'] == []
    assert disabled.json()['taxonomy'] == []
    assert disabled.json()['directory_errors'] == []
    assert store.path.read_text() == 'EXISTING_KEY=old-secret\n'


def test_unavailable_backend_returns_empty_opt_in_directory(client, monkeypatch):
    client, _ = client
    def unavailable(*args, **kwargs):
        raise OSError('private socket/path must not be echoed')
    monkeypatch.setattr(routes, 'call', unavailable)
    client.post('/ops/api/auth/login', json={'password': 'admin-password'})
    response = client.get('/ops/api/environment?include_directory=true')
    assert response.json()['directory'] == []
    assert response.json()['directory_errors'] == []
    assert response.json()['backend_available'] is False
    assert 'private socket' not in response.text
