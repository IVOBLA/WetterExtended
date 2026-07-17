import json
import hydro_flood_ml as h


def test_readiness_uses_sqlite_not_broken_jsonl(monkeypatch, tmp_path):
    monkeypatch.setattr(h, 'HYDRO_SAMPLE_DB_PATH', tmp_path/'s.sqlite3')
    monkeypatch.setattr(h, 'HYDRO_ML_DIR', tmp_path)
    monkeypatch.setattr(h, 'HYDRO_DATASET_JSONL_PATH', tmp_path/'broken.jsonl')
    monkeypatch.setattr(h, 'MIN_TRAINING_SAMPLES', 1)
    h.HYDRO_DATASET_JSONL_PATH.write_text('{broken\n', encoding='utf-8')
    features={k:1.0 for k in h.HYDRO_FLOOD_ML_FEATURES}
    row={'sample_id':'1','station_id':'s','sample_kind':h.SAMPLE_KIND_LIVE,'feature_schema_version':h.FEATURE_SCHEMA_VERSION,'feature_schema_hash':h._feature_schema_hash(),'feature_snapshot_complete':True,'target_missing':False,'target_q_delta_m3s':1.0,'sample_start_time':'2026-01-01T00:00:00Z','features':features}
    with h._sample_db() as con:
        con.execute('INSERT INTO labeled_samples(sample_id,station_id,sample_start_time,labeled_at,payload,sample_kind,feature_schema_version,feature_schema_hash,feature_snapshot_complete,target_missing,target_q_delta_m3s) VALUES(?,?,?,?,?,?,?,?,?,?,?)', ('1','s',row['sample_start_time'],row['sample_start_time'],json.dumps(row),row['sample_kind'],row['feature_schema_version'],row['feature_schema_hash'],1,0,row['target_q_delta_m3s']))
    st=h.readiness_status()
    assert st['sample_count'] == 1
