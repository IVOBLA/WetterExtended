"""P84 — Deterministische Drift-Checks AC-046 (Pooling-Guard) und AC-047
(uebersprungene Horizonte). Schema aus drift_detector.py belegt.
"""
import json
from pathlib import Path

from tools.ai_checks import parse_open_acs, run_all
from tools.ai_checks.checks_local import (
    check_ac046_drift_pooling as ac046,
    check_ac047_skipped_horizons as ac047,
)

REPO = Path(__file__).resolve().parents[1]
AICHECKS = REPO / "AIChecks.md"


def _write_drift(tmp_path, obj):
    ev = tmp_path / "train_data" / "evaluation"
    ev.mkdir(parents=True, exist_ok=True)
    (ev / "drift_status.json").write_text(json.dumps(obj), encoding="utf-8")
    return tmp_path


def test_ac046_ok_when_no_drift(tmp_path):
    _write_drift(tmp_path, {"drift_detected": False})
    assert ac046(tmp_path)["status"] == "ok"


def test_ac046_ok_when_legit_trigger(tmp_path):
    _write_drift(tmp_path, {"drift_detected": True, "triggering_horizons": [5],
                            "delta_by_horizon": {"5": 0.9}})
    assert ac046(tmp_path)["status"] == "ok"


def test_ac046_finding_when_no_triggering_horizon(tmp_path):
    _write_drift(tmp_path, {"drift_detected": True, "triggering_horizons": [],
                            "delta_by_horizon": {"5": -0.2, "10": 0.0}})
    assert ac046(tmp_path)["status"] == "finding"


def test_ac046_finding_when_all_horizons_equal_or_better(tmp_path):
    _write_drift(tmp_path, {"drift_detected": True, "triggering_horizons": [5],
                            "delta_by_horizon": {"5": -0.5, "10": 0.0}})
    assert ac046(tmp_path)["status"] == "finding"


def test_ac046_ok_when_missing_file(tmp_path):
    assert ac046(tmp_path)["status"] == "ok"


def test_ac047_finding_when_skipped(tmp_path):
    _write_drift(tmp_path, {"skipped_horizons_not_in_both_windows": [30, 45]})
    r = ac047(tmp_path)
    assert r["status"] == "finding" and "30" in r["beleg"]


def test_ac047_ok_when_none_skipped(tmp_path):
    _write_drift(tmp_path, {"skipped_horizons_not_in_both_windows": []})
    assert ac047(tmp_path)["status"] == "ok"


def test_ac047_ok_when_missing_file(tmp_path):
    assert ac047(tmp_path)["status"] == "ok"


def test_harness_now_implements_ac046_and_ac047():
    summary = run_all(REPO, AICHECKS)
    by = {r["ac"]: r for r in summary["results"]}
    assert by["AC-046"]["status"] != "not_implemented"
    assert by["AC-047"]["status"] != "not_implemented"
    assert summary["total_acs"] == len(parse_open_acs(AICHECKS))
