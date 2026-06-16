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
from debug_utils import debug_log, log_api_failure, log_http_response
from api_cache import cache_key, cache_get, cache_set, get_ttl

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
_GFS_URL = "https://api.open-meteo.com/v1/gfs"   # für lifted_index (icon_eu liefert null)
_MODEL = "icon_d2"
# icon_d2 liefert KEINEN lifted_index — der Parameter wird über icon_eu separat geholt.
# Quelle: https://open-meteo.com/en/docs/dwd-api (icon_d2 hourly variables).
_PARAMS = ",".join([
    "temperature_2m",
    "dewpoint_2m",
    "wind_speed_10m",
    "wind_direction_10m",
    "freezing_level_height",
])
# Sekundär-Modell für lifted_index (icon_eu liefert ihn als hourly Variable).
_MODEL_LI = "icon_eu"
_PARAMS_LI = "lifted_index"
_TZ = "Europe/Vienna"
_SAVE_DIR = SAVE_PATHS.get("arome", "train_data/arome/").rstrip("/")
_TIMEOUT = 25   # Bulk-Requests mit vielen Koordinaten brauchen Read-Toleranz

_DEFAULT = {
    "arome_t2m": 0.0,
    "arome_td2m": 0.0,
    "arome_ff10m": 0.0,
    "arome_dd_cos": 0.0,
    "arome_dd_sin": 0.0,
    "arome_li": 0.0,
    "arome_fl_height": 0.0,
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
    # arome_li wird nicht hier extrahiert — icon_d2 liefert keinen lifted_index.
    # Der Wert wird in assign_arome_to_objects() über _fetch_arome_li_via_icon_eu()
    # injiziert, oder bleibt auf _DEFAULT (0.0) falls icon_eu nicht erreichbar.
    return {
        "arome_t2m": round(_val("temperature_2m"), 2),
        "arome_td2m": round(_val("dewpoint_2m"), 2),
        "arome_ff10m": round(_val("wind_speed_10m"), 2),
        "arome_dd_cos": round(cos(dd_rad), 4),
        "arome_dd_sin": round(sin(dd_rad), 4),
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
    target_time_cache = _nearest_hour_str(timestamp)
    coord_list = [(obj["lat"], obj["lon"]) for _, obj in valid]
    ck = cache_key("openmeteo:icon_d2", coord_list, target_time_cache, _PARAMS)
    cached = cache_get(ck, ttl_seconds=get_ttl("openmeteo_icon_d2", 1800))
    if cached is not None:
        debug_log(f"[AROME] Cache-HIT — kein HTTP-Request ({len(valid)} Objekte).")
        data = cached
        _apply_data_to_objects(data, valid, objects, timestamp, bulk_url)
        return objects

    import time as _t_arome
    _t0_arome = _t_arome.monotonic()
    try:
        from http_retry import retry_get
        # B157: kanonischer Service-Name + Circuit-Breaker ("openmeteo_icon_d2").
        r = retry_get(bulk_url, service="openmeteo_icon_d2",
                      breaker_service="openmeteo_icon_d2", timeout=_TIMEOUT)
        _dur_arome = (_t_arome.monotonic() - _t0_arome) * 1000
        log_http_response("openmeteo_icon_d2", "GET", r, _dur_arome)
        data = r.json()
        cache_set(ck, data)
    except Exception as exc:
        # B157: retry_get protokolliert den Ausfall bereits unter "openmeteo_icon_d2"
        # (log_api_failure + log_api_call) und bedient den Breaker → kein Doppel-Log.
        debug_log(f"[AROME] Alle Versuche fehlgeschlagen: {exc} — Default-Werte.")
        for _, obj in valid:
            obj.update(_DEFAULT)
        _save_results({}, timestamp)
        return objects

    _apply_data_to_objects(data, valid, objects, timestamp, bulk_url)
    return objects


def _apply_data_to_objects(data, valid, objects, timestamp, bulk_url):
    """Schreibt AROME-Werte aus der API-Response/Cache in die Objekte.

    Holt lifted_index getrennt über icon_eu (icon_d2 liefert ihn nicht) und
    injiziert ihn unter arome_li. Bei Fehler bleibt arome_li auf _DEFAULT (0.0).
    """
    # Response normalisieren: Single-Object → Liste
    if isinstance(data, dict):
        data = [data]

    target_time = _nearest_hour_str(timestamp)
    results: dict = {}

    # NEU: lifted_index separat aus icon_eu (icon_d2 liefert keinen LI)
    li_map = _fetch_arome_li_via_icon_eu(valid, timestamp)

    for loc_idx, (_, obj) in enumerate(valid):
        if loc_idx >= len(data):
            obj.update(_DEFAULT)
            # LI-Injection auch im Fehlerfall (falls icon_eu separat geliefert hat)
            if obj.get("id") in li_map:
                obj["arome_li"] = li_map[obj.get("id")]
            debug_log(f"[AROME] Fehlende Response für Objekt {obj.get('id')} — Default.")
            continue
        arome_vals = _parse_location_response(data[loc_idx], target_time)
        # arome_li aus icon_eu injizieren (Default 0.0 bleibt bei Fehlschlag)
        arome_vals["arome_li"] = li_map.get(obj.get("id"), 0.0)
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


def _fetch_arome_li_via_icon_eu(valid: list, ref_ts_str: str | None = None) -> dict:
    """
    Holt lifted_index aus icon_eu (DWD ICON-EU, 7 km) — icon_d2 liefert ihn nicht.
    Returns: dict {obj_id: float} mit LI-Werten in °C (negativ = instabil).
    Bei Fehler: leeres dict, Caller behält _DEFAULT (0.0).
    """
    if not valid:
        return {}
    from api_cache import cache_key, cache_get, cache_set, get_ttl
    try:
        from api_cache import cache_get_stale
    except ImportError:
        cache_get_stale = lambda *a, **kw: None  # noqa: E731

    lats = ",".join(f"{obj['lat']:.4f}" for _, obj in valid)
    lons = ",".join(f"{obj['lon']:.4f}" for _, obj in valid)
    # GFS liefert lifted_index zuverlässig (icon_eu gibt null zurück).
    # Identische Quelle wie fetch_atmospheric_snapshot.py (_GFS_CONV_PARAMS).
    url = (
        f"{_GFS_URL}?latitude={lats}&longitude={lons}"
        f"&hourly={_PARAMS_LI}&timezone={_TZ}&forecast_days=1"
    )

    target_time = _nearest_hour_str(ref_ts_str)
    coord_list = [(obj["lat"], obj["lon"]) for _, obj in valid]
    ck = cache_key("openmeteo:icon_eu_li", coord_list, target_time, _PARAMS_LI)
    cached = cache_get(ck, ttl_seconds=get_ttl("openmeteo_icon_eu", 3600))
    if cached is not None:
        debug_log(f"[AROME-LI] icon_eu Cache-HIT ({len(valid)} Objekte).")
        data = cached
    else:
        try:
            from http_retry import retry_get
            # B157: Circuit-Breaker ("openmeteo_icon_eu_li").
            r = retry_get(url, service="openmeteo_icon_eu_li",
                          breaker_service="openmeteo_icon_eu_li", timeout=_TIMEOUT)
            data = r.json()
            cache_set(ck, data)
        except Exception as exc:
            debug_log(f"[AROME-LI] icon_eu fehlgeschlagen ({type(exc).__name__}) — versuche STALE-Cache")
            data = cache_get_stale(ck, max_stale_seconds=24*3600)
            if data is None:
                return {}

    if isinstance(data, dict):
        data = [data]

    out = {}
    for loc_idx, (_, obj) in enumerate(valid):
        if loc_idx >= len(data) or not data[loc_idx]:
            continue
        hourly = data[loc_idx].get("hourly", {})
        times = hourly.get("time", [])
        idx = times.index(target_time) if target_time in times else 0
        vals = hourly.get("lifted_index", [])
        v = vals[idx] if idx < len(vals) else None
        if v is not None:
            out[obj.get("id")] = round(float(v), 2)
    debug_log(f"[AROME-LI] icon_eu: {len(out)}/{len(valid)} Objekte mit lifted_index befüllt.")
    return out


def _save_results(results: dict, timestamp: str) -> None:
    out_path = os.path.join(_SAVE_DIR, f"{timestamp}.json")
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        debug_log(f"[AROME] Gespeichert: {out_path} ({len(results)} Objekte)")
    except Exception as exc:
        debug_log(f"[AROME] Fehler beim Speichern von {out_path}: {exc}")
