"""B220: forecast_speed_factor dämpft den kinematischen Forecast tatsächlich."""
import pytest


def _run(prediction, factor):
    obj = {
        "id": f"damp-{factor}",
        "x": 0.0, "y": 0.0,
        "lat": 46.60, "lon": 14.00,
        "of_available": 1, "of_vx": 7.5, "of_vy": 0.0,  # ~30 km/h (unter Cap)
        "history": [],
        "forecast_speed_factor": factor,
    }
    prediction._append_kinematic(obj, {10: []})
    return obj


def test_factor_halves_forecast_speed(monkeypatch):
    prediction = pytest.importorskip("prediction")
    monkeypatch.setattr(prediction, "_get_horizons", lambda: [10])

    full = _run(prediction, 1.0)["forecast_speed_kmh_10"]
    damped = _run(prediction, 0.5)["forecast_speed_kmh_10"]

    assert full > 0.0
    assert damped < full
    assert abs(damped - 0.5 * full) < 0.5  # ~ Halbierung


def test_neutral_factor_does_not_damp(monkeypatch):
    prediction = pytest.importorskip("prediction")
    monkeypatch.setattr(prediction, "_get_horizons", lambda: [10])

    obj = _run(prediction, 1.0)
    assert int(obj.get("forecast_speed_damped", 0)) == 0


def test_damped_flag_set_when_factor_below_one(monkeypatch):
    prediction = pytest.importorskip("prediction")
    monkeypatch.setattr(prediction, "_get_horizons", lambda: [10])

    obj = _run(prediction, 0.4)
    assert int(obj.get("forecast_speed_damped", 0)) == 1
