"""
test_locations_e2e.py — Pytest-kompatible E2E-Smoke-Tests.

Fix P06:
  - Kein sys.exit() mehr auf Modulebene → pytest kann die Datei sammeln.
  - Jeder Test ist eine eigene Funktion und benutzt assert.
  - Tests, die einen laufenden Flask-Server brauchen, werden mit
    pytest.skip(...) übersprungen wenn der Server nicht erreichbar ist.
  - Optional weiterhin als CLI ausführbar via `python3 -m tests.test_locations_e2e`
    (siehe __main__-Block am Ende).
"""

import json
import os
import sys

import pytest


# ---------------------------------------------------------------------------
# Helfer
# ---------------------------------------------------------------------------

def _flask_alive(url: str = "http://localhost:5000/api/health", timeout: float = 2.0) -> bool:
    """True wenn die lokale Flask-API erreichbar ist."""
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Test 1 — pixel_to_geo liefert plausible Koordinaten in Kärnten
# ---------------------------------------------------------------------------

def test_pixel_to_geo_inside_kaernten():
    try:
        from geo_utils import pixel_to_geo
        from config import UPSCALE_FACTOR
    except ImportError as exc:
        pytest.skip(f"Abhängigkeit fehlt: {exc}")

    test_pixels = [(300, 300), (100, 100), (500, 400)]
    for px, py in test_pixels:
        lat, lon = pixel_to_geo(px * UPSCALE_FACTOR, py * UPSCALE_FACTOR)
        # (0,0) wäre ein Fallback-Indikator → unzulässig
        assert not (abs(lat) < 0.1 and abs(lon) < 0.1), (
            f"pixel_to_geo({px},{py}) lieferte Fallback (0,0)"
        )

    lat_c, lon_c = pixel_to_geo(300 * UPSCALE_FACTOR, 300 * UPSCALE_FACTOR)
    assert 44 < lat_c < 49, f"lat={lat_c:.3f} außerhalb Kärnten-Region"
    assert 10 < lon_c < 18, f"lon={lon_c:.3f} außerhalb Kärnten-Region"


# ---------------------------------------------------------------------------
# Test 2 — annotate_locations: Treffer-Logik mit synthetischen Daten
# ---------------------------------------------------------------------------

def test_annotate_locations_current_hit():
    """Eine Zelle direkt am Ort muss als 'current' (Horizon 0) markiert sein."""
    try:
        from locations_check import annotate_locations
    except ImportError as exc:
        pytest.skip(f"locations_check nicht importierbar: {exc}")

    objects = [
        {
            "id": "cell-A",
            "lat": 46.6228,
            "lon": 14.3050,
            "vx": 0.0,
            "vy": 0.0,
            "forecast_mode": "kinematic",
        }
    ]
    locations = [{"name": "Klagenfurt", "lat": 46.6228, "lon": 14.3050, "radius_km": 5.0}]
    horizons = [10, 20, 30]
    colors = {10: "#0f0", 20: "#00f", 30: "#f00"}

    out = annotate_locations(objects, locations, horizons, colors)
    assert isinstance(out, list)
    assert len(out) == 1
    hits = out[0].get("hits", {})
    assert 0 in hits, f"Erwarte current-Hit (Horizon-Key 0), bekam {list(hits.keys())}"
    assert hits[0]["hit_type"] == "current"


def test_annotate_locations_no_hit_far_cell():
    """Weit entfernte Zelle darf keinen Treffer auslösen."""
    try:
        from locations_check import annotate_locations
    except ImportError as exc:
        pytest.skip(f"locations_check nicht importierbar: {exc}")

    objects = [
        {
            "id": "cell-B",
            "lat": 50.0,
            "lon": 20.0,
            "vx": 0.0,
            "vy": 0.0,
            "forecast_mode": "kinematic",
        }
    ]
    locations = [{"name": "Villach", "lat": 46.61, "lon": 13.85, "radius_km": 5.0}]
    out = annotate_locations(objects, locations, [10, 20, 30], {10: "#0f0", 20: "#00f", 30: "#f00"})
    assert out == [] or out[0].get("hits", {}) == {}, "Weit entfernte Zelle darf keine Hits erzeugen"


