import json
from datetime import datetime, timedelta, timezone

import hydro_flood_ml


def test_pending_sample_materializes_once_without_w_cm(tmp_path, monkeypatch):
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_PENDING_SAMPLES_PATH", tmp_path/"pending.jsonl")
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_DATASET_JSONL_PATH", tmp_path/"dataset.jsonl")
    monkeypatch.setattr(hydro_flood_ml, "HYDRO_HISTORY_PATH", tmp_path/"history.jsonl")
    start=datetime(2026,1,1,tzinfo=timezone.utc)
    row={"station_id":"s1","current_q_m3s":1.0,"current_q_measured_at":start.isoformat(),"station_q_threshold_m3s":2.0,"catchment_geometry_available":True,"physical_predicted_q_delta_m3s":.5}
    assert hydro_flood_ml.record_pending_samples([row])["pending_added"] == 1
    later={"station_id":"s1","measured_at":(start+timedelta(minutes=30)).isoformat(),"q_m3s":2.2}
    hydro_flood_ml.HYDRO_HISTORY_PATH.write_text(json.dumps(later)+"\n", encoding="utf-8")
    assert hydro_flood_ml.materialize_pending_samples()["labeled_added"] == 1
    assert hydro_flood_ml.materialize_pending_samples()["labeled_added"] == 0
    data=[json.loads(x) for x in hydro_flood_ml.HYDRO_DATASET_JSONL_PATH.read_text().splitlines()]
    assert len(data) == 1
    assert "w_cm" not in data[0]
    assert data[0]["target_q_delta_m3s"] == 1.2
