"""B352: GET /api/config filtert Schluessel heraus, die als Runtime-Override
ohnehin nie akzeptiert wuerden — damit "kompletten Stand kopieren, kleine
Aenderung machen, zurueckspeichern" nicht mehr in B351-artige Fehler laeuft."""
import pytest


def _auth(monkeypatch, role="admin"):
    import app as app_module
    import auth as auth_module
    user = {"role": role, "sub": "1"}
    monkeypatch.setattr(app_module, "get_current_user", lambda: user)
    monkeypatch.setattr(auth_module, "get_current_user", lambda: user)


@pytest.fixture()
def client(monkeypatch):
    pytest.importorskip("flask")
    import app as app_module
    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client()


def test_get_config_excludes_quality_target_structural_keys(client, monkeypatch):
    _auth(monkeypatch)
    resp = client.get("/api/config")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert "QUALITY_TARGET_MAE_KM_FIXED" not in payload
    assert "QUALITY_TARGET_MAE_KM_CONFIGURABLE_DEFAULT" not in payload


def test_get_config_excludes_upscale_factor(client, monkeypatch):
    _auth(monkeypatch)
    resp = client.get("/api/config")
    payload = resp.get_json()
    assert "UPSCALE_FACTOR" not in payload


def test_get_config_still_includes_normal_editable_keys(client, monkeypatch):
    _auth(monkeypatch)
    resp = client.get("/api/config")
    payload = resp.get_json()
    assert "KINEMATIC_ACCELERATION_ENABLED" in payload
    assert "WARN_MAX_HORIZON_MIN" in payload
    assert "PX_TO_KMH" in payload


def test_full_get_response_can_be_posted_back_unchanged(client, monkeypatch):
    """Kernversprechen von B352: der komplette GET-Response ist immer ein
    gueltiger POST-Payload — kein einzelner Schluessel darf mehr zum
    B351-Fehler fuehren, wenn der Nutzer den Stand unveraendert speichert."""
    _auth(monkeypatch)
    get_resp = client.get("/api/config")
    payload = get_resp.get_json()
    post_resp = client.post("/api/config", json=payload)
    assert post_resp.status_code == 200
    assert post_resp.get_json()["ok"] is True


def test_hydro_runtime_keys_still_present_after_filtering(client, monkeypatch):
    """Regressionsschutz fuer tests/test_hydro_runtime_config_contract.py."""
    _auth(monkeypatch)
    resp = client.get("/api/config")
    payload = resp.get_json()
    for key in ("HYDRO_ENABLED", "HYDRO_API_TTL_SECONDS", "HYDRO_STATION_OVERRIDES"):
        assert key in payload, f"{key} fehlt nach B352-Filterung"
