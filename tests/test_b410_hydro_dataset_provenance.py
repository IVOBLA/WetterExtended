import json
from pathlib import Path
import hydro_flood_ml as h

def test_legacy_q_samples_are_separated(tmp_path, monkeypatch):
    monkeypatch.setattr(h, 'HYDRO_ML_DIR', tmp_path)
    monkeypatch.setattr(h, 'HYDRO_DATASET_JSONL_PATH', tmp_path/'hydro_flood_dataset.jsonl')
    monkeypatch.setattr(h, 'HYDRO_DATASET_PATH', tmp_path/'hydro_flood_legacy_q_dataset.jsonl')
    live = {'sample_id':'l','sample_kind':h.SAMPLE_KIND_LIVE,'feature_schema_version':h.FEATURE_SCHEMA_VERSION,'feature_schema_hash':h._feature_schema_hash(),'feature_snapshot_complete':True,'target_q_delta_m3s':1,'target_missing':False,'cell_frame_hash':'x'}
    legacy = {'sample_id':'q','target_q_delta_m3s':1,'target_missing':False}
    h._write_jsonl(h.HYDRO_DATASET_JSONL_PATH, [live, legacy])
    meta = h.migrate_productive_dataset()
    assert meta['rows_live_kept'] == 1
    assert meta['rows_legacy_moved'] == 1
    assert h._jsonl_rows(h.HYDRO_DATASET_JSONL_PATH) == [live]
    assert h._jsonl_rows(h.HYDRO_DATASET_PATH)[0]['sample_kind'] == h.SAMPLE_KIND_LEGACY

def test_train_filter_requires_live_complete_schema():
    row = {'station_id':'s','sample_start_time':'2026-01-01T00:00:00Z','sample_kind':h.SAMPLE_KIND_LEGACY,'feature_schema_version':h.FEATURE_SCHEMA_VERSION,'feature_snapshot_complete':True,'features':{k:1.0 for k in h.HYDRO_FLOOD_ML_FEATURES},'target_q_delta_m3s':1,'target_missing':False}
    assert not h._sample_is_trainable_live(row)
    row['sample_kind'] = h.SAMPLE_KIND_LIVE
    row['feature_schema_hash'] = h._feature_schema_hash()
    assert h._sample_is_trainable_live(row)
