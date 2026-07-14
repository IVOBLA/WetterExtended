import json
from datetime import datetime, timedelta


def _import_accuracy_tracker(monkeypatch, tmp_path):
    # B359: siehe test_b296_nn_threshold_and_median.py — kein sys.modules.pop
    # mehr, direktes Patchen des bereits importierten Moduls.
    import accuracy_tracker as at
    monkeypatch.setattr(at, "debug_log", lambda *args, **kwargs: None, raising=False)
    # B216: evaluation-Schreibpfade pro Test nach tmp_path (defense-in-depth zur
    # conftest-Fixture) — evaluate_for_horizon darf nie die echte
    # forecast_error_details.jsonl/accuracy_history.jsonl berühren.
    ev = tmp_path / "evaluation"
    ev.mkdir(exist_ok=True)
    monkeypatch.setattr(at, "EVAL_DIR", str(ev), raising=False)
    monkeypatch.setattr(at, "DETAILS_FILE", str(ev / "forecast_error_details.jsonl"), raising=False)
    monkeypatch.setattr(at, "HISTORY_FILE", str(ev / "accuracy_history.jsonl"), raising=False)
    return at


def _write_objects(directory, ts, objects):
    path = directory / f"{ts:%Y-%m-%d_%H-%M-%S}.json"
    path.write_text(json.dumps(objects), encoding="utf-8")
    return path


def test_evaluate_for_horizon_uses_per_horizon_forecast_mode(monkeypatch, tmp_path):
    accuracy_tracker = _import_accuracy_tracker(monkeypatch, tmp_path)

    obj_dir = tmp_path / "objects"
    obj_dir.mkdir()
    t0 = datetime(2026, 6, 18, 12, 0, 0)
    _write_objects(
        obj_dir,
        t0,
        [{
            "id": "WX-TEST-1",
            "cell_id": "WX-TEST-1",
            "x": 10.0,
            "y": 20.0,
            "lat": 46.70,
            "lon": 14.10,
            "forecast_x_30": 10.0,
            "forecast_y_30": 20.0,
            "forecast_lat_30": 46.70,
            "forecast_lon_30": 14.10,
            "forecast_mode": "ml",
            "forecast_mode_30": "kinematic",
            "kinematic_source": "object-summary",
            "kinematic_source_30": "ewma_3f",
        }],
    )
    _write_objects(obj_dir, t0 + timedelta(minutes=30), [{"id": "WX-TEST-1", "cell_id": "WX-TEST-1", "x": 10.0, "y": 20.0, "lat": 46.70, "lon": 14.10}])

    monkeypatch.setitem(accuracy_tracker.SAVE_PATHS, "objects", str(obj_dir))

    result = accuracy_tracker.evaluate_for_horizon(30, since_hours=24)

    assert result["by_forecast_mode"]["kinematic"]["samples"] == 1
    assert "ml" not in result["by_forecast_mode"]
    assert result["by_kinematic_source"]["ewma_3f"]["samples"] == 1


def test_evaluate_for_horizon_falls_back_to_object_forecast_mode(monkeypatch, tmp_path):
    accuracy_tracker = _import_accuracy_tracker(monkeypatch, tmp_path)

    obj_dir = tmp_path / "objects"
    obj_dir.mkdir()
    t0 = datetime(2026, 6, 18, 12, 0, 0)
    _write_objects(
        obj_dir,
        t0,
        [{
            "id": "WX-TEST-1",
            "cell_id": "WX-TEST-1",
            "x": 10.0,
            "y": 20.0,
            "lat": 46.70,
            "lon": 14.10,
            "forecast_x_30": 10.0,
            "forecast_y_30": 20.0,
            "forecast_lat_30": 46.70,
            "forecast_lon_30": 14.10,
            "forecast_mode": "ml",
            "kinematic_source": "legacy-source",
        }],
    )
    _write_objects(obj_dir, t0 + timedelta(minutes=30), [{"id": "WX-TEST-1", "cell_id": "WX-TEST-1", "x": 10.0, "y": 20.0, "lat": 46.70, "lon": 14.10}])

    monkeypatch.setitem(accuracy_tracker.SAVE_PATHS, "objects", str(obj_dir))

    result = accuracy_tracker.evaluate_for_horizon(30, since_hours=24)

    assert result["by_forecast_mode"]["ml"]["samples"] == 1
    assert result["by_kinematic_source"]["legacy-source"]["samples"] == 1


def test_evaluate_for_horizon_isolates_details_file(monkeypatch, tmp_path):
    """B216: evaluate_for_horizon schreibt NICHT in die echte forecast_error_details.jsonl."""
    from pathlib import Path

    accuracy_tracker = _import_accuracy_tracker(monkeypatch, tmp_path)
    assert str(tmp_path) in str(accuracy_tracker.DETAILS_FILE), \
        f"DETAILS_FILE nicht isoliert: {accuracy_tracker.DETAILS_FILE}"

    obj_dir = tmp_path / "objects"
    obj_dir.mkdir()
    t0 = datetime(2026, 6, 18, 12, 0, 0)
    _write_objects(obj_dir, t0, [{
        "id": "WX-TEST-1", "cell_id": "WX-TEST-1", "x": 10.0, "y": 20.0, "lat": 46.70, "lon": 14.10,
        "forecast_x_30": 10.0, "forecast_y_30": 20.0,
        "forecast_lat_30": 46.70, "forecast_lon_30": 14.10,
        "forecast_mode_30": "kinematic", "kinematic_source_30": "ewma_3f",
    }])
    _write_objects(obj_dir, t0 + timedelta(minutes=30),
                   [{"id": "WX-TEST-1", "cell_id": "WX-TEST-1", "x": 10.0, "y": 20.0, "lat": 46.70, "lon": 14.10}])
    monkeypatch.setitem(accuracy_tracker.SAVE_PATHS, "objects", str(obj_dir))

    accuracy_tracker.evaluate_for_horizon(30, since_hours=24)

    assert Path(accuracy_tracker.DETAILS_FILE).exists(), \
        "Detail-Record nicht in den isolierten tmp-Pfad geschrieben"
    assert str(tmp_path) in str(accuracy_tracker.DETAILS_FILE)
