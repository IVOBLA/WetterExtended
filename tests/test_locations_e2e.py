#!/usr/bin/env python3
"""
End-to-End Test: Orte-Durchquerung / Berührung / Streifung.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = "✅ PASS"
FAIL = "❌ FAIL"
WARN = "⚠️  WARN"

results = []


def check(name: str, condition: bool, detail: str = "") -> bool:
    status = PASS if condition else FAIL
    line = f"  {status}  {name}"
    if detail:
        line += f"\n         {detail}"
    print(line)
    results.append(condition)
    return condition


def warn(name: str, detail: str = "") -> None:
    line = f"  {WARN}  {name}"
    if detail:
        line += f"\n         {detail}"
    print(line)
    results.append(None)


print("\n── Test 1: annotate_locations — Zelle IST im Ort-Radius ──")
try:
    from locations_check import annotate_locations

    HORIZONS = [10, 20, 30, 40, 60]
    COLORS = {10: "#60a5fa", 20: "#3b82f6", 30: "#2563eb", 40: "#1d4ed8", 60: "#1e40af"}
    klagenfurt = {"name": "Klagenfurt", "lat": 46.623, "lon": 14.305, "radius_km": 5.0}

    obj_inside = {
        "id": "Z01",
        "lat": 46.624,
        "lon": 14.306,
        "vx": 3.0,
        "vy": -1.0,
        "forecast_mode": "kinematic",
        **{f"forecast_lat_{h}": 46.624 for h in HORIZONS},
        **{f"forecast_lon_{h}": 14.306 for h in HORIZONS},
    }
    hits = annotate_locations([obj_inside], [klagenfurt], HORIZONS, COLORS)
    hit_types = [list(loc["hits"].values())[0]["hit_type"] for loc in hits if loc["hits"]]
    check("Zelle im Radius → hit_type='current'", "current" in hit_types, f"hit_types={hit_types}")
except Exception as e:
    check("annotate_locations importierbar", False, str(e))


print("\n── Test 2: annotate_locations — Zelle WEIT WEG ──")
try:
    obj_far = {
        "id": "Z02",
        "lat": 47.5,
        "lon": 14.3,
        "vx": 0.0,
        "vy": 0.0,
        "forecast_mode": "kinematic",
        **{f"forecast_lat_{h}": 47.5 for h in HORIZONS},
        **{f"forecast_lon_{h}": 14.3 for h in HORIZONS},
    }
    hits = annotate_locations([obj_far], [klagenfurt], HORIZONS, COLORS)
    no_hit = all(not loc["hits"] for loc in hits)
    check("Zelle weit weg → keine hits", no_hit, f"hits={[loc['hits'] for loc in hits]}")
except Exception as e:
    check("annotate_locations (kein Treffer)", False, str(e))


print("\n── Test 3: annotate_locations — Zelle zieht in 30min über Ort ──")
try:
    obj_approaching = {
        "id": "Z03",
        "lat": 46.700,
        "lon": 14.305,
        "vx": 0.0,
        "vy": 1.5,
        "forecast_mode": "kinematic",
        "forecast_lat_10": 46.680,
        "forecast_lon_10": 14.305,
        "forecast_lat_20": 46.660,
        "forecast_lon_20": 14.305,
        "forecast_lat_30": 46.625,
        "forecast_lon_30": 14.305,
        "forecast_lat_40": 46.590,
        "forecast_lon_40": 14.305,
        "forecast_lat_60": 46.540,
        "forecast_lon_60": 14.305,
    }
    hits = annotate_locations([obj_approaching], [klagenfurt], HORIZONS, COLORS)
    hit_horizons = []
    for loc in hits:
        for hk, hv in loc["hits"].items():
            if hk != 0:
                hit_horizons.append((hk, hv["hit_type"]))
    check("Forecast-Hit bei H=30", any(k == 30 for k, _ in hit_horizons), f"hit_horizons={hit_horizons}")
except Exception as e:
    check("annotate_locations (Forecast-Hit)", False, str(e))


print("\n── Test 4: pixel_to_geo — keine (0.0, 0.0) Ausgabe für Kärnten ──")
try:
    from geo_utils import pixel_to_geo
    from config import UPSCALE_FACTOR

    test_pixels = [(300, 300), (100, 100), (500, 400)]
    zero_results = []
    for px, py in test_pixels:
        lat, lon = pixel_to_geo(px * UPSCALE_FACTOR, py * UPSCALE_FACTOR)
        if abs(lat) < 0.1 and abs(lon) < 0.1:
            zero_results.append((px, py, lat, lon))
    check("pixel_to_geo gibt keine (0,0)-Koordinaten", len(zero_results) == 0, f"Null-Ausgaben: {zero_results}")
    lat_c, lon_c = pixel_to_geo(300 * UPSCALE_FACTOR, 300 * UPSCALE_FACTOR)
    in_range = 44 < lat_c < 49 and 10 < lon_c < 18
    check("pixel_to_geo Bildmitte liegt in Kärnten-Region", in_range, f"lat={lat_c:.3f}, lon={lon_c:.3f}")
except ModuleNotFoundError as e:
    warn("pixel_to_geo nicht prüfbar (optional dependency fehlt)", str(e))
except Exception as e:
    check("pixel_to_geo importierbar", False, str(e))


print("\n── Test 5: /api/objects — Live-API prüfen (Flask muss laufen) ──")
try:
    import urllib.request

    with urllib.request.urlopen("http://localhost:5000/api/objects", timeout=3) as r:
        objs = json.loads(r.read())
    check("/api/objects erreichbar und gibt Liste zurück", isinstance(objs, list), f"{len(objs)} Objekte")
    if objs:
        first = objs[0]
        check("forecast_mode im Objekt vorhanden", "forecast_mode" in first, f"Schlüssel: {list(first.keys())[:10]}")
        check("forecast_lat_10 im Objekt vorhanden", "forecast_lat_10" in first)
except Exception as e:
    warn("/api/objects nicht erreichbar (Flask läuft nicht?)", str(e))

print("\n── Test 6: /api/forecast — Live-API prüfen (Flask muss laufen) ──")
try:
    import urllib.request

    with urllib.request.urlopen("http://localhost:5000/api/forecast", timeout=3) as r:
        fc = json.loads(r.read())
    check("/api/forecast erreichbar", isinstance(fc, (list, dict)), f"Typ: {type(fc).__name__}")
except Exception as e:
    warn("/api/forecast nicht erreichbar (Flask läuft nicht?)", str(e))

print("\n── Test 7: forecast.kmz vorhanden und lesbar ──")
try:
    import zipfile

    kmz_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "forecast.kmz")
    if os.path.exists(kmz_path):
        with zipfile.ZipFile(kmz_path, "r") as z:
            names = z.namelist()
        check("forecast.kmz enthält .kml", any(n.endswith(".kml") for n in names), f"Dateien: {names}")
    else:
        warn("forecast.kmz nicht vorhanden — noch kein KMZ-Export gelaufen")
except Exception as e:
    check("forecast.kmz lesbar", False, str(e))

print("\n── Zusammenfassung ──────────────────────────────────────────────────")
hard = [r for r in results if r is not None]
passed = sum(1 for r in hard if r)
failed = sum(1 for r in hard if not r)
skipped = sum(1 for r in results if r is None)
print(f"  Bestanden: {passed} / {len(hard)}   Übersprungen: {skipped}")
if failed:
    print(f"  ❌ {failed} Test(s) fehlgeschlagen")
    sys.exit(1)
print("  ✅ Alle ausführbaren Tests bestanden")
sys.exit(0)
