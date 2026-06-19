import math

import pytest

import prediction
from config import MAX_CELL_SPEED_KMH, UPSCALE_FACTOR
from prediction import (
    _append_kinematic,
    _motion_dir_deg_from_vxy,
    _steering_motion_vector_from_obj,
)


def _forecasts():
    return {h: [] for h in [10, 20, 30, 40, 60]}


def _young_obj():
    return {
        "id": "s",
        "x": 100.0,
        "y": 100.0,
        "lat": 46.0,
        "lon": 14.0,
        "vx": 0.0,
        "vy": 0.0,
        "of_available": 0,
        "active_frames": 2,
        "history": [
            {"timestamp": "2026-01-01_00-00-00", "x": 100.0, "y": 100.0},
            {"timestamp": "2026-01-01_00-05-00", "x": 100.0, "y": 90.0},
        ],
    }


def _runtime(overrides):
    def get(name, default=None):
        return overrides.get(name, default)
    return get


def test_wind_from_west_moves_to_east():
    obj = {
        "wind_700hpa": 50.0,
        "wind_dir_cos": math.cos(math.radians(270.0)),
        "wind_dir_sin": math.sin(math.radians(270.0)),
    }
    steering = _steering_motion_vector_from_obj(obj)
    assert steering["level"] == "700hpa"
    assert steering["direction_to_deg"] == pytest.approx(90.0)
    assert steering["vx"] > 0.0
    assert abs(steering["vy"]) < 1e-9


def test_young_cell_with_large_angle_diff_blends_to_500hpa(monkeypatch):
    monkeypatch.setattr(prediction._runtime_cfg, "get", _runtime({
        "STEERING_BLEND_ENABLED": True,
        "STEERING_BLEND_MAX_ACTIVE_FRAMES": 3,
        "STEERING_BLEND_MIN_ANGLE_DEG": 60,
        "STEERING_BLEND_WEIGHT": 0.35,
        "STEERING_BLEND_MIN_WIND_KMH": 10,
    }))
    obj = _young_obj()
    obj.update({
        "wind_500_speed": 50.0,
        "wind_500_dir_cos": math.cos(math.radians(270.0)),
        "wind_500_dir_sin": math.sin(math.radians(270.0)),
        "wind_700hpa": 50.0,
        "wind_dir_cos": math.cos(math.radians(180.0)),
        "wind_dir_sin": math.sin(math.radians(180.0)),
    })
    _append_kinematic(obj, _forecasts())
    assert obj["steering_available"] == 1
    assert obj["steering_level_used"] == "500hpa"
    assert obj["steering_angle_diff_deg"] == pytest.approx(90.0)
    assert obj["steering_blend_applied"] == 1
    assert obj["kinematic_source"].endswith("+steering")
    assert _motion_dir_deg_from_vxy(obj["kinematic_vx"], obj["kinematic_vy"]) > 0.0


def test_old_stable_optflow_does_not_blend(monkeypatch):
    monkeypatch.setattr(prediction._runtime_cfg, "get", _runtime({
        "STEERING_BLEND_ENABLED": True,
        "STEERING_BLEND_MAX_ACTIVE_FRAMES": 3,
        "STEERING_BLEND_MIN_ANGLE_DEG": 60,
        "STEERING_BLEND_WEIGHT": 0.35,
        "STEERING_BLEND_MIN_WIND_KMH": 10,
    }))
    obj = _young_obj()
    obj.update({
        "active_frames": 10,
        "of_available": 1,
        "of_vx": 0.0,
        "of_vy": -10.0,
        "wind_700hpa": 50.0,
        "wind_dir_cos": math.cos(math.radians(270.0)),
        "wind_dir_sin": math.sin(math.radians(270.0)),
    })
    _append_kinematic(obj, _forecasts())
    assert obj["steering_available"] == 1
    assert obj["steering_blend_applied"] == 0
    assert "+steering" not in obj["kinematic_source"]


def test_no_wind_fields_keeps_existing_kinematic_vector(monkeypatch):
    monkeypatch.setattr(prediction._runtime_cfg, "get", _runtime({
        "STEERING_BLEND_ENABLED": True,
        "STEERING_BLEND_MAX_ACTIVE_FRAMES": 3,
        "STEERING_BLEND_MIN_ANGLE_DEG": 60,
        "STEERING_BLEND_WEIGHT": 0.35,
        "STEERING_BLEND_MIN_WIND_KMH": 10,
    }))
    base = _young_obj()
    _append_kinematic(base, _forecasts())
    assert base["steering_available"] == 0
    assert base["steering_blend_applied"] == 0
    assert base["kinematic_vx"] == pytest.approx(0.0)
    assert base["kinematic_vy"] == pytest.approx(-2.0)
    assert base["kinematic_source"] == "ewma_2f_a0.6"


def test_speed_clamped_to_max_cell_speed(monkeypatch):
    monkeypatch.setattr(prediction._runtime_cfg, "get", _runtime({
        "STEERING_BLEND_ENABLED": True,
        "STEERING_BLEND_MAX_ACTIVE_FRAMES": 3,
        "STEERING_BLEND_MIN_ANGLE_DEG": 60,
        "STEERING_BLEND_WEIGHT": 0.35,
        "STEERING_BLEND_MIN_WIND_KMH": 10,
        "MAX_CELL_SPEED_KMH": MAX_CELL_SPEED_KMH,
    }))
    obj = _young_obj()
    obj["history"] = [
        {"timestamp": "2026-01-01_00-00-00", "x": 0.0, "y": 0.0},
        {"timestamp": "2026-01-01_00-05-00", "x": 500.0, "y": 0.0},
    ]
    obj.update({
        "wind_700hpa": 50.0,
        "wind_dir_cos": math.cos(math.radians(0.0)),
        "wind_dir_sin": math.sin(math.radians(0.0)),
    })
    _append_kinematic(obj, _forecasts())
    assert obj["steering_blend_applied"] == 1
    max_px_min = MAX_CELL_SPEED_KMH * UPSCALE_FACTOR / 60.0
    assert math.hypot(obj["kinematic_vx"], obj["kinematic_vy"]) <= max_px_min + 1e-9
    assert obj["kinematic_speed_kmh"] <= MAX_CELL_SPEED_KMH + 1e-9
