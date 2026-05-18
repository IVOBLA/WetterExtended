# valley_feature.py
"""
Talkanalisierungs-Features für Gewitterzellen in Kärnten.

Das ML-Modell lernt aus Trainingsdaten wie Zellen in Tälern kanalisiert werden.
Diese Features kodieren die statische Geländestruktur.

Features:
  valley_alignment    – |cos(angle)| Zell-Bewegung vs. nächstes Tal (0=quer, 1=parallel)
  valley_distance_km  – Abstand zur Talmitten-Linie (km)
  valley_confinement  – 1.0 wenn Zelle im Talquerschnitt (< width/2), sonst 0.0
"""
from __future__ import annotations
import math

try:
    from debug_utils import debug_log
except Exception:
    def debug_log(msg):
        print(msg)

# axis_deg: 0=N, 90=E, 180=S (meteorologisch)
_VALLEY_AXES = [
    {"name": "Drautal",             "lat": 46.620, "lon": 13.850, "axis_deg":  88, "width_km": 12},
    {"name": "Gailtal",             "lat": 46.565, "lon": 13.200, "axis_deg":  98, "width_km":  8},
    {"name": "Lavanttal",           "lat": 46.780, "lon": 14.790, "axis_deg":   5, "width_km":  8},
    {"name": "Moelltal",            "lat": 46.880, "lon": 13.250, "axis_deg": 135, "width_km":  6},
    {"name": "Gurkttal",            "lat": 46.870, "lon": 14.420, "axis_deg": 160, "width_km":  7},
    {"name": "Liesertal",           "lat": 46.870, "lon": 13.490, "axis_deg": 170, "width_km":  5},
    {"name": "Rosental",            "lat": 46.530, "lon": 14.340, "axis_deg": 120, "width_km":  5},
    {"name": "Klagenfurter Becken", "lat": 46.630, "lon": 14.350, "axis_deg":  85, "width_km": 22},
]
_R = 6371.0


def _haversine(lat1, lon1, lat2, lon2):
    dlat = math.radians(lat2-lat1)
    dlon = math.radians(lon2-lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return _R * 2 * math.asin(math.sqrt(max(0.0, a)))


def get_valley_features(lat, lon, vx=0.0, vy=0.0):
    default = {"valley_alignment": 0.0, "valley_distance_km": 999.0, "valley_confinement": 0.0}
    try:
        best, best_d = None, float("inf")
        for v in _VALLEY_AXES:
            d = _haversine(lat, lon, v["lat"], v["lon"])
            if d < best_d:
                best_d, best = d, v

        if best is None:
            return default

        confinement = 1.0 if best_d <= best["width_km"]/2.0 else 0.0

        speed = math.hypot(vx, vy)
        if speed < 0.3:
            alignment = 0.0
        else:
            cell_deg = (math.degrees(math.atan2(vx, -vy)) + 360) % 360
            delta = abs(cell_deg - best["axis_deg"]) % 180.0
            if delta > 90.0:
                delta = 180.0 - delta
            alignment = round(math.cos(math.radians(delta)), 4)

        return {"valley_alignment":   alignment,
                "valley_distance_km": round(best_d, 2),
                "valley_confinement": confinement}
    except Exception as exc:
        debug_log(f"[VALLEY] Fehler ({lat:.3f},{lon:.3f}): {exc}")
        return default


if __name__ == "__main__":
    tests = [
        ("Drautal W->E",  46.62, 13.85, 3.0,  0.0),
        ("Lavanttal N",   46.78, 14.79, 0.0, -2.0),
        ("Quer",          46.95, 13.50, 2.0,  2.0),
    ]
    for name, lat, lon, vx, vy in tests:
        r = get_valley_features(lat, lon, vx=vx, vy=vy)
        print(f"  {name}: align={r['valley_alignment']:.2f} dist={r['valley_distance_km']:.1f}km confined={r['valley_confinement']:.0f}")
