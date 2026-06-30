"""B272 — hydro_kaernten fehlte komplett im Admin-Panel "API-Cache Status",
weil hydro_fetch.py einen eigenen Cache-Mechanismus (LATEST_FILE) nutzt statt
api_cache.py. Live im Admin-Panel verifiziert: kein Eintrag für Hydro,
obwohl die Schnittstelle ganz normal alle paar Minuten aufgerufen wird.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    pytest.importorskip("flask")
    import app as app_module
    import hydro_fetch

    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client(), hydro_fetch


def test_hydro_kaernten_missing_when_no_fetch_yet(client, tmp_path, monkeypatch):
    c, hydro_fetch = client
    monkeypatch.setattr(hydro_fetch, "LATEST_FILE", tmp_path / "does_not_exist.json")
    services = c.get("/api/cache_status").get_json()["services"]
    rows = [s for s in services if s["namespace"] == "hydro_kaernten"]
    assert rows, "hydro_kaernten fehlt komplett in /api/cache_status"
    assert rows[0]["status"] == "MISSING"
    assert rows[0]["next_fetch_ts"] is None


def test_hydro_kaernten_fresh_after_recent_fetch(client, tmp_path, monkeypatch):
    c, hydro_fetch = client
    latest = tmp_path / "latest_hydro.json"
    latest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(hydro_fetch, "LATEST_FILE", latest)
    monkeypatch.setattr("runtime_config.get", lambda key, default=None: default)
    services = c.get("/api/cache_status").get_json()["services"]
    rows = [s for s in services if s["namespace"] == "hydro_kaernten"]
    assert rows
    assert rows[0]["status"] == "FRESH"
    assert rows[0]["ttl_s"] == hydro_fetch.DEFAULT_TTL_SECONDS
    assert rows[0]["age_s"] is not None and rows[0]["age_s"] < 5


def test_hydro_kaernten_in_known_external_services():
    pytest.importorskip("flask")
    import app as app_module
    assert "hydro_kaernten" in app_module._KNOWN_EXTERNAL_SERVICES


def test_hydro_kaernten_has_public_url():
    pytest.importorskip("flask")
    import app as app_module
    assert "hydro_kaernten" in app_module._API_PUBLIC_URLS
