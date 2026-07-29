"""P87 — Deterministischer Check AC-043 (Richtungs-Drift-Alarm gegen Rohwerte).
Self-contained aus drift_status.json (min_points seit P86 persistiert).
"""
import json
from pathlib import Path

from tools.ai_checks import parse_open_acs, run_all
from tools.ai_checks.checks_local import check_ac043_direction_drift_alarm as ac043

REPO = Path(__file__).resolve().parents[1]
AICHECKS = REPO / "AIChecks.md"


def _write(tmp_path, by_h, alarm):
    d = tmp_path / "train_data" / "evaluation"
    d.mkdir(parents=True, exist_ok=True)
    (d / "drift_status.json").write_text(json.dumps(
        {"direction_drift_by_horizon": by_h, "direction_drift_alarm": alarm}), encoding="utf-8")
    return tmp_path


def test_dead_alarm_is_finding(tmp_path):
    _write(tmp_path, {"5": {"p90_deg": 120.0, "threshold_deg": 90.0, "samples": 25, "min_points": 20}}, False)
    r = ac043(tmp_path)
    assert r["status"] == "finding" and "toter Alarm" in r["beleg"]


def test_phantom_alarm_is_finding(tmp_path):
    _write(tmp_path, {"5": {"p90_deg": 50.0, "threshold_deg": 90.0, "samples": 25, "min_points": 20}}, True)
    r = ac043(tmp_path)
    assert r["status"] == "finding" and "Phantom" in r["beleg"]


def test_consistent_alarm_true_is_ok(tmp_path):
    _write(tmp_path, {"5": {"p90_deg": 120.0, "threshold_deg": 90.0, "samples": 25, "min_points": 20}}, True)
    assert ac043(tmp_path)["status"] == "ok"


def test_consistent_alarm_false_is_ok(tmp_path):
    _write(tmp_path, {"5": {"p90_deg": 50.0, "threshold_deg": 90.0, "samples": 25, "min_points": 20}}, False)
    assert ac043(tmp_path)["status"] == "ok"


def test_insufficient_samples_no_trigger(tmp_path):
    _write(tmp_path, {"5": {"p90_deg": 120.0, "threshold_deg": 90.0, "samples": 5, "min_points": 20}}, False)
    assert ac043(tmp_path)["status"] == "ok"


def test_old_data_without_min_points_skipped(tmp_path):
    _write(tmp_path, {"5": {"p90_deg": 120.0, "threshold_deg": 90.0, "samples": 25}}, False)
    assert ac043(tmp_path)["status"] == "ok"


def test_missing_file_is_ok(tmp_path):
    assert ac043(tmp_path)["status"] == "ok"


def test_harness_now_implements_ac043():
    summary = run_all(REPO, AICHECKS)
    by = {r["ac"]: r for r in summary["results"]}
    assert by["AC-043"]["status"] != "not_implemented"
    assert summary["total_acs"] == len(parse_open_acs(AICHECKS))
