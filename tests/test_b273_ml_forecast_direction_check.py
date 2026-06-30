"""B273: validate_forecast_point() lehnt ML-Horizontpunkte ab, die grob
entgegen der zuletzt beobachteten Zugrichtung (direction_deg) liegen.
Kinematische Forecasts (reine Geradenextrapolation) sind nicht betroffen.

Testkoordinaten fuer die Schwellwert-/Grenzfaelle sind exakt ueber die
Grosskreis-Zielpunktformel (gleiche Mathematik wie _bearing_deg) erzeugt,
sodass die Abweichung zur Referenzrichtung (30 Grad) exakt 10/169/90/90,5
Grad betraegt. Der Regressionstest nutzt die realen Koordinaten der Zelle
346I2ILB aus dem Debug-Export vom 2026-06-30 (17:00-Frame, Horizont +20 min),
bei der die Kursabweichung exakt 164,27 Grad betraegt.
"""
import pytest

prediction = pytest.importorskip("prediction")

ORIGIN_LAT, ORIGIN_LON = 46.62, 14.20
REF_DIR = 30.0


def _base_obj(**overrides):
    obj = {
        "id": "test-cell",
        "lat": ORIGIN_LAT,
        "lon": ORIGIN_LON,
        "direction_deg": REF_DIR,
        "speed_kmh": 20.0,
    }
    obj.update(overrides)
    return obj


def test_ml_forecast_consistent_direction_accepted():
    """10 Grad Abweichung von der Zugrichtung liegt klar unter dem 90-Grad-Schwellwert."""
    obj = _base_obj()
    ok, reason, metrics = prediction.validate_forecast_point(
        obj, 20, 46.65443829477275, 14.242109223535977, mode="ml"
    )
    assert ok is True
    assert reason is None
    assert "bearing_deviation_deg" not in metrics


def test_ml_forecast_reversed_direction_rejected():
    """169 Grad Abweichung (fast Kehrtwende) muss abgelehnt werden."""
    obj = _base_obj()
    ok, reason, metrics = prediction.validate_forecast_point(
        obj, 20, 46.577481758698475, 14.178702215091675, mode="ml"
    )
    assert ok is False
    assert reason == "ml_forecast_direction_implausible"
    assert abs(metrics["bearing_deviation_deg"] - 169.0) <= 0.1


def test_ml_forecast_exactly_at_threshold_is_accepted():
    """Exakt 90 Grad Abweichung (Default-Schwellwert) ist noch GUELTIG (dev > max_dev, nicht >=)."""
    obj = _base_obj()
    ok, reason, _ = prediction.validate_forecast_point(
        obj, 20, 46.5975029634459, 14.256673968058635, mode="ml"
    )
    assert ok is True
    assert reason is None


def test_ml_forecast_just_over_threshold_is_rejected():
    """90,5 Grad Abweichung liegt knapp ueber dem Default-Schwellwert -> Reject."""
    obj = _base_obj()
    ok, reason, metrics = prediction.validate_forecast_point(
        obj, 20, 46.597164134664666, 14.256385918796468, mode="ml"
    )
    assert ok is False
    assert reason == "ml_forecast_direction_implausible"
    assert abs(metrics["bearing_deviation_deg"] - 90.5) <= 0.1


def test_stationary_cell_skips_direction_check():
    """direction_deg=None (stationaer/keine verlaessliche Richtung) -> Pruefung uebersprungen."""
    obj = _base_obj(direction_deg=None, speed_kmh=0.0)
    ok, reason, _ = prediction.validate_forecast_point(
        obj, 20, 46.577481758698475, 14.178702215091675, mode="ml"
    )
    assert ok is True
    assert reason is None


def test_slow_cell_below_arrow_threshold_skips_direction_check():
    """speed_kmh unter MIN_MOVEMENT_FOR_ARROW_KMH -> Richtung gilt als zu unsicher, Pruefung uebersprungen."""
    obj = _base_obj(speed_kmh=2.0)
    ok, reason, _ = prediction.validate_forecast_point(
        obj, 20, 46.577481758698475, 14.178702215091675, mode="ml"
    )
    assert ok is True
    assert reason is None


def test_kinematic_mode_not_affected_by_direction_check():
    """B273 betrifft ausschliesslich mode='ml'; kinematische Punkte werden nicht geprueft."""
    obj = _base_obj()
    ok, reason, _ = prediction.validate_forecast_point(
        obj, 20, 46.577481758698475, 14.178702215091675, mode="kinematic"
    )
    assert ok is True
    assert reason is None


def test_real_world_zigzag_case_346i2ilb_h20_rejected():
    """Regression: reale Zelle 346I2ILB aus dem Debug-Export 2026-06-30 17:00,
    deren ML-Punkt bei +20 min um 164,27 Grad von direction_deg abweicht und
    vor B273 unentdeckt ausgeliefert wurde."""
    obj = _base_obj(
        id="346I2ILB",
        lat=46.53330251210977,
        lon=14.11617909944946,
        direction_deg=26.6,
        speed_kmh=15.0,
    )
    ok, reason, metrics = prediction.validate_forecast_point(
        obj, 20, 46.52886149053565, 14.11029932634905, mode="ml"
    )
    assert ok is False
    assert reason == "ml_forecast_direction_implausible"
    assert abs(metrics["bearing_deviation_deg"] - 164.3) <= 0.1


def test_config_default_bearing_threshold_is_90():
    import config
    assert config.ML_FORECAST_MAX_BEARING_DEVIATION_DEG == 90.0
