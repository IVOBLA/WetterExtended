import json
from pathlib import Path

import config
import hydro_flood_ml
import hydro_impact


def test_hydro_flood_features_are_separate_from_cell_ml():
    assert hasattr(config, "HYDRO_FLOOD_ML_FEATURES")
    forbidden = ("hydro", "q_", "w_", "hq")
    assert not any(any(tok in f.lower() for tok in forbidden) for f in config.ML_CELL_FEATURES)
    assert "current_q_m3s" in config.HYDRO_FLOOD_ML_FEATURES
    assert "w_cm" not in config.HYDRO_FLOOD_ML_FEATURES


def test_station_threshold_uses_mark_q_and_missing(monkeypatch):
    monkeypatch.setattr(hydro_flood_ml.runtime_config, "get", lambda k, d=None: None if k == "HYDRO_MAP_MARK_Q_M3S" else d)
    row = hydro_flood_ml.build_feature_row({"station_id":"S1", "mark_q_m3s": 10, "q_m3s": 8})
    assert row["station_q_threshold_m3s"] == 10
    assert row["station_q_threshold_source"] == "station_override"
    missing = hydro_flood_ml.build_feature_row({"station_id":"S2", "q_m3s": 8})
    assert missing["station_q_threshold_missing"] is True
    assert missing["station_q_threshold_source"] == "missing"
    sc = hydro_flood_ml.heuristic_score(missing)
    assert sc["flood_expected"] is False
    assert "missing_station_q_threshold" in sc["warning_reasons"]


def test_observed_precip_never_overwritten_by_proxy():
    station = {"station_id":"S1", "mark_q_m3s": 10, "q_m3s": 5, "observed_precip": {"sum_mm": 4, "quality": "high", "source_name":"gauge"}}
    cell = {"_hydro_overlap": {"hit": True, "overlap_area_km2": 5, "overlap_ratio_cell": 1, "cell_area_km2": 5}, "nowcast_rr_mm15": 20, "core_ratio": 1}
    row = hydro_flood_ml.build_feature_row(station, cells=[cell])
    assert row["observed_precip_available"] is True
    assert row["effective_catchment_precip_sum_mm"] == 4
    assert row["effective_precip_source_type"] == "measured"
    assert row["effective_precip_is_proxy"] is False


def test_cell_in_catchment_increases_precip_features(monkeypatch):
    from shapely.geometry import Polygon

    catchment = Polygon([(0, 0), (0.1, 0), (0.1, 0.1), (0, 0.1), (0, 0)])
    monkeypatch.setattr(hydro_flood_ml.runtime_config, "get", lambda name, default=None: 0.0 if name == "HYDRO_MIN_OVERLAP_AREA_KM2" else default)
    monkeypatch.setattr(hydro_impact, "load_station_catchment_index", lambda force_reload=False: {"S1": {"station_id": "S1", "geometry": catchment, "feature_count": 1, "status": "ok", "area_km2": 1, "signature": "x", "properties": {}}})
    monkeypatch.setattr(hydro_impact, "catchment_diagnostics", lambda sid: {"catchment_geometry_available": True, "catchment_geometry_status": "ok", "catchment_feature_count": 1, "catchment_area_geometry_km2": 1, "catchment_signature": "x"})

    station = {"station_id": "S1", "mark_q_m3s": 10, "q_m3s": 5}
    inside = {"id": "C1", "contour_geo": [[0.02, 0.02], [0.08, 0.02], [0.08, 0.08], [0.02, 0.08], [0.02, 0.02]], "lat": 0.05, "lon": 0.05, "nowcast_rr_mm15": 6, "core_ratio": 0.7}
    outside = {"id": "C2", "contour_geo": [[0.2, 0.2], [0.3, 0.2], [0.3, 0.3], [0.2, 0.3], [0.2, 0.2]], "lat": 0.25, "lon": 0.25, "nowcast_rr_mm15": 100}
    row_with_inside = hydro_flood_ml.build_feature_row(station, cells=[inside, outside])
    row_only_outside = hydro_flood_ml.build_feature_row(station, cells=[outside])
    assert row_with_inside["cell_catchment_count"] == 1
    assert row_only_outside["cell_catchment_count"] == 0
    assert row_with_inside["effective_catchment_precip_sum_mm"] > 0
    assert row_only_outside["effective_catchment_precip_sum_mm"] == 0
    assert row_with_inside["cell_catchment_overlap_area_km2_sum"] > 0


