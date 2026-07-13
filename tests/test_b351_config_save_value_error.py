"""B351: /api/config gibt bei QUALITY_TARGET_MAE_KM_<=30-Verstoss einen
klaren 400 statt eines unbehandelten 500 zurueck."""
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


def test_protected_quality_target_key_returns_400_not_500(client, monkeypatch):
    _auth(monkeypatch)
    resp = client.post("/api/config", json={"QUALITY_TARGET_MAE_KM_10": 1.0})
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["ok"] is False
    assert "QUALITY_TARGET_MAE_KM_10" in body["error"]
    assert "zieldefinition.txt" in body["error"]


def test_protected_quality_target_key_20_and_30_also_400(client, monkeypatch):
    _auth(monkeypatch)
    for key in ("QUALITY_TARGET_MAE_KM_20", "QUALITY_TARGET_MAE_KM_30"):
        resp = client.post("/api/config", json={key: 1.0})
        assert resp.status_code == 400, f"{key} sollte 400 liefern, war {resp.status_code}"


def test_configurable_quality_target_above_30_still_allowed(client, monkeypatch):
    """Regressionsschutz: administrierbare Ziele (>30 Min) duerfen weiterhin gesetzt werden."""
    _auth(monkeypatch)
    resp = client.post("/api/config", json={"QUALITY_TARGET_MAE_KM_40": 1.5})
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_normal_key_still_saves_successfully(client, monkeypatch):
    _auth(monkeypatch)
    resp = client.post("/api/config", json={"KINEMATIC_ACCELERATION_ENABLED": True})
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_forbidden_secret_key_still_returns_400_unchanged(client, monkeypatch):
    """Regressionsschutz: bestehende UPSCALE_FACTOR/Secret-Pruefung unveraendert."""
    _auth(monkeypatch)
    resp = client.post("/api/config", json={"UPSCALE_FACTOR": 5.0})
    assert resp.status_code == 400
    assert "UPSCALE_FACTOR" in resp.get_json()["error"]


def test_mixed_payload_with_protected_key_returns_400_and_does_not_partially_save(client, monkeypatch):
    """Bei ValueError darf gar nichts aus dem Payload persistiert werden (patch()
    wirft VOR dem Merge/Save, da alle Keys zuerst validiert werden)."""
    _auth(monkeypatch)
    import runtime_config
    before = dict(runtime_config._OVERRIDES)
    resp = client.post("/api/config", json={
        "KINEMATIC_ACCELERATION_ENABLED": True,
        "QUALITY_TARGET_MAE_KM_10": 1.0,
    })
    assert resp.status_code == 400
    assert runtime_config._OVERRIDES == before
