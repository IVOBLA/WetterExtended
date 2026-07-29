"""P90 — Deterministischer Check AC-042 (Schluessel-Kontrakt accuracy_history.jsonl
<-> drift_detector.py). Enthaelt einen Contract-Test, der die hartkodierten Schluessel
mit den tatsaechlichen _v.get(...)-Lesevorgaengen in drift_detector.py synchron haelt.
"""
import json
from pathlib import Path

from tools.ai_checks import parse_open_acs, run_all
from tools.ai_checks.checks_local import check_ac042_stats_key_contract as ac042

REPO = Path(__file__).resolve().parents[1]
AICHECKS = REPO / "AIChecks.md"


def _write_hist(tmp_path, record):
    d = tmp_path / "train_data" / "evaluation"
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "accuracy_history.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps({"old": True}) + "\n")
        f.write(json.dumps(record) + "\n")  # letzte Zeile = ausgewertet
    return tmp_path


def _complete_dir():
    return {"count": 25, "median_direction_error_deg": 30.0, "p90_direction_error_deg": 120.0}


def _complete_spd():
    return {"count": 25, "median_speed_error_kmh": 5.0, "p90_speed_error_kmh": 40.0}


def test_ok_when_contract_met(tmp_path):
    _write_hist(tmp_path, {"direction_stats_by_horizon": {"5": _complete_dir()},
                           "speed_stats_by_horizon": {"5": _complete_spd()}})
    assert ac042(tmp_path)["status"] == "ok"


def test_finding_when_p90_missing(tmp_path):
    broken = {"count": 25, "median_direction_error_deg": 30.0}  # p90 fehlt
    _write_hist(tmp_path, {"direction_stats_by_horizon": {"5": broken}})
    r = ac042(tmp_path)
    assert r["status"] == "finding" and "p90_direction_error_deg" in r["beleg"]


def test_finding_when_count_missing(tmp_path):
    broken = {"median_direction_error_deg": 30.0, "p90_direction_error_deg": 120.0}
    _write_hist(tmp_path, {"direction_stats_by_horizon": {"5": broken}})
    assert ac042(tmp_path)["status"] == "finding"


def test_empty_entry_skipped(tmp_path):
    _write_hist(tmp_path, {"direction_stats_by_horizon": {"5": {}}})
    assert ac042(tmp_path)["status"] == "ok"


def test_ok_when_missing_file(tmp_path):
    assert ac042(tmp_path)["status"] == "ok"


def test_ac042_contract_matches_drift_detector():
    dd = (REPO / "drift_detector.py").read_text(encoding="utf-8")
    for key in ("p90_direction_error_deg", "median_direction_error_deg",
                "p90_speed_error_kmh", "median_speed_error_kmh"):
        assert f'_v.get("{key}")' in dd, (
            f"drift_detector liest {key} nicht mehr — AC-042-Kontrakt aktualisieren")


def test_harness_now_implements_ac042():
    summary = run_all(REPO, AICHECKS)
    by = {r["ac"]: r for r in summary["results"]}
    assert by["AC-042"]["status"] != "not_implemented"
    assert summary["total_acs"] == len(parse_open_acs(AICHECKS))
