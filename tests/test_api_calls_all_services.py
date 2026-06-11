"""B128: /api/api_calls listet alle bekannten Dienste, auch ohne Aufruf."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture()
def client(monkeypatch):
    pytest.importorskip("flask")
    import app as app_module
    import debug_utils

    def fake_api_call_summary(since_hours=24):
        return {"since_hours": since_hours, "by_service": {
            "arso_radar": {"calls": 5, "errors": 0, "last_ts": None,
                           "last_url": None, "last_status": 200}
        }}

    # api_call_summary auf nur EINEN Dienst mit Aufrufen reduzieren
    monkeypatch.setattr(debug_utils, "api_call_summary", fake_api_call_summary)
    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client(), app_module


def test_all_known_services_present(client):
    c, app_module = client
    data = c.get("/api/api_calls?hours=24").get_json()
    bs = data["by_service"]
    # Der aufgerufene Dienst behält seine Zähler
    assert bs["arso_radar"]["calls"] == 5
    # Alle kanonischen Dienste sind vorhanden (auch mit 0)
    for svc in app_module._KNOWN_EXTERNAL_SERVICES:
        assert svc in bs, f"{svc} fehlt in by_service"
    # Ein nicht aufgerufener Dienst hat 0 Anfragen
    assert bs["geosphere_cape"]["calls"] == 0
    assert bs["geosphere_cape"]["errors"] == 0
