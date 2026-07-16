import hydro_flood_ml as h

def test_materialize_empty_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(h,'HYDRO_ML_DIR',tmp_path); monkeypatch.setattr(h,'HYDRO_SAMPLE_DB_PATH',tmp_path/'db.sqlite3')
    assert h.materialize_pending_samples()['loaded_pending']==0
