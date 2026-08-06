"""P113 — Welle B (Teil 1): drei ACs deterministisch migriert (AC-057, AC-077,
AC-078).

AC-057 nur der Datei-Teil (Journal-Livezugriff bleibt LLM). AC-078 nur Punkt 7
der Anweisung (duration_s vs. 80% von timeout_s); Punkte 1-5 deckt bereits
check_ac080_incomplete_step_budget ab, Punkte 2/6 bleiben LLM.
"""
import json
from pathlib import Path

from tools.ai_checks.checks_local import (
    check_ac057_export_admin_panel_persistence as ac057,
    check_ac077_cycle_timing as ac077,
    check_ac078_analysis_duration_vs_timeout as ac078,
)


# ---------------------------------------------------------------------------
# AC-057
# ---------------------------------------------------------------------------

def _write_export_meta(tmp_path, doc):
    d = tmp_path / "train_data" / "evaluation" / "latest_export"
    d.mkdir(parents=True, exist_ok=True)
    (d / "latest_export_meta.json").write_text(json.dumps(doc), encoding="utf-8")


def test_ac057_finding_no_meta_file(tmp_path):
    r = ac057(tmp_path)
    assert r["status"] == "finding"
    assert "noch nie" in r["beleg"]


def test_ac057_finding_wrong_export_reason(tmp_path):
    _write_export_meta(tmp_path, {"export_reason": "last_24h_debug_run",
                                   "created_at_utc": "2026-08-05T03:00:00Z"})
    r = ac057(tmp_path)
    assert r["status"] == "finding"
    assert "last_24h_debug_run" in r["beleg"]


def test_ac057_ok_scheduled_publish(tmp_path):
    _write_export_meta(tmp_path, {"export_reason": "scheduled_branch_publish",
                                   "created_at_utc": "2026-08-05T03:00:00Z"})
    r = ac057(tmp_path)
    assert r["status"] == "ok"
    assert r["detail"]["created_at_utc"] == "2026-08-05T03:00:00Z"


# ---------------------------------------------------------------------------
# AC-077
# ---------------------------------------------------------------------------

def _write_cycle_timing(tmp_path, doc):
    d = tmp_path / "train_data" / "status"
    d.mkdir(parents=True, exist_ok=True)
    (d / "cycle_timing.json").write_text(json.dumps(doc), encoding="utf-8")


def test_ac077_ok_no_file(tmp_path):
    r = ac077(tmp_path)
    assert r["status"] == "ok"


def test_ac077_ok_below_interval(tmp_path):
    _write_cycle_timing(tmp_path, {"last_duration_s": 40, "avg_duration_s": 45,
                                    "max_duration_s": 60, "cells_active": True})
    r = ac077(tmp_path)
    assert r["status"] == "ok"


def test_ac077_ok_cells_inactive(tmp_path):
    _write_cycle_timing(tmp_path, {"last_duration_s": 500, "avg_duration_s": 500,
                                    "max_duration_s": 500, "cells_active": False})
    r = ac077(tmp_path)
    assert r["status"] == "ok"
    assert r["detail"]["cells_active"] is False


def test_ac077_finding_bottleneck(tmp_path):
    _write_cycle_timing(tmp_path, {"last_duration_s": 130, "avg_duration_s": 125,
                                    "max_duration_s": 180, "cells_active": True})
    r = ac077(tmp_path)
    assert r["status"] == "finding"
    assert "125" in r["beleg"] and "120" in r["beleg"]


def test_ac077_respects_runtime_override(tmp_path):
    _write_cycle_timing(tmp_path, {"last_duration_s": 250, "avg_duration_s": 250,
                                    "max_duration_s": 260, "cells_active": True})
    d = tmp_path / "config"
    d.mkdir(parents=True, exist_ok=True)
    (d / "effective_runtime_config.json").write_text(
        json.dumps({"LOOP_INTERVAL_CELLS_S": 300}), encoding="utf-8")
    r = ac077(tmp_path)
    assert r["status"] == "ok"
    assert r["detail"]["interval_s"] == 300


# ---------------------------------------------------------------------------
# AC-078 (nur Punkt 7)
# ---------------------------------------------------------------------------

def _write_analysis_status(tmp_path, doc):
    d = tmp_path / "train_data" / "evaluation"
    d.mkdir(parents=True, exist_ok=True)
    (d / "local_analysis_status.json").write_text(json.dumps(doc), encoding="utf-8")


def test_ac078_ok_no_duration(tmp_path):
    r = ac078(tmp_path)
    assert r["status"] == "ok"


def test_ac078_ok_well_below_timeout(tmp_path):
    _write_analysis_status(tmp_path, {"state": "ok", "duration_s": 600})
    r = ac078(tmp_path)
    assert r["status"] == "ok"


def test_ac078_finding_near_timeout_default(tmp_path):
    _write_analysis_status(tmp_path, {"state": "ok", "duration_s": 1500})
    r = ac078(tmp_path)
    assert r["status"] == "finding"
    assert r["detail"]["timeout_s"] == 1700


def test_ac078_respects_runtime_override(tmp_path):
    _write_analysis_status(tmp_path, {"state": "ok", "duration_s": 1500})
    d = tmp_path / "config"
    d.mkdir(parents=True, exist_ok=True)
    (d / "effective_runtime_config.json").write_text(
        json.dumps({"LOCAL_ANALYSIS_CONFIG": {"timeout_s": 3000}}), encoding="utf-8")
    r = ac078(tmp_path)
    assert r["status"] == "ok"
    assert r["detail"]["timeout_s"] == 3000
