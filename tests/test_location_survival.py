"""P-T06: Forecast-/Slow-Treffer werden unterdrückt, wenn die Zelle sich
voraussichtlich vor dem Ort auflöst. current-Hits bleiben unberührt."""
import pytest



def _import_lc():
    try:
        import importlib
        return importlib.import_module("locations_check")
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"locations_check nicht importierbar: {exc}")


def test_survival_fraction_stable_cell_is_one():
    lc = _import_lc()
    obj = {"intensity_tendency": "stabil", "size_tendency": "stabil"}
    assert lc._cell_survival_fraction(obj, 60.0) == 1.0


def test_survival_fraction_growing_cell_is_one():
    lc = _import_lc()
    obj = {"intensity_tendency": "staerker", "size_tendency": "waechst"}
    assert lc._cell_survival_fraction(obj, 60.0) == 1.0


def test_survival_fraction_decays_with_horizon():
    lc = _import_lc()
    obj = {"intensity_tendency": "schwaecher", "size_tendency": "schrumpft"}
    near = lc._cell_survival_fraction(obj, 10.0)
    far = lc._cell_survival_fraction(obj, 60.0)
    assert 0.0 < far < near <= 1.0


def test_decaying_cell_far_horizon_suppressed():
    """Stark abklingende Zelle: weit entfernter Horizont wird unterdrückt."""
    lc = _import_lc()
    obj = {
        "id": "decay-1", "lat": 46.60, "lon": 14.20,
        "forecast_mode": "kinematic",
        "vx": 3.0, "vy": 0.0, "speed_kmh": 30.0,
        "intensity_tendency": "schwaecher", "size_tendency": "schrumpft",
        "delta_core_ratio_pred": -0.5,
        # Forecast-Position bei h=60 direkt am Ort:
        "forecast_lat_60": 46.62, "forecast_lon_60": 14.30,
    }
    loc = [{"name": "Klagenfurt", "lat": 46.62, "lon": 14.30, "radius_km": 5.0}]
    out = lc.annotate_locations([obj], loc, [60], {60: "#f00"},
                                min_speed_kmh=5.0, slow_cell_max_kmh=15.0)
    # Treffer bei h=60 muss unterdrückt sein → kein Ort in der Ausgabe
    assert all(60 not in o.get("hits", {}) for o in out)


def test_growing_cell_hit_kept_with_metadata():
    """Wachsende Zelle: Treffer bleibt und trägt survival_frac/Tendenzen."""
    lc = _import_lc()
    obj = {
        "id": "grow-1", "lat": 46.60, "lon": 14.20,
        "forecast_mode": "kinematic",
        "vx": 3.0, "vy": 0.0, "speed_kmh": 30.0,
        "intensity_tendency": "staerker", "size_tendency": "waechst",
        "forecast_lat_60": 46.62, "forecast_lon_60": 14.30,
    }
    loc = [{"name": "Klagenfurt", "lat": 46.62, "lon": 14.30, "radius_km": 5.0}]
    out = lc.annotate_locations([obj], loc, [60], {60: "#f00"},
                                min_speed_kmh=5.0, slow_cell_max_kmh=15.0)
    assert len(out) == 1
    hit = out[0]["hits"].get(60)
    assert hit is not None
    assert hit["survival_frac"] == 1.0
    assert hit["size_tendency"] == "waechst"


def test_current_hit_is_kept_even_when_cell_would_decay():
    """Akuter Treffer bleibt erhalten, auch wenn spätere Forecasts zerfallen."""
    lc = _import_lc()
    obj = {
        "id": "current-decay-1", "lat": 46.62, "lon": 14.30,
        "forecast_mode": "kinematic",
        "vx": 3.0, "vy": 0.0, "speed_kmh": 30.0,
        "intensity_tendency": "schwaecher", "size_tendency": "schrumpft",
        "delta_core_ratio_pred": -0.5,
        "forecast_lat_60": 46.62, "forecast_lon_60": 14.30,
    }
    loc = [{"name": "Klagenfurt", "lat": 46.62, "lon": 14.30, "radius_km": 5.0}]
    out = lc.annotate_locations([obj], loc, [60], {60: "#f00"},
                                min_speed_kmh=5.0, slow_cell_max_kmh=15.0)
    assert len(out) == 1
    assert out[0]["hits"][0]["hit_type"] == "current"
    assert 60 not in out[0]["hits"]
