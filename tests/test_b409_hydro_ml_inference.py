import json
from pathlib import Path

import hydro_flood_ml as h


def _row(i):
    features = {k: 0.0 for k in h.HYDRO_FLOOD_ML_FEATURES}
    features.update({"current_q_m3s": 10+i%3, "physical_predicted_q_delta_m3s": float(i%5), "physical_predicted_q_max_m3s": 10+float(i%5), "rain_rate_mm_h_max": float(i), "routing_tau_min": 60})
    return {"sample_id": str(i), "station_id": f"S{i%3}", "sample_start_time": f"2026-01-{1+i//24:02d}T{i%24:02d}:00:00Z", "sample_kind": h.SAMPLE_KIND_LIVE, "feature_schema_version": h.FEATURE_SCHEMA_VERSION, "feature_schema_hash": h._feature_schema_hash(), "feature_snapshot_complete": True, "event_id": f"event-{i//10}", "cell_frame_hash": f"c{i}", "features": features, **features, "target_missing": False, "target_q_delta_m3s": features["physical_predicted_q_delta_m3s"] + features["rain_rate_mm_h_max"]*0.1}


def test_train_model_writes_joblib_and_predicts(monkeypatch, tmp_path):
    monkeypatch.setattr(h, "HYDRO_ML_DIR", tmp_path)
    monkeypatch.setattr(h, "HYDRO_DATASET_JSONL_PATH", tmp_path/"hydro_flood_dataset.jsonl")
    monkeypatch.setattr(h, "HYDRO_PENDING_SAMPLES_PATH", tmp_path/"hydro_flood_pending_samples.jsonl")
    monkeypatch.setattr(h, "HYDRO_MODEL_CURRENT_DIR", tmp_path/"model")
    monkeypatch.setattr(h, "HYDRO_MODEL_ROOT_DIR", tmp_path/"models")
    monkeypatch.setattr(h, "HYDRO_MODEL_CANDIDATES_DIR", tmp_path/"models"/"candidates")
    monkeypatch.setattr(h, "HYDRO_MODEL_HISTORY_DIR", tmp_path/"models"/"history")
    monkeypatch.setattr(h, "HYDRO_MODEL_PREVIOUS_DIR", tmp_path/"models"/"previous")
    monkeypatch.setattr(h, "MIN_TRAINING_SAMPLES", 20)
    with h._sample_db() as con:
        for i in range(40):
            row = _row(i)
            con.execute("INSERT INTO labeled_samples(sample_id,station_id,sample_start_time,labeled_at,payload,sample_kind,feature_schema_version,feature_schema_hash,feature_snapshot_complete,target_missing,target_q_delta_m3s,event_id,cell_frame_hash,precip_event_active) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (row["sample_id"],row["station_id"],row["sample_start_time"],row["sample_start_time"],json.dumps(row),*h._labeled_values(row)))
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
