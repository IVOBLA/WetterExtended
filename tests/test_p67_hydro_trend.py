import json
from pathlib import Path

import hydro_api
import hydro_flood_ml


def _write_history(path: Path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _patch_thresholds(monkeypatch):
    def get(key, default=None):
        return {
            "HYDRO_TREND_MIN_DELTA_M3S": 0.02,
            "HYDRO_TREND_MIN_DELTA_REL_PCT": 0.03,
            "HYDRO_TREND_LOOKBACK_MIN": 65,
            "HYDRO_MAP_MARK_Q_M3S": 10,
        }.get(key, default)
    monkeypatch.setattr(hydro_flood_ml.runtime_config, "get", get)


def test_missing_history_gives_insufficient_history(tmp_path, monkeypatch):
    _patch_thresholds(monkeypatch)
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_HISTORY_PATH", tmp_path / "missing.jsonl")
    row = hydro_flood_ml.build_feature_row({"station_id": "S1", "q_m3s": 1, "measured_at": "2026-06-25T12:00:00Z"})
    assert row["q_trend_status"] == "insufficient_history"
    assert row["current_q_trend_10min"] is None


def test_rising_trend_is_detected(tmp_path, monkeypatch):
    _patch_thresholds(monkeypatch)
    hist = tmp_path / "hydro_history.jsonl"
    _write_history(hist, [{"station_id": "S1", "measured_at": "2026-06-25T11:00:00Z", "q_m3s": 1.0}])
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_HISTORY_PATH", hist)
    trend = hydro_flood_ml.load_q_trend_history(hydro_flood_ml._dt("2026-06-25T12:00:00Z"))
    row = hydro_flood_ml.build_feature_row({"station_id": "S1", "q_m3s": 1.1, "measured_at": "2026-06-25T12:00:00Z"}, trend_history=trend)
    assert row["q_trend_status"] == "rising"
    assert row["current_q_trend_60min"] == 0.1
    assert row["already_rising_flag"] is True


def test_falling_trend_is_detected(tmp_path, monkeypatch):
    _patch_thresholds(monkeypatch)
    hist = tmp_path / "hydro_history.jsonl"
    _write_history(hist, [{"station_id": "S1", "measured_at": "2026-06-25T11:30:00Z", "q_m3s": 1.2}])
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_HISTORY_PATH", hist)
    trend = hydro_flood_ml.load_q_trend_history(hydro_flood_ml._dt("2026-06-25T12:00:00Z"))
    row = hydro_flood_ml.build_feature_row({"station_id": "S1", "q_m3s": 1.0, "measured_at": "2026-06-25T12:00:00Z"}, trend_history=trend)
    assert row["q_trend_status"] == "falling"
    assert row["q_trend_reference_window_min"] == 30


def test_small_change_under_threshold_is_stable(tmp_path, monkeypatch):
    _patch_thresholds(monkeypatch)
    hist = tmp_path / "hydro_history.jsonl"
    _write_history(hist, [{"station_id": "S1", "measured_at": "2026-06-25T11:50:00Z", "q_m3s": 100.0}])
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_HISTORY_PATH", hist)
    trend = hydro_flood_ml.load_q_trend_history(hydro_flood_ml._dt("2026-06-25T12:00:00Z"))
    row = hydro_flood_ml.build_feature_row({"station_id": "S1", "q_m3s": 100.01, "measured_at": "2026-06-25T12:00:00Z"}, trend_history=trend)
    assert row["q_trend_status"] == "stable"


def test_build_feature_row_uses_trend_history_and_old_callers_are_compatible(monkeypatch):
    _patch_thresholds(monkeypatch)
    trend = {"S1": [{"ts": hydro_flood_ml._dt("2026-06-25T11:50:00Z"), "q_m3s": 1.0}]}
    row = hydro_flood_ml.build_feature_row({"station_id": "S1", "q_m3s": 1.1, "measured_at": "2026-06-25T12:00:00Z"}, trend_history=trend)
    legacy = hydro_flood_ml.build_feature_row({"station_id": "S1", "q_m3s": 1.1, "measured_at": "2026-06-25T12:00:00Z"})
    assert row["q_trend_status"] == "rising"
    assert legacy["q_trend_status"] == "insufficient_history"


def test_evaluate_live_flood_risk_exposes_trend_fields(tmp_path, monkeypatch):
    _patch_thresholds(monkeypatch)
    hist = tmp_path / "hydro_history.jsonl"
    _write_history(hist, [{"station_id": "S1", "measured_at": "2026-06-25T11:50:00Z", "q_m3s": 1.0}])
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_HISTORY_PATH", hist)
    live = {"stations": [{"station_id": "S1", "q_m3s": 1.1, "measured_at": "2026-06-25T12:00:00Z"}]}
    doc = hydro_flood_ml.evaluate_live_flood_risk(stations=[{"station_id": "S1"}], live=live, write=False)
    row = doc["stations"][0]
    assert row["q_trend_status"] == "rising"
    assert row["q_trend_delta_m3s"] == 0.1
    assert row["q_trend_reference_window_min"] == 10


def test_hydro_stations_merges_trend_fields_from_valid_cache(tmp_path, monkeypatch):
    risk = tmp_path / "latest_hydro_flood_risk.json"
    risk.write_text(json.dumps({"stations": [{"station_id": "S1", "q_trend_status": "falling", "q_trend_delta_m3s": -0.2, "q_trend_reference_window_min": 60}]}), encoding="utf-8")
    monkeypatch.setattr(hydro_api, "HYDRO_FLOOD_RISK", risk)
    monkeypatch.setattr(hydro_api, "_static_index", lambda: {"S1": {"station_id": "S1", "lat": 46.0, "lon": 14.0, "impact_eligible": True, "impact_eligible_auto": True}})
    monkeypatch.setattr(hydro_api, "_json", lambda path, default: {"stations": [{"station_id": "S1", "q_m3s": 1.0}]} if path == hydro_api.LIVE_LATEST else json.loads(risk.read_text()))
    monkeypatch.setattr(hydro_api, "normalized_impacts", lambda latest_only=False, include_disabled=False: [])
    monkeypatch.setattr(hydro_api.runtime_config, "get", lambda k, d=None: None)
    monkeypatch.setattr(hydro_api, "_is_flood_risk_cache_valid_for_live", lambda risk_doc, live: True)
    fc = hydro_api.station_features()
    props = fc["features"][0]["properties"]
    assert props["q_trend_status"] == "falling"
    assert props["q_trend_delta_m3s"] == -0.2
    assert props["q_trend_reference_window_min"] == 60


def test_hydro_stations_omits_trend_fields_from_stale_cache(tmp_path, monkeypatch):
    risk = tmp_path / "latest_hydro_flood_risk.json"
    risk.write_text(json.dumps({"stations": [{"station_id": "S1", "q_trend_status": "falling", "q_trend_delta_m3s": -0.2, "q_trend_reference_window_min": 60}]}), encoding="utf-8")
    monkeypatch.setattr(hydro_api, "HYDRO_FLOOD_RISK", risk)
    monkeypatch.setattr(hydro_api, "_static_index", lambda: {"S1": {"station_id": "S1", "lat": 46.0, "lon": 14.0, "impact_eligible": True, "impact_eligible_auto": True}})
    monkeypatch.setattr(hydro_api, "_json", lambda path, default: {"stations": [{"station_id": "S1", "q_m3s": 1.0}]} if path == hydro_api.LIVE_LATEST else json.loads(risk.read_text()))
    monkeypatch.setattr(hydro_api, "normalized_impacts", lambda latest_only=False, include_disabled=False: [])
    monkeypatch.setattr(hydro_api.runtime_config, "get", lambda k, d=None: None)
    monkeypatch.setattr(hydro_api, "_is_flood_risk_cache_valid_for_live", lambda risk_doc, live: False)
    props = hydro_api.station_features()["features"][0]["properties"]
    assert "q_trend_status" not in props
    assert "q_trend_delta_m3s" not in props
    assert "q_trend_reference_window_min" not in props


def test_frontend_contains_trend_color_popup_and_no_old_hydro_color():
    for path in (Path("frontend/src/pages/MapView.jsx"), Path("frontend/src/pages/MapFullscreen.jsx")):
        text = path.read_text(encoding="utf-8")
        assert "hydroTrendColor" in text
        assert "Tendenz:" in text
        assert "function hydroColor" not in text
