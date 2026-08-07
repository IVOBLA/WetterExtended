"""P119 — Welle F: AC-028 und AC-029 deterministisch migriert."""
import json
from tools.ai_checks.checks_local import check_ac028_observed_precip_usage as ac028, check_ac029_precip_window_overlap as ac029


def _write_diag(tmp_path, doc):
    d = tmp_path / "train_data" / "hydro" / "impact"; d.mkdir(parents=True, exist_ok=True)
    (d / "precip_window_diagnostics.json").write_text(json.dumps(doc), encoding="utf-8")


def test_ac028_ok_no_file(tmp_path): assert ac028(tmp_path)["status"] == "ok"
def test_ac028_ok_no_measured_precip_rows(tmp_path):
    _write_diag(tmp_path, {"stations": [{"observed_precip_available": False}]}); assert ac028(tmp_path)["status"] == "ok"
def test_ac028_ok_all_used(tmp_path):
    _write_diag(tmp_path, {"stations": [{"observed_precip_available": True, "observed_precip_used_in_forecast": True}] * 2}); assert ac028(tmp_path)["status"] == "ok"
def test_ac028_ok_below_fifty_percent_rejection(tmp_path):
    _write_diag(tmp_path, {"stations": [{"observed_precip_available": True, "observed_precip_used_in_forecast": False, "observed_precip_rejection_reason": "reason_x"}, {"observed_precip_available": True, "observed_precip_used_in_forecast": True}, {"observed_precip_available": True, "observed_precip_used_in_forecast": True}]}); assert ac028(tmp_path)["status"] == "ok"
def test_ac028_finding_dominant_rejection_reason(tmp_path):
    _write_diag(tmp_path, {"stations": [{"observed_precip_available": True, "observed_precip_used_in_forecast": False, "observed_precip_rejection_reason": "measurement_window_overlap"}, {"observed_precip_available": True, "observed_precip_used_in_forecast": False, "observed_precip_rejection_reason": "measurement_window_overlap"}, {"observed_precip_available": True, "observed_precip_used_in_forecast": True}]}); r=ac028(tmp_path); assert r["status"] == "finding" and "measurement_window_overlap" in r["beleg"]
def test_ac028_ignores_rows_without_observed_precip(tmp_path):
    _write_diag(tmp_path, {"stations": [{"observed_precip_available": False, "observed_precip_used_in_forecast": False}]}); assert ac028(tmp_path)["status"] == "ok"
def test_ac029_ok_no_file(tmp_path): assert ac029(tmp_path)["status"] == "ok"
def test_ac029_ok_zero_overlap(tmp_path):
    _write_diag(tmp_path, {"stations": [{"station_id": "A", "precip_window_overlap_min": 0.0}]}); assert ac029(tmp_path)["status"] == "ok"
def test_ac029_finding_positive_overlap(tmp_path):
    _write_diag(tmp_path, {"stations": [{"station_id": "A", "precip_window_overlap_min": 5.5}]}); r=ac029(tmp_path); assert r["status"] == "finding" and r["detail"]["hits"][0]["station_id"] == "A"
def test_ac029_finding_multiple_stations(tmp_path):
    _write_diag(tmp_path, {"stations": [{"station_id":"A","precip_window_overlap_min":1.0},{"station_id":"B","precip_window_overlap_min":0.0},{"station_id":"C","precip_window_overlap_min":2.0}]}); r=ac029(tmp_path); assert r["status"] == "finding" and len(r["detail"]["hits"]) == 2
def test_ac029_ok_missing_field_ignored(tmp_path):
    _write_diag(tmp_path, {"stations": [{"station_id": "A"}]}); assert ac029(tmp_path)["status"] == "ok"
