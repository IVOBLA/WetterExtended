import json
from pathlib import Path

import pytest


HYDRO_RUNTIME_KEYS = [
    "HYDRO_ENABLED",
    "HYDRO_API_TTL_SECONDS",
    "HYDRO_MIN_OVERLAP_AREA_KM2",
    "HYDRO_MIN_CELL_OVERLAP_RATIO",
    "HYDRO_MIN_OVERLAP_RATIO_CELL",
    "HYDRO_MIN_DURATION_MIN",
    "HYDRO_RELEVANT_INTENSITIES",
    "HYDRO_DEFAULT_LAG_MIN",
    "HYDRO_LAG_WINDOW_MIN",
    "HYDRO_VERIFY_MIN_DELTA_Q_M3S",
    "HYDRO_VERIFY_MIN_DELTA_W_CM",
    "HYDRO_VERIFY_MIN_RELATIVE_DELTA_PCT",
    "HYDRO_VERIFY_MAX_GAP_MIN",
    "HYDRO_STATION_OVERRIDES",
    "HYDRO_STATIC_REQUIRED",
]


def test_all_hydro_runtime_keys_are_allowed():
    runtime_config = pytest.importorskip("runtime_config")
    for key in HYDRO_RUNTIME_KEYS:
        assert not runtime_config.is_forbidden_override_key(key), f"{key} muss als Runtime-Override erlaubt sein"
        assert runtime_config.forbidden_keys_in({key: "test"}) == []


def test_all_hydro_runtime_keys_are_seeded_without_overwriting_existing(tmp_path):
    init_runtime_overrides = pytest.importorskip("init_runtime_overrides")
    path = tmp_path / "runtime_overrides.json"
    existing = {
        "HYDRO_ENABLED": False,
        "HYDRO_VERIFY_MAX_GAP_MIN": 123,
        "CUSTOM_RUNTIME_OVERRIDE": {"keep": True},
    }
    path.write_text(json.dumps(existing), encoding="utf-8")

    added = init_runtime_overrides.init_overrides(str(path))
    stored = json.loads(path.read_text(encoding="utf-8"))

    for key in HYDRO_RUNTIME_KEYS:
        assert key in stored, f"{key} fehlt in init_runtime_overrides.DEFAULTS/runtime_overrides.json"
    assert stored["HYDRO_ENABLED"] is False
    assert stored["HYDRO_VERIFY_MAX_GAP_MIN"] == 123
    assert stored["CUSTOM_RUNTIME_OVERRIDE"] == {"keep": True}
    assert "HYDRO_ENABLED" not in added
    assert "HYDRO_VERIFY_MAX_GAP_MIN" not in added


def test_admin_config_api_delivers_all_hydro_runtime_keys(monkeypatch):
    app_module = pytest.importorskip("app")
    runtime_config = pytest.importorskip("runtime_config")
    app_module.app.config.update(TESTING=True)
    monkeypatch.setattr("auth.get_current_user", lambda: {"role": "admin"})
    monkeypatch.setattr(runtime_config, "_OVERRIDES", {}, raising=False)

    response = app_module.app.test_client().get("/api/config")
    assert response.status_code == 200
    payload = response.get_json()

    for key in HYDRO_RUNTIME_KEYS:
        assert key in payload, f"{key} fehlt im Admin-Config-Schema /api/config"


def test_frontend_renders_relevant_hydro_runtime_keys_and_station_toggle_contract():
    src = Path("frontend/src/pages/Configuration.jsx").read_text(encoding="utf-8")

    for key in HYDRO_RUNTIME_KEYS:
        assert key in src, f"{key} fehlt in der Admin-Konfigurationsreferenz"
    assert "Hydro-Impact Admin" in src
    assert "/api/hydro/stations/${st.station_id}" in src
    assert "{ enabled: e.target.checked }" in src
    assert "all_effective" not in src


def test_hydro_station_toggle_persists_only_station_overrides_and_drops_existing_secrets(monkeypatch, tmp_path):
    app_module = pytest.importorskip("app")
    runtime_config = pytest.importorskip("runtime_config")
    app_module.app.config.update(TESTING=True)
    monkeypatch.setattr("auth.get_current_user", lambda: {"role": "admin"})
    monkeypatch.setattr(runtime_config, "_get_path", lambda: str(tmp_path / "runtime_overrides.json"))
    runtime_config.save({
        "FORECAST_MAX_SPEED_KMH": 120,
        "GITHUB_VERIFY_CONFIG": {"token": "must-not-persist", "enabled": True},
        "HYDRO_STATION_OVERRIDES": {"OLD": {"enabled": True}},
    })

    response = app_module.app.test_client().patch("/api/hydro/stations/S1", json={"enabled": False})
    assert response.status_code == 200
    stored = json.loads((tmp_path / "runtime_overrides.json").read_text(encoding="utf-8"))

    assert stored["FORECAST_MAX_SPEED_KMH"] == 120
    assert stored["HYDRO_STATION_OVERRIDES"] == {"OLD": {"enabled": True}, "S1": {"enabled": False}}
    assert "GITHUB_VERIFY_CONFIG" in stored
    assert "token" not in stored["GITHUB_VERIFY_CONFIG"]
    assert "BBOX_KAERNTEN_EXTENDED" not in stored


def test_runtime_patch_does_not_persist_forbidden_keys_or_nested_secrets(monkeypatch):
    runtime_config = pytest.importorskip("runtime_config")
    written = {}
    monkeypatch.setattr(runtime_config, "_OVERRIDES", {"OLD_SECRET": "drop", "SAFE": {"token": "drop", "value": 1}}, raising=False)
    monkeypatch.setattr(runtime_config, "save", lambda merged: written.update({"data": merged}))

    runtime_config.patch({"HYDRO_ENABLED": False, "GITHUB_TOKEN": "drop", "NESTED": {"api_key": "drop", "value": 2}})

    assert written["data"]["HYDRO_ENABLED"] is False
    assert "OLD_SECRET" not in written["data"]
    assert "GITHUB_TOKEN" not in written["data"]
    assert written["data"]["SAFE"] == {"value": 1}
    assert "NESTED" not in written["data"]
