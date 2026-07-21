"""B452: slow_approach prüft gegen den NORMALEN Ortsradius — kein erweiterter
Radius mehr.

Reproduziert das Krumpendorf-Szenario (Zelle JQQSFXE8, radius_km=2.0):
- Ein langsamer Zug, dessen Bahn in ~2.5 km Segmentabstand am Ort vorbeizieht,
  lag zwischen radius (2.0) und dem alten extended_r (2.0 x 1.5 = 3.0) und
  erzeugte fälschlich eine Warnung. Nach B452 darf hier KEIN Treffer entstehen.
- Ein Zug in ~1.5 km Abstand (<= radius) erzeugt weiterhin einen Treffer.
"""
import importlib

import pytest


def _import_lc():
    return importlib.import_module("locations_check")


def _slow_obj():
    # Langsame Zelle (8 km/h), ohne Kontur -> Fallback-Pfad (d <= radius).
    # Ursprung weit oestlich, Forecast weit westlich: die Bahn liegt auf
    # konstanter Breite und zieht am Ort in perpendikularem Abstand vorbei.
    return {
        "id": "TESTSLOW1",
        "lat": 46.60,
        "lon": 14.30,
        "speed_kmh": 8.0,
        "forecast_mode": "ml",
        "forecast_lat_20": 46.60,
        "forecast_lon_20": 14.10,
        "intensity_tendency": "stabil",
        "size_tendency": "stabil",
        "radar_age_min": 0.0,
    }


def _run(lc, loc_lat, loc_lon, radius_km):
    loc = [{"name": "TestOrt", "lat": loc_lat, "lon": loc_lon, "radius_km": radius_km}]
    return lc.annotate_locations(
        [_slow_obj()], loc, [20], {20: "#f00"},
        min_speed_kmh=5.0, slow_cell_max_kmh=15.0,
    )


def test_no_slow_hit_between_radius_and_old_extended(monkeypatch):
    lc = _import_lc()
    monkeypatch.setattr(lc, "_survival_allows", lambda obj, h: (True, 1.0))
    # Ort ~2.5 km noerdlich der Bahn (lat 46.60): 2.5/111 = 0.02252 Grad.
    # Segmentabstand ~2.5 km -> > radius(2.0), aber < altem extended_r(3.0).
    out = _run(lc, 46.62252, 14.20, 2.0)
    hit = out[0]["hits"].get(20) if out else None
    assert hit is None, (
        "B452-Verletzung: slow_approach-Treffer bei ~2.5 km "
        "(zwischen radius=2.0 und altem extended_r=3.0) — erweiterter "
        "Radius offenbar noch aktiv."
    )


def test_slow_hit_inside_normal_radius(monkeypatch):
    lc = _import_lc()
    monkeypatch.setattr(lc, "_survival_allows", lambda obj, h: (True, 1.0))
    # Ort ~1.5 km noerdlich der Bahn: 1.5/111 = 0.01352 Grad -> <= radius(2.0).
    out = _run(lc, 46.61352, 14.20, 2.0)
    hit = out[0]["hits"].get(20)
    assert hit is not None, "slow_approach-Treffer im normalen Radius erwartet"
    assert hit["hit_type"] == "slow_approach"


def test_signature_has_no_slow_radius_factor():
    import inspect
    lc = _import_lc()
    params = inspect.signature(lc.annotate_locations).parameters
    assert "slow_radius_factor" not in params, (
        "annotate_locations darf keinen slow_radius_factor-Parameter mehr haben"
    )
