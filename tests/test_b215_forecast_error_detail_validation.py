import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from forecast_error_diagnosis import build_forecast_error_diagnosis, is_valid_forecast_error_detail
from tools.diagnose_motion_pipeline import build_health

NOW = datetime.now(timezone.utc).replace(microsecond=0)


def _row(i=0, err=1.0, created=None, target=None, verified=None, **extra):
    created = created or (NOW - timedelta(minutes=20 + i))
    target = target or (created + timedelta(minutes=10))
    verified = verified or (target + timedelta(minutes=1))
    row = {
        "forecast_created_at_utc": created.isoformat().replace("+00:00", "Z"),
        "target_timestamp_utc": target.isoformat().replace("+00:00", "Z"),
        "verified_at_utc": verified.isoformat().replace("+00:00", "Z"),
        "horizon_min": 10,
        "object_id": f"cell-{100+i}",
        "cell_id": f"cell-{100+i}",
        "forecast_mode": "ml",
        "kinematic_source": "optflow_fm5.0",
        "of_available": 1,
        "forecast_error_km": err,
        "match_type": "id",
        "direction_error_deg": 5,
        "speed_error_kmh": 3,
    }
    row.update(extra)
    return row


def _write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_valid_detail_passes_validation():
    assert is_valid_forecast_error_detail(_row(), now_utc=NOW) == (True, None)


def test_rejects_verified_before_forecast_created():
    row = _row(created=NOW, target=NOW + timedelta(minutes=10), verified=NOW - timedelta(minutes=1))
    assert is_valid_forecast_error_detail(row, now_utc=NOW)[1] == "invalid_time_order"


def test_rejects_target_before_forecast_created():
    row = _row(created=NOW, target=NOW - timedelta(minutes=1), verified=NOW + timedelta(minutes=1))
    assert is_valid_forecast_error_detail(row, now_utc=NOW)[1] == "invalid_time_order"


def test_accepts_tolerance_early_verified_target_frame():
    target = NOW
    row = _row(
        created=target - timedelta(minutes=10),
        target=target,
        verified=target - timedelta(seconds=90),
    )
    assert is_valid_forecast_error_detail(row, now_utc=NOW) == (True, None)


def test_rejects_verified_before_target_beyond_time_tolerance():
    target = NOW
    row = _row(
        created=target - timedelta(minutes=10),
        target=target,
        verified=target - timedelta(seconds=91),
    )
    assert is_valid_forecast_error_detail(row, now_utc=NOW)[1] == "invalid_time_order"

def test_rejects_synthetic_cell_one_fixture():
    row = _row(object_id="cell-1", forecast_lat=47.0, actual_lat=47.0, origin_lat=47.0, forecast_lon=15.0, actual_lon=15.0, origin_lon=15.0)
    assert is_valid_forecast_error_detail(row, now_utc=NOW)[1] == "synthetic_or_test_fixture"


def test_rejects_forecast_created_in_future():
    row = _row(created=NOW + timedelta(minutes=6), target=NOW + timedelta(minutes=16), verified=NOW + timedelta(minutes=17))
    assert is_valid_forecast_error_detail(row, now_utc=NOW)[1] == "forecast_created_in_future"


def test_diagnosis_uses_only_valid_details(tmp_path):
    valid = [_row(1, err=1.0), _row(2, err=2.0)]
    invalid = [
        _row(3, verified=NOW - timedelta(hours=1), created=NOW, target=NOW + timedelta(minutes=10)),
        _row(4, target=NOW - timedelta(hours=1), created=NOW, verified=NOW + timedelta(minutes=1)),
        _row(5, object_id="cell-1", forecast_lat=47.0, actual_lat=47.0, origin_lat=47.0, forecast_lon=15.0, actual_lon=15.0, origin_lon=15.0),
        _row(6, created=NOW + timedelta(minutes=6), target=NOW + timedelta(minutes=16), verified=NOW + timedelta(minutes=17)),
        _row(7, forecast_error_km=None),
    ]
    p = tmp_path / "forecast_error_details.jsonl"
    _write_jsonl(p, valid + invalid)
    diag = build_forecast_error_diagnosis(details_path=p, accuracy_history_path=tmp_path / "h.jsonl")
    assert diag["sample_counts"]["details_total"] == 7
    assert diag["sample_counts"]["details_valid"] == 2
    assert diag["sample_counts"]["details_invalid"] == 5
    assert all(r["forecast_error_km"] in {1.0, 2.0} for r in diag["worst_forecasts"])


