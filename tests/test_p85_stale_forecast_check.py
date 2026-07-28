"""P85 — Deterministischer Check AC-014 (stale Forecasts schreiben Warnungen fort).
Schema (Container 'stations', Felder forecast_evaluation_stale/flood_expected/
current_q_above_threshold) aus hydro_flood_ml.py belegt.
"""
import json
from pathlib import Path

from tools.ai_checks import parse_open_acs, run_all
from tools.ai_checks.checks_local import check_ac014_stale_forecast_warnings as ac014

REPO = Path(__file__).resolve().parents[1]
AICHECKS = REPO / "AIChecks.md"


def _write_risk(tmp_path, stations):
    d = tmp_path / "train_data" / "hydro" / "impact"
    d.mkdir(parents=True, exist_ok=True)
    (d / "latest_hydro_flood_risk.json").write_text(
        json.dumps({"status": "ok", "stations": stations}), encoding="utf-8")
    return tmp_path


def test_finding_on_stale_carried_warning(tmp_path):
    _write_risk(tmp_path, [{"station_id": "X1", "forecast_evaluation_stale": True,
                            "flood_expected": True, "current_q_above_threshold": False}])
    r = ac014(tmp_path)
    assert r["status"] == "finding" and "X1" in r["beleg"]


def test_ok_when_current_q_above_threshold(tmp_path):
    _write_risk(tmp_path, [{"station_id": "X1", "forecast_evaluation_stale": True,
                            "flood_expected": True, "current_q_above_threshold": True}])
    assert ac014(tmp_path)["status"] == "ok"


def test_ok_when_not_stale(tmp_path):
    _write_risk(tmp_path, [{"station_id": "X1", "forecast_evaluation_stale": False,
                            "flood_expected": True, "current_q_above_threshold": False}])
    assert ac014(tmp_path)["status"] == "ok"


def test_ok_when_no_flood_expected(tmp_path):
    _write_risk(tmp_path, [{"station_id": "X1", "forecast_evaluation_stale": True,
                            "flood_expected": False, "current_q_above_threshold": False}])
    assert ac014(tmp_path)["status"] == "ok"


def test_ok_when_missing_file(tmp_path):
    assert ac014(tmp_path)["status"] == "ok"


def test_harness_now_implements_ac014():
    summary = run_all(REPO, AICHECKS)
    by = {r["ac"]: r for r in summary["results"]}
    assert by["AC-014"]["status"] != "not_implemented"
    assert summary["total_acs"] == len(parse_open_acs(AICHECKS))
