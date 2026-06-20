import json
import sys
import types

sys.modules.setdefault("requests", types.SimpleNamespace(exceptions=types.SimpleNamespace(Timeout=TimeoutError, HTTPError=Exception), get=lambda *a, **k: None))

import fetch_atmospheric_snapshot as mod
import size_regressor


def _resp(hourly):
    return {"hourly": {"time": ["2026-06-20T12:00"], **hourly}}


def test_300hpa_values_are_taken_from_pressure_response(monkeypatch, tmp_path):
    locs = [{"name": "A", "lat": 46.6, "lon": 14.3}]
    monkeypatch.setattr(mod.runtime_config, "get", lambda key, default=None: locs if key == "ATM_SNAPSHOT_LOCATIONS" else default)
    monkeypatch.setattr(mod, "_nearest_hour_str", lambda: "2026-06-20T12:00")
    monkeypatch.setattr(mod, "_OUT_FILE", str(tmp_path / "atmosphere_latest.json"))
    monkeypatch.setattr(mod, "_QUALITY_FILE", str(tmp_path / "atmosphere_feature_quality.json"))

    def fake_bulk(base, label, locations):
        if "Pressure" in label:
            return [_resp({
                "wind_speed_700hPa": [25], "wind_direction_700hPa": [90],
                "temperature_500hPa": [-15], "temperature_700hPa": [2],
                "wind_speed_300hPa": [88], "wind_direction_300hPa": [180],
                "geopotential_height_300hPa": [9300],
            })]
        if "AROME" in label:
            return [_resp({"temperature_2m": [20], "dewpoint_2m": [12], "wind_speed_10m": [10], "freezing_level_height": [3000], "cape": [500]})]
        return [_resp({"lifted_index": [-2], "convective_inhibition": [-20], "total_column_integrated_water_vapour": [25]})]

    monkeypatch.setattr(mod, "_bulk_get_batched", fake_bulk)
    monkeypatch.setitem(__import__("sys").modules, "cloud_height_from_eumetview", type("M", (), {"fetch_cloud_height_for_points": staticmethod(lambda pts: {pts[0]: 12000.0})}))

    result = mod.fetch_atmospheric_snapshot()
    out = result["locations"][0]
    assert out["wind_300hpa"] == 88.0
    assert out["wind_300hpa_missing"] == 0
    assert out["wind_dir_300_missing"] == 0
    assert out["geopotential_300hpa"] == 9300.0
    assert out["geopotential_300hpa_missing"] == 0


def test_missing_300hpa_values_set_missing_flags(monkeypatch, tmp_path):
    locs = [{"name": "A", "lat": 46.6, "lon": 14.3}]
    monkeypatch.setattr(mod.runtime_config, "get", lambda key, default=None: locs if key == "ATM_SNAPSHOT_LOCATIONS" else default)
    monkeypatch.setattr(mod, "_nearest_hour_str", lambda: "2026-06-20T12:00")
    monkeypatch.setattr(mod, "_OUT_FILE", str(tmp_path / "atmosphere_latest.json"))
    monkeypatch.setattr(mod, "_QUALITY_FILE", str(tmp_path / "atmosphere_feature_quality.json"))
    monkeypatch.setattr(mod, "_bulk_get_batched", lambda base, label, locations: [_resp({})])
    monkeypatch.setitem(__import__("sys").modules, "cloud_height_from_eumetview", type("M", (), {"fetch_cloud_height_for_points": staticmethod(lambda pts: {pts[0]: 9000.0})}))

    out = mod.fetch_atmospheric_snapshot()["locations"][0]
    assert out["wind_300hpa"] is None
    assert out["wind_300hpa_missing"] == 1
    assert out["wind_dir_300_cos"] is None
    assert out["wind_dir_300_missing"] == 1
    assert out["geopotential_300hpa"] is None
    assert out["geopotential_300hpa_missing"] == 1


def test_cloud_height_missing_is_not_stored_as_zero(monkeypatch, tmp_path):
    locs = [{"name": "A", "lat": 46.6, "lon": 14.3}]
    monkeypatch.setattr(mod.runtime_config, "get", lambda key, default=None: locs if key == "ATM_SNAPSHOT_LOCATIONS" else default)
    monkeypatch.setattr(mod, "_nearest_hour_str", lambda: "2026-06-20T12:00")
    monkeypatch.setattr(mod, "_OUT_FILE", str(tmp_path / "atmosphere_latest.json"))
    monkeypatch.setattr(mod, "_QUALITY_FILE", str(tmp_path / "atmosphere_feature_quality.json"))
    monkeypatch.setattr(mod, "_bulk_get_batched", lambda base, label, locations: [_resp({})])
    monkeypatch.setitem(__import__("sys").modules, "cloud_height_from_eumetview", type("M", (), {"fetch_cloud_height_for_points": staticmethod(lambda pts: {pts[0]: None})}))

    out = mod.fetch_atmospheric_snapshot()["locations"][0]
    assert out["cloud_height_m"] is None
    assert out["cloud_height_missing"] == 1


def test_constant_zero_feature_is_reported_in_quality_status(tmp_path):
    quality = mod._build_feature_quality([
        {"cape": 0.0, "li": -1.0, "cloud_height_m": None, "cloud_height_missing": 1},
        {"cape": 0, "li": -2.0, "cloud_height_m": None, "cloud_height_missing": 1},
    ])
    assert "cape" in quality["constant_zero_features"]
    assert "li" not in quality["constant_zero_features"]
    assert quality["missing_counts"]["cloud_height_missing"] == 2


def test_size_training_vector_uses_nan_and_missing_flag_for_missing_cloud_height():
    vec = size_regressor._to_feature_vector({"cloud_height_m": None, "cloud_height_missing": 1})
    cloud_idx = size_regressor._FEATURE_KEYS.index("cloud_height_m")
    flag_idx = size_regressor._FEATURE_KEYS.index("cloud_height_missing")
    assert vec[cloud_idx] != vec[cloud_idx]  # NaN
    assert vec[flag_idx] == 1.0
