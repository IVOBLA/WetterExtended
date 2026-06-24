import json
import os
import subprocess
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from forecast_error_diagnosis import build_forecast_error_diagnosis
from tools.diagnose_motion_pipeline import build_health
import debug_export

NOW = datetime.now(timezone.utc)


def _row(i, mode="ml", err=1.0, h=10, match="id", direction=5, speed=3, no_target=False):
    return {
        "verified_at_utc": (NOW - timedelta(minutes=i)).isoformat().replace("+00:00", "Z"),
        "horizon_min": h,
        "forecast_mode": mode,
        "kinematic_source": "optflow_fm5.0" if mode == "ml" else "kalman_only",
        "forecast_error_km": None if no_target else err,
        "match_type": "none" if no_target else match,
        "direction_error_deg": direction,
        "speed_error_kmh": speed,
        "no_target_frame": no_target,
        "cell_id": f"c{i}",
    }


def _write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _codes(diag):
    return {c["code"] for c in diag["root_cause_candidates"]}


def test_diagnose_motion_pipeline_help_runs_without_pythonpath():
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, "tools/diagnose_motion_pipeline.py", "--help"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert "ModuleNotFoundError" not in result.stderr


def test_diagnosis_missing_details_file(tmp_path):
    diag = build_forecast_error_diagnosis(details_path=tmp_path / "missing.jsonl", accuracy_history_path=tmp_path / "history.jsonl")
    assert diag["status"] in {"missing", "insufficient_data"}


def test_detects_ml_worse_than_kinematic(tmp_path):
    p = tmp_path / "forecast_error_details.jsonl"
    _write_jsonl(p, [_row(i, "ml", 7.0) for i in range(6)] + [_row(i + 10, "kinematic", 1.0) for i in range(6)])
    assert "ml_worse_than_kinematic" in _codes(build_forecast_error_diagnosis(details_path=p, accuracy_history_path=tmp_path / "h.jsonl"))


def test_detects_direction_error_dominates(tmp_path):
    p = tmp_path / "forecast_error_details.jsonl"
    _write_jsonl(p, [_row(i, direction=70, speed=5) for i in range(12)])
    assert "direction_error_dominates" in _codes(build_forecast_error_diagnosis(details_path=p, accuracy_history_path=tmp_path / "h.jsonl"))


def test_detects_speed_error_dominates(tmp_path):
    p = tmp_path / "forecast_error_details.jsonl"
    _write_jsonl(p, [_row(i, direction=5, speed=35) for i in range(12)])
    assert "speed_error_dominates" in _codes(build_forecast_error_diagnosis(details_path=p, accuracy_history_path=tmp_path / "h.jsonl"))


def test_detects_nearest_match_problem(tmp_path):
    p = tmp_path / "forecast_error_details.jsonl"
    _write_jsonl(p, [_row(i, err=6.0, match="nearest") for i in range(6)] + [_row(i + 10, err=1.0, match="id") for i in range(6)])
    assert "nearest_match_problem" in _codes(build_forecast_error_diagnosis(details_path=p, accuracy_history_path=tmp_path / "h.jsonl"))


def test_detects_coverage_limited_from_history(tmp_path):
    p = tmp_path / "forecast_error_details.jsonl"; h = tmp_path / "accuracy_history.jsonl"
    _write_jsonl(p, [_row(i) for i in range(10)])
    _write_jsonl(h, [{"timestamp_utc": NOW.isoformat().replace("+00:00", "Z"), "horizons": [{"horizon": 10, "samples": 10, "no_target_frame": 5}]}])
    assert "coverage_limited" in _codes(build_forecast_error_diagnosis(details_path=p, accuracy_history_path=h))


