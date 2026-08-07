"""P118 — Welle E: sechs ACs deterministisch migriert."""
import json
import sqlite3

from tools.ai_checks.checks_local import (
    check_ac013_flood_warning_without_cell_frame as ac013,
    check_ac017_cell_catchment_assignment as ac017,
    check_ac022_sample_exclusion_reasons as ac022,
    check_ac027_target_distribution as ac027,
    check_ac036_event_id_not_null as ac036,
    check_ac037_event_distribution_plausibility as ac037,
)


def _write_risk_doc(tmp_path, doc):
    d = tmp_path / "train_data" / "hydro" / "impact"
    d.mkdir(parents=True, exist_ok=True)
    (d / "latest_hydro_flood_risk.json").write_text(json.dumps(doc), encoding="utf-8")


def _make_sqlite(tmp_path, labeled_rows, failure_rows=None):
    d = tmp_path / "hydro_ml"
    d.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(d / "hydro_flood_samples_snapshot.sqlite3"))
    con.execute("CREATE TABLE labeled_samples (sample_id TEXT, station_id TEXT, sample_kind TEXT, "
                "target_missing INTEGER, target_q_delta_m3s REAL, event_id TEXT, precip_event_active INTEGER)")
    con.execute("CREATE TABLE sample_failures (sample_id TEXT, station_id TEXT, reason TEXT)")
    con.executemany("INSERT INTO labeled_samples VALUES (?,?,?,?,?,?,?)", labeled_rows)
    if failure_rows:
        con.executemany("INSERT INTO sample_failures VALUES (?,?,?)", failure_rows)
    con.commit()
    con.close()


def test_ac013_ok_no_file(tmp_path): assert ac013(tmp_path)["status"] == "ok"
def test_ac013_ok_consistent_flood_expected(tmp_path):
    _write_risk_doc(tmp_path, {"cell_frame_status": "stale", "stations": [{"station_id": "A", "current_q_above_threshold": True, "flood_expected": True}]})
    assert ac013(tmp_path)["status"] == "ok"
def test_ac013_finding_suppressed_flood_expected(tmp_path):
    _write_risk_doc(tmp_path, {"cell_frame_status": "stale", "stations": [{"station_id": "A", "current_q_above_threshold": True, "flood_expected": False}]})
    r = ac013(tmp_path); assert r["status"] == "finding" and "A" in r["detail"]["stations"]
def test_ac013_ok_below_threshold_stations_ignored(tmp_path):
    _write_risk_doc(tmp_path, {"stations": [{"station_id": "A", "current_q_above_threshold": False, "flood_expected": False}]})
    assert ac013(tmp_path)["status"] == "ok"

def test_ac017_ok_no_cells_at_all(tmp_path):
    _write_risk_doc(tmp_path, {"stations": [{"station_id": "A", "input_cell_count": 0, "contributing_cell_count": 0}]})
    assert ac017(tmp_path)["status"] == "ok"
def test_ac017_ok_catchment_assignment_active(tmp_path):
    _write_risk_doc(tmp_path, {"stations": [{"station_id": "A", "input_cell_count": 3, "contributing_cell_count": 2}]})
    assert ac017(tmp_path)["status"] == "ok"
def test_ac017_finding_assignment_never_contributes(tmp_path):
    _write_risk_doc(tmp_path, {"stations": [{"station_id": "A", "input_cell_count": 3, "contributing_cell_count": 0}, {"station_id": "B", "input_cell_count": 5, "contributing_cell_count": 0}]})
    r = ac017(tmp_path); assert r["status"] == "finding" and set(r["detail"]["stations"]) == {"A", "B"}
def test_ac017_ok_mixed_stations_one_contributes(tmp_path):
    _write_risk_doc(tmp_path, {"stations": [{"station_id": "A", "input_cell_count": 3, "contributing_cell_count": 0}, {"station_id": "B", "input_cell_count": 5, "contributing_cell_count": 2}]})
    assert ac017(tmp_path)["status"] == "ok"

def test_ac022_ok_no_snapshot(tmp_path): assert ac022(tmp_path)["status"] == "ok"
def test_ac022_ok_below_five_percent(tmp_path):
    _make_sqlite(tmp_path, [("s1", "A", "live_catchment_snapshot", 0, 0.1, "e1", 0)] * 95, [("f1", "A", "reason_x")] * 3)
    assert ac022(tmp_path)["status"] == "ok"
def test_ac022_finding_above_five_percent(tmp_path):
    _make_sqlite(tmp_path, [("s1", "A", "live_catchment_snapshot", 0, 0.1, "e1", 0)] * 90, [("f1", "A", "reason_x")] * 10)
    r = ac022(tmp_path); assert r["status"] == "finding" and "reason_x" in r["beleg"]

def test_ac027_ok_no_labeled_samples(tmp_path): assert ac027(tmp_path)["status"] == "ok"
def test_ac027_ok_no_negatives_reasonable_zero_ratio(tmp_path):
    _make_sqlite(tmp_path, [(f"s{i}", "A", "live_catchment_snapshot", 0, 0.5 if i < 5 else 0.0, "e1", 0) for i in range(10)])
    assert ac027(tmp_path)["status"] == "ok"
def test_ac027_finding_negative_value(tmp_path):
    _make_sqlite(tmp_path, [("s1", "A", "live_catchment_snapshot", 0, -0.5, "e1", 0)])
    r = ac027(tmp_path); assert r["status"] == "finding" and "negative" in r["beleg"]
def test_ac027_finding_excessive_zero_ratio(tmp_path):
    _make_sqlite(tmp_path, [(f"s{i}", "A", "live_catchment_snapshot", 0, 0.0 if i < 19 else 1.0, "e1", 0) for i in range(20)])
    r = ac027(tmp_path); assert r["status"] == "finding" and "Nullanteil" in r["beleg"]
def test_ac027_ignores_rows_with_missing_target(tmp_path):
    _make_sqlite(tmp_path, [("s1", "A", "live_catchment_snapshot", 1, -99.0, "e1", 0)])
    assert ac027(tmp_path)["status"] == "ok"

def test_ac036_ok_all_event_ids_set(tmp_path):
    _make_sqlite(tmp_path, [("s1", "A", "live_catchment_snapshot", 0, 0.1, "e1", 0)])
    assert ac036(tmp_path)["status"] == "ok"
def test_ac036_finding_null_event_id(tmp_path):
    _make_sqlite(tmp_path, [("s1", "A", "live_catchment_snapshot", 0, 0.1, None, 0)])
    r = ac036(tmp_path); assert r["status"] == "finding" and r["detail"]["null_event_id_count"] == 1

def test_ac037_ok_no_events(tmp_path): assert ac037(tmp_path)["status"] == "ok"
def test_ac037_ok_evenly_distributed(tmp_path):
    _make_sqlite(tmp_path, [(f"s{i}", "A", "live_catchment_snapshot", 0, 0.1, f"e{i % 4}", 0) for i in range(20)])
    assert ac037(tmp_path)["status"] == "ok"
def test_ac037_finding_dominant_event(tmp_path):
    _make_sqlite(tmp_path, [(f"s{i}", "A", "live_catchment_snapshot", 0, 0.1, "e1" if i < 15 else "e2", 0) for i in range(20)])
    r = ac037(tmp_path); assert r["status"] == "finding" and r["detail"]["dominant_event"] == "e1"
