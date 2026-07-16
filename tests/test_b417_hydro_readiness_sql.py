import json
import hydro_flood_ml as h

def test_readiness_uses_sql_without_json_loads(tmp_path, monkeypatch):
    monkeypatch.setattr(h, 'HYDRO_ML_DIR', tmp_path); monkeypatch.setattr(h, 'HYDRO_SAMPLE_DB_PATH', tmp_path/'hydro_flood_samples.sqlite3')
    with h._sample_db() as con:
        payload={'sample_kind':h.SAMPLE_KIND_LIVE,'feature_schema_version':h.FEATURE_SCHEMA_VERSION,'feature_schema_hash':h._feature_schema_hash(),'feature_snapshot_complete':True,'target_missing':False,'target_q_delta_m3s':1,'event_id':'e'}
        con.execute("INSERT INTO labeled_samples(sample_id,station_id,sample_start_time,labeled_at,payload,sample_kind,feature_schema_version,feature_schema_hash,feature_snapshot_complete,target_missing,target_q_delta_m3s,event_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",('x','s','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z',json.dumps(payload),h.SAMPLE_KIND_LIVE,h.FEATURE_SCHEMA_VERSION,h._feature_schema_hash(),1,0,1,'e'))
    monkeypatch.setattr(json,'loads',lambda *_: (_ for _ in ()).throw(AssertionError('json.loads')))
    assert h.readiness_status()['sample_count']==1