def test_live_output_has_no_horizons_or_w_forecast():
    doc = hydro_flood_ml.evaluate_live_flood_risk(stations=[{"station_id":"S1", "mark_q_m3s": 10, "q_m3s": 11}], write=False, include_debug=True)
    row = doc["stations"][0]
    assert row["flood_expected"] is True
    assert row["model_source"] == "heuristic_scoring"
    forbidden = {"w_cm_pred", "w_delta_cm_pred", "q_m3s_max_pred", "q_forecast_m3s", "forecasts"}
    assert forbidden.isdisjoint(row)


def test_append_history_writes_q_without_using_w_as_feature(tmp_path, monkeypatch):
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_HISTORY_PATH", tmp_path / "hydro_history.jsonl")
    n = hydro_flood_ml.append_hydro_history({"fetched_at":"2026-06-25T00:00:00Z", "source":"x", "stations":[{"station_id":"S1", "name":"A", "river":"R", "q_m3s":1.2, "w_cm":99}]})
    assert n == 1
    row = json.loads((tmp_path / "hydro_history.jsonl").read_text().strip())
    assert row["q_m3s"] == 1.2
    assert row["q_missing"] is False
    assert "w_cm" in row  # roh erlaubt


def test_dataset_scan_labels_future_q_without_w_features(tmp_path, monkeypatch):
    from shapely.geometry import Polygon

    hist = tmp_path / "hydro_history.jsonl"
    future = {"fetched_at": "2026-06-25T00:30:00Z", "measured_at": "2026-06-25T00:30:00Z", "station_id": "S1", "q_m3s": 11.0}
    hist.write_text(json.dumps(future) + "\n", encoding="utf-8")
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_HISTORY_PATH", hist)
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_ML_DIR", tmp_path)
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_SAMPLE_DB_PATH", tmp_path / "samples.sqlite3")
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_DATASET_JSONL_PATH", tmp_path / "dataset.jsonl")
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_TRAINING_META_PATH", tmp_path / "meta.json")
    monkeypatch.setattr(hydro_flood_ml.runtime_config, "get", lambda k, d=None: 10.0 if k == "HYDRO_MAP_MARK_Q_M3S" else d)
    catchment = Polygon([(0, 0), (0.1, 0), (0.1, 0.1), (0, 0.1), (0, 0)])
    monkeypatch.setattr(hydro_impact, "load_station_catchment_index", lambda force_reload=False: {"S1": {"station_id": "S1", "geometry": catchment, "feature_count": 1, "status": "ok", "area_km2": 1, "signature": "x", "properties": {}}})
    monkeypatch.setattr(hydro_impact, "catchment_diagnostics", lambda sid: {"catchment_geometry_available": True, "catchment_geometry_status": "ok", "catchment_feature_count": 1, "catchment_area_geometry_km2": 1, "catchment_signature": "x"})

    live = {"fetched_at": "2026-06-25T00:00:00Z", "stations": [{"station_id": "S1", "q_m3s": 8.0, "measured_at": "2026-06-25T00:00:00Z"}]}
    cells = [{"contour_geo": [[0.02, 0.02], [0.08, 0.02], [0.08, 0.08], [0.02, 0.08], [0.02, 0.02]], "lat": 0.05, "lon": 0.05, "nowcast_rr_mm15": 1}]
    hydro_flood_ml.evaluate_live_flood_risk(stations=[{"station_id": "S1"}], live=live, cells=cells, write=True)
    status = hydro_flood_ml.build_dataset_scan()
    assert status["sample_count"] >= 1
    sample = json.loads((tmp_path / "dataset.jsonl").read_text().splitlines()[0])
    assert sample["current_q_m3s"] == 8.0
    assert sample["station_q_threshold_m3s"] == 10.0
    assert sample["target_q_delta_m3s"] == 3.0
    assert sample["target_q_threshold_exceeded"] is True
    assert sample["target_flood_expected"] is True
    assert not any(k.startswith("w_cm") for k in sample)


