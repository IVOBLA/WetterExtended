"""
tests/test_forecast_uses_optflow.py

P-M02: Liegt ein gültiger optischer Fluss vor (of_available=1), nutzt der
kinematische Forecast of_vx/of_vy (in px/min) statt der centroid-basierten
EWMA-Geschwindigkeit. Ohne Flow bleibt EWMA/Kalman aktiv.

Ausführbar: python3 -m pytest tests/test_forecast_uses_optflow.py -v
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


def _eastward_history():
    # 2 Frames, 5 min Abstand, +10 px in x → EWMA ergäbe Ostbewegung (avg_vx > 0)
    return [
        {"timestamp": "2026-06-11_14-00-00", "x": 50.0, "y": 50.0,
         "vx": 2.0, "vy": 0.0, "lat": 46.6, "lon": 14.2},
        {"timestamp": "2026-06-11_14-05-00", "x": 60.0, "y": 50.0,
         "vx": 2.0, "vy": 0.0, "lat": 46.6, "lon": 14.3},
    ]


def test_optflow_overrides_ewma_when_available():
    """of_vx = -30 px/Frame (West), of_vy = +15; frame_min = 5 →
    kinematic_vx = -6.0, kinematic_vy = +3.0, source = optflow_*."""
    fn = _fn()
    obj = {
        "id": "of_used",
        "x": 60.0, "y": 50.0,
        "lat": 46.6, "lon": 14.3,
        "vx": 2.0, "vy": 0.0,
        "of_vx": -30.0, "of_vy": 15.0, "of_available": 1,
        "history": _eastward_history(),
    }
    forecasts = {10: [], 20: [], 30: [], 40: [], 60: []}
    fn(obj, forecasts)

    assert obj.get("kinematic_source", "").startswith("optflow"), (
        f"Quelle muss optflow sein, war: {obj.get('kinematic_source')}"
    )
    assert abs(obj["kinematic_vx"] - (-6.0)) < 1e-6, obj["kinematic_vx"]
    assert abs(obj["kinematic_vy"] - (3.0)) < 1e-6, obj["kinematic_vy"]
    # Richtung muss nach Westen zeigen (entgegen der EWMA-Ostbewegung)
    assert obj["kinematic_vx"] < 0.0


def test_ewma_used_when_flow_unavailable():
    """of_available=0 → EWMA/Kalman bleibt aktiv, Ostbewegung (vx > 0)."""
    fn = _fn()
    obj = {
        "id": "of_missing",
        "x": 60.0, "y": 50.0,
        "lat": 46.6, "lon": 14.3,
        "vx": 2.0, "vy": 0.0,
        "of_vx": -30.0, "of_vy": 15.0, "of_available": 0,
        "history": _eastward_history(),
    }
    forecasts = {10: [], 20: [], 30: [], 40: [], 60: []}
    fn(obj, forecasts)

    assert not obj.get("kinematic_source", "").startswith("optflow"), (
        "Ohne gültigen Flow darf optflow NICHT als Quelle dienen"
    )
    assert obj["kinematic_vx"] > 0.0, "EWMA-Ostbewegung erwartet"
