"""B219: Der kinematische Forecast wird IMMER auf FORECAST_MAX_SPEED_KMH
geklemmt — auch im reinen optischen-Fluss-Pfad ohne Steering-Blend."""
import pytest


def _cap_kmh(prediction):
    return prediction._runtime_float_value(
        "FORECAST_MAX_SPEED_KMH",
        prediction._runtime_float_value("MAX_CELL_SPEED_KMH", prediction._STATIC_MAX_CELL_SPEED_KMH),
    )


def test_optical_flow_forecast_is_capped(monkeypatch):
    prediction = pytest.importorskip("prediction")
    monkeypatch.setattr(prediction, "_get_horizons", lambda: [10])

    # x=0,y=0 → analytischer Projektionspfad (kein pixel_to_geo/config nötig).
    # of_vx riesig → unkapped ~ >1000 km/h; kein Wind → kein Steering-Blend.
    obj = {
        "id": "cap-1",
        "x": 0.0, "y": 0.0,
        "lat": 46.60, "lon": 14.00,
        "of_available": 1, "of_vx": 300.0, "of_vy": 0.0,
        "history": [],
    }
    prediction._append_kinematic(obj, {10: []})

    cap = _cap_kmh(prediction)
    speed = float(obj["forecast_speed_kmh_10"])
    assert speed <= cap + 1.0, f"Forecast-Speed {speed} > Cap {cap} — Cap nicht durchgesetzt."
    assert int(obj.get("forecast_speed_capped", 0)) == 1


def test_slow_forecast_not_altered(monkeypatch):
    prediction = pytest.importorskip("prediction")
    monkeypatch.setattr(prediction, "_get_horizons", lambda: [10])

    # langsame Zelle (~30 km/h bei UF=3) → unter Cap, NICHT geklemmt
    obj = {
        "id": "slow-1",
        "x": 0.0, "y": 0.0,
        "lat": 46.60, "lon": 14.00,
        "of_available": 1, "of_vx": 7.5, "of_vy": 0.0,
        "history": [],
    }
    prediction._append_kinematic(obj, {10: []})

    cap = _cap_kmh(prediction)
    speed = float(obj["forecast_speed_kmh_10"])
    assert speed < cap
    assert int(obj.get("forecast_speed_capped", 0)) == 0
