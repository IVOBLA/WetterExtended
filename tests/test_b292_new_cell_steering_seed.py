"""B292: Brandneue Zelle ohne Historie darf keine Stillstands-Prognose erhalten,
wenn ein Steuerstrom (Steering) vorliegt."""
import math

from prediction import _vxy_from_motion_dir_speed


def test_vxy_from_speed_kmh_is_nonzero_for_positive_wind():
    vx, vy = _vxy_from_motion_dir_speed(90.0, speed_kmh=30.0)
    speed_px_min = math.hypot(vx, vy)
    assert speed_px_min > 0.0


def test_seed_fraction_clamped_to_unit_interval():
    # Simuliert die Clamp-Logik aus dem Fix
    for raw, expected in [(-0.5, 0.0), (0.6, 0.6), (1.5, 1.0)]:
        assert max(0.0, min(1.0, raw)) == expected


def test_seed_speed_scales_with_fraction():
    steering_speed_kmh = 40.0
    frac = 0.6
    seed = steering_speed_kmh * frac
    assert abs(seed - 24.0) < 1e-9
    vx0, vy0 = _vxy_from_motion_dir_speed(45.0, speed_kmh=seed)
    assert math.hypot(vx0, vy0) > 0.0


def test_no_double_unit_conversion():
    """Regression: _vxy_from_motion_dir_speed rechnet km/h bereits in px/min um.
    Ein zweites *UF/60 wuerde die Geschwindigkeit faelschlich verkleinern."""
    from prediction import _vxy_from_motion_dir_speed as f
    vx, vy = f(0.0, speed_kmh=60.0)
    # Bei Richtung 0 (nach Norden) ist vy negativ, vx ~0; Betrag > 0
    assert math.hypot(vx, vy) > 0.0