def test_feldkirchen_live_q_is_used_when_latest_hydro_is_newer_than_risk_cache(tmp_path, monkeypatch):
    risk = tmp_path / "latest_hydro_flood_risk.json"
    live_file = tmp_path / "latest_hydro.json"
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_RISK_PATH", risk)
    import hydro_fetch
    monkeypatch.setattr(hydro_fetch, "LATEST_FILE", live_file)
    risk.write_text(json.dumps({"input_hash": "old", "stations": [{"station_id": "2002485", "current_q_m3s": None}]}), encoding="utf-8")
    live = {"fetched_at": "2026-06-25T13:03:35Z", "stations": [{"station_id": "2002485", "q_m3s": 0.96, "data_age_min": 18.58}]}
    live_file.write_text(json.dumps(live), encoding="utf-8")
    import os, time
    os.utime(risk, (time.time() - 100, time.time() - 100))
    os.utime(live_file, None)
    monkeypatch.setattr(hydro_flood_ml.runtime_config, "get", lambda k, d=None: None if k == "HYDRO_MAP_MARK_Q_M3S" else d)
    assert hydro_flood_ml.is_flood_risk_cache_valid(json.loads(risk.read_text()), live=live, cells=[]) is False
    doc = hydro_flood_ml.evaluate_live_flood_risk(stations=[{"station_id": "2002485", "mark_q_m3s": 8}], live=live, cells=[], write=False)
    row = doc["stations"][0]
    assert row["current_q_m3s"] == 0.96
    assert row["current_q_missing"] is False


def test_stale_flood_risk_cache_is_invalidated_after_hydro_fetch(tmp_path, monkeypatch):
    risk = tmp_path / "latest_hydro_flood_risk.json"
    live_file = tmp_path / "latest_hydro.json"
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_RISK_PATH", risk)
    import hydro_fetch
    monkeypatch.setattr(hydro_fetch, "LATEST_FILE", live_file)
    live = {"fetched_at": "new", "stations": []}
    live_file.write_text(json.dumps(live), encoding="utf-8")
    risk.write_text(json.dumps({"input_hash": hydro_flood_ml.flood_risk_input_hash(live=live, cells=[])}), encoding="utf-8")
    import os, time
    os.utime(risk, (time.time() - 120, time.time() - 120))
    os.utime(live_file, None)
    assert hydro_flood_ml.is_flood_risk_cache_valid(json.loads(risk.read_text()), live=live, cells=[]) is False




def test_flood_risk_cache_hash_includes_trend_config_and_history_mtime(tmp_path, monkeypatch):
    hist = tmp_path / "hydro_history.jsonl"
    hist.write_text(json.dumps({"station_id": "S1", "q_m3s": 1.0}) + "\n", encoding="utf-8")
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_HISTORY_PATH", hist)
    values = {"HYDRO_TREND_MIN_DELTA_M3S": 0.02}
    monkeypatch.setattr(hydro_flood_ml.runtime_config, "get", lambda k, d=None: values.get(k, d))
    live = {"stations": [{"station_id": "S1", "q_m3s": 1.0}]}

    original_hash = hydro_flood_ml.flood_risk_input_hash(live=live, cells=[])
    values["HYDRO_TREND_MIN_DELTA_M3S"] = 0.5
    assert hydro_flood_ml.flood_risk_input_hash(live=live, cells=[]) != original_hash

    updated_config_hash = hydro_flood_ml.flood_risk_input_hash(live=live, cells=[])
    import os, time
    os.utime(hist, (time.time() + 10, time.time() + 10))
    assert hydro_flood_ml.flood_risk_input_hash(live=live, cells=[]) != updated_config_hash


def test_threshold_value_and_source_are_consistent(monkeypatch):
    monkeypatch.setattr(hydro_flood_ml.runtime_config, "get", lambda k, d=None: None if k == "HYDRO_MAP_MARK_Q_M3S" else d)
    row = hydro_flood_ml.build_feature_row({"station_id": "2002485", "mark_q_m3s": 8}, live={"stations": [{"station_id": "2002485", "q_m3s": 0.96}]})
    assert row["station_q_threshold_m3s"] == 8
    assert row["station_q_threshold_source"] != "missing"
    assert row["station_q_threshold_missing"] is False
    assert round(row["current_q_distance_to_threshold_m3s"], 2) == 7.04


