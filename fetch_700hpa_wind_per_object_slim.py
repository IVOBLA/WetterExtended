# fetch_700hpa_wind_per_object_slim.py
"""
Holt 700 hPa Winddaten für alle Objekte eines Frames über Open-Meteo
(Modell: icon_global — einziges Modell das 700-hPa-Level liefert).

Bulk-Query: alle Zellen in einem einzigen HTTP-Request.
  1 Request/Frame statt 1 Request/Zelle × N Zellen.

API-Spec: https://open-meteo.com/en/docs
Rate-Limit: kostenlos bis 10 000 req/Tag, kein API-Key nötig.
"""

import json
import os
import requests
from math import cos, radians, sin
from datetime import datetime
from zoneinfo import ZoneInfo

from config import SAVE_PATHS
from debug_utils import debug_log, log_api_failure, log_api_call, log_http_response
from api_cache import cache_key, cache_get, cache_set, get_ttl

_OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
_MODEL   = "icon_global"   # Einziges Modell mit 700-hPa-Level
_PARAMS  = "wind_speed_700hPa,wind_direction_700hPa,wind_speed_300hPa,wind_direction_300hPa,geopotential_height_300hPa"
_TZ      = "Europe/Vienna"
_TIMEOUT = 15

_DEFAULT_WIND = {
    "wind_speed_700hPa":  0.0,
    "wind_dir_cos":       0.0,
    "wind_dir_sin":       0.0,
    "wind_speed_300hPa":  0.0,
    "wind_dir_300_cos":   0.0,
    "wind_dir_300_sin":   0.0,
    "geopotential_300hPa": 0.0,
}


def _nearest_hour_str(ref_ts_str: str | None = None) -> str:
    """
    Gibt die volle Stunde des Referenz-Zeitstempels als ISO-String zurück.
    Falls ref_ts_str angegeben (Format YYYY-MM-DD_HH-MM-SS oder ähnlich):
      Aufnahme-Zeitstempel parsen und auf volle Stunde runden.
    Fallback: aktuelle Systemzeit (Europe/Vienna).
    Beispiel-Rückgabe: '2026-05-28T14:00'
    """
    _FORMATS = (
        "%Y-%m-%d_%H-%M-%S",
        "%Y%m%d_%H%M%S",
        "%Y-%m-%dT%H:%M:%S",
    )
    if ref_ts_str:
        for fmt in _FORMATS:
            try:
                dt = datetime.strptime(ref_ts_str, fmt).replace(tzinfo=ZoneInfo(_TZ))
                return dt.strftime("%Y-%m-%dT%H:00")
            except ValueError:
                continue
    return datetime.now(ZoneInfo(_TZ)).strftime("%Y-%m-%dT%H:00")


def _parse_wind_response(loc_data: dict, target_time: str) -> dict:
    """
    Extrahiert 700-hPa-Windwerte aus einem einzelnen Locations-Eintrag.
    Gibt _DEFAULT_WIND zurück wenn Slot nicht verfügbar.
    """
    hourly = loc_data.get("hourly", {})
    times  = hourly.get("time", [])

    if target_time in times:
        idx = times.index(target_time)
    else:
        idx = 0

    speeds = hourly.get("wind_speed_700hPa", [])
    dirs   = hourly.get("wind_direction_700hPa", [])

    speed_val = speeds[idx] if idx < len(speeds) else None
    dir_val   = dirs[idx]   if idx < len(dirs)   else None

    if speed_val is None or dir_val is None:
        return dict(_DEFAULT_WIND)

    dir_rad = radians(float(dir_val))

    speeds_300 = hourly.get("wind_speed_300hPa", [])
    dirs_300   = hourly.get("wind_direction_300hPa", [])
    geo_300    = hourly.get("geopotential_height_300hPa", [])

    speed_300_val = speeds_300[idx] if idx < len(speeds_300) else None
    dir_300_val   = dirs_300[idx]   if idx < len(dirs_300)   else None
    geo_300_val   = geo_300[idx]    if idx < len(geo_300)    else None

    dir_300_rad = radians(float(dir_300_val)) if dir_300_val is not None else 0.0

    return {
        "wind_speed_700hPa":   round(float(speed_val), 2),
        "wind_dir_cos":        round(cos(dir_rad), 4),
        "wind_dir_sin":        round(sin(dir_rad), 4),
        "wind_speed_300hPa":   round(float(speed_300_val), 2) if speed_300_val is not None else 0.0,
        "wind_dir_300_cos":    round(cos(dir_300_rad), 4),
        "wind_dir_300_sin":    round(sin(dir_300_rad), 4),
        "geopotential_300hPa": round(float(geo_300_val), 1) if geo_300_val is not None else 0.0,
    }


