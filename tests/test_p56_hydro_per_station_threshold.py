"""P56 — Per-Station-Markierungsschwelle + deselektierte Stationen bleiben sichtbar/sofort aktualisiert."""

import os
import pytest
import hydro_api


def _setup(monkeypatch, overrides, global_mark):
    monkeypatch.setattr(hydro_api, "_static_index", lambda: {
        "S1": {"lat": 1.0, "lon": 1.0, "station_name": "A", "impact_eligible": True},
        "S2": {"lat": 2.0, "lon": 2.0, "station_name": "B", "impact_eligible": True},
    })
    monkeypatch.setattr(hydro_api, "_json", lambda path, default=None: {"stations": [
        {"station_id": "S1", "q_m3s": 6.0}, {"station_id": "S2", "q_m3s": 6.0},
    ]} if "latest" in str(path) or "live" in str(path).lower() else (default if default is not None else {}))
    monkeypatch.setattr(hydro_api, "normalized_impacts", lambda *a, **k: [])
    monkeypatch.setattr(hydro_api, "enabled", lambda: True)
    cfg = {"HYDRO_STATION_OVERRIDES": overrides, "HYDRO_MAP_MIN_Q_M3S": 0.0, "HYDRO_MAP_MARK_Q_M3S": global_mark}
    monkeypatch.setattr(hydro_api.runtime_config, "get", lambda key, default=None: cfg.get(key, default))


def test_per_station_threshold_overrides_global(monkeypatch):
    _setup(monkeypatch, {"S1": {"mark_q_m3s": 5.0}}, 10.0)
    fc = hydro_api.station_features(map_view=True)
    by = {f["properties"]["station_id"]: f["properties"] for f in fc["features"]}
    assert by["S1"]["marked"] is True
    assert by["S2"]["marked"] is False
    assert by["S1"]["mark_q_m3s"] == 5.0


def test_station_features_exposes_threshold_without_map(monkeypatch):
    _setup(monkeypatch, {"S2": {"mark_q_m3s": 3.0}}, None)
    fc = hydro_api.station_features(include_disabled=True)
    by = {f["properties"]["station_id"]: f["properties"] for f in fc["features"]}
    assert by["S2"]["mark_q_m3s"] == 3.0


def test_disabled_station_visible_with_include_disabled(monkeypatch):
    _setup(monkeypatch, {"S1": {"enabled": False}}, None)
    ids_default = {f["properties"]["station_id"] for f in hydro_api.station_features()["features"]}
    ids_incl = {f["properties"]["station_id"] for f in hydro_api.station_features(include_disabled=True)["features"]}
    assert "S1" not in ids_default
    assert ids_incl == {"S1", "S2"}


@pytest.fixture
def client():
    pytest.importorskip("flask")
    import app as app_module
    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client()


def test_patch_accepts_and_clears_mark_q(client, monkeypatch):
    import auth, runtime_config
    monkeypatch.setattr(auth, "get_current_user", lambda: {"role": "admin"})
    store = {"HYDRO_STATION_OVERRIDES": {}}
    monkeypatch.setattr(runtime_config, "get", lambda key, default=None: store.get(key, default))
    monkeypatch.setattr(runtime_config, "patch", lambda d: store.update(d))
    r = client.patch("/api/hydro/stations/S1", json={"mark_q_m3s": 4.5})
    assert r.status_code == 200 and store["HYDRO_STATION_OVERRIDES"]["S1"]["mark_q_m3s"] == 4.5
    assert client.patch("/api/hydro/stations/S1", json={"mark_q_m3s": -1}).status_code == 400
    r = client.patch("/api/hydro/stations/S1", json={"mark_q_m3s": None})
    assert r.status_code == 200 and "mark_q_m3s" not in store["HYDRO_STATION_OVERRIDES"]["S1"]


def test_frontend_admin_list_contract():
    from pathlib import Path
    s = (Path(__file__).resolve().parent.parent / "frontend" / "src" / "pages" / "Configuration.jsx").read_text(encoding="utf-8")
    assert "/api/hydro/stations?include_disabled=1" in s
    assert "async function patchHydroStation(" in s
    assert "await reloadHydroAdminData({ nocache: true })" in s
    assert "/api/hydro/status" in s
    assert "mark_q_m3s" in s
