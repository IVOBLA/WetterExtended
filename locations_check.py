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


def _point_in_polygon_geo(plat: float, plon: float, contour_geo: list) -> bool:
    """Ray-Casting: liegt Punkt (plat, plon) innerhalb des Geo-Polygons?
    contour_geo: [[lon, lat], ...] — GeoJSON-Format (lon zuerst).
    """
    n = len(contour_geo)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = contour_geo[i][0], contour_geo[i][1]
        xj, yj = contour_geo[j][0], contour_geo[j][1]
        if ((yi > plat) != (yj > plat)) and (
            plon < (xj - xi) * (plat - yi) / max(abs(yj - yi), 1e-12) + xi
        ):
            inside = not inside
        j = i
    return inside


def _min_dist_to_polygon_km(plat: float, plon: float, contour_geo: list) -> float:
    """Kleinster Abstand Punkt → Polygon-Rand in km.
    Gibt 0.0 zurück wenn der Punkt innerhalb des Polygons liegt.
    contour_geo: [[lon, lat], ...] — GeoJSON-Format (lon zuerst).
    """
    if not contour_geo or len(contour_geo) < 3:
        return float("inf")
    if _point_in_polygon_geo(plat, plon, contour_geo):
        return 0.0
    n = len(contour_geo)
    min_d = float("inf")
    for i in range(n):
        a_lon, a_lat = contour_geo[i][0], contour_geo[i][1]
        b_lon, b_lat = contour_geo[(i + 1) % n][0], contour_geo[(i + 1) % n][1]
        d = _point_to_segment_km(plat, plon, a_lat, a_lon, b_lat, b_lon)
        if d < min_d:
            min_d = d
    return min_d


def _linreg_slope(xs: list, ys: list) -> float:
    """Lineare Regression: gibt Steigung (slope) zurück. 0 bei zu wenig Daten."""
    n = len(xs)
    if n < 2:
        return 0.0
    x_m = sum(xs) / n
    y_m = sum(ys) / n
    cov = sum((xs[i] - x_m) * (ys[i] - y_m) for i in range(n))
    var = sum((xs[i] - x_m) ** 2 for i in range(n))
    return cov / var if var > 1e-9 else 0.0


def _directional_growth_rates(obj: dict) -> tuple:
    """Misst richtungsabhängige Wachstumsraten aus der History.

    Liest lat_span_km (N-S-Ausdehnung) und lon_span_km (E-W-Ausdehnung)
    aus den History-Einträgen und berechnet die Steigung per lineare Regression.

    Gibt (rate_ns_km_per_min, rate_ew_km_per_min) zurück:
      positiv = wächst in dieser Richtung
      negativ = schrumpft
      0.0     = keine Daten oder stabil

    Die Raten beschreiben die Änderung der HALBEN Ausdehnung, damit sie direkt
    als Skalierungsgrundlage verwendet werden können.
    """
    from datetime import datetime as _dt
    history = obj.get("history") or []

    ts_min: list = []
    ns_vals: list = []
    ew_vals: list = []
    t0 = None

    for entry in history:
        ts_str = entry.get("timestamp")
        lat_span = entry.get("lat_span_km")
        lon_span = entry.get("lon_span_km")
        if not ts_str or lat_span is None or lon_span is None:
            continue
        if lat_span <= 0 or lon_span <= 0:
            continue
        try:
            t = _dt.strptime(ts_str, "%Y-%m-%d_%H-%M-%S")
        except Exception:
            continue
        if t0 is None:
            t0 = t
        t_min = (t - t0).total_seconds() / 60.0
        ts_min.append(t_min)
        ns_vals.append(lat_span / 2.0)   # Halbausdehnung N-S
        ew_vals.append(lon_span / 2.0)   # Halbausdehnung E-W

    rate_ns = _linreg_slope(ts_min, ns_vals)
    rate_ew = _linreg_slope(ts_min, ew_vals)

    # Cap: ±0.3 km/min (physikalisches Maximum für konvektive Zellen)
    cap = 0.3
    return (max(-cap, min(cap, rate_ns)), max(-cap, min(cap, rate_ew)))


def _predict_polygon(
    contour_geo: list,
    cell_lat: float, cell_lon: float,
    forecast_lat: float, forecast_lon: float,
    scale_ns: float, scale_ew: float,
) -> list:
    """Verschiebt und skaliert das aktuelle Polygon zur vorhergesagten Position.

    Jeder Polygon-Punkt wird:
      1. Relativ zum aktuellen Zellzentrum berechnet
      2. Richtungsabhängig skaliert (N-S ≠ E-W)
      3. Zum vorhergesagten Zentrum verschoben

    neues_pt = forecast_zentrum + scale × (pt - aktuelles_zentrum)

    Gibt [[lon, lat], ...] zurück (GeoJSON-Format).
    """
    source = contour_geo
    if (
        len(source) > 1
        and source[0][0] == source[-1][0]
        and source[0][1] == source[-1][1]
    ):
        source = source[:-1]

    result = []
    for pt in source:
        pt_lon, pt_lat = pt[0], pt[1]
        rel_lat = (pt_lat - cell_lat) * scale_ns
        rel_lon = (pt_lon - cell_lon) * scale_ew
        result.append([forecast_lon + rel_lon, forecast_lat + rel_lat])
    return result


