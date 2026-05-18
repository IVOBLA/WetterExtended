import math
from typing import Iterable, List

EARTH_RADIUS_KM = 6371.0088


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    return EARTH_RADIUS_KM * c


def _point_to_segment_km(plat, plon, alat, alon, blat, blon) -> float:
    """Kleinste Strecke Punkt zu Segment (lokal-eben in km)."""
    if alat == blat and alon == blon:
        return _haversine_km(plat, plon, alat, alon)
    m_lat = (alat + blat) / 2.0
    kx = 111.320 * math.cos(math.radians(m_lat))
    ky = 110.574
    px, py = plon * kx, plat * ky
    ax, ay = alon * kx, alat * ky
    bx, by = blon * kx, blat * ky
    dx, dy = bx - ax, by - ay
    t_num = (px - ax) * dx + (py - ay) * dy
    t_den = max(dx * dx + dy * dy, 1e-9)
    t = max(0.0, min(1.0, t_num / t_den))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy)


def annotate_locations(objects: Iterable[dict], locations: List[dict], horizons: List[int], colors: dict) -> List[dict]:
    """Pro Ort prüfen, welche Forecast-Pfade ihn berühren.
    Rückgabe: Liste von Hits {name, lat, lon, radius_km, hits: {h: {color, cell_id, distance_km}}}

    Orts-Markierung ist aktiv sobald Forecast-Pfade vorliegen (ML oder
    kinematisch), sofern mindestens ein Forecast-Lat/Lon-Wert je Objekt
    für die geprüften Horizonte vorhanden ist.
    """
    objects = list(objects)

    # F3-FIX: ML UND kinematische Forecasts markieren Orte (Zieldefinition).
    forecast_objects = [
        obj for obj in objects
        if obj.get("forecast_mode") in ("ml", "kinematic")
        and any(obj.get(f"forecast_lat_{h}") is not None for h in horizons)
    ]
    if not forecast_objects:
        try:
            from debug_utils import debug_log
            debug_log("[LOCATIONS] Keine Forecast-Felder verfügbar — Orts-Markierung übersprungen.")
        except Exception:
            pass
        return []

    out = []
    for loc in locations:
        try:
            lat = float(loc["lat"])
            lon = float(loc["lon"])
            radius = float(loc.get("radius_km", 5.0))
            name = str(loc.get("name", ""))
        except (KeyError, TypeError, ValueError):
            continue

        hits = {}
        for obj in forecast_objects:
            o_lat = obj.get("lat")
            o_lon = obj.get("lon")
            if o_lat is None or o_lon is None:
                continue
            for h in horizons:
                fy = obj.get(f"forecast_lat_{h}")
                fx = obj.get(f"forecast_lon_{h}")
                if fy is None or fx is None:
                    continue
                d = _point_to_segment_km(lat, lon, float(o_lat), float(o_lon), float(fy), float(fx))
                if d <= radius and h not in hits:
                    hits[h] = {
                        "color": colors.get(h, "#888888"),
                        "cell_id": obj.get("id"),
                        "distance_km": round(d, 3),
                    }
        if hits:
            out.append({
                "name": name, "lat": lat, "lon": lon,
                "radius_km": radius, "hits": hits,
            })
    return out
