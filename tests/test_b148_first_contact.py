"""B148: Präzise Erstkontaktzeit (ETA) bis Radius-Berührung + Transit-Treffer
zwischen zwei Horizonten. Reine Logiktests gegen locations_check (kein TF/cv2)."""
import pytest


def _lc():
    try:
        import importlib
        return importlib.import_module("locations_check")
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"locations_check nicht importierbar: {exc}")


# Ort + Geometrie (Klagenfurt-nah). 1° lon ≈ 76.49 km bei 46.60° N.
LOC_LAT, LOC_LON = 46.60, 14.20
KM_PER_DEG_LON = 111.32 * __import__("math").cos(__import__("math").radians(LOC_LAT))


def _lon_offset_km(km):
    return LOC_LON + km / KM_PER_DEG_LON


def test_contact_start_inside_is_zero():
    lc = _lc()
    track = [(0.0, LOC_LAT, LOC_LON)]
    assert lc._first_radius_contact_min(track, LOC_LAT, LOC_LON, 5.0) == 0.0


def test_contact_never_reached_is_none():
    lc = _lc()
    # Punkt 20 km östlich, bleibt dort → nie im 5-km-Radius.
    track = [(0.0, LOC_LAT, _lon_offset_km(20.0)), (30.0, LOC_LAT, _lon_offset_km(20.0))]
    assert lc._first_radius_contact_min(track, LOC_LAT, LOC_LON, 5.0) is None


def test_contact_interpolated_between_horizons():
    """Beide Stützpunkte (6 km O / 6 km W) liegen AUSSERHALB des 5-km-Radius,
    der Pfad dazwischen kreuzt den Radius → Kontakt wird interpoliert (~21.7 min)."""
    lc = _lc()
    track = [(20.0, LOC_LAT, _lon_offset_km(6.0)), (40.0, LOC_LAT, _lon_offset_km(-6.0))]
    t = lc._first_radius_contact_min(track, LOC_LAT, LOC_LON, 5.0)
    assert t is not None, "Transit zwischen den Horizonten nicht erkannt"
    assert t == pytest.approx(21.67, abs=0.8)


def test_annotate_sets_first_contact_and_hit_for_transit():
    """Zelle quert zwischen h=20 und h=40 den Ort: Treffer vorhanden UND
    first_contact_min ist die echte (frühere) Kontaktzeit, nicht der Horizont."""
    lc = _lc()
    obj = {
        "id": "transit-1", "lat": LOC_LAT, "lon": _lon_offset_km(12.0),
        "forecast_mode": "kinematic", "vx": 6.0, "vy": 0.0, "speed_kmh": 40.0,
        "intensity_tendency": "stabil", "size_tendency": "stabil",
        "forecast_lat_20": LOC_LAT, "forecast_lon_20": _lon_offset_km(6.0),
        "forecast_lat_40": LOC_LAT, "forecast_lon_40": _lon_offset_km(-6.0),
    }
    loc = [{"name": "Klagenfurt", "lat": LOC_LAT, "lon": LOC_LON, "radius_km": 5.0}]
    out = lc.annotate_locations([obj], loc, [20, 40], {20: "#0f0", 40: "#f00"},
                                min_speed_kmh=5.0, slow_cell_max_kmh=15.0)
    assert len(out) == 1
    assert out[0]["hits"], "kein Treffer für querende Zelle"
    fc = out[0]["first_contact_min"]
    assert fc is not None
    assert fc == pytest.approx(21.67, abs=1.0)
    assert fc < 40, "ETA muss früher sein als der diskrete Horizont"
    assert out[0]["first_contact_cell_id"] == "transit-1"


def test_annotate_current_cell_eta_zero():
    """Zelle direkt im Ort → ETA 0 (jetzt)."""
    lc = _lc()
    obj = {"id": "now-1", "lat": LOC_LAT, "lon": LOC_LON,
           "forecast_mode": "kinematic", "vx": 0.0, "vy": 0.0, "speed_kmh": 5.0}
    loc = [{"name": "Klagenfurt", "lat": LOC_LAT, "lon": LOC_LON, "radius_km": 5.0}]
    out = lc.annotate_locations([obj], loc, [20], {20: "#f00"})
    assert len(out) == 1
    assert out[0]["first_contact_min"] == 0.0
