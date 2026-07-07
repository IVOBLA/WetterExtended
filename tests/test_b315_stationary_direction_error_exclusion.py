"""
B315: direction_error_deg/speed_error_kmh werden bei quasi-stationaeren Zellen
(actual_displacement_km < DIRECTION_ERROR_MIN_DISPLACEMENT_KM) aus den Drift-/
Accuracy-Aggregaten ausgeklammert. forecast_error_km/MAE bleibt vollstaendig erfasst.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _write_obj(path, objs):
    path.write_text(json.dumps(objs), encoding="utf-8")


def _setup(monkeypatch, tmp_path):
    import importlib
    obj_dir = tmp_path / "objects"
    obj_dir.mkdir()
    ev_dir = tmp_path / "evaluation"
    ev_dir.mkdir()
    at = importlib.import_module("accuracy_tracker")
    importlib.reload(at)
    monkeypatch.setitem(at.SAVE_PATHS, "objects", str(obj_dir))
    monkeypatch.setitem(at.SAVE_PATHS, "evaluation", str(ev_dir))
    at.DETAILS_FILE = os.path.join(str(ev_dir), "forecast_error_details.jsonl")
    return at, obj_dir


def test_direction_error_min_displacement_default():
    import accuracy_tracker as at
    assert at.DIRECTION_ERROR_MIN_DISPLACEMENT_KM == 0.3
    assert at._direction_error_min_displacement_km() == 0.3


def test_stationary_cell_excluded_from_direction_stats(monkeypatch, tmp_path):
    at, obj_dir = _setup(monkeypatch, tmp_path)
    # Zelle bewegt sich real kaum (~0.02 km Verschiebung durch Rundung),
    # Forecast prognostiziert eine Richtung -> geometrisch instabiler grosser
    # direction_error trotz winziger tatsaechlicher Bewegung.
    _write_obj(obj_dir / "2026-07-07_00-00-00.json", [
        {"id": "WX-1", "lat": 46.60000, "lon": 13.50000,
         "forecast_lat_10": 46.605, "forecast_lon_10": 13.505,
         "forecast_x_10": 100, "forecast_y_10": 100,
         "forecast_mode": "kinematic_fallback", "kinematic_source": "optflow_fm5.0"},
    ])
    _write_obj(obj_dir / "2026-07-07_00-10-00.json", [
        {"id": "WX-1", "lat": 46.60015, "lon": 13.50012, "x": 100, "y": 100},
    ])
    res = at.evaluate_for_horizon(10, since_hours=24)
    assert res["verified"] == 1
    # Positionsfehler bleibt erfasst:
    assert res["mae_km"] is not None
    # Aber Richtungs-/Geschwindigkeitsstatistik bleibt leer (einziger Sample war stationaer):
    assert res["direction_stats"].get("count", 0) == 0


def test_moving_cell_still_counted_in_direction_stats(monkeypatch, tmp_path):
    at, obj_dir = _setup(monkeypatch, tmp_path)
    # Deutliche reale Bewegung (~5 km) -> direction_error bleibt in der Aggregation.
    _write_obj(obj_dir / "2026-07-07_00-00-00.json", [
        {"id": "WX-2", "lat": 46.60000, "lon": 13.50000,
         "forecast_lat_10": 46.63, "forecast_lon_10": 13.53,
         "forecast_x_10": 100, "forecast_y_10": 100,
         "forecast_mode": "kinematic_fallback", "kinematic_source": "optflow_fm5.0"},
    ])
    _write_obj(obj_dir / "2026-07-07_00-10-00.json", [
        {"id": "WX-2", "lat": 46.65000, "lon": 13.55000, "x": 100, "y": 100},
    ])
    res = at.evaluate_for_horizon(10, since_hours=24)
    assert res["verified"] == 1
    assert res["direction_stats"].get("count", 0) == 1
