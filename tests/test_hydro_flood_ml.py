import json
from pathlib import Path

import config
import hydro_flood_ml


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


def test_cell_in_catchment_increases_precip_features():
    station = {"station_id":"S1", "mark_q_m3s": 10, "q_m3s": 5}
    inside = {"_hydro_overlap": {"hit": True, "overlap_area_km2": 5, "overlap_ratio_cell": 0.5, "cell_area_km2": 10}, "nowcast_rr_mm15": 6, "core_ratio": 0.7}
    outside = {"_hydro_overlap": {"hit": False, "overlap_area_km2": 0, "overlap_ratio_cell": 0, "cell_area_km2": 10}, "nowcast_rr_mm15": 100}
    row = hydro_flood_ml.build_feature_row(station, cells=[inside, outside])
    assert row["cell_catchment_count"] == 1
    assert row["effective_catchment_precip_sum_mm"] == 6
    assert row["cell_catchment_overlap_area_km2_sum"] == 5


def test_live_output_has_no_horizons_or_w_forecast():
    doc = hydro_flood_ml.evaluate_live_flood_risk(stations=[{"station_id":"S1", "mark_q_m3s": 10, "q_m3s": 11}], write=False)
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
    hist = tmp_path / "hydro_history.jsonl"
    rows = [
        {"fetched_at":"2026-06-25T00:00:00Z", "measured_at":"2026-06-25T00:00:00Z", "station_id":"S1", "q_m3s":8.0},
        {"fetched_at":"2026-06-25T00:30:00Z", "measured_at":"2026-06-25T00:30:00Z", "station_id":"S1", "q_m3s":11.0},
    ]
    hist.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_HISTORY_PATH", hist)
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_ML_DIR", tmp_path)
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_DATASET_JSONL_PATH", tmp_path / "dataset.jsonl")
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_TRAINING_META_PATH", tmp_path / "meta.json")
    monkeypatch.setattr(hydro_flood_ml.runtime_config, "get", lambda k, d=None: 10.0 if k == "HYDRO_MAP_MARK_Q_M3S" else d)
    status = hydro_flood_ml.build_dataset_scan()
    assert status["sample_count"] >= 1
    sample = json.loads((tmp_path / "dataset.jsonl").read_text().splitlines()[0])
    assert sample["current_q_m3s"] == 8.0
    assert sample["mark_q_m3s"] == 10.0
    assert sample["target_q_delta_m3s"] == 3.0
    assert sample["target_q_threshold_exceeded"] is True
    assert sample["target_flood_expected"] is True
    assert not any(k.startswith("w_cm") for k in sample)
