import json
import sys
import types
from datetime import datetime, timedelta


def _import_accuracy_tracker(monkeypatch):
    sys.modules.pop("accuracy_tracker", None)
    monkeypatch.setitem(sys.modules, "debug_utils", types.SimpleNamespace(debug_log=lambda *args, **kwargs: None))
    return __import__("accuracy_tracker")


def _write_objects(directory, ts, objects):
    path = directory / f"{ts:%Y-%m-%d_%H-%M-%S}.json"
    path.write_text(json.dumps(objects), encoding="utf-8")
    return path


def test_evaluate_for_horizon_uses_per_horizon_forecast_mode(monkeypatch, tmp_path):
    accuracy_tracker = _import_accuracy_tracker(monkeypatch)

    obj_dir = tmp_path / "objects"
    obj_dir.mkdir()
    t0 = datetime(2026, 6, 18, 12, 0, 0)
    _write_objects(
        obj_dir,
        t0,
        [{
            "id": "cell-1",
            "x": 10.0,
            "y": 20.0,
            "lat": 47.0,
            "lon": 15.0,
            "forecast_x_30": 10.0,
            "forecast_y_30": 20.0,
            "forecast_lat_30": 47.0,
            "forecast_lon_30": 15.0,
            "forecast_mode": "ml",
            "forecast_mode_30": "kinematic",
            "kinematic_source": "object-summary",
            "kinematic_source_30": "ewma_3f",
        }],
    )
    _write_objects(obj_dir, t0 + timedelta(minutes=30), [{"id": "cell-1", "x": 10.0, "y": 20.0, "lat": 47.0, "lon": 15.0}])

    monkeypatch.setitem(accuracy_tracker.SAVE_PATHS, "objects", str(obj_dir))

    result = accuracy_tracker.evaluate_for_horizon(30, since_hours=24)

    assert result["by_forecast_mode"]["kinematic"]["samples"] == 1
    assert "ml" not in result["by_forecast_mode"]
    assert result["by_kinematic_source"]["ewma_3f"]["samples"] == 1


def test_evaluate_for_horizon_falls_back_to_object_forecast_mode(monkeypatch, tmp_path):
    accuracy_tracker = _import_accuracy_tracker(monkeypatch)

    obj_dir = tmp_path / "objects"
    obj_dir.mkdir()
    t0 = datetime(2026, 6, 18, 12, 0, 0)
    _write_objects(
        obj_dir,
        t0,
        [{
            "id": "cell-1",
            "x": 10.0,
            "y": 20.0,
            "lat": 47.0,
            "lon": 15.0,
            "forecast_x_30": 10.0,
            "forecast_y_30": 20.0,
            "forecast_lat_30": 47.0,
            "forecast_lon_30": 15.0,
            "forecast_mode": "ml",
            "kinematic_source": "legacy-source",
        }],
    )
    _write_objects(obj_dir, t0 + timedelta(minutes=30), [{"id": "cell-1", "x": 10.0, "y": 20.0, "lat": 47.0, "lon": 15.0}])

    monkeypatch.setitem(accuracy_tracker.SAVE_PATHS, "objects", str(obj_dir))

    result = accuracy_tracker.evaluate_for_horizon(30, since_hours=24)

    assert result["by_forecast_mode"]["ml"]["samples"] == 1
    assert result["by_kinematic_source"]["legacy-source"]["samples"] == 1
