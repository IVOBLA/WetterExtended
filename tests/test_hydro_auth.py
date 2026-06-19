import pytest
pytest.importorskip("flask")

@pytest.fixture
def client():
    import app as app_module
    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client()


def test_hydro_admin_requires_admin(client, monkeypatch):
    import auth
    monkeypatch.setattr(auth, 'get_current_user', lambda: {'role': 'operator'})
    assert client.post('/api/hydro/fetch-live', json={}).status_code == 403
    assert client.post('/api/hydro/reload-static', json={}).status_code == 403
    assert client.post('/api/hydro/verify', json={}).status_code == 403
    assert client.patch('/api/hydro/stations/S1', json={'enabled': False}).status_code == 403


def test_hydro_public_get_is_public(client):
    assert client.get('/api/hydro/status').status_code == 200