def fetch_and_assign_700hpa_wind(objects: list, timestamp: str) -> list:
    """
    Holt 700 hPa Winddaten für alle Objekte in einem Bulk-Request.
    Speichert Ergebnis in SAVE_PATHS["wind"]/wind_<timestamp>.json.
    Objekte ohne Koordinaten erhalten Null-Werte.

    Parameter
    ---------
    objects   : Liste der aktuellen Objekte mit "lat", "lon", "id"
    timestamp : Aktueller Zeitstempel (Format YYYY-MM-DD_HH-MM-SS)
    """
    output_folder = SAVE_PATHS["wind"].rstrip("/")
    os.makedirs(output_folder, exist_ok=True)

    # Gültige Objekte mit ursprünglichem Index merken
    valid: list = [
        (i, obj)
        for i, obj in enumerate(objects)
        if obj.get("lat") is not None
        and obj.get("lon") is not None
        and obj.get("id") is not None
    ]

    # Ungültige Objekte mit Default befüllen
    valid_idxs = {i for i, _ in valid}
    for i, obj in enumerate(objects):
        if i not in valid_idxs:
            obj.update(_DEFAULT_WIND)

    if not valid:
        debug_log("[WIND] Keine Objekte mit Koordinaten — kein API-Call.")
        _save_wind_file([], output_folder, timestamp)
        return objects

    # Bulk-Request aufbauen
    lats = ",".join(f"{obj['lat']:.4f}" for _, obj in valid)
    lons = ",".join(f"{obj['lon']:.4f}" for _, obj in valid)
    bulk_url = (
        f"{_OPEN_METEO_URL}?latitude={lats}&longitude={lons}"
        f"&hourly={_PARAMS}&models={_MODEL}&timezone={_TZ}&forecast_days=1"
    )

    # --- Cache-Lookup (TTL 60 Min — icon_global alle 6 h, Werte stündlich) ---
    target_time_cache = _nearest_hour_str(timestamp)
    coord_list = [(obj["lat"], obj["lon"]) for _, obj in valid]
    ck = cache_key("openmeteo:icon_global", coord_list, target_time_cache, _PARAMS)
    cached = cache_get(ck, ttl_seconds=get_ttl("openmeteo_icon_global", 3600))
    if cached is not None:
        debug_log(f"[700hPa] Cache-HIT — kein HTTP-Request ({len(valid)} Objekte).")
        data = cached
    else:
        import time as _t_wind
        _t0_wind = _t_wind.monotonic()
        try:
            from http_retry import retry_get
            r = retry_get(bulk_url, service="Open-Meteo-700hPa",
                          breaker_service="openmeteo_icon_global", timeout=10)  # B153
            _dur_wind = (_t_wind.monotonic() - _t0_wind) * 1000
            data = r.json()
            log_http_response(
                service="openmeteo_icon_global",
                method="GET",
                response=r,
                duration_ms=_dur_wind,
            )
            cache_set(ck, data)
        except requests.exceptions.Timeout:
            log_api_failure("Open-Meteo-icon_global", bulk_url, "timeout", fallback_used=True)
            log_api_call("openmeteo_icon_global", bulk_url, 408,
                         duration_ms=(_t_wind.monotonic() - _t0_wind) * 1000)
            for _, obj in valid:
                obj.update(_DEFAULT_WIND)
            return objects
        except requests.exceptions.HTTPError as exc:
            status = getattr(exc.response, "status_code", None)
            log_api_failure("Open-Meteo-icon_global", bulk_url,
                            f"http-{status}", fallback_used=True, http_status=status)
            for _, obj in valid:
                obj.update(_DEFAULT_WIND)
            return objects
        except Exception as exc:
            log_api_failure("Open-Meteo-icon_global", bulk_url,
                            f"{type(exc).__name__}: {exc}", fallback_used=True)
            for _, obj in valid:
                obj.update(_DEFAULT_WIND)
            return objects

    # Response normalisieren
    if isinstance(data, dict):
        data = [data]

    target_time = _nearest_hour_str(timestamp)
    wind_records: list = []

    for loc_idx, (_, obj) in enumerate(valid):
        if loc_idx >= len(data):
            obj.update(_DEFAULT_WIND)
            debug_log(f"[WIND] Fehlende Response für Objekt {obj.get('id')} — Default.")
            continue
        wind_vals = _parse_wind_response(data[loc_idx], target_time)
        obj.update(wind_vals)
        wind_records.append({"id": obj.get("id"), **wind_vals})

    # Stille Datenfehler: wenn ALLE Objekte Default-Windwerte haben →
    # API hat HTTP 200 geliefert aber keine gültigen Werte im Ziel-Zeitslot
    if wind_records and all(
        r.get("wind_speed_700hPa", 0.0) == 0.0
        and r.get("wind_dir_cos", 0.0) == 0.0
        for r in wind_records
    ):
        log_api_failure("Open-Meteo-700hPa", bulk_url,
                        "wind_speed_700hPa: alle Werte None/0 im Ziel-Zeitslot — "
                        "icon_global liefert keine Daten für diesen Zeitraum",
                        fallback_used=True)

    _save_wind_file(wind_records, output_folder, timestamp)
    debug_log(f"[WIND] Bulk-Request OK: {len(valid)} Objekte in 1 API-Call.")
    return objects


