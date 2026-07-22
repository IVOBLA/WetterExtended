import hydro_flood_ml as h

def test_readiness_regression_not_blocked_by_class_diversity(tmp_path, monkeypatch):
    monkeypatch.setattr(h, 'MIN_TRAINING_SAMPLES', 2)
    monkeypatch.setattr(h, 'HYDRO_DATASET_JSONL_PATH', tmp_path/'d.jsonl')
    monkeypatch.setattr(h, 'HYDRO_DATASET_PATH', tmp_path/'l.jsonl')
    monkeypatch.setattr(h, 'HYDRO_ML_DIR', tmp_path)
    monkeypatch.setattr(h.runtime_config, 'get', lambda key, default=None: 1 if key in ('HYDRO_ML_MIN_TRAIN_EVENTS','HYDRO_ML_MIN_VALIDATION_EVENTS') else default)
    rows=[]
    for i in range(2):
        features={k:1.0 for k in h.HYDRO_FLOOD_ML_FEATURES}
        rows.append({'sample_id':str(i),'station_id':'s','sample_start_time':f'2026-01-0{i+1}T00:00:00Z','sample_kind':h.SAMPLE_KIND_LIVE,'feature_schema_version':h.FEATURE_SCHEMA_VERSION,'feature_schema_hash':h._feature_schema_hash(),'feature_snapshot_complete':True,'features':features,'target_q_delta_m3s':float(i),'target_missing':False,'event_id':f'e{i}','cell_frame_hash':'c'})
    with h._sample_db() as con:
        for row in rows:
            con.execute('INSERT INTO labeled_samples(sample_id,station_id,sample_start_time,labeled_at,payload,sample_kind,feature_schema_version,feature_schema_hash,feature_snapshot_complete,target_missing,target_q_delta_m3s,event_id,cell_frame_hash,precip_event_active) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (row['sample_id'],row['station_id'],row['sample_start_time'],row['sample_start_time'],__import__('json').dumps(row),*h._labeled_values(row)))
    st=h.readiness_status()
    assert st['readiness_status'] == 'ready'
    assert 'missing_class_diversity' not in st['rejection_reasons']
