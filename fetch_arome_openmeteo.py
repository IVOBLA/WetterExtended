# fetch_arome_openmeteo.py
"""
Holt AROME-äquivalente Gitterpunktdaten für alle Objekte eines Frames
über die Open-Meteo API (Modell: icon_d2, 2,2 km, AT/DE/CH).

Bulk-Query: alle Zellen in einem einzigen HTTP-Request.
  1 Request/Frame statt 1 Request/Zelle × N Zellen.

Neue Features je Objekt:
  arome_t2m, arome_td2m, arome_ff10m, arome_dd_cos, arome_dd_sin,
  arome_li, arome_fl_height

API-Spec: https://open-meteo.com/en/docs (models=icon_d2)
Rate-Limit: kostenlos bis 10 000 req/Tag, kein API-Key nötig.
"""

import json
import os
import requests
from math import cos, radians, sin
from datetime import datetime
from zoneinfo import ZoneInfo

from config import SAVE_PATHS
from debug_utils import debug_log, log_api_failure
from api_cache import cache_key, cache_get, cache_set, get_ttl

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
_MODEL = "icon_d2"
_PARAMS = ",".join([
    "temperature_2m",
    "dewpoint_2m",
    "wind_speed_10m",
    "wind_direction_10m",
    "lifted_index",
    "freezing_level_height",
])
_TZ = "Europe/Vienna"
_SAVE_DIR = SAVE_PATHS.get("arome", "train_data/arome/").rstrip("/")
_TIMEOUT = 15   # Sekunden — etwas mehr als bei Single-Call da mehr Daten

_DEFAULT = {
    "arome_t2m": 0.0,
    "arome_td2m": 0.0,
    "arome_ff10m": 0.0,
    "arome_dd_cos": 0.0,
    "arome_dd_sin": 0.0,
    "arome_li": 0.0,
    "arome_fl_height": 0.0,
}


def _nearest_hour_str() -> str:
    """Aktuelle volle Stunde als ISO-String, z. B. '2025-05-16T14:00'."""
    return datetime.now(ZoneInfo(_TZ)).strftime("%Y-%m-%dT%H:00")


def _parse_location_response(loc_data: dict, target_time: str) -> dict:
    """
    Extrahiert AROME-Features aus einem einzelnen Locations-Eintrag der Bulk-Response.
    Gibt _DEFAULT zurück falls Slot nicht vorhanden.
    """
    hourly = loc_data.get("hourly", {})
    times = hourly.get("time", [])

    if target_time in times:
        idx = times.index(target_time)
    else:
        idx = 0  # Fallback auf ersten verfügbaren Slot

    def _val(key: str, default: float = 0.0) -> float:
        vals = hourly.get(key, [])
        v = vals[idx] if idx < len(vals) else None
        return float(v) if v is not None else default

    dd_rad = radians(_val("wind_direction_10m"))
    return {
        "arome_t2m": round(_val("temperature_2m"), 2),
        "arome_td2m": round(_val("dewpoint_2m"), 2),
        "arome_ff10m": round(_val("wind_speed_10m"), 2),
        "arome_dd_cos": round(cos(dd_rad), 4),
        "arome_dd_sin": round(sin(dd_rad), 4),
        "arome_li": round(_val("lifted_index"), 2),
        "arome_fl_height": round(_val("freezing_level_height"), 1),
    }


