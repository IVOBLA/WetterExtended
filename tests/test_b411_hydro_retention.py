import json
import hydro_flood_ml as h


def test_maintenance_deletes_old_failure_and_dataset_rows(monkeypatch, tmp_path):
    monkeypatch.setattr(h, 'HYDRO_SAMPLE_DB_PATH', tmp_path/'s.sqlite3')
    monkeypatch.setattr(h, 'HYDRO_ML_DIR', tmp_path)
    monkeypatch.setattr(h, 'HYDRO_MODEL_CANDIDATES_DIR', tmp_path/'candidates')
    monkeypatch.setattr(h, 'HYDRO_MODEL_HISTORY_DIR', tmp_path/'history')
    with h._sample_db() as con:
        con.execute('INSERT INTO sample_failures VALUES(?,?,?,?,?)', ('f','s','2000-01-01T00:00:00Z','old','{}'))
        con.execute('INSERT INTO labeled_samples(sample_id,station_id,sample_start_time,labeled_at,payload) VALUES(?,?,?,?,?)', ('l','s','2000-01-01T00:00:00Z','2000-01-01T00:00:00Z',json.dumps({'sample_id':'l'})))
    report=h.hydro_ml_maintenance()
    assert report['deleted_failure_rows'] == 1
    assert report['deleted_dataset_rows'] == 1
