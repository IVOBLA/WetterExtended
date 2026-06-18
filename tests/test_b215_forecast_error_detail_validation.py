import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from forecast_error_diagnosis import build_forecast_error_diagnosis, is_valid_forecast_error_detail
from tools.diagnose_motion_pipeline import build_health

NOW = datetime.now(timezone.utc).replace(microsecond=0)


def _iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


def _valid_row(i=0, **overrides):
    created = NOW - timedelta(minutes=30 + i)
    target = created + timedelta(minutes=10)
    row = {
        "forecast_created_at_utc": _iso(created),
        "target_timestamp_utc": _iso(target),
        "verified_at_utc": _iso(target + timedelta(minutes=1)),
        "horizon_min": 10,
        "object_id": f"cell-{100+i}",
        "cell_id": f"cell-{100+i}",
        "forecast_mode": "ml",
        "kinematic_source": "optflow_fm5.0",
        "of_available": 1,
        "forecast_lat": 47.2,
        "forecast_lon": 15.2,
        "actual_lat": 47.21,
        "actual_lon": 15.21,
        "origin_lat": 47.1,
        "origin_lon": 15.1,
        "forecast_error_km": 0.7,
        "match_type": "id",
        "direction_error_deg": 5,
        "speed_error_kmh": 3,
        "missed": False,
        "no_target_frame": False,
    }
    row.update(overrides)
    return row


def _write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _codes(diag):
    return {c["code"] for c in diag.get("root_cause_candidates", [])}


def test_valid_detail_passes_validation():
    assert is_valid_forecast_error_detail(_valid_row(), now_utc=NOW) == (True, None)


def test_rejects_verified_before_forecast_created():
    row = _valid_row(verified_at_utc=_iso(NOW - timedelta(hours=2)))
    assert is_valid_forecast_error_detail(row, now_utc=NOW) == (False, "invalid_time_order")


def test_rejects_target_before_forecast_created():
    created = NOW - timedelta(minutes=30)
    row = _valid_row(forecast_created_at_utc=_iso(created), target_timestamp_utc=_iso(created - timedelta(minutes=1)))
    assert is_valid_forecast_error_detail(row, now_utc=NOW) == (False, "invalid_time_order")


def test_rejects_synthetic_cell_one_fixture():
    row = _valid_row(object_id="cell-1", forecast_lat=47.0, actual_lat=47.0, origin_lat=47.0, forecast_lon=15.0, actual_lon=15.0, origin_lon=15.0)
    assert is_valid_forecast_error_detail(row, now_utc=NOW) == (False, "synthetic_or_test_fixture")


def test_rejects_forecast_created_in_future():
    row = _valid_row(forecast_created_at_utc=_iso(NOW + timedelta(minutes=6)), target_timestamp_utc=_iso(NOW + timedelta(minutes=16)), verified_at_utc=_iso(NOW + timedelta(minutes=17)))
    assert is_valid_forecast_error_detail(row, now_utc=NOW) == (False, "forecast_created_in_future")


def test_diagnosis_uses_only_valid_details(tmp_path):
    p = tmp_path / "forecast_error_details.jsonl"
    invalids = [
        _valid_row(10, verified_at_utc=_iso(NOW - timedelta(hours=2))),
        _valid_row(11, target_timestamp_utc=_iso(NOW - timedelta(hours=2))),
        _valid_row(12, object_id="cell-1", forecast_lat=47.0, actual_lat=47.0, origin_lat=47.0, forecast_lon=15.0, actual_lon=15.0, origin_lon=15.0),
        _valid_row(13, forecast_created_at_utc=_iso(datetime.now(timezone.utc) + timedelta(minutes=6))),
        _valid_row(14, forecast_error_km=None),
    ]
    _write_jsonl(p, [_valid_row(1), _valid_row(2)] + invalids)
    diag = build_forecast_error_diagnosis(details_path=p, accuracy_history_path=tmp_path / "history.jsonl", hours=999999)
    assert diag["sample_counts"]["details_total"] == 7
    assert diag["sample_counts"]["details_valid"] == 2
    assert diag["sample_counts"]["details_invalid"] == 5
    assert "low_sample_count" in _codes(diag)
    assert diag["sample_counts"]["verified_total"] == 2


def test_invalid_detail_counts_exposed_in_api(monkeypatch, tmp_path):
    pytest.importorskip("flask")
    import app as app_module
    ev = tmp_path / "evaluation"; ev.mkdir()
    monkeypatch.setitem(app_module.SAVE_PATHS, "evaluation", str(ev))
    _write_jsonl(ev / "forecast_error_details.jsonl", [_valid_row(), _valid_row(object_id="cell-1", forecast_lat=47.0, actual_lat=47.0, origin_lat=47.0, forecast_lon=15.0, actual_lon=15.0, origin_lon=15.0)])
    _write_jsonl(ev / "accuracy_history.jsonl", [{"timestamp_utc": _iso(NOW), "breakdown_by_forecast_mode": {}}])
    data = app_module.app.test_client().get("/api/forecast_error_breakdown").get_json()
    assert "detail_validation" in data
    assert data["detail_validation"]["details_total"] == 2
    assert data["detail_validation"]["details_invalid"] == 1


def test_motion_pipeline_health_contains_detail_validation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ev = tmp_path / "train_data/evaluation"; ev.mkdir(parents=True)
    (tmp_path / "train_data/objects").mkdir(parents=True)
    _write_jsonl(ev / "forecast_error_details.jsonl", [_valid_row(), _valid_row(dummy=True)])
    health = build_health(24, tmp_path)
    assert health["detail_validation"]["details_total"] == 2
    assert health["detail_validation"]["details_invalid"] == 1


def test_no_test_fixture_written_to_runtime_eval_dir(tmp_path):
    runtime = Path("train_data/evaluation/forecast_error_details.jsonl")
    before = runtime.read_text(encoding="utf-8") if runtime.exists() else None
    p = tmp_path / "forecast_error_details.jsonl"
    _write_jsonl(p, [_valid_row(dummy=True)])
    build_forecast_error_diagnosis(details_path=p, accuracy_history_path=tmp_path / "history.jsonl")
    after = runtime.read_text(encoding="utf-8") if runtime.exists() else None
    assert after == before
