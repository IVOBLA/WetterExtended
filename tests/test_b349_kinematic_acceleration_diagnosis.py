"""B349: Validierung der Beschleunigungs-Root-Cause-Hypothese (Offline-Diagnose)."""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.diagnose_kinematic_acceleration import build_diagnosis, run_before_export, load_latest, _accel_bucket, _pearson_r


def _write_details(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")


def _row(accel_proxy, fc_speed, ac_speed, horizon=10, applied=False, mode="kinematic_fallback", minutes_ago=1):
    ts = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")
    return {
        "verified_at_utc": ts,
        "forecast_mode": mode,
        "horizon_min": horizon,
        "kinematic_accel_proxy_kmh": accel_proxy,
        "kinematic_acceleration_applied": applied,
        "forecast_speed_kmh": fc_speed,
        "actual_speed_kmh": ac_speed,
        "forecast_error_km": abs(ac_speed - fc_speed) * 0.1,
    }


def test_accel_bucket_thresholds():
    assert _accel_bucket(15.0) == "accelerating_strong"
    assert _accel_bucket(5.0) == "accelerating_moderate"
    assert _accel_bucket(0.0) == "stable"
    assert _accel_bucket(-5.0) == "decelerating_moderate"
    assert _accel_bucket(-15.0) == "decelerating_strong"


def test_insufficient_data_status(tmp_path):
    ev = tmp_path / "evaluation"
    ev.mkdir()
    _write_details(ev / "forecast_error_details.jsonl", [_row(5.0, 20.0, 22.0) for _ in range(5)])
    diag = build_diagnosis(tmp_path, hours=24, evaluation_dir=ev)
    assert diag["status"] == "insufficient_data"
    assert diag["sample_counts"]["short_horizon_le_30min"] == 5


def test_detects_positive_correlation_for_accelerating_cells(tmp_path):
    """Konstruierter Fall: staerker beschleunigende Zellen haben groesseren
    (positiven) signierten Speed-Error -> Korrelation muss deutlich positiv sein."""
    ev = tmp_path / "evaluation"
    ev.mkdir()
    rows = []
    for i in range(30):
        accel = -15.0 + i  # -15 .. +14
        fc_speed = 20.0
        ac_speed = 20.0 + max(0.0, accel) * 0.6  # je staerker Beschleunigung, desto groesser Ist-Speed vs Forecast
        rows.append(_row(accel, fc_speed, ac_speed))
    _write_details(ev / "forecast_error_details.jsonl", rows)
    diag = build_diagnosis(tmp_path, hours=24, evaluation_dir=ev)
    assert diag["status"] == "ok"
    assert diag["correlation_accel_proxy_vs_signed_speed_error"] is not None
    assert diag["correlation_accel_proxy_vs_signed_speed_error"] > 0.5
    assert any("EWMA-Lag" in f for f in diag["important_findings"])


def test_no_correlation_when_speed_error_random(tmp_path):
    ev = tmp_path / "evaluation"
    ev.mkdir()
    rows = []
    pattern = [1.0, -1.0, 0.5, -0.5]
    for i in range(30):
        accel = -15.0 + i
        fc_speed = 20.0
        ac_speed = 20.0 + pattern[i % 4]
        rows.append(_row(accel, fc_speed, ac_speed))
    _write_details(ev / "forecast_error_details.jsonl", rows)
    diag = build_diagnosis(tmp_path, hours=24, evaluation_dir=ev)
    assert diag["status"] == "ok"
    assert diag["correlation_accel_proxy_vs_signed_speed_error"] is not None
    assert abs(diag["correlation_accel_proxy_vs_signed_speed_error"]) < 0.5


def test_rows_without_proxy_are_excluded(tmp_path):
    ev = tmp_path / "evaluation"
    ev.mkdir()
    rows = [_row(5.0, 20.0, 22.0) for _ in range(5)]
    legacy_row = {
        "verified_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "forecast_mode": "kinematic_fallback",
        "horizon_min": 10,
        "forecast_speed_kmh": 20.0,
        "actual_speed_kmh": 22.0,
        # kein kinematic_accel_proxy_kmh -> Legacy-Zeile vor B348
    }
    _write_details(ev / "forecast_error_details.jsonl", rows + [legacy_row])
    diag = build_diagnosis(tmp_path, hours=24, evaluation_dir=ev)
    assert diag["sample_counts"]["forecast_error_details_total"] == 6
    assert diag["sample_counts"]["kinematic_fallback_with_proxy"] == 5


def test_non_kinematic_fallback_rows_excluded(tmp_path):
    ev = tmp_path / "evaluation"
    ev.mkdir()
    rows = [_row(5.0, 20.0, 22.0, mode="ml") for _ in range(5)]
    _write_details(ev / "forecast_error_details.jsonl", rows)
    diag = build_diagnosis(tmp_path, hours=24, evaluation_dir=ev)
    assert diag["sample_counts"]["kinematic_fallback_with_proxy"] == 0


def test_run_before_export_writes_latest_file(tmp_path):
    ev = tmp_path / "train_data" / "evaluation"
    ev.mkdir(parents=True)
    rows = [_row(5.0, 20.0, 22.0) for _ in range(25)]
    _write_details(ev / "forecast_error_details.jsonl", rows)
    result = run_before_export(hours=24, base_dir=tmp_path, save_paths={"evaluation": "train_data/evaluation"})
    assert result["status"] == "ok"
    assert (ev / "kinematic_acceleration_validation_latest.json").exists()


def test_run_before_export_handles_missing_file_gracefully(tmp_path):
    result = run_before_export(hours=24, base_dir=tmp_path, save_paths={"evaluation": "train_data/evaluation"})
    assert result["status"] == "ok"  # leere Liste ist kein Fehler, nur insufficient_data


def test_load_latest_missing_returns_status_missing(tmp_path):
    result = load_latest(base_dir=tmp_path, save_paths={"evaluation": "train_data/evaluation"})
    assert result["status"] == "missing"
