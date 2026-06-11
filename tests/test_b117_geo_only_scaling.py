"""
tests/test_b117_geo_only_scaling.py

B117: Geo-only Forecast-Fallback muss Pixelversatz mit der Geometrieauflösung
(1/UPSCALE_FACTOR km/px) projizieren, NICHT mit PX_TO_KMH/60.

Szenario: Objekt mit gültigem lat/lon, aber x==0 und y==0 (Geo-only-Pfad).
Bekannte Ostwärts-Bewegung in der History → erwartete Längen-Verschiebung
entspricht px-Versatz × (1/UPSCALE_FACTOR) km, in Grad-Lon umgerechnet.

Der Test schlägt fehl, wenn wieder PX_TO_KMH/60 (5× zu kurz) verwendet wird.

Ausführbar: python3 -m pytest tests/test_b117_geo_only_scaling.py -v
"""
import sys, os, math, importlib
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import UPSCALE_FACTOR, PX_TO_KMH


def _append_kinematic():
    try:
        return importlib.import_module("prediction")._append_kinematic
    except (ImportError, AttributeError) as e:
        pytest.skip(f"_append_kinematic nicht verfügbar: {e}")


def test_geo_only_uses_geometry_resolution():
    """
    Objekt x=0/y=0, lat/lon gesetzt. History: 1 Frame, danach Ostbewegung
    von 5 Original-px über 5 min → avg_vx = 1 px/min (Primärpfad via Timestamps).
    Bei horizon=10 min: px-Versatz = 10 px (original).
    Erwartete km = 10 × (1/UPSCALE_FACTOR) = 10/3 ≈ 3.333 km.
    Erwartete dLon = 3.333 / (111 × cos(lat)).
    """
    fn = _append_kinematic()
    base_lat, base_lon = 46.6, 14.3

    obj = {
        "id": "geo_only",
        "x": 0.0, "y": 0.0,            # erzwingt Geo-only-Pfad
        "lat": base_lat, "lon": base_lon,
        "vx": 1.0, "vy": 0.0,
        "history": [
            {"timestamp": "2026-06-11_14-00-00", "x": 0.0, "y": 0.0,
             "vx": 1.0, "vy": 0.0, "lat": base_lat, "lon": base_lon - 0.02},
            {"timestamp": "2026-06-11_14-05-00", "x": 5.0, "y": 0.0,
             "vx": 1.0, "vy": 0.0, "lat": base_lat, "lon": base_lon},
        ],
    }
    forecasts = {10: [], 20: [], 30: [], 40: [], 60: []}
    fn(obj, forecasts)

    lon10 = obj.get("forecast_lon_10")
    lat10 = obj.get("forecast_lat_10")
    assert lon10 is not None and lat10 is not None, "Kein Geo-only-Forecast erzeugt"

    # avg_vx aus Primärpfad: (5-0)/5min = 1 px/min → 10 px über 10 min
    avg_vx_pm = 1.0
    horizon = 10.0
    px_versatz = avg_vx_pm * horizon                      # 10 original-px
    km_expected = px_versatz * (1.0 / UPSCALE_FACTOR)     # 10/3 km
    dlon_expected = km_expected / (111.0 * math.cos(math.radians(base_lat)))
    lon_expected = base_lon + dlon_expected

    # Toleranz 5 %
    assert abs(lon10 - lon_expected) < abs(dlon_expected) * 0.05 + 1e-6, (
        f"Geo-only-Lon falsch: got {lon10:.5f}, erwartet {lon_expected:.5f} "
        f"(dLon={dlon_expected:.5f}). Vermutlich noch PX_TO_KMH/60 statt 1/UPSCALE."
    )

    # Lat sollte (Ostbewegung) nahezu unverändert sein
    assert abs(lat10 - base_lat) < 1e-4, f"Lat sollte ~konstant sein, ist {lat10}"


def test_geo_only_not_using_px_to_kmh_over_60():
    """
    Regressionsschutz: Mit dem alten Faktor PX_TO_KMH/60 wäre die Projektion
    um Faktor (1/UPSCALE)/(PX_TO_KMH/60) zu kurz. Dieser Test stellt sicher,
    dass die tatsächliche Verschiebung NICHT dem alten (kurzen) Wert entspricht.
    """
    fn = _append_kinematic()
    base_lat, base_lon = 46.6, 14.3
    obj = {
        "id": "geo_only2",
        "x": 0.0, "y": 0.0,
        "lat": base_lat, "lon": base_lon,
        "vx": 1.0, "vy": 0.0,
        "history": [
            {"timestamp": "2026-06-11_14-00-00", "x": 0.0, "y": 0.0,
             "vx": 1.0, "vy": 0.0, "lat": base_lat, "lon": base_lon - 0.02},
            {"timestamp": "2026-06-11_14-05-00", "x": 5.0, "y": 0.0,
             "vx": 1.0, "vy": 0.0, "lat": base_lat, "lon": base_lon},
        ],
    }
    forecasts = {10: [], 20: [], 30: [], 40: [], 60: []}
    fn(obj, forecasts)
    lon10 = obj["forecast_lon_10"]

    px_versatz = 1.0 * 10.0
    # ALTER (falscher) Faktor:
    km_old = px_versatz * (PX_TO_KMH / 60.0)
    dlon_old = km_old / (111.0 * math.cos(math.radians(base_lat)))
    lon_old = base_lon + dlon_old

    # Die tatsächliche Projektion darf NICHT dem alten kurzen Wert entsprechen
    assert abs(lon10 - lon_old) > abs(dlon_old) * 0.2, (
        f"Geo-only nutzt noch den alten PX_TO_KMH/60-Faktor: lon10={lon10:.5f} "
        f"≈ lon_old={lon_old:.5f}"
    )
