"""
B307: 2nd-Order-Beschleunigungsterm in der kinematischen Extrapolation.
Default AUS; bei Aktivierung wird die Beschleunigung aus den beiden juengsten
Geschwindigkeitsintervallen der History geschaetzt und additiv angewendet,
gekappt auf KINEMATIC_ACCEL_MAX_FRACTION der linearen Verschiebung.
"""
import pytest

pred = pytest.importorskip("prediction")


def _hist(points):
    """points: Liste von (timestamp_str, x, y)."""
    return [{"timestamp": t, "x": x, "y": y} for t, x, y in points]


def test_returns_none_with_fewer_than_three_points():
    h = _hist([("2026-07-05_12-00-00", 0.0, 0.0), ("2026-07-05_12-05-00", 5.0, 0.0)])
    assert pred._compute_acceleration_px_per_min2(h) is None


def test_constant_velocity_yields_zero_acceleration():
    # Gleichmaessige Bewegung: 2 px/min konstant -> Beschleunigung ~0.
    h = _hist([
        ("2026-07-05_12-00-00", 0.0, 0.0),
        ("2026-07-05_12-05-00", 10.0, 0.0),
        ("2026-07-05_12-10-00", 20.0, 0.0),
    ])
    ax, ay = pred._compute_acceleration_px_per_min2(h)
    assert abs(ax) < 1e-9
    assert abs(ay) < 1e-9


def test_accelerating_cell_yields_positive_acceleration():
    # Intervall 1: 5 px/min, Intervall 2: 10 px/min -> Beschleunigung positiv.
    h = _hist([
        ("2026-07-05_12-00-00", 0.0, 0.0),
        ("2026-07-05_12-05-00", 25.0, 0.0),   # 5 px/min
        ("2026-07-05_12-10-00", 75.0, 0.0),   # 10 px/min
    ])
    ax, ay = pred._compute_acceleration_px_per_min2(h)
    assert ax > 0
    assert abs(ay) < 1e-9


def test_duplicate_timestamps_return_none_not_crash():
    h = _hist([
        ("2026-07-05_12-00-00", 0.0, 0.0),
        ("2026-07-05_12-00-00", 5.0, 0.0),
        ("2026-07-05_12-05-00", 10.0, 0.0),
    ])
    # Darf nicht crashen; Ergebnis None oder ein endlicher Wert, niemals Exception.
    result = pred._compute_acceleration_px_per_min2(h)
    assert result is None or (isinstance(result, tuple) and len(result) == 2)


def test_bounded_displacement_is_zero_without_accel():
    dx, dy = pred._bounded_acceleration_displacement(2.0, 0.0, None, 20.0)
    assert dx == 0.0 and dy == 0.0


def test_bounded_displacement_is_capped_at_max_fraction(monkeypatch):
    # Lineare Verschiebung: vx=1 px/min * 20 min = 20 px.
    # Extreme Beschleunigung soll auf 30% von 20px = 6px gekappt werden.
    monkeypatch.setattr(pred, "_runtime_cfg", None)  # erzwingt Static-Default-Pfad
    dx, dy = pred._bounded_acceleration_displacement(1.0, 0.0, (100.0, 0.0), 20.0)
    lin_disp = 1.0 * 20.0
    accel_disp = (dx ** 2 + dy ** 2) ** 0.5
    assert accel_disp <= lin_disp * pred._STATIC_ACCEL_MAX_FRACTION + 1e-6


def test_small_acceleration_is_not_scaled_down():
    # Kleine, plausible Beschleunigung bleibt unveraendert (kein unnoetiges Kappen).
    dx, dy = pred._bounded_acceleration_displacement(5.0, 0.0, (0.01, 0.0), 10.0)
    expected_dx = 0.5 * 0.01 * 10.0 * 10.0
    assert abs(dx - expected_dx) < 1e-9


def test_acceleration_disabled_by_default_constant():
    assert pred._STATIC_ACCEL_ENABLED is False
