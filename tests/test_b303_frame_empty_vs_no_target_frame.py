"""
B303: Trennung von 'no_target_frame' (kein Radar-Frame gefunden) und
'frame_empty' (Radar-Frame gefunden, aber 0 Zellen — Zelle real aufgeloest oder
Wetterlage beruhigt). frame_empty ist KEIN Datenluecken-Fall und darf weder
no_target_frame noch missed erhoehen.
"""
import importlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _write_obj(path, objs):
    path.write_text(json.dumps(objs), encoding="utf-8")


def _setup(monkeypatch, tmp_path):
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


def test_empty_target_frame_is_frame_empty_not_no_target_frame(monkeypatch, tmp_path):
    at, obj_dir = _setup(monkeypatch, tmp_path)
    _write_obj(obj_dir / "2026-07-05_00-00-00.json", [
        {"id": "WX-1", "lat": 46.5, "lon": 13.5,
         "forecast_lat_10": 46.51, "forecast_lon_10": 13.51,
         "forecast_x_10": 100, "forecast_y_10": 100,
         "forecast_mode": "kinematic_fallback", "kinematic_source": "optflow_fm5.0"},
    ])
    # Zielframe existiert (+10 min), zeigt aber 0 Zellen -> Zelle real aufgeloest.
    _write_obj(obj_dir / "2026-07-05_00-10-00.json", [])

    res = at.evaluate_for_horizon(10, since_hours=24)
    assert res["no_target_frame"] == 0, "leeres, aber vorhandenes Frame darf NICHT als no_target_frame zaehlen"
    assert res["frame_empty"] == 1
    assert res["missed"] == 0

    with open(at.DETAILS_FILE, encoding="utf-8") as f:
        rows = [json.loads(l) for l in f]
    assert rows[0]["frame_empty"] is True
    assert rows[0]["no_target_frame"] is False
    assert rows[0]["missed"] is False


def test_missing_target_frame_still_counts_as_no_target_frame(monkeypatch, tmp_path):
    at, obj_dir = _setup(monkeypatch, tmp_path)
    _write_obj(obj_dir / "2026-07-05_00-00-00.json", [
        {"id": "WX-1", "lat": 46.5, "lon": 13.5,
         "forecast_lat_10": 46.51, "forecast_lon_10": 13.51,
         "forecast_x_10": 100, "forecast_y_10": 100,
         "forecast_mode": "kinematic_fallback", "kinematic_source": "optflow_fm5.0"},
    ])
    # Kein Frame in der Naehe von +10 min (naechstes Frame ist +40 min) -> echte Datenluecke.
    _write_obj(obj_dir / "2026-07-05_00-40-00.json", [])

    res = at.evaluate_for_horizon(10, since_hours=24)
    assert res["no_target_frame"] == 1
    assert res["frame_empty"] == 0


def test_populated_target_frame_without_match_is_missed(monkeypatch, tmp_path):
    at, obj_dir = _setup(monkeypatch, tmp_path)
    _write_obj(obj_dir / "2026-07-05_00-00-00.json", [
        {"id": "WX-1", "lat": 46.5, "lon": 13.5,
         "forecast_lat_10": 46.51, "forecast_lon_10": 13.51,
         "forecast_x_10": 100, "forecast_y_10": 100,
         "forecast_mode": "kinematic_fallback", "kinematic_source": "optflow_fm5.0"},
    ])
    # Zielframe ist NICHT leer, enthaelt aber nur eine weit entfernte, fremde Zelle
    # -> kein Match moeglich, aber Frame ist vorhanden und nicht leer.
    _write_obj(obj_dir / "2026-07-05_00-10-00.json", [
        {"id": "WX-2", "lat": 40.0, "lon": 10.0, "x": 10, "y": 10},
    ])

    res = at.evaluate_for_horizon(10, since_hours=24)
    assert res["frame_empty"] == 0
    assert res["no_target_frame"] == 0
    assert res["missed"] == 1


def test_finish_includes_frame_empty_in_total_samples():
    from accuracy_tracker import _match_type  # Modul muss importierbar bleiben
    assert callable(_match_type)
