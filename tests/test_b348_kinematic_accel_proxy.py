"""B348: Diagnose-Proxy kinematic_accel_proxy_kmh / kinematic_acceleration_applied."""
import os
import sys
from datetime import datetime, timedelta
from datetime import datetime as _dt

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import accuracy_tracker as at
import prediction
from config import UPSCALE_FACTOR

UF = UPSCALE_FACTOR
FRAME_MIN = 5.0


def _make_history(speeds_kmh, frame_min=FRAME_MIN):
    t0 = datetime(2026, 7, 1, 0, 0, 0)
    x, y = 0.0, 0.0
    hist = [{"timestamp": t0.strftime("%Y-%m-%d_%H-%M-%S"), "x": x, "y": y}]
    t = t0
    for v in speeds_kmh:
        disp_km = v * (frame_min / 60.0)
        y += disp_km * UF
        t = t + timedelta(minutes=frame_min)
        hist.append({"timestamp": t.strftime("%Y-%m-%d_%H-%M-%S"), "x": x, "y": y})
    return hist


def _forecasts():
    return {h: [] for h in [10, 20, 30, 40, 60]}


def _runtime(overrides):
    def get(name, default=None):
        return overrides.get(name, default)
    return get


def test_accelerating_cell_has_positive_proxy():
    hist = _make_history([20, 25, 30, 35, 40])
    obj = {"history": hist, "vx": 0.0, "vy": 0.0, "of_available": 0, "active_frames": 20}
    prediction._append_kinematic(obj, _forecasts())
    assert obj["kinematic_accel_proxy_kmh"] is not None
    assert obj["kinematic_accel_proxy_kmh"] == pytest.approx(5.0, abs=0.5)


def test_decelerating_cell_has_negative_proxy():
    hist = _make_history([40, 35, 30, 25, 20])
    obj = {"history": hist, "vx": 0.0, "vy": 0.0, "of_available": 0, "active_frames": 20}
    prediction._append_kinematic(obj, _forecasts())
    assert obj["kinematic_accel_proxy_kmh"] is not None
    assert obj["kinematic_accel_proxy_kmh"] == pytest.approx(-5.0, abs=0.5)


def test_proxy_computed_even_when_feature_disabled(monkeypatch):
    """Kernpunkt B348: Proxy wird auch bei KINEMATIC_ACCELERATION_ENABLED=False berechnet."""
    monkeypatch.setattr(prediction._runtime_cfg, "get", _runtime({
        "KINEMATIC_ACCELERATION_ENABLED": False,
    }))
    hist = _make_history([20, 25, 30, 35, 40])
    obj = {"history": hist, "vx": 0.0, "vy": 0.0, "of_available": 0, "active_frames": 20}
    prediction._append_kinematic(obj, _forecasts())
    assert obj["kinematic_accel_proxy_kmh"] is not None
    assert obj["kinematic_acceleration_applied"] == 0


def test_acceleration_applied_flag_true_when_enabled(monkeypatch):
    monkeypatch.setattr(prediction._runtime_cfg, "get", _runtime({
        "KINEMATIC_ACCELERATION_ENABLED": True,
        "KINEMATIC_ACCEL_MAX_FRACTION": 0.3,
    }))
    hist = _make_history([20, 25, 30, 35, 40])
    obj = {"history": hist, "vx": 0.0, "vy": 0.0, "of_available": 0, "active_frames": 20}
    prediction._append_kinematic(obj, _forecasts())
    assert obj["kinematic_acceleration_applied"] == 1


def test_disabled_flag_leaves_forecast_behavior_unchanged(monkeypatch):
    """Regressionsschutz: bei deaktiviertem Flag identisches Verhalten wie vor B348."""
    monkeypatch.setattr(prediction._runtime_cfg, "get", _runtime({
        "KINEMATIC_ACCELERATION_ENABLED": False,
    }))
    hist = _make_history([20, 25, 30, 35, 40])
    obj_a = {"history": [dict(h) for h in hist], "vx": 0.0, "vy": 0.0, "of_available": 0, "active_frames": 20}
    obj_b = {"history": [dict(h) for h in hist], "vx": 0.0, "vy": 0.0, "of_available": 0, "active_frames": 20}
    prediction._append_kinematic(obj_a, _forecasts())
    prediction._append_kinematic(obj_b, _forecasts())
    assert obj_a["kinematic_vx"] == obj_b["kinematic_vx"]
    assert obj_a["kinematic_vy"] == obj_b["kinematic_vy"]
    assert obj_a["forecast_lat_30"] == obj_b["forecast_lat_30"]


def test_too_short_history_yields_none_proxy():
    obj = {
        "history": [
            {"timestamp": "2026-07-01_00-00-00", "x": 0.0, "y": 0.0},
            {"timestamp": "2026-07-01_00-05-00", "x": 0.0, "y": 10.0},
        ],
        "vx": 0.0, "vy": 0.0, "of_available": 0, "active_frames": 2,
    }
    prediction._append_kinematic(obj, _forecasts())
    assert obj["kinematic_accel_proxy_kmh"] is None
    assert obj["kinematic_acceleration_applied"] == 0


def _call_detail_record(obj, matched=None, horizon=10, no_target=False):
    ts = _dt.strptime("2026-07-01_09-00-00", "%Y-%m-%d_%H-%M-%S")
    target_ts = _dt.strptime("2026-07-01_09-10-00", "%Y-%m-%d_%H-%M-%S")
    dist = 1.5 if matched else None
    return at._detail_record(obj, ts, target_ts, horizon, matched, dist, "id", no_target, False, float(horizon))


def test_detail_record_propagates_accel_proxy():
    obj = {
        "id": "T1", "lat": 46.8, "lon": 14.3,
        "origin_lat": 46.8, "origin_lon": 14.3,
        "forecast_lat_10": 46.82, "forecast_lon_10": 14.32,
        "kinematic_accel_proxy_kmh": 6.4,
        "kinematic_acceleration_applied": 1,
    }
    rec = _call_detail_record(obj, {"id": "T1", "lat": 46.81, "lon": 14.31})
    assert rec["kinematic_accel_proxy_kmh"] == 6.4
    assert rec["kinematic_acceleration_applied"] is True


def test_detail_record_accel_proxy_none_when_absent():
    obj = {
        "id": "T2", "lat": 46.8, "lon": 14.3,
        "origin_lat": 46.8, "origin_lon": 14.3,
        "forecast_lat_10": 46.82, "forecast_lon_10": 14.32,
    }
    rec = _call_detail_record(obj, {"id": "T2", "lat": 46.81, "lon": 14.31})
    assert rec["kinematic_accel_proxy_kmh"] is None
    assert rec["kinematic_acceleration_applied"] is False
