"""
tests/test_location_growth.py

P-M05: Eine stationäre, WACHSENDE Zelle erreicht einen Ort durch reine
Flächenausdehnung → growth_approach-Treffer (Vorwarnung). Eine stationäre,
NICHT wachsende Zelle an derselben Position erzeugt keinen Treffer.

Ausführbar: python3 -m pytest tests/test_location_growth.py -v
"""
import pytest


def _import_lc():
    try:
        import importlib
        return importlib.import_module("locations_check")
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"locations_check nicht importierbar: {exc}")


# Quadrat-Kontur ~±0.02° um (14.30, 46.62) — GeoJSON [[lon,lat],...]
_CONTOUR = [
    [14.28, 46.60], [14.32, 46.60],
    [14.32, 46.64], [14.28, 46.64], [14.28, 46.60],
]
# Ort östlich, knapp außerhalb der statischen Kontur (Ostrand 14.32 → 14.38 ≈ 4,6 km).
_LOC = [{"name": "Ostort", "lat": 46.62, "lon": 14.38, "radius_km": 3.0}]
_HORIZONS = [10, 20, 30, 40, 60]
_COLORS = {h: "#a855f7" for h in _HORIZONS}


def _stationary_obj(spans, oid):
    """Stationäre Zelle (speed_kmh=1 < min_speed) mit Span-History."""
    history = [
        {"timestamp": ts, "lat_span_km": ns, "lon_span_km": ew}
        for ts, ns, ew in spans
    ]
    return {
        "id": oid, "lat": 46.62, "lon": 14.30,
        "vx": 0.0, "vy": 0.0, "speed_kmh": 1.0,
        "forecast_mode": "kinematic",
        "size_tendency": "waechst", "intensity_tendency": "stabil",
        "contour_geo": list(_CONTOUR),
        "history": history,
    }


def test_growing_stationary_cell_triggers_growth_approach():
    lc = _import_lc()
    # lon_span wächst stark (4→8→12 km) → rate_ew positiv (gedeckelt 0.3 km/min)
    obj = _stationary_obj([
        ("2026-06-01_12-00-00", 4.0, 4.0),
        ("2026-06-01_12-05-00", 5.0, 8.0),
        ("2026-06-01_12-10-00", 6.0, 12.0),
    ], "grow-stat")
    out = lc.annotate_locations([obj], _LOC, _HORIZONS, _COLORS,
                                min_speed_kmh=5.0, slow_cell_max_kmh=15.0)
    assert len(out) == 1, "Wachsende stationäre Zelle muss einen Treffer liefern"
    hits = out[0]["hits"]
    growth = [v for v in hits.values() if v.get("hit_type") == "growth_approach"]
    assert growth, f"growth_approach erwartet, hits={hits}"
    assert all("survival_frac" in g for g in growth)


def test_stationary_non_growing_cell_no_hit():
    lc = _import_lc()
    # Konstante Spans → rate ≈ 0 → kein Wachstum, Ort außerhalb statischer Kontur
    obj = _stationary_obj([
        ("2026-06-01_12-00-00", 4.0, 4.0),
        ("2026-06-01_12-05-00", 4.0, 4.0),
        ("2026-06-01_12-10-00", 4.0, 4.0),
    ], "stable-stat")
    out = lc.annotate_locations([obj], _LOC, _HORIZONS, _COLORS,
                                min_speed_kmh=5.0, slow_cell_max_kmh=15.0)
    # Kein Wachstum + außerhalb → kein Treffer
    assert all(
        not any(v.get("hit_type") == "growth_approach" for v in o.get("hits", {}).values())
        for o in out
    )


def test_growth_disabled_via_flag(monkeypatch):
    """LOCATION_GROWTH_APPROACH_ENABLED=False → kein growth_approach."""
    lc = _import_lc()
    import runtime_config
    monkeypatch.setattr(
        runtime_config, "get",
        lambda k, d=None: False if k == "LOCATION_GROWTH_APPROACH_ENABLED" else d,
        raising=False,
    )
    obj = _stationary_obj([
        ("2026-06-01_12-00-00", 4.0, 4.0),
        ("2026-06-01_12-05-00", 5.0, 8.0),
        ("2026-06-01_12-10-00", 6.0, 12.0),
    ], "grow-off")
    out = lc.annotate_locations([obj], _LOC, _HORIZONS, _COLORS,
                                min_speed_kmh=5.0, slow_cell_max_kmh=15.0)
    assert all(
        not any(v.get("hit_type") == "growth_approach" for v in o.get("hits", {}).values())
        for o in out
    )