def assign_arome_to_objects(objects: list, timestamp: str) -> list:
    """
    Holt AROME icon_d2 Werte für alle Objekte in einem Bulk-Request.
    Schreibt Ergebnisse in train_data/arome/<timestamp>.json.
    Objekte ohne Koordinaten erhalten _DEFAULT-Werte.

    Parameter
    ---------
    objects   : Liste der aktuellen Objekte mit "lat", "lon", "id"
    timestamp : Aktueller Zeitstempel (Format YYYY-MM-DD_HH-MM-SS)
    """
    os.makedirs(_SAVE_DIR, exist_ok=True)

    # Gültige Objekte mit Index merken
    valid: list = [
        (i, obj)
        for i, obj in enumerate(objects)
        if obj.get("lat") is not None
        and obj.get("lon") is not None
        and obj.get("id") is not None
    ]

    # Ungültige Objekte mit Defaults befüllen
    valid_idxs = {i for i, _ in valid}
    for i, obj in enumerate(objects):
        if i not in valid_idxs:
            obj.update(_DEFAULT)

    if not valid:
        debug_log("[AROME] Keine Objekte mit Koordinaten — kein API-Call.")
        _save_results({}, timestamp)
        return objects

    # Bulk-Request aufbauen — komma-separierte Koordinaten
    lats = ",".join(f"{obj['lat']:.4f}" for _, obj in valid)
    lons = ",".join(f"{obj['lon']:.4f}" for _, obj in valid)
    bulk_url = (
        f"{OPEN_METEO_URL}?latitude={lats}&longitude={lons}"
        f"&hourly={_PARAMS}&models={_MODEL}&timezone={_TZ}&forecast_days=1"
    )

    # --- Cache-Lookup (TTL 30 Min — Modell-Run alle 3 h, Werte stündlich) ---
    target_time_cache = _nearest_hour_str()
    coord_list = [(obj["lat"], obj["lon"]) for _, obj in valid]
    ck = cache_key("openmeteo:icon_d2", coord_list, target_time_cache, _PARAMS)
    cached = cache_get(ck, ttl_seconds=get_ttl("openmeteo_icon_d2", 1800))
    if cached is not None:
        debug_log(f"[AROME] Cache-HIT — kein HTTP-Request ({len(valid)} Objekte).")
        data = cached
        _apply_data_to_objects(data, valid, objects, timestamp, bulk_url)
        return objects

    try:
        r = requests.get(bulk_url, timeout=_TIMEOUT)
        try:
            from debug_utils import log_api_call
            log_api_call("openmeteo_icon_d2", url=bulk_url, status_code=r.status_code)
        except Exception:
            pass
        r.raise_for_status()
        data = r.json()
        cache_set(ck, data)
    except requests.exceptions.Timeout:
        log_api_failure("Open-Meteo-icon_d2", bulk_url, "timeout", fallback_used=True)
        debug_log("[AROME] Timeout beim Bulk-Request — alle Objekte erhalten Default-Werte.")
        for _, obj in valid:
            obj.update(_DEFAULT)
        _save_results({}, timestamp)
        return objects
    except requests.exceptions.HTTPError as exc:
        status = getattr(exc.response, "status_code", None)
        log_api_failure("Open-Meteo-icon_d2", bulk_url,
                        f"http-{status}", fallback_used=True, http_status=status)
        debug_log(f"[AROME] HTTP-Fehler {status} — Default-Werte.")
        for _, obj in valid:
            obj.update(_DEFAULT)
        _save_results({}, timestamp)
        return objects
    except Exception as exc:
        log_api_failure("Open-Meteo-icon_d2", bulk_url,
                        f"{type(exc).__name__}: {exc}", fallback_used=True)
        debug_log(f"[AROME] Fehler: {exc} — Default-Werte.")
        for _, obj in valid:
            obj.update(_DEFAULT)
        _save_results({}, timestamp)
        return objects

    _apply_data_to_objects(data, valid, objects, timestamp, bulk_url)
    return objects


def _apply_data_to_objects(data, valid, objects, timestamp, bulk_url):
    """Schreibt AROME-Werte aus der API-Response/Cache in die Objekte."""
    # Response normalisieren: Single-Object → Liste
    if isinstance(data, dict):
        data = [data]

    target_time = _nearest_hour_str()
    results: dict = {}

    for loc_idx, (_, obj) in enumerate(valid):
        if loc_idx >= len(data):
            obj.update(_DEFAULT)
            debug_log(f"[AROME] Fehlende Response für Objekt {obj.get('id')} — Default.")
            continue
        arome_vals = _parse_location_response(data[loc_idx], target_time)
        obj.update(arome_vals)
        results[obj.get("id")] = arome_vals

    # Stille Datenfehler: wenn ALLE Objekte 0.0 für T2m → API liefert keinen Ziel-Zeitslot
    if results and all(v.get("arome_t2m", 0.0) == 0.0 for v in results.values()):
        log_api_failure(
            "Open-Meteo-icon_d2", bulk_url,
            "arome_t2m: alle Werte 0.0 — icon_d2 liefert keine Daten für diesen Zeitslot",
            fallback_used=True,
        )

    _save_results(results, timestamp)
    debug_log(f"[AROME] Bulk-Request OK: {len(valid)} Objekte in 1 API-Call.")


def _save_results(results: dict, timestamp: str) -> None:
    out_path = os.path.join(_SAVE_DIR, f"{timestamp}.json")
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        debug_log(f"[AROME] Gespeichert: {out_path} ({len(results)} Objekte)")
    except Exception as exc:
        debug_log(f"[AROME] Fehler beim Speichern von {out_path}: {exc}")