def test_invalid_detail_counts_exposed_in_api(monkeypatch, tmp_path):
    pytest.importorskip("flask")
    import app as app_module
    ev = tmp_path / "evaluation"
    ev.mkdir()
    monkeypatch.setitem(app_module.SAVE_PATHS, "evaluation", str(ev))
    _write_jsonl(ev / "forecast_error_details.jsonl", [_row(), _row(object_id="cell-1", forecast_lat=47.0, actual_lat=47.0, origin_lat=47.0, forecast_lon=15.0, actual_lon=15.0, origin_lon=15.0)])
    _write_jsonl(ev / "accuracy_history.jsonl", [{"timestamp_utc": NOW.isoformat().replace("+00:00", "Z")}])
    data = app_module.app.test_client().get("/api/forecast_error_breakdown").get_json()
    assert data["detail_validation"]["details_total"] == 2
    assert data["detail_validation"]["details_invalid"] == 1


def test_motion_pipeline_health_contains_detail_validation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ev = tmp_path / "train_data/evaluation"
    (tmp_path / "train_data/objects").mkdir(parents=True)
    _write_jsonl(ev / "forecast_error_details.jsonl", [_row(), _row(dummy=True)])
    health = build_health(24, tmp_path)
    assert health["detail_validation"]["details_total"] == 2
    assert health["detail_validation"]["details_invalid"] == 1


def test_no_test_fixture_written_to_runtime_eval_dir(tmp_path):
    runtime = Path("train_data/evaluation/forecast_error_details.jsonl")
    before = runtime.read_text(encoding="utf-8") if runtime.exists() else None
    p = tmp_path / "forecast_error_details.jsonl"
    _write_jsonl(p, [_row(dummy=True)])
    after = runtime.read_text(encoding="utf-8") if runtime.exists() else None
    assert after == before


def test_duplicate_details_count_once_for_mae(tmp_path):
    p = tmp_path / "forecast_error_details.jsonl"
    duplicate = _row(1, err=1.0, forecast_lat=46.0, forecast_lon=14.0, actual_lat=46.01, actual_lon=14.01)
    high = _row(2, err=9.0, forecast_lat=46.0, forecast_lon=14.0, actual_lat=46.09, actual_lon=14.09)
    _write_jsonl(p, [duplicate, dict(duplicate), high])

    diag = build_forecast_error_diagnosis(details_path=p, accuracy_history_path=tmp_path / "h.jsonl")

    assert diag["sample_counts"]["details_raw"] == 3
    assert diag["sample_counts"]["details_valid_before_dedup"] == 3
    assert diag["sample_counts"]["details_deduped"] == 2
    assert diag["sample_counts"]["duplicates_removed"] == 1
    assert diag["match_type_comparison"]["id"]["mae_km"] == 5.0


def test_no_target_frame_counts_coverage_but_not_mae(tmp_path):
    p = tmp_path / "forecast_error_details.jsonl"
    no_target = _row(1, err=None, no_target_frame=True, match_type="none")
    valid = _row(2, err=2.0)
    _write_jsonl(p, [no_target, valid])

    diag = build_forecast_error_diagnosis(details_path=p, accuracy_history_path=tmp_path / "h.jsonl")

    assert diag["coverage_diagnosis"]["no_target_frame"] == 1
    assert diag["sample_counts"]["verified_total"] == 1
    assert diag["match_type_comparison"]["id"]["mae_km"] == 2.0


def test_rejects_pytest_path_marker_as_fixture():
    row = _row(source_path="tests/tmp/pytest-123/forecast_error_details.jsonl")
    assert is_valid_forecast_error_detail(row, now_utc=NOW)[1] == "synthetic_or_test_fixture"
