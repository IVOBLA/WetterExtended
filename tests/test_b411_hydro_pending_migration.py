import json
import hydro_flood_ml as h


def test_pending_jsonl_migrates_once_and_archives(monkeypatch, tmp_path):
    monkeypatch.setattr(h, 'HYDRO_SAMPLE_DB_PATH', tmp_path/'s.sqlite3')
    monkeypatch.setattr(h, 'HYDRO_ML_DIR', tmp_path)
    monkeypatch.setattr(h, 'HYDRO_PENDING_SAMPLES_PATH', tmp_path/'hydro_flood_pending_samples.jsonl')
    valid={'sample_id':'a','station_id':'s','sample_start_time':'2026-01-01T00:00:00Z','features':{'current_q_m3s':1},'created_at':'2026-01-01T00:00:00Z'}
    invalid={'sample_id':'b','station_id':'','features':None}
    h.HYDRO_PENDING_SAMPLES_PATH.write_text(json.dumps(valid)+'\n'+json.dumps(valid)+'\n'+json.dumps(invalid)+'\n')
    meta=h.migrate_pending_jsonl_to_sqlite()
    assert meta['rows_imported'] == 1
    assert meta['duplicate_rows'] == 1
    assert meta['rows_invalid'] == 1
    assert len(h._db_rows('pending_samples')) == 1
    assert not h.HYDRO_PENDING_SAMPLES_PATH.exists()
