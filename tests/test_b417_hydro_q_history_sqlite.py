import json
import hydro_flood_ml as h

def test_q_history_migrates_and_archives(tmp_path, monkeypatch):
    live=tmp_path/'live'; live.mkdir(); src=live/'hydro_history.jsonl'; src.write_text(json.dumps({'station_id':'s','measured_at':'2026-01-01T00:00:00Z','q_m3s':1})+'\n')
    monkeypatch.setattr(h,'HYDRO_HISTORY_PATH',src); monkeypatch.setattr(h,'HYDRO_ML_DIR',tmp_path/'ml'); monkeypatch.setattr(h,'HYDRO_SAMPLE_DB_PATH',tmp_path/'ml/db.sqlite3')
    result=h.migrate_q_history_to_sqlite()
    assert result['rows_imported']==1 and not src.exists() and result['archived_path']