def test_missing_threshold_is_not_evaluable(monkeypatch):
    monkeypatch.setattr(hydro_flood_ml.runtime_config, "get", lambda k, d=None: None if k == "HYDRO_MAP_MARK_Q_M3S" else d)
    sc = hydro_flood_ml.heuristic_score(hydro_flood_ml.build_feature_row({"station_id": "S", "q_m3s": 1}))
    assert sc["flood_evaluable"] is False
    assert sc["flood_status"] == "missing_threshold"
    assert sc["flood_expected"] is False


def test_data_age_exported_from_current_data_age_min(monkeypatch):
    monkeypatch.setattr(hydro_flood_ml.runtime_config, "get", lambda k, d=None: 8 if k == "HYDRO_MAP_MARK_Q_M3S" else d)
    live = {"stations": [{"station_id": "S", "q_m3s": 1, "data_age_min": 18.58}]}
    doc = hydro_flood_ml.evaluate_live_flood_risk(stations=[{"station_id": "S"}], live=live, write=False)
    assert doc["stations"][0]["current_data_age_min"] == 18.58
    assert doc["stations"][0]["data_age_min"] == 18.58


def test_missing_precip_source_is_not_confirmed_zero(monkeypatch):
    monkeypatch.setattr(hydro_flood_ml.runtime_config, "get", lambda k, d=None: 8 if k == "HYDRO_MAP_MARK_Q_M3S" else d)
    row = hydro_flood_ml.build_feature_row({"station_id": "S", "q_m3s": 1})
    assert row["precip_evaluable"] is False
    assert row["precip_status"] == "catchment_geometry_missing"
    assert row["effective_catchment_precip_sum_mm"] is None

def test_hydro_flood_exports_current_q_measured_at(monkeypatch):
    monkeypatch.setattr(hydro_flood_ml.runtime_config, "get", lambda k, d=None: 8 if k == "HYDRO_MAP_MARK_Q_M3S" else d)
    live = {"fetched_at": "2026-06-25T12:00:00Z", "stations": [{"station_id": "S", "q_m3s": 0.89, "measured_at": "2026-06-25T11:45:00Z"}]}
    row = hydro_flood_ml.evaluate_live_flood_risk(stations=[{"station_id": "S"}], live=live, write=False, include_debug=True)["stations"][0]
    assert row["current_q_m3s"] == 0.89
    assert row["current_q_measured_at"] == "2026-06-25T11:45:00Z"
    assert row["current_q_timestamp_source"] == "hydro_live.measured_at"


def test_hydro_flood_uses_fetched_at_only_as_q_timestamp_fallback(monkeypatch):
    monkeypatch.setattr(hydro_flood_ml.runtime_config, "get", lambda k, d=None: 8 if k == "HYDRO_MAP_MARK_Q_M3S" else d)
    live = {"fetched_at": "2026-06-25T12:00:00Z", "stations": [{"station_id": "S", "q_m3s": 0.89}]}
    row = hydro_flood_ml.evaluate_live_flood_risk(stations=[{"station_id": "S"}], live=live, write=False, include_debug=True)["stations"][0]
    assert row["current_q_measured_at"] == "2026-06-25T12:00:00Z"
    assert row["current_q_timestamp_source"] == "hydro_live.fetched_at_fallback"


def test_generated_at_is_not_used_as_q_measured_at(monkeypatch):
    monkeypatch.setattr(hydro_flood_ml.runtime_config, "get", lambda k, d=None: 8 if k == "HYDRO_MAP_MARK_Q_M3S" else d)
    row = hydro_flood_ml.evaluate_live_flood_risk(stations=[{"station_id": "S", "q_m3s": 0.89, "generated_at": "2026-06-25T12:00:00Z"}], write=False, include_debug=True)["stations"][0]
    assert row["current_q_measured_at"] is None
    assert row["current_q_timestamp_source"] == "missing"
