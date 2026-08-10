"""B520 — Wartungshistorie mit Vorher-/Nachher-Zählungen."""
import json
import hydro_flood_ml as h

def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(h, "HYDRO_SAMPLE_DB_PATH", tmp_path / "s.sqlite3")
    monkeypatch.setattr(h, "HYDRO_ML_DIR", tmp_path)
    monkeypatch.setattr(h, "HYDRO_MODEL_CANDIDATES_DIR", tmp_path / "candidates")
    monkeypatch.setattr(h, "HYDRO_MODEL_HISTORY_DIR", tmp_path / "history")

def _ensure_db_exists():
    with h._sample_db(): pass

def _insert_labeled_sample(sample_id, start_time, extreme):
    with h._sample_db() as con:
        con.execute("INSERT INTO labeled_samples(sample_id,station_id,sample_start_time,labeled_at,payload) VALUES(?,?,?,?,?)", (sample_id,"s",start_time,start_time,json.dumps({"sample_id":sample_id,"current_q_above_threshold":extreme})))

def test_maintenance_report_includes_before_after_counts(monkeypatch,tmp_path):
    _isolate(monkeypatch,tmp_path); _insert_labeled_sample("l1","2026-08-06T00:00:00Z",True); r=h.hydro_ml_maintenance()
    assert (r["extreme_samples_before"],r["extreme_samples_after"],r["q_history_rows_before"],r["q_history_rows_after"])==(1,1,0,0); assert "ts_utc" in r

def test_maintenance_history_file_is_created_and_appended(monkeypatch,tmp_path):
    _isolate(monkeypatch,tmp_path); _ensure_db_exists(); h.hydro_ml_maintenance(); hist=h._maintenance_history_path(); assert len(hist.read_text().splitlines())==1; h.hydro_ml_maintenance(); assert len(hist.read_text().splitlines())==2

def test_maintenance_history_entries_are_valid_json_with_expected_fields(monkeypatch,tmp_path):
    _isolate(monkeypatch,tmp_path); _insert_labeled_sample("l1","2026-08-06T00:00:00Z",True); h.hydro_ml_maintenance(); e=json.loads(h._maintenance_history_path().read_text().splitlines()[-1]); assert all(k in e for k in ("extreme_samples_before","extreme_samples_after","q_history_rows_before","q_history_rows_after","ts_utc","db_size_before","db_size_after"))

def test_maintenance_history_is_capped_at_max_entries(monkeypatch,tmp_path):
    _isolate(monkeypatch,tmp_path); _ensure_db_exists(); monkeypatch.setattr(h,"MAINTENANCE_HISTORY_MAX_ENTRIES",3)
    for _ in range(5): h.hydro_ml_maintenance()
    assert len(h._maintenance_history_path().read_text().splitlines())==3

def test_maintenance_still_writes_latest_status_unchanged(monkeypatch,tmp_path):
    _isolate(monkeypatch,tmp_path); r=h.hydro_ml_maintenance(); assert json.loads(h._maintenance_status_path().read_text())["db_size_before"]==r["db_size_before"]

def test_maintenance_history_survives_unrelated_write_errors(monkeypatch,tmp_path):
    _isolate(monkeypatch,tmp_path); _ensure_db_exists(); monkeypatch.setattr(h,"_append_maintenance_history",lambda report: (_ for _ in ()).throw(OSError("Platte voll"))); assert h.hydro_ml_maintenance()["status"]=="ok"

def test_extreme_sample_count_reflects_actual_threshold_field(monkeypatch,tmp_path):
    _isolate(monkeypatch,tmp_path)
    for i,x in enumerate((True,False,True),1): _insert_labeled_sample(f"l{i}","2026-08-06T00:00:00Z",x)
    assert h.hydro_ml_maintenance()["extreme_samples_before"]==2
