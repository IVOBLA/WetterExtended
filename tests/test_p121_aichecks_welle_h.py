"""P121 — Welle H: AC-024 und AC-026 deterministisch migriert."""
import json
from tools.ai_checks.checks_local import check_ac024_q_history_growth as ac024, check_ac026_extreme_events_preserved as ac026

def _write_history(p,entries):
 d=p/"hydro_ml"; d.mkdir(parents=True,exist_ok=True); (d/"hydro_ml_maintenance_history.jsonl").write_text("".join(json.dumps(e)+"\n" for e in entries))
def test_ac024_ok_no_history(tmp_path): assert ac024(tmp_path)["status"]=="ok"
def test_ac024_ok_single_run(tmp_path): _write_history(tmp_path,[{"q_history_rows_after":100,"deleted_q_history_rows":5}]); assert ac024(tmp_path)["detail"]["runs"]==1
def test_ac024_ok_retention_actively_deleting(tmp_path): _write_history(tmp_path,[{"q_history_rows_after":100,"deleted_q_history_rows":5},{"q_history_rows_after":95,"deleted_q_history_rows":10}]); assert ac024(tmp_path)["status"]=="ok"
def test_ac024_finding_unbounded_growth_without_deletion(tmp_path): _write_history(tmp_path,[{"q_history_rows_after":100,"deleted_q_history_rows":0},{"q_history_rows_after":200,"deleted_q_history_rows":0}]); r=ac024(tmp_path); assert r["status"]=="finding" and r["detail"]["first"]==100 and r["detail"]["last"]==200
def test_ac024_ok_growth_with_occasional_deletion(tmp_path): _write_history(tmp_path,[{"q_history_rows_after":100,"deleted_q_history_rows":0},{"q_history_rows_after":120,"deleted_q_history_rows":30}]); assert ac024(tmp_path)["status"]=="ok"
def test_ac026_ok_no_history(tmp_path): assert ac026(tmp_path)["status"]=="ok"
def test_ac026_ok_extreme_samples_preserved(tmp_path): _write_history(tmp_path,[{"extreme_samples_before":5,"extreme_samples_after":5}]); assert ac026(tmp_path)["status"]=="ok"
def test_ac026_ok_extreme_samples_growing(tmp_path): _write_history(tmp_path,[{"extreme_samples_before":5,"extreme_samples_after":8}]); assert ac026(tmp_path)["status"]=="ok"
def test_ac026_finding_extreme_samples_lost(tmp_path): _write_history(tmp_path,[{"extreme_samples_before":5,"extreme_samples_after":3}]); r=ac026(tmp_path); assert r["status"]=="finding" and r["detail"]["hits"][0]["before"]==5
def test_ac026_finds_loss_anywhere_in_history_not_just_latest(tmp_path): _write_history(tmp_path,[{"ts_utc":"t1","extreme_samples_before":5,"extreme_samples_after":5},{"ts_utc":"t2","extreme_samples_before":5,"extreme_samples_after":2},{"ts_utc":"t3","extreme_samples_before":2,"extreme_samples_after":2}]); r=ac026(tmp_path); assert r["status"]=="finding" and r["detail"]["hits"][0]["ts_utc"]=="t2"
def test_ac026_ignores_runs_with_missing_counts(tmp_path): _write_history(tmp_path,[{"status":"refused"}]); assert ac026(tmp_path)["status"]=="ok"
