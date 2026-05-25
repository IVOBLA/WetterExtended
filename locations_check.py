import math
from typing import Iterable, List

EARTH_RADIUS_KM = 6371.0088


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2)
    return EARTH_RADIUS_KM * 2 * math.asin(math.sqrt(a))


def _point_to_segment_km(
    plat: float, plon: float,
    alat: float, alon: float,
    blat: float, blon: float,
) -> float:
    """Kleinste Strecke Punkt → Segment (lokal-eben, km)."""
    if alat == blat and alon == blon:
        return _haversine_km(plat, plon, alat, alon)
    m_lat = (alat + blat) / 2.0
    kx = 111.320 * math.cos(math.radians(m_lat))
    ky = 110.574
    px, py = plon * kx, plat * ky
    ax, ay = alon * kx, alat * ky
    bx, by = blon * kx, blat * ky
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0,
        ((px - ax) * dx + (py - ay) * dy) / max(dx * dx + dy * dy, 1e-9)
    ))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def annotate_locations(
    objects: Iterable[dict],
    locations: List[dict],
    horizons: List[int],
    colors: dict,
    min_speed_kmh: float = 0.0,
    slow_cell_max_kmh: float = 15.0,
    slow_radius_factor: float = 1.5,
) -> List[dict]:
    """Pro Ort prüfen, ob eine Gewitterzelle ihn bedroht.

    DREI Bedrohungstypen (Priorität: current > slow_approach > forecast):

    1. "current"  — Zelle befindet sich JETZT im Ortsradius.
                    Gilt unabhängig von Geschwindigkeit (stationär,
                    entstehend, überlappend). Horizon-Key: 0.

    2. "slow_approach" — Langsam ziehende Zelle (min_speed_kmh ≤ speed ≤
                    slow_cell_max_kmh). Meteorologisch: höheres Unwetter-
                    potential durch Verweilzeit (Überflutung, Hagel).
                    Prüfung gegen Radius × slow_radius_factor.
                    Horizon-Key: jeweiliger Forecast-Horizont.

    3. "forecast"  — Schnell ziehende Zelle (speed > slow_cell_max_kmh).
                    Forecast-Pfad schneidet Ortsradius (normal).
                    Horizon-Key: jeweiliger Forecast-Horizont.

    Rückgabe:
        [{ name, lat, lon, radius_km,
           hits: { horizon_key: { hit_type, color, cell_id,
                                  distance_km, speed_kmh } } }]

    Hinweis: Horizon-Key 0 = "jetzt", positive Integerwerte = Minuten.
    """
    try:
        from config import PX_TO_KMH as _PX_TO_KMH
    except ImportError:
        _PX_TO_KMH = 10.0          # Fallback falls config nicht importierbar

    objects = list(objects)
    if not objects or not locations:
        return []

    out = []

    for loc in locations:
        try:
            loc_lat  = float(loc["lat"])
            loc_lon  = float(loc["lon"])
            radius   = float(loc.get("radius_km", 5.0))
            name     = str(loc.get("name", ""))
        except (KeyError, TypeError, ValueError):
            continue

        hits: dict = {}
        extended_r = radius * slow_radius_factor

        for obj in objects:
            o_lat = obj.get("lat")
            o_lon = obj.get("lon")
            if o_lat is None or o_lon is None:
                continue
            o_lat = float(o_lat)
            o_lon = float(o_lon)

            vx        = float(obj.get("vx") or 0.0)
            vy        = float(obj.get("vy") or 0.0)
            speed_kmh = math.hypot(vx, vy) * _PX_TO_KMH
            cell_id   = obj.get("id")

            # ── Typ 1: CURRENT ────────────────────────────────────────────
            # Zelle jetzt im Ort — immer prüfen, egal wie schnell.
            d_now = _haversine_km(loc_lat, loc_lon, o_lat, o_lon)
            if d_now <= radius:
                # Horizon 0 = "jetzt". Nicht durch spätere Typen überschreiben.
                if 0 not in hits:
                    hits[0] = {
                        "hit_type":    "current",
                        "color":       "#dc2626",
                        "cell_id":     cell_id,
                        "distance_km": round(d_now, 3),
                        "speed_kmh":   round(speed_kmh, 1),
                    }

            # Zelle zu langsam für Pfeil → keine Forecast-Checks
            if speed_kmh < min_speed_kmh:
                continue

            # Kein Forecast-Mode → keine Forecast-Checks
            if obj.get("forecast_mode") not in ("ml", "kinematic"):
                continue

            # ── Typ 2: SLOW_APPROACH ──────────────────────────────────────
            # Langsam ziehende Zelle: erweiterter Warnradius.
            # P34: Zwischensegmente wie bei Typ 3.
            if speed_kmh <= slow_cell_max_kmh:
                _fpts_slow: list = [(o_lat, o_lon)]
                for _h in sorted(horizons):
                    _fy = obj.get(f"forecast_lat_{_h}")
                    _fx = obj.get(f"forecast_lon_{_h}")
                    _fpts_slow.append(
                        (float(_fy), float(_fx)) if _fy is not None and _fx is not None else None
                    )

                for h_idx, h in enumerate(sorted(horizons)):
                    if h in hits:
                        continue
                    fy = obj.get(f"forecast_lat_{h}")
                    fx = obj.get(f"forecast_lon_{h}")
                    if fy is None or fx is None:
                        continue
                    fy_f, fx_f = float(fy), float(fx)

                    d = _point_to_segment_km(loc_lat, loc_lon,
                                             o_lat, o_lon, fy_f, fx_f)
                    if d > extended_r and h_idx > 0:
                        _prev_s = _fpts_slow[h_idx] if h_idx < len(_fpts_slow) else None
                        if _prev_s is not None:
                            d_seg = _point_to_segment_km(
                                loc_lat, loc_lon,
                                _prev_s[0], _prev_s[1],
                                fy_f, fx_f,
                            )
                            d = min(d, d_seg)

                    if d <= extended_r:
                        hits[h] = {
                            "hit_type":    "slow_approach",
                            "color":       "#f97316",  # Orange: Starkregenpotential
                            "cell_id":     cell_id,
                            "distance_km": round(d, 3),
                            "speed_kmh":   round(speed_kmh, 1),
                        }

            # ── Typ 3: FORECAST ───────────────────────────────────────────
            # Schnell ziehende Zelle: Forecast-Pfad vs. normaler Radius.
            # P34: Zwei Prüfungsebenen:
            #   a) origin → h (wie bisher) — erfasst direkten Pfad
            #   b) h[n] → h[n+1]           — erfasst Kursbewegungen zwischen Horizonten
            else:
                # Forecast-Punkte sammeln (für Zwischensegment-Prüfung)
                _fpts: list = [(o_lat, o_lon)]   # [origin, h0, h1, h2, ...]
                for _h in sorted(horizons):
                    _fy = obj.get(f"forecast_lat_{_h}")
                    _fx = obj.get(f"forecast_lon_{_h}")
                    if _fy is not None and _fx is not None:
                        _fpts.append((float(_fy), float(_fx)))
                    else:
                        _fpts.append(None)   # Lücke merken

                for h_idx, h in enumerate(sorted(horizons)):
                    if h in hits:
                        continue
                    fy = obj.get(f"forecast_lat_{h}")
                    fx = obj.get(f"forecast_lon_{h}")
                    if fy is None or fx is None:
                        continue
                    fy_f, fx_f = float(fy), float(fx)

                    # a) origin → h (bestehende Prüfung)
                    d = _point_to_segment_km(loc_lat, loc_lon,
                                             o_lat, o_lon,
                                             fy_f, fx_f)

                    # b) P34: Zwischensegment h_prev → h prüfen (falls verfügbar)
                    if d > radius and h_idx > 0:
                        _prev = _fpts[h_idx] if h_idx < len(_fpts) else None
                        if _prev is not None:
                            d_seg = _point_to_segment_km(
                                loc_lat, loc_lon,
                                _prev[0], _prev[1],
                                fy_f, fx_f,
                            )
                            d = min(d, d_seg)

                    if d <= radius:
                        hits[h] = {
                            "hit_type":    "forecast",
                            "color":       colors.get(h) or colors.get(str(h), "#888888"),
                            "cell_id":     cell_id,
                            "distance_km": round(d, 3),
                            "speed_kmh":   round(speed_kmh, 1),
                        }

        if hits:
            out.append({
                "name":      name,
                "lat":       loc_lat,
                "lon":       loc_lon,
                "radius_km": radius,
                "hits":      hits,
            })

    if not out:
        try:
            from debug_utils import debug_log
            debug_log(
                f"[LOCATIONS] Keine Orts-Hits "
                f"(Objekte={len(objects)}, Orte={len(locations)}, "
                f"min_speed={min_speed_kmh} km/h, slow_max={slow_cell_max_kmh} km/h)."
            )
        except Exception:
            pass

    return out
