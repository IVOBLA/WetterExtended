import hydro_flood_ml as h

def test_readiness_regression_not_blocked_by_class_diversity(tmp_path, monkeypatch):
    monkeypatch.setattr(h, 'MIN_TRAINING_SAMPLES', 2)
    monkeypatch.setattr(h, 'HYDRO_DATASET_JSONL_PATH', tmp_path/'d.jsonl')
    monkeypatch.setattr(h, 'HYDRO_DATASET_PATH', tmp_path/'l.jsonl')
    monkeypatch.setattr(h, 'HYDRO_TRAINING_META_PATH', tmp_path/'m.json')
    rows=[]
    for i in range(2):
        rows.append({'sample_id':str(i),'station_id':'s','sample_kind':h.SAMPLE_KIND_LIVE,'feature_schema_version':h.FEATURE_SCHEMA_VERSION,'feature_snapshot_complete':True,'target_q_delta_m3s':float(i),'target_missing':False,'cell_frame_hash':'c'})
    h._write_jsonl(h.HYDRO_DATASET_JSONL_PATH, rows)
    st=h.readiness_status()
    assert st['readiness_status'] == 'ready'
    assert 'missing_class_diversity' not in st['rejection_reasons']
