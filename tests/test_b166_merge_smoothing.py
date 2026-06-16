"""
tests/test_b166_merge_smoothing.py

B166: Bei einem Merge/Split-Frame schließt _append_kinematic den jüngsten
(diskontinuierlichen) History-Eintrag aus der kinematischen Geschwindigkeit aus,
damit der Schwerpunktsprung die Vorhersage nicht verbiegt. Optischer Fluss bleibt
Vorrang und unbeeinflusst.

Ausführbar: python3 -m pytest tests/test_b166_merge_smoothing.py -v
"""
import os
import sys
import importlib

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _fn():
    try:
        return importlib.import_module("prediction")._append_kinematic
    except (ImportError, AttributeError) as e:
        pytest.skip(f"_append_kinematic nicht verfügbar: {e}")


def _history_with_jump():
    # 3 Frames, gleichmäßige Ostbewegung (vx=2), aber der JÜNGSTE Frame hat einen
    # Sprung (vx=20) — simuliert den Merge-Schwerpunktsprung.
    return [
        {"timestamp": "2026-06-11_14-00-00", "x": 50.0, "y": 50.0, "vx": 2.0, "vy": 0.0, "lat": 46.6, "lon": 14.1},
        {"timestamp": "2026-06-11_14-05-00", "x": 60.0, "y": 50.0, "vx": 2.0, "vy": 0.0, "lat": 46.6, "lon": 14.2},
        {"timestamp": "2026-06-11_14-10-00", "x": 110.0, "y": 50.0, "vx": 20.0, "vy": 0.0, "lat": 46.6, "lon": 14.5},
    ]


def _base_obj(extra):
    obj = {
        "id": "merge_test",
        "x": 110.0, "y": 50.0,
        "lat": 46.6, "lon": 14.5,
        "vx": 20.0, "vy": 0.0,
        "of_available": 0,
        "history": _history_with_jump(),
    }
    obj.update(extra)
    return obj


def test_merge_excludes_jump_frame():
    fn = _fn()
    obj = _base_obj({"is_merged": 1.0})
    forecasts = {10: [], 20: [], 30: [], 40: [], 60: []}
    fn(obj, forecasts)
    # Guard markiert die Quelle
    assert "mguard" in obj.get("kinematic_source", ""), obj.get("kinematic_source")
    # Ohne den Sprung-Frame: vx aus vx=2-Frames → deutlich < halber Sprung (20/5=4 px/min)
    assert obj["kinematic_vx"] <= 2.0, f"vx soll Vor-Merge-Bewegung folgen, war {obj['kinematic_vx']}"


def test_no_merge_keeps_jump_frame():
    fn = _fn()
    obj = _base_obj({})  # kein is_merged/is_split/merge_discontinuity
    forecasts = {10: [], 20: [], 30: [], 40: [], 60: []}
    fn(obj, forecasts)
    assert "mguard" not in obj.get("kinematic_source", "")
    # Sprung-Frame fließt mit ein → größere vx als im geglätteten Fall
    assert obj["kinematic_vx"] >= 2.0


def test_split_also_triggers_guard():
    fn = _fn()
    obj = _base_obj({"is_split": 1.0})
    forecasts = {10: [], 20: [], 30: [], 40: [], 60: []}
    fn(obj, forecasts)
    assert "mguard" in obj.get("kinematic_source", "")


def test_merge_discontinuity_flag_triggers_guard():
    fn = _fn()
    obj = _base_obj({"merge_discontinuity": 1})
    forecasts = {10: [], 20: [], 30: [], 40: [], 60: []}
    fn(obj, forecasts)
    assert "mguard" in obj.get("kinematic_source", "")


def test_short_history_no_guard():
    # Nur 2 Frames → Ausschluss würde n<2 ergeben → kein Guard, Kalman-Clamp greift.
    fn = _fn()
    obj = {
        "id": "short", "x": 60.0, "y": 50.0, "lat": 46.6, "lon": 14.2,
        "vx": 2.0, "vy": 0.0, "of_available": 0, "is_merged": 1.0,
        "history": [
            {"timestamp": "2026-06-11_14-00-00", "x": 50.0, "y": 50.0, "vx": 2.0, "vy": 0.0},
            {"timestamp": "2026-06-11_14-05-00", "x": 60.0, "y": 50.0, "vx": 2.0, "vy": 0.0},
        ],
    }
    forecasts = {10: [], 20: [], 30: [], 40: [], 60: []}
    fn(obj, forecasts)
    assert "mguard" not in obj.get("kinematic_source", "")


def test_optflow_priority_not_marked_mguard():
    # of_available=1 → optischer Fluss gewinnt; Guard markiert die Quelle NICHT.
    fn = _fn()
    obj = _base_obj({"is_merged": 1.0, "of_available": 1, "of_vx": -30.0, "of_vy": 0.0})
    forecasts = {10: [], 20: [], 30: [], 40: [], 60: []}
    fn(obj, forecasts)
    assert obj.get("kinematic_source", "").startswith("optflow")
    assert "mguard" not in obj.get("kinematic_source", "")
    assert obj["kinematic_vx"] < 0.0  # Flow-Richtung West
