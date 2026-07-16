import json
from datetime import datetime, timedelta, timezone

import hydro_flood_ml as h


def test_label_without_threshold_materializes_q_targets():
    start = {"measured_at":"2026-01-01T00:00:00Z", "q_m3s": 5.0}
    future = [{"measured_at":"2026-01-01T01:00:00Z", "q_m3s": 7.0}]
    label = h._label_from_future(start, future, None)
    assert label["target_missing"] is False
    assert label["target_q_delta_m3s"] == 2.0
    assert label["target_q_max_m3s"] == 7.0
    assert label["target_q_threshold_exceeded"] is None


def test_build_dataset_scan_preserves_existing_complete_sample(monkeypatch, tmp_path):
    monkeypatch.setattr(h, "HYDRO_DATASET_JSONL_PATH", tmp_path/"dataset.jsonl")
    monkeypatch.setattr(h, "HYDRO_DATASET_PATH", tmp_path/"legacy.jsonl")
    monkeypatch.setattr(h, "HYDRO_TRAINING_META_PATH", tmp_path/"meta.json")
    existing = {"sample_id":"keep", "station_id":"S", "features":{"contributing_cell_count": 1}, "target_q_delta_m3s": 1.2}
    h.HYDRO_DATASET_JSONL_PATH.write_text(json.dumps(existing)+"\n", encoding="utf-8")
    monkeypatch.setattr(h, "_read_history_rows", lambda: [])
    h.build_dataset_scan()
    rows = [json.loads(l) for l in h.HYDRO_DATASET_JSONL_PATH.read_text(encoding="utf-8").splitlines()]
    assert any(r.get("sample_id") == "keep" and r.get("features", {}).get("contributing_cell_count") == 1 for r in rows)
