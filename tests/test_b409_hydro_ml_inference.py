import json
from pathlib import Path

import hydro_flood_ml as h


def _row(i):
    features = {k: 0.0 for k in h.HYDRO_FLOOD_ML_FEATURES}
    features.update({"current_q_m3s": 10+i%3, "physical_predicted_q_delta_m3s": float(i%5), "physical_predicted_q_max_m3s": 10+float(i%5), "rain_rate_mm_h_max": float(i), "routing_tau_min": 60})
    return {"sample_id": str(i), "station_id": f"S{i%3}", "sample_start_time": f"2026-01-{1+i//24:02d}T{i%24:02d}:00:00Z", "feature_schema_version": h.FEATURE_SCHEMA_VERSION, "features": features, **features, "target_missing": False, "target_q_delta_m3s": features["physical_predicted_q_delta_m3s"] + features["rain_rate_mm_h_max"]*0.1}


def test_train_model_writes_joblib_and_predicts(monkeypatch, tmp_path):
    monkeypatch.setattr(h, "HYDRO_ML_DIR", tmp_path)
    monkeypatch.setattr(h, "HYDRO_DATASET_JSONL_PATH", tmp_path/"hydro_flood_dataset.jsonl")
    monkeypatch.setattr(h, "HYDRO_PENDING_SAMPLES_PATH", tmp_path/"hydro_flood_pending_samples.jsonl")
    monkeypatch.setattr(h, "HYDRO_TRAINING_META_PATH", tmp_path/"hydro_flood_training_meta.json")
    monkeypatch.setattr(h, "HYDRO_MODEL_CURRENT_DIR", tmp_path/"model")
    monkeypatch.setattr(h, "MIN_TRAINING_SAMPLES", 20)
    h.HYDRO_DATASET_JSONL_PATH.write_text("".join(json.dumps(_row(i))+"\n" for i in range(40)), encoding="utf-8")
    meta = h.train_model()
    assert (h.HYDRO_MODEL_CURRENT_DIR / "model.joblib").exists()
    assert meta["model_filename"] == "model.joblib"
    meta["promoted"] = True
    (h.HYDRO_MODEL_CURRENT_DIR / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    h._write_model_manifest(h.HYDRO_MODEL_CURRENT_DIR, meta)
    pred = h.predict_q_delta(_row(41))
    assert pred["prediction_source"] == "hydro_ml"
    assert pred["predicted_q_max_m3s"] >= pred["physical_predicted_q_delta_m3s"]


def test_predict_falls_back_on_schema_mismatch(monkeypatch, tmp_path):
    monkeypatch.setattr(h, "HYDRO_MODEL_CURRENT_DIR", tmp_path)
    (tmp_path/"metadata.json").write_text(json.dumps({"promoted": True, "feature_schema_version":"old", "feature_names":[]}), encoding="utf-8")
    row = _row(1)
    pred = h.predict_q_delta(row)
    assert pred["prediction_source"] == "physical_fallback"
    assert pred["model_rejection_reason"] == "feature_schema_mismatch"
