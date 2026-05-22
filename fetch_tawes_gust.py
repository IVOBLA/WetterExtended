# fetch_tawes_gust.py
"""
Einzige TAWES-Datenquelle für WetterExtended.
Holt alle Kärntner GeoSphere-TAWES-Stationen (tawes-v1-10min) mit
vollständigem Parametersatz. Cache TTL = 600 s (Aktualisierungsintervall
TAWES = 10 min). Dual-Format-Output: kompatibel mit max_gust_near()
und weather_api.get_weather_data().
"""
import math
import requests
from debug_utils import debug_log, log_api_call, log_api_failure
from api_cache import cache_key, cache_get, cache_set

_BASE_URL = "https://dataset.api.hub.geosphere.at/v1/station/current/tawes-v1-10min"
_TIMEOUT  = 15
_TTL      = 600   # 10 Minuten — entspricht TAWES-Aktualisierungsintervall


def _get_station_ids() -> str:
    """Station-IDs aus runtime_config (überschreibbar im Admin-Panel)."""
    try:
        import runtime_config
        from config import TAWES_GUST_STATION_IDS
        return runtime_config.get("TAWES_GUST_STATION_IDS", TAWES_GUST_STATION_IDS)
    except Exception:
        return "11275,11218,11234,11206,11227,11235,11222,11273,11232,11259,11216,11349,11086,11255,11331,8989078,11217,11260,11215,11262,11278,11272,11229,11237,11213,11265,11257,11225,11228,8989076,11214,11330,11301,11315,11320,11350"


def _get_params() -> str:
    """Parameter-String aus runtime_config (überschreibbar im Admin-Panel)."""
    try:
        import runtime_config
        from config import TAWES_PARAMS
        return runtime_config.get("TAWES_PARAMS", TAWES_PARAMS)
    except Exception:
        return "RR,DD,FF,FFX,GLOW,P,RF,TL,TP"


def _safe_float(v, default=0.0):
    """Wandelt einen Wert sicher in float um. Gibt default zurück wenn None oder 0 bei Drucksensoren."""
    if v is None:
        return default
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


def _extract_param(params_raw: dict, key: str):
    """Liest einen Parameter aus dem GeoSphere-TAWES-Response-Dict."""
    entry = params_raw.get(key, {})
    if isinstance(entry, dict):
        data = entry.get("data", [None])
        v = data[0] if data else None
    else:
        v = entry
    return v


