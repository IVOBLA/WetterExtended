"""P120 — Welle G: AC-020 und AC-025 deterministisch migriert.

Beide lesen payload-JSON aus SQLite-Tabellen (labeled_samples bzw.
pending_samples) statt eigener Spalten -- der Payload-Parse-Aufwand, der in
Welle E bewusst vermieden wurde, um die Welle klein zu halten.
"""
import json
import sqlite3
from pathlib import Path

from tools.ai_checks.checks_local import (
    check_ac020_cell_reference_in_new_samples as ac020,
    check_ac025_no_cell_sampling_rate as ac025,
)


def _make_snapshot_with_tables(tmp_path):
    d = tmp_path / "hydro_ml"
    d.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(d / "hydro_flood_samples_snapshot.sqlite3"))
    con.execute("CREATE TABLE labeled_samples (sample_id TEXT, precip_event_active INTEGER, payload TEXT)")
    con.execute("CREATE TABLE pending_samples (sample_id TEXT, station_id TEXT, sample_start_time TEXT, payload TEXT)")
    con.commit()
    return con


def _insert_labeled(con, rows):
    con.executemany("INSERT INTO labeled_samples VALUES (?,?,?)", rows)
    con.commit()
    con.close()


def _insert_pending(con, rows):
    con.executemany("INSERT INTO pending_samples VALUES (?,?,?,?)", rows)
    con.commit()
    con.close()


# ---------------------------------------------------------------------------
# AC-020
# ---------------------------------------------------------------------------

def test_ac020_ok_no_snapshot(tmp_path):
    r = ac020(tmp_path)
    assert r["status"] == "ok"


def test_ac020_ok_all_active_samples_have_lineage(tmp_path):
    con = _make_snapshot_with_tables(tmp_path)
    _insert_labeled(con, [("s1", 1, json.dumps({"contributing_lineage_ids": ["l1", "l2"]}))])
    r = ac020(tmp_path)
    assert r["status"] == "ok"


def test_ac020_ignores_inactive_rows_with_empty_lineage(tmp_path):
    con = _make_snapshot_with_tables(tmp_path)
    _insert_labeled(con, [("s1", 0, json.dumps({"contributing_lineage_ids": []}))])
    r = ac020(tmp_path)
    assert r["status"] == "ok"


def test_ac020_finding_lost_cell_reference(tmp_path):
    con = _make_snapshot_with_tables(tmp_path)
    _insert_labeled(con, [
        ("s1", 1, json.dumps({"contributing_lineage_ids": []})),
        ("s2", 1, json.dumps({"contributing_lineage_ids": ["l1"]})),
    ])
    r = ac020(tmp_path)
    assert r["status"] == "finding"
    assert r["detail"]["count"] == 1
    assert "s1" in r["detail"]["sample_ids"]


def test_ac020_finding_missing_lineage_key(tmp_path):
    con = _make_snapshot_with_tables(tmp_path)
    _insert_labeled(con, [("s1", 1, json.dumps({}))])
    r = ac020(tmp_path)
    assert r["status"] == "finding"


# ---------------------------------------------------------------------------
# AC-025
# ---------------------------------------------------------------------------

def test_ac025_ok_no_snapshot(tmp_path):
    r = ac025(tmp_path)
    assert r["status"] == "ok"


def test_ac025_ok_below_default_limit(tmp_path):
    con = _make_snapshot_with_tables(tmp_path)
    rows = [(f"s{i}", "A", "2026-08-06T00:00:00",
              json.dumps({"precip_event_active": False, "contributing_cell_count": 0}))
            for i in range(10)]
    _insert_pending(con, rows)
    r = ac025(tmp_path)
    assert r["status"] == "ok"


def test_ac025_finding_above_default_limit(tmp_path):
    con = _make_snapshot_with_tables(tmp_path)
    rows = [(f"s{i}", "A", "2026-08-06T00:00:00",
              json.dumps({"precip_event_active": False, "contributing_cell_count": 0}))
            for i in range(30)]
    _insert_pending(con, rows)
    r = ac025(tmp_path)
    assert r["status"] == "finding"
    assert r["detail"]["offenders"][0]["station_id"] == "A"
    assert r["detail"]["offenders"][0]["count"] == 30


def test_ac025_ignores_extreme_samples(tmp_path):
    con = _make_snapshot_with_tables(tmp_path)
    rows = [(f"s{i}", "A", "2026-08-06T00:00:00",
              json.dumps({"precip_event_active": True, "contributing_cell_count": 0}))
            for i in range(30)]
    _insert_pending(con, rows)
    r = ac025(tmp_path)
    assert r["status"] == "ok"


def test_ac025_ignores_samples_with_cells(tmp_path):
    con = _make_snapshot_with_tables(tmp_path)
    rows = [(f"s{i}", "A", "2026-08-06T00:00:00",
              json.dumps({"precip_event_active": False, "contributing_cell_count": 3}))
            for i in range(30)]
    _insert_pending(con, rows)
    r = ac025(tmp_path)
    assert r["status"] == "ok"


def test_ac025_groups_by_station_and_day_separately(tmp_path):
    con = _make_snapshot_with_tables(tmp_path)
    rows = ([(f"a{i}", "A", "2026-08-06T00:00:00",
               json.dumps({"precip_event_active": False, "contributing_cell_count": 0}))
              for i in range(15)]
            + [(f"a{i}", "A", "2026-08-07T00:00:00",
                json.dumps({"precip_event_active": False, "contributing_cell_count": 0}))
               for i in range(15)])
    _insert_pending(con, rows)
    r = ac025(tmp_path)
    assert r["status"] == "ok"


def test_ac025_respects_runtime_override(tmp_path):
    con = _make_snapshot_with_tables(tmp_path)
    rows = [(f"s{i}", "A", "2026-08-06T00:00:00",
              json.dumps({"precip_event_active": False, "contributing_cell_count": 0}))
            for i in range(30)]
    _insert_pending(con, rows)
    d = tmp_path / "config"
    d.mkdir(parents=True, exist_ok=True)
    (d / "effective_runtime_config.json").write_text(
        json.dumps({"HYDRO_ML_MAX_NO_CELL_SAMPLES_PER_DAY": 50}), encoding="utf-8")
    r = ac025(tmp_path)
    assert r["status"] == "ok"
    assert r["detail"]["limit"] == 50