def _forecast_polygon_at_h(
    obj: dict,
    forecast_lat: float,
    forecast_lon: float,
    horizon_min: float,
) -> list:
    """Berechnet das vorhergesagte Polygon einer Zelle bei +horizon_min Minuten.

    Kombiniert:
    - Aktuelle Form (contour_geo)
    - Gemessene richtungsabhängige Wachstumsraten (rate_ns, rate_ew)
    - Vorhergesagte Zentrumsposition (forecast_lat/lon)

    Gibt das vorhergesagte Polygon zurück, oder [] wenn nicht berechenbar.
    """
    contour = obj.get("contour_geo") or []
    if len(contour) < 3:
        return []

    cell_lat = float(obj.get("lat") or 0)
    cell_lon = float(obj.get("lon") or 0)

    # Aktuelle Halbausdehnungen
    history = obj.get("history") or []
    last_h = history[-1] if history else {}
    half_ns = max(float(last_h.get("lat_span_km") or 0) / 2.0, 0.01)
    half_ew = max(float(last_h.get("lon_span_km") or 0) / 2.0, 0.01)

    # Gemessene Wachstumsraten
    rate_ns, rate_ew = _directional_growth_rates(obj)

    # Skalierungsfaktoren bei +horizon_min
    scale_ns = max(0.1, (half_ns + rate_ns * horizon_min) / half_ns)
    scale_ew = max(0.1, (half_ew + rate_ew * horizon_min) / half_ew)

    return _predict_polygon(
        contour, cell_lat, cell_lon,
        forecast_lat, forecast_lon,
        scale_ns, scale_ew,
    )


def _cell_survival_fraction(obj: dict, horizon_min: float) -> float:
    """P-T06: Geschätzter Anteil der Zell-Lebenskraft bei +horizon_min Minuten.

    1.0 = unverändert / wachsend / verstärkend → kein Abzug.
    →0  = Zelle löst sich auf, bevor sie den Ort erreicht.

    Grundlage: intensity_tendency ("schwaecher") und size_tendency ("schrumpft");
    ML-Feinjustage über delta_core_ratio_pred (negativ = Kern schwächt sich ab).
    Exponentieller Zerfall mit konfigurierbarer Halbwertszeit.
    """
    try:
        import runtime_config as _rc
        _HL = float(_rc.get("CELL_DECAY_HALF_LIFE_MIN", 25.0))
    except Exception:
        try:
            from config import CELL_DECAY_HALF_LIFE_MIN as _HL
        except Exception:
            _HL = 25.0
    intens = str(obj.get("intensity_tendency", "stabil"))
    size = str(obj.get("size_tendency", "stabil"))
    weakening = (intens == "schwaecher")
    shrinking = (size == "schrumpft")
    if not weakening and not shrinking:
        return 1.0
    half_life = float(_HL)
    if not (weakening and shrinking):
        half_life *= 2.0  # nur ein Signal → langsamerer Zerfall
    try:
        dc = float(obj.get("delta_core_ratio_pred", 0.0) or 0.0)
    except (TypeError, ValueError):
        dc = 0.0
    if dc < 0:
        half_life = max(5.0, half_life * (1.0 + dc))  # dc∈(-1,0) → kürzere HWZ
    h = max(0.0, float(horizon_min))
    return 0.5 ** (h / max(1.0, half_life))