def _save_wind_file(records: list, folder: str, timestamp: str) -> None:
    path = os.path.join(folder, f"wind_{timestamp}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2)
        debug_log(f"[WIND] Gespeichert: {path} ({len(records)} Einträge)")
    except Exception as exc:
        debug_log(f"[WIND] Fehler beim Speichern von {path}: {exc}")


# ---------------------------------------------------------------------------
# Einzelabfrage (rückwärtskompatibel, z. B. für reprocess.py)
# ---------------------------------------------------------------------------

def get_700hpa_wind(lat: float, lon: float) -> tuple:
    """
    Einzelabfrage für einen Koordinaten-Punkt.
    Rückgabe: (speed, cos(dir), sin(dir)) oder (None, None, None) bei Fehler.
    """
    url = (
        f"{_OPEN_METEO_URL}?latitude={lat:.4f}&longitude={lon:.4f}"
        f"&hourly={_PARAMS}&models={_MODEL}&timezone={_TZ}&forecast_days=1"
    )
    import time as _t_wind_single
    _t0_single = _t_wind_single.monotonic()
    try:
        from http_retry import retry_get
        r = retry_get(url, service="Open-Meteo-700hPa-single", timeout=10)
        _dur_single = (_t_wind_single.monotonic() - _t0_single) * 1000
        data = r.json()
        log_http_response(
            service="openmeteo_icon_global",
            method="GET",
            response=r,
            duration_ms=_dur_single,
        )
        wind = _parse_wind_response(data, _nearest_hour_str())
        return (
            wind["wind_speed_700hPa"],
            wind["wind_dir_cos"],
            wind["wind_dir_sin"],
        )
    except Exception as exc:
        log_api_failure("Open-Meteo-700hPa", url,
                        f"{type(exc).__name__}: {exc}", fallback_used=True)
        debug_log(f"[WIND] Einzelabfrage Fehler bei ({lat}, {lon}): {exc}")
        return None, None, None
