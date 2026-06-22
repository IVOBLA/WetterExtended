# tests/test_p52_ml_shadow_scoring.py
"""P52 — _compute_ml_shadow berechnet Challenger-Felder ohne Auslieferung.
Champion-Pfad nicht betroffen; NaN -> None; Reject wird markiert."""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import prediction as p


def _stub_geo(monkeypatch):
    monkeypatch.setattr(p, "pixel_to_geo", lambda x, y: (46.5 + y / 1000.0, 13.5 + x / 1000.0))


def test_valid_ml_raw_produces_shadow_fields(monkeypatch):
    _stub_geo(monkeypatch)
    monkeypatch.setattr(
        p, "validate_forecast_point",
        lambda obj, h, lat, lon, mode="ml": (True, None, {"forecast_displacement_km": 4.2, "forecast_speed_kmh": 25.0}),
    )
    sh = p._compute_ml_shadow({}, 10, 100.0, 50.0)
    assert sh is not None
    assert sh["forecast_ml_x_10"] == 100.0 * p._UF
    assert sh["forecast_ml_y_10"] == 50.0 * p._UF
    assert sh["forecast_ml_lat_10"] is not None and sh["forecast_ml_lon_10"] is not None
    assert sh["forecast_ml_displacement_km_10"] == 4.2
    assert sh["forecast_ml_speed_kmh_10"] == 25.0
    assert sh["forecast_ml_rejected_10"] is False
    assert sh["forecast_ml_reject_reason_10"] is None


def test_nan_returns_none(monkeypatch):
    _stub_geo(monkeypatch)
    monkeypatch.setattr(p, "validate_forecast_point", lambda *a, **k: (True, None, {}))
    assert p._compute_ml_shadow({}, 10, float("nan"), 50.0) is None
    assert p._compute_ml_shadow({}, 10, 50.0, float("nan")) is None


def test_rejected_point_is_flagged(monkeypatch):
    _stub_geo(monkeypatch)
    monkeypatch.setattr(
        p, "validate_forecast_point",
        lambda obj, h, lat, lon, mode="ml": (False, "out_of_bounds", {}),
    )
    sh = p._compute_ml_shadow({}, 30, 5.0, 5.0)
    assert sh["forecast_ml_rejected_30"] is True
    assert sh["forecast_ml_reject_reason_30"] == "out_of_bounds"


def test_default_switch_is_enabled():
    from config import ML_SHADOW_SCORING_ENABLED
    assert ML_SHADOW_SCORING_ENABLED is True


def test_shadow_writes_only_ml_prefixed_fields(monkeypatch):
    _stub_geo(monkeypatch)
    monkeypatch.setattr(
        p, "validate_forecast_point",
        lambda obj, h, lat, lon, mode="ml": (True, None, {"forecast_displacement_km": 1.0, "forecast_speed_kmh": 2.0}),
    )
    sh = p._compute_ml_shadow({}, 10, 1.0, 1.0)
    # Es duerfen ausschliesslich forecast_ml_*-Schluessel zurueckkommen (kein Champion-Feld).
    assert all(k.startswith("forecast_ml_") for k in sh)