def _survival_allows(obj: dict, horizon_min: float):
    """P-T06: (allowed, survival_frac). allowed=False → Treffer unterdrücken,
    weil sich die Zelle voraussichtlich vor dem Ort auflöst.
    Konfig über runtime_overrides.json überschreibbar."""
    try:
        import runtime_config as _rc
        _enabled = bool(_rc.get("CELL_DECAY_SUPPRESS_ENABLED", True))
        _min = float(_rc.get("CELL_SURVIVAL_MIN_FRAC", 0.35))
    except Exception:
        try:
            from config import (
                CELL_DECAY_SUPPRESS_ENABLED as _enabled,
                CELL_SURVIVAL_MIN_FRAC as _min,
            )
        except Exception:
            _enabled, _min = True, 0.35
    frac = _cell_survival_fraction(obj, horizon_min)
    if not _enabled:
        return True, frac
    return (frac >= float(_min)), frac


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

            cell_id   = obj.get("id")
            # B78-FIX: speed_kmh aus obj übernehmen — bereits korrekt mit
            # UPSCALE_FACTOR skaliert von object_tracking.py.
            # Fallback: vx/vy-Betrag mit Skalierungsfaktor umrechnen.
            _precomp_spd = obj.get("speed_kmh")
            if _precomp_spd is not None:
                speed_kmh = float(_precomp_spd)
            else:
                # B105/P0-1: vx/vy sind ORIGINAL-px/Frame → direkt PX_TO_KMH, kein /UF.
                vx = float(obj.get("vx") or 0.0)
                vy = float(obj.get("vy") or 0.0)
                try:
                    from config import speed_kmh_from_px as _spd_fn_lc
                    speed_kmh = _spd_fn_lc(vx, vy)
                except ImportError:
                    speed_kmh = math.hypot(vx, vy) * _PX_TO_KMH

            # ── Typ 1: CURRENT ────────────────────────────────────────────
            # Abstand Ort → nächster Polygon-Punkt (0 wenn Ort im Polygon).
            # Fallback auf Zentrum-Distanz wenn kein Polygon verfügbar.
            _contour = obj.get("contour_geo") or []
            if len(_contour) >= 3:
                d_now = _min_dist_to_polygon_km(loc_lat, loc_lon, _contour)
            else:
                d_now = _haversine_km(loc_lat, loc_lon, o_lat, o_lon)
            if d_now <= radius:
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

                    # Vorhergesagtes Polygon bei +h min (richtungsabhängig skaliert).
                    _fpoly_s = _forecast_polygon_at_h(obj, fy_f, fx_f, float(h))
                    if _fpoly_s:
                        # Polygon-basierter Check: Distanz Ort → vorhergesagtes Polygon
                        _d_poly_s = _min_dist_to_polygon_km(loc_lat, loc_lon, _fpoly_s)
                        _hit_s = _d_poly_s <= extended_r
                    else:
                        # Fallback: kein Polygon verfügbar
                        _hit_s = d <= extended_r
                    if _hit_s:
                        # P-T06: Überlebensprüfung (current-Hits sind nicht betroffen).
                        _ok_surv, _surv = _survival_allows(obj, float(h))
                        if _ok_surv:
                            hits[h] = {
                                "hit_type":    "slow_approach",
                                "color":       "#f97316",  # Orange: Starkregenpotential
                                "cell_id":     cell_id,
                                "distance_km": round(d, 3),
                                "speed_kmh":   round(speed_kmh, 1),
                                "survival_frac": round(_surv, 2),
                                "intensity_tendency": obj.get("intensity_tendency", "stabil"),
                                "size_tendency": obj.get("size_tendency", "stabil"),
                            }
                        else:
                            try:
                                from debug_utils import debug_log as _dlog_s
                                _dlog_s(
                                    f"[LOCATIONS] P-T06: '{name}' slow-Hit h={h} "
                                    f"unterdrückt (Zelle {cell_id} löst sich auf, "
                                    f"survival={_surv:.2f})"
                                )
                            except Exception:
                                pass

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

                    # Vorhergesagtes Polygon bei +h min (richtungsabhängig skaliert).
                    _fpoly_f = _forecast_polygon_at_h(obj, fy_f, fx_f, float(h))
                    if _fpoly_f:
                        _d_poly_f = _min_dist_to_polygon_km(loc_lat, loc_lon, _fpoly_f)
                        _hit_f = _d_poly_f <= radius
                    else:
                        _hit_f = d <= radius
                    if _hit_f:
                        # P-T06: Überlebensprüfung (current-Hits sind nicht betroffen).
                        _ok_surv, _surv = _survival_allows(obj, float(h))
                        if _ok_surv:
                            hits[h] = {
                                "hit_type":    "forecast",
                                "color":       colors.get(h) or colors.get(str(h), "#888888"),
                                "cell_id":     cell_id,
                                "distance_km": round(d, 3),
                                "speed_kmh":   round(speed_kmh, 1),
                                "survival_frac": round(_surv, 2),
                                "intensity_tendency": obj.get("intensity_tendency", "stabil"),
                                "size_tendency": obj.get("size_tendency", "stabil"),
                            }
                        else:
                            try:
                                from debug_utils import debug_log as _dlog_f
                                _dlog_f(
                                    f"[LOCATIONS] P-T06: '{name}' forecast-Hit h={h} "
                                    f"unterdrückt (Zelle {cell_id} löst sich auf, "
                                    f"survival={_surv:.2f})"
                                )
                            except Exception:
                                pass

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
