# fetch_arome_openmeteo.py
"""
Holt AROME-äquivalente Gitterpunktdaten direkt auf jeder Objektkoordinate
über die Open-Meteo API (Modell: icon_d2, 2,2 km Auflösung, deckt AT/DE/CH ab).

Damit entfällt die Abhängigkeit von der nächsten TAWES-Station (bis zu 20 km
entfernt). TAWES-Beobachtungswerte bleiben als eigene Features erhalten —
AROME ist eine ergänzende Modell-Perspektive.

Neue Features je Objekt:
  arome_t2m       — Temperatur 2 m (°C)
  arome_td2m      — Taupunkt 2 m (°C)
  arome_ff10m     — Windgeschwindigkeit 10 m (km/h)
  arome_dd_cos    — cos(Windrichtung 10 m) — zyklisch kodiert
  arome_dd_sin    — sin(Windrichtung 10 m)
  arome_li        — Lifted Index (°C, negativ → Instabilität)
  arome_fl_height — Gefriergrenze (m MSL)

API-Spec: https://open-meteo.com/en/docs (models=icon_d2)
Rate-Limit: kostenlos bis 10 000 req/Tag, kein API-Key nötig.
"""

import os
import json
import time
import requests
from math import radians, cos, sin
from datetime import datetime
from zoneinfo import ZoneInfo
from debug_utils import debug_log

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
_MODEL = "icon_d2"   # DWD ICON-D2, 2,2 km, stündlich, AT/DE/CH
_PARAMS = ",".join([
    "temperature_2m",
    "dewpoint_2m",
    "wind_speed_10m",
    "wind_direction_10m",
    "lifted_index",
    "freezing_level_height",
])
_TZ = "Europe/Vienna"
_SAVE_DIR = "train_data/arome"
_RATE_SLEEP = 0.3   # Sekunden zwischen API-Calls (Rate-Limit-Schutz)

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
    """Gibt die aktuelle volle Stunde als ISO-String zurück, z. B. '2025-05-07T14:00'."""
    now = datetime.now(ZoneInfo(_TZ))
    return now.strftime("%Y-%m-%dT%H:00")


def _fetch_single(lat: float, lon: float) -> dict:
    """
    Ruft Open-Meteo icon_d2 für einen Gitterpunkt ab.
    Gibt dict mit arome_* Keys zurück; bei Fehler alle 0.0.

    API-Aufruf:
      GET https://api.open-meteo.com/v1/forecast
        ?latitude=<lat>&longitude=<lon>
        &hourly=temperature_2m,dewpoint_2m,...
        &models=icon_d2
        &timezone=Europe/Vienna
        &forecast_days=1
    """
    params = {
        "latitude": round(lat, 4),
        "longitude": round(lon, 4),
        "hourly": _PARAMS,
        "models": _MODEL,
        "timezone": _TZ,
        "forecast_days": 1,
    }
    try:
        r = requests.get(OPEN_METEO_URL, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        hourly = data.get("hourly", {})

        target_time = _nearest_hour_str()
        times = hourly.get("time", [])
        if target_time not in times:
            debug_log(f"[AROME] Kein Slot für {target_time} in icon_d2 — verwende Index 0")
            idx = 0
        else:
            idx = times.index(target_time)

        def _val(key, default=0.0):
            vals = hourly.get(key, [])
            v = vals[idx] if idx < len(vals) else None
            return float(v) if v is not None else default

        t2m    = _val("temperature_2m")
        td2m   = _val("dewpoint_2m")
        ff10m  = _val("wind_speed_10m")
        dd_deg = _val("wind_direction_10m")
        li     = _val("lifted_index")
        fl_h   = _val("freezing_level_height")

        dd_rad = radians(dd_deg)
        return {
            "arome_t2m":       round(t2m, 2),
            "arome_td2m":      round(td2m, 2),
            "arome_ff10m":     round(ff10m, 2),
            "arome_dd_cos":    round(cos(dd_rad), 4),
            "arome_dd_sin":    round(sin(dd_rad), 4),
            "arome_li":        round(li, 2),
            "arome_fl_height": round(fl_h, 1),
        }

    except Exception as e:
        debug_log(f"[AROME] Fehler bei ({lat:.3f},{lon:.3f}): {e}")
        return dict(_DEFAULT)


def assign_arome_to_objects(objects: list, timestamp: str) -> list:
    """
    Holt AROME icon_d2 Werte für alle Objekte und schreibt sie ins dict.
    Speichert Ergebnis in train_data/arome/<timestamp>.json.

    Parameter
    ---------
    objects   : Liste der aktuellen Objekte mit "lat" und "lon"
    timestamp : Aktueller Zeitstempel (Format YYYY-MM-DD_HH-MM-SS)
    """
    os.makedirs(_SAVE_DIR, exist_ok=True)
    results = {}

    for obj in objects:
        lat = obj.get("lat")
        lon = obj.get("lon")
        obj_id = obj.get("id")
        if lat is None or lon is None or obj_id is None:
            obj.update(_DEFAULT)
            continue

        arome_vals = _fetch_single(lat, lon)
        obj.update(arome_vals)
        results[obj_id] = arome_vals
        time.sleep(_RATE_SLEEP)

    out_path = os.path.join(_SAVE_DIR, f"{timestamp}.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    debug_log(f"[AROME] Daten gespeichert: {out_path} ({len(results)} Objekte)")

    return objects