def fetch_tawes_stations() -> list:
    """
    Holt alle konfigurierten Kärntner TAWES-Stationen von GeoSphere.
    Cached für 10 Minuten (TAWES-Aktualisierungsintervall).

    Rückgabe: Liste von Station-Dicts mit DUAL-FORMAT:
    - Uppercase-Keys (TL, FF, FFX, RR, ...): raw-Werte in SI-Einheiten
      → für cloud_height_from_eumetview.py, weather_api.py
    - Lowercase-Keys (ffx_kmh, ff_kmh, rr_mm, tl_c):
      → für max_gust_near()
    """
    _station_ids = _get_station_ids()
    _params      = _get_params()
    ck = cache_key("geosphere:tawes_all", _station_ids, _params)
    cached = cache_get(ck, ttl_seconds=_TTL)
    if cached is not None:
        debug_log(f"[TAWES] Cache-HIT — {len(cached)} Stationen, kein HTTP-Request")
        return cached

    url = (
        f"{_BASE_URL}"
        f"?parameters={_params}"
        f"&station_ids={_station_ids}"
        f"&output_format=geojson"
    )

    try:
        import time as _t_tawes
        _t0_tawes = _t_tawes.monotonic()
        r = requests.get(url, timeout=_TIMEOUT, headers={"Accept": "application/json"})
        r.raise_for_status()
        log_api_call("geosphere_tawes", url, r.status_code,
                     duration_ms=(_t_tawes.monotonic() - _t0_tawes) * 1000)
        data = r.json()
    except requests.exceptions.Timeout:
        log_api_failure("geosphere_tawes", url, "timeout", fallback_used=True)
        return []
    except requests.exceptions.HTTPError as exc:
        status = getattr(exc.response, "status_code", None) or 0
        log_api_call("geosphere_tawes", url, status)
        log_api_failure("geosphere_tawes", url, f"http-error: {exc}",
                        fallback_used=True, http_status=status)
        return []
    except Exception as exc:
        log_api_call("geosphere_tawes", url, 0)
        log_api_failure("geosphere_tawes", url, f"{type(exc).__name__}: {exc}",
                        fallback_used=True)
        return []

    out = []
    for feat in data.get("features", []):
        props  = feat.get("properties", {})
        geom   = feat.get("geometry",   {})
        coords = geom.get("coordinates", [0, 0])
        pr     = props.get("parameters", {})

        station_id   = str(props.get("station", "?"))
        station_name = str(props.get("name", f"Station {station_id}"))
        lon          = float(coords[0]) if coords else 0.0
        lat          = float(coords[1]) if len(coords) > 1 else 0.0

        if lat == 0.0 or lon == 0.0:
            debug_log(f"[TAWES] Station {station_id} ohne Koordinaten — übersprungen")
            continue

        # Rohe SI-Werte
        raw_rr   = _extract_param(pr, "RR")
        raw_dd   = _extract_param(pr, "DD")
        raw_ff   = _extract_param(pr, "FF")
        raw_ffx  = _extract_param(pr, "FFX")
        raw_glow = _extract_param(pr, "GLOW")
        raw_p    = _extract_param(pr, "P")
        raw_rf   = _extract_param(pr, "RF")
        raw_tl   = _extract_param(pr, "TL")
        raw_tp   = _extract_param(pr, "TP")

        # P=0 ist Sensorausfall — als None behandeln (wie weather_api.py)
        p_val = _safe_float(raw_p) if raw_p not in (None, 0, "0") else None

        out.append({
            # ── Stationsmetadaten ──────────────────────────────────────────
            "station_id": station_id,
            "name":       station_name,
            "lat":        lat,
            "lon":        lon,
            # ── Uppercase-Format (SI-Einheiten) — weather_api.py-kompatibel ─
            "RR":   round(_safe_float(raw_rr),  3),
            "DD":   round(_safe_float(raw_dd),  0),
            "FF":   round(_safe_float(raw_ff),  2),   # m/s
            "FFX":  round(_safe_float(raw_ffx), 2),   # m/s
            "GLOW": round(_safe_float(raw_glow), 1),
            "P":    p_val,
            "RF":   round(_safe_float(raw_rf),  1),
            "TL":   round(_safe_float(raw_tl),  1),   # °C
            "TP":   round(_safe_float(raw_tp),  1),   # °C
            # ── Lowercase km/h-Format — max_gust_near()-kompatibel ─────────
            "ffx_kmh": round(_safe_float(raw_ffx) * 3.6, 1),
            "ff_kmh":  round(_safe_float(raw_ff)  * 3.6, 1),
            "rr_mm":   round(_safe_float(raw_rr),  3),
            "tl_c":    round(_safe_float(raw_tl),  1),
        })

    if not out:
        log_api_failure("geosphere_tawes", url,
                        "stations-empty: HTTP 200 aber keine Stationen mit "
                        "gültigen Koordinaten in Response",
                        fallback_used=True)
    else:
        debug_log(f"[TAWES] {len(out)} Kärntner Stationen geladen und gecacht")

    cache_set(ck, out)
    return out


def max_gust_near(lat: float, lon: float,
                  stations: list, radius_km: float = 30.0) -> float:
    """
    Gibt den maximalen gemessenen Böenwert (km/h) im radius_km-Umkreis zurück.
    Nutzt das `ffx_kmh`-Feld der Station-Dicts.
    """
    max_gust = 0.0
    for s in stations:
        slat = s.get("lat", 0.0)
        slon = s.get("lon", 0.0)
        dlat = math.radians(slat - lat)
        dlon = math.radians(slon - lon)
        a    = (math.sin(dlat / 2) ** 2
                + math.cos(math.radians(lat))
                * math.cos(math.radians(slat))
                * math.sin(dlon / 2) ** 2)
        dist_km = 6371 * 2 * math.asin(math.sqrt(a))
        if dist_km <= radius_km:
            max_gust = max(max_gust, s.get("ffx_kmh", 0.0))
    return max_gust
