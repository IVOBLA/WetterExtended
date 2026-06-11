"""P47: Manueller Job-Trigger /api/system/run_job + job_status."""

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture()
def admin_client(monkeypatch):
    pytest.importorskip("flask")
    import app as app_module
    import auth as auth_module

    # Admin-Auth simulieren (umgeht JWT für den Test). POST nutzt in app.py
    # den gebundenen Import, GET nutzt auth.get_current_user über Modul-Dict.
    admin_user = lambda: {"username": "t", "role": "admin"}
    monkeypatch.setattr(auth_module, "get_current_user", admin_user, raising=False)
    monkeypatch.setattr(app_module, "get_current_user", admin_user, raising=False)
    app_module.app.config.update(TESTING=True)
    with app_module._P47_LOCK:
        app_module._P47_RUNS.clear()
    return app_module.app, app_module.app.test_client()


def test_unknown_job_returns_400(admin_client):
    _, c = admin_client
    r = c.post("/api/system/run_job/does_not_exist")
    assert r.status_code == 400
    assert "available" in r.get_json()


def test_known_job_starts_and_status(admin_client):
    app_module, c = admin_client
    # Den eigentlichen Fetch durch einen schnellen Dummy ersetzen
    import app as _app
    orig = _app._p47_job_map

    def _fake_map():
        def _ok():
            return "dummy ok"
        return {"atmospheric_snapshot": ("Test", _ok)}

    _app._p47_job_map = _fake_map
    try:
        r = c.post("/api/system/run_job/atmospheric_snapshot")
        assert r.status_code == 202
        assert r.get_json()["started"] is True
        # kurz warten bis Thread fertig
        for _ in range(50):
            st = c.get("/api/system/job_status").get_json()["runs"]
            if st.get("atmospheric_snapshot", {}).get("state") in ("ok", "error"):
                break
            time.sleep(0.05)
        runs = c.get("/api/system/job_status").get_json()["runs"]
        assert runs["atmospheric_snapshot"]["state"] == "ok"
        assert runs["atmospheric_snapshot"]["message"] == "dummy ok"
    finally:
        _app._p47_job_map = orig


def test_job_status_lists_available(admin_client):
    _, c = admin_client
    data = c.get("/api/system/job_status").get_json()
    ids = {a["job_id"] for a in data["available"]}
    assert {"atmospheric_snapshot", "api_health", "stats_aggregate"} <= ids