# ---------------------------------------------------------------------------
# Test 3 — Live-API erreichbar (überspringen wenn Flask aus)
# ---------------------------------------------------------------------------

def test_api_objects_endpoint():
    if not _flask_alive():
        pytest.skip("Flask läuft nicht lokal — Endpoint-Test übersprungen")
    import urllib.request
    with urllib.request.urlopen("http://localhost:5000/api/objects", timeout=3) as r:
        body = json.loads(r.read())
    assert isinstance(body, list)


def test_api_forecast_endpoint(monkeypatch):
    pytest.importorskip("flask")
    import app as wetter_app

    obj = {
        "id": "WX-TEST-FORECAST",
        "lat": 46.70,
        "lon": 14.10,
        "x": 100.0,
        "y": 200.0,
        "vx": 1.0,
        "vy": 0.5,
        "speed_kmh": 20.0,
        "forecast_lat_10": 46.71,
        "forecast_lon_10": 14.12,
        "forecast_mode_10": "kinematic",
        "contour_geo": [[14.09, 46.69], [14.11, 46.69], [14.10, 46.71]],
    }
    monkeypatch.setattr(wetter_app, "_objects_for_ts", lambda ts=None: [obj])
    monkeypatch.setattr(wetter_app.runtime_config, "get", lambda key, default=None: [10] if key == "ML_FORECAST_HORIZONS_MIN" else default)

    client = wetter_app.app.test_client()
    response = client.get("/api/forecast")

    assert response.status_code == 200
    body = response.get_json()
    assert isinstance(body, dict)
    assert body["type"] == "FeatureCollection"
    assert isinstance(body["features"], list)


# ---------------------------------------------------------------------------
# Test 4 — forecast.kmz vorhanden + enthält .kml
# ---------------------------------------------------------------------------

def test_forecast_kmz_contains_kml():
    import zipfile
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    kmz_path = os.path.join(root, "forecast.kmz")
    if not os.path.exists(kmz_path):
        pytest.skip("forecast.kmz noch nicht erzeugt (Live-Loop noch nicht gelaufen)")
    with zipfile.ZipFile(kmz_path, "r") as z:
        names = z.namelist()
    assert any(n.endswith(".kml") for n in names), f"forecast.kmz ohne .kml: {names}"


# ---------------------------------------------------------------------------
# CLI-Ausführbarkeit (manueller Modus)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Manuelle Ausführung ohne pytest — gibt eine kurze Zusammenfassung.
    test_funcs = [
        ("pixel_to_geo inside Kärnten", test_pixel_to_geo_inside_kaernten),
        ("annotate current hit", test_annotate_locations_current_hit),
        ("annotate no hit (far cell)", test_annotate_locations_no_hit_far_cell),
        ("/api/objects endpoint", test_api_objects_endpoint),
        ("/api/forecast endpoint", test_api_forecast_endpoint),
        ("forecast.kmz contains .kml", test_forecast_kmz_contains_kml),
    ]
    passed = skipped = failed = 0
    for name, fn in test_funcs:
        try:
            fn()
            print(f"  ✅ {name}")
            passed += 1
        except pytest.skip.Exception as e:
            print(f"  ⏭️  {name} — skipped: {e}")
            skipped += 1
        except AssertionError as e:
            print(f"  ❌ {name} — {e}")
            failed += 1
        except Exception as e:
            print(f"  ❌ {name} — {type(e).__name__}: {e}")
            failed += 1
    print(f"\nBestanden: {passed}   Übersprungen: {skipped}   Fehlgeschlagen: {failed}")
    sys.exit(0 if failed == 0 else 1)