def test_rejects_verified_detail_with_target_after_verification(tmp_path):
    p = tmp_path / "forecast_error_details.jsonl"
    verified_at = NOW.replace(microsecond=0)
    impossible = _row(1, err=99.0, direction=90)
    impossible.update({
        "forecast_created_at_utc": (verified_at - timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
        "verified_at_utc": verified_at.isoformat().replace("+00:00", "Z"),
        "target_timestamp_utc": (verified_at + timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
    })
    valid = _row(2, err=1.0, direction=5)
    valid.update({
        "forecast_created_at_utc": (verified_at - timedelta(minutes=20)).isoformat().replace("+00:00", "Z"),
        "verified_at_utc": verified_at.isoformat().replace("+00:00", "Z"),
        "target_timestamp_utc": (verified_at - timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
    })
    _write_jsonl(p, [impossible, valid])

    diag = build_forecast_error_diagnosis(details_path=p, accuracy_history_path=tmp_path / "h.jsonl")

    assert diag["invalid_detail_counts"] == {"invalid_time_order": 1}
    assert diag["sample_counts"]["details"] == 1
    assert diag["sample_counts"]["verified_total"] == 1
    assert diag["worst_forecasts"][0]["forecast_error_km"] == 1.0

def test_low_sample_count_is_watch_not_critical(tmp_path):
    p = tmp_path / "forecast_error_details.jsonl"
    _write_jsonl(p, [_row(1), _row(2)])
    diag = build_forecast_error_diagnosis(details_path=p, accuracy_history_path=tmp_path / "h.jsonl")
    assert "low_sample_count" in _codes(diag)
    assert diag["severity"] in {"ok", "watch"}


def test_motion_pipeline_health_contains_forecast_error_diagnosis(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ev = tmp_path / "train_data/evaluation"; obj = tmp_path / "train_data/objects"
    ev.mkdir(parents=True); obj.mkdir(parents=True)
    _write_jsonl(ev / "forecast_error_details.jsonl", [_row(i) for i in range(10)])
    health = build_health(24, tmp_path)
    assert "forecast_error_diagnosis" in health
    assert (ev / "forecast_error_diagnosis.json").exists()


@pytest.mark.parametrize("have_history", [True])
def test_api_forecast_error_breakdown_contains_diagnosis(monkeypatch, tmp_path, have_history):
    flask = pytest.importorskip("flask")
    import app as app_module
    ev = tmp_path / "evaluation"; ev.mkdir()
    monkeypatch.setitem(app_module.SAVE_PATHS, "evaluation", str(ev))
    _write_jsonl(ev / "forecast_error_details.jsonl", [_row(i) for i in range(10)])
    _write_jsonl(ev / "accuracy_history.jsonl", [{"timestamp_utc": NOW.isoformat().replace("+00:00", "Z"), "breakdown_by_forecast_mode": {}}])
    data = app_module.app.test_client().get("/api/forecast_error_breakdown").get_json()
    assert data["forecast_error_diagnosis"]["status"] in {"ok", "insufficient_data"}
    assert "root_cause_candidates" in data


def test_drift_status_keeps_drift_true_and_adds_diagnosis(monkeypatch, tmp_path):
    import sys, types
    monkeypatch.setitem(sys.modules, "debug_utils", types.SimpleNamespace(debug_log=lambda *a, **k: None))
    sys.modules.pop("drift_detector", None)
    import drift_detector as dd
    monkeypatch.setattr(dd, "_EVAL_DIR", str(tmp_path), raising=True)
    monkeypatch.setattr(dd, "_HISTORY_FILE", str(tmp_path / "accuracy_history.jsonl"), raising=True)
    monkeypatch.setattr(dd, "_STATUS_FILE", str(tmp_path / "drift_status.json"), raising=True)
    monkeypatch.setattr(dd, "DRIFT_MIN_POINTS", 1, raising=True)
    monkeypatch.setattr(dd, "_has_ml_model", lambda: True)
    _write_jsonl(tmp_path / "forecast_error_details.jsonl", [_row(i, err=5.0) for i in range(10)])
    _write_jsonl(tmp_path / "accuracy_history.jsonl", [
        {
            "timestamp_utc": NOW.isoformat().replace("+00:00", "Z"),
            "horizons": [{"horizon": 10, "mae_km": 5.0}],
        },
        {
            "timestamp_utc": (NOW - timedelta(hours=40)).isoformat().replace("+00:00", "Z"),
            "horizons": [{"horizon": 10, "mae_km": 1.0}],
        },
    ])
    status = dd.check_drift()
    assert status["drift_detected"] is True
    assert status["drift_reason"] == "relative"
    assert "diagnosis_summary" in status


def test_debug_export_includes_forecast_error_diagnosis(tmp_path):
    ev = tmp_path / "train_data/evaluation"; ev.mkdir(parents=True)
    (ev / "forecast_error_diagnosis.json").write_text('{"status":"ok"}', encoding="utf-8")
    z, _, _ = debug_export.create_debug_export_zip(base_dir=tmp_path, tmp_path=tmp_path / "out.zip", now=NOW)
    with zipfile.ZipFile(z) as zf:
        assert any(n.endswith("forecast_error_diagnosis.json") for n in zf.namelist())


def test_no_external_requests_in_forecast_error_diagnosis():
    src = Path("forecast_error_diagnosis.py").read_text(encoding="utf-8")
    for token in ("requests", "httpx", "urllib.request"):
        assert token not in src
