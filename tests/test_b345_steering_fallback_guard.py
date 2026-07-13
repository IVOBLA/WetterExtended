"""B345: Open-Meteo-Fallback-Wind (500hPa) wird nicht mehr als gueltiger
Steuerstrom-Kandidat verwendet."""
import math

import pytest

from prediction import _steering_motion_vector_from_obj


def test_500hpa_fallback_marker_skips_candidate_falls_back_to_700hpa():
    """wind_500_speed=20.0 (Fallback-Default) mit gesetztem Marker ->
    Kandidat wird uebersprungen, 700hpa-Kandidat greift."""
    obj = {
        "wind_500_speed": 20.0,
        "wind_500_dir_cos": 0.0,
        "wind_500_dir_sin": 1.0,
        "wind_500_speed_fallback": 1,
        "wind_700hpa": 50.0,
        "wind_dir_cos": math.cos(math.radians(270.0)),
        "wind_dir_sin": math.sin(math.radians(270.0)),
    }
    steering = _steering_motion_vector_from_obj(obj)
    assert steering is not None
    assert steering["level"] == "700hpa"


def test_500hpa_fallback_marker_with_no_other_candidate_returns_none():
    obj = {
        "wind_500_speed": 20.0,
        "wind_500_dir_cos": 0.0,
        "wind_500_dir_sin": 1.0,
        "wind_500_speed_fallback": 1,
    }
    assert _steering_motion_vector_from_obj(obj) is None


def test_500hpa_real_value_without_marker_still_used():
    """Regressionsschutz: echte Messwerte (kein Marker) funktionieren wie zuvor."""
    obj = {
        "wind_500_speed": 25.0,
        "wind_500_dir_cos": math.cos(math.radians(270.0)),
        "wind_500_dir_sin": math.sin(math.radians(270.0)),
    }
    steering = _steering_motion_vector_from_obj(obj)
    assert steering is not None
    assert steering["level"] == "500hpa"
    assert steering["speed_kmh"] == pytest.approx(25.0)


def test_500hpa_marker_false_or_absent_is_not_skipped():
    obj = {
        "wind_500_speed": 30.0,
        "wind_500_dir_cos": math.cos(math.radians(180.0)),
        "wind_500_dir_sin": math.sin(math.radians(180.0)),
        "wind_500_speed_fallback": 0,
    }
    steering = _steering_motion_vector_from_obj(obj)
    assert steering is not None
    assert steering["level"] == "500hpa"


def test_wind_from_west_moves_to_east_unchanged():
    """Bestehendes Verhalten (700hpa, kein Marker-Feld involviert) unveraendert."""
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
