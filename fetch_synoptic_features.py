# fetch_synoptic_features.py
"""
500-hPa-Großwetterlage via Open-Meteo icon_global.

Synoptische Lage ist der wichtigste Faktor für wiederkehrende Zugbahnen.
Gleiche Großwetterlage -> ähnliche Zugbahnen -> das Modell lernt das.

Features:
  z500_dam         – Geopotential 500 hPa in dam (Trog ~520, Rücken ~580)
  wind_500_speed   – Windgeschwindigkeit 500 hPa (km/h)
  wind_500_dir_cos – cos(Windrichtung 500 hPa)
  wind_500_dir_sin – sin(Windrichtung 500 hPa)

API: https://api.open-meteo.com/en/docs/pressure-level-api
Cache TTL: 3600 s (icon_global alle 6 h)
"""
from __future__ import annotations
import json
import os
from math import cos, radians, sin
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from config import SAVE_PATHS
from debug_utils import debug_log, log_api_failure, log_http_response
from api_cache import cache_key, cache_get, cache_set, get_ttl

_URL     = "https://api.open-meteo.com/v1/forecast"
_MODEL   = "icon_global"
_PARAMS = "geopotential_height_500hPa,wind_speed_500hPa,wind_direction_500hPa"
_TZ      = "Europe/Vienna"
_TIMEOUT = 15


_DEFAULT = {
    "z500_dam":        560.0,
    "wind_500_speed":   20.0,
    "wind_500_dir_cos": 0.0,
    "wind_500_dir_sin": 1.0,
}


def _nearest_hour(ref_ts_str: str | None = None) -> str:
    """
    Gibt die volle Stunde des Referenz-Zeitstempels als ISO-String zurück.
    Falls ref_ts_str angegeben (Format YYYY-MM-DD_HH-MM-SS oder ähnlich):
      Aufnahme-Zeitstempel parsen und auf volle Stunde runden (Europe/Vienna).
    Fallback: aktuelle Systemzeit.
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


def _parse(loc, target):
    h = loc.get("hourly", {})
    times = h.get("time", [])
    idx = times.index(target) if (times and target in times) else 0

    g = h.get("geopotential_height_500hPa", [])
    s = h.get("wind_speed_500hPa", [])
    d = h.get("wind_direction_500hPa", [])

    gv = g[idx] if idx < len(g) else None
    sv = s[idx] if idx < len(s) else None
    dv = d[idx] if idx < len(d) else None

    if None in (gv, sv, dv):
        return dict(_DEFAULT)

    dr = radians(float(dv))
    return {
        "z500_dam":        round(float(gv) / 10.0, 1),
        "wind_500_speed":  round(float(sv), 1),
        "wind_500_dir_cos": round(cos(dr), 4),
        "wind_500_dir_sin": round(sin(dr), 4),
    }


def assign_synoptic_features(objects, timestamp):
    """500-hPa-Felder für alle Objekte in einem Bulk-Request."""
    valid = [(i, o) for i, o in enumerate(objects)
             if o.get("lat") is not None and o.get("lon") is not None]
    valid_idx = {i for i, _ in valid}
    for i, o in enumerate(objects):
        if i not in valid_idx:
            o.update(_DEFAULT)

    if not valid:
        debug_log("[SYNOPTIC] Keine Koordinaten — kein API-Call.")
        return objects

    lats = ",".join(f"{o['lat']:.4f}" for _, o in valid)
    lons = ",".join(f"{o['lon']:.4f}" for _, o in valid)
    url = (f"{_URL}?latitude={lats}&longitude={lons}"
           f"&hourly={_PARAMS}&models={_MODEL}&timezone={_TZ}&forecast_days=1")

    t = _nearest_hour(timestamp)
    ck = cache_key("openmeteo:synoptic_500",
                   [(o["lat"], o["lon"]) for _, o in valid], t, _PARAMS)
    cached = cache_get(ck, ttl_seconds=get_ttl("openmeteo_synoptic", 3600))
    if cached is not None:
        debug_log(f"[SYNOPTIC] Cache-HIT {len(valid)} Objekte.")
        data = cached
    else:
        try:
            import time as _t_syn
            _t0_syn = _t_syn.monotonic()
            from http_retry import retry_get as _rg_syn
            r = _rg_syn(url, timeout=_TIMEOUT, service="Open-Meteo-synoptic")
            _dur_syn = (_t_syn.monotonic() - _t0_syn) * 1000
            r.raise_for_status()
            data = r.json()
            log_http_response("openmeteo_synoptic", "GET", r, _dur_syn)
            cache_set(ck, data)
        except requests.exceptions.Timeout:
            log_api_failure("Open-Meteo-synoptic", url, "timeout", fallback_used=True)
            for _, o in valid:
                o.update(_DEFAULT)
            return objects
        except Exception as exc:
            log_api_failure("Open-Meteo-synoptic", url,
                            f"{type(exc).__name__}: {exc}", fallback_used=True)
            for _, o in valid:
                o.update(_DEFAULT)
            return objects

    if isinstance(data, dict):
        data = [data]
    for i, (_, o) in enumerate(valid):
        o.update(_parse(data[i] if i < len(data) else {}, t))

    debug_log(f"[SYNOPTIC] {len(valid)} Objekte mit 500-hPa versehen.")
    return objects
