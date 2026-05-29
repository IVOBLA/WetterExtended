# fetch_outlook_series.py
"""
Holt die stuendliche Zeitreihe (+0..+12 h) der konvektiven Felder fuer die
Kaernten-Rasterpunkte (ATM_SNAPSHOT_LOCATIONS) und schreibt sie als
train_data/forecast/atmosphere_timeseries.json.

Schonend: Frische-Guard (kein Request wenn Datei juenger als TTL) + Batching.
Robuste Parameter-Fallback-Logik gegen Open-Meteo-400 bei unbekanntem Param.
"""

import os
import json
import time
import importlib.util
from datetime import datetime, timezone

import requests

from config import ATM_SNAPSHOT_LOCATIONS, SAVE_PATHS
from debug_utils import debug_log, log_api_failure
import runtime_config

_URL          = "https://api.open-meteo.com/v1/forecast"
_TZ           = "Europe/Vienna"
_TIMEOUT      = 25
_BATCH_SIZE   = 8
_FORECAST_H   = 13          # +0..+12 h => 13 Stundenwerte
_DEFAULT_TTL  = 30          # Minuten

_OUT_DIR = os.path.join(
    os.path.dirname(SAVE_PATHS.get("evaluation", "train_data/evaluation/").rstrip("/")),
    "forecast",
)
_OUT_FILE = os.path.join(_OUT_DIR, "atmosphere_timeseries.json")

# Vollsatz und Minimalsatz (Fallback). Reihenfolge unwichtig.
_HOURLY_FULL = ",".join([
    "cape", "convective_inhibition", "lifted_index", "precipitable_water",
    "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m",
    "wind_speed_700hPa", "wind_direction_700hPa",
    "temperature_500hPa", "temperature_700hPa", "freezing_level_height",
])
_HOURLY_MIN = ",".join([
    "cape", "lifted_index", "wind_speed_10m", "wind_direction_10m", "freezing_level_height",
])


def _ttl_min():
    try:
        return int(runtime_config.get("OUTLOOK_SERIES_TTL_MIN", _DEFAULT_TTL))
    except Exception:
        return _DEFAULT_TTL


def _is_fresh():
    if not os.path.exists(_OUT_FILE):
        return False
    age_min = (time.time() - os.path.getmtime(_OUT_FILE)) / 60.0
    return age_min < _ttl_min()


def _batches(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _request(lats, lons, hourly):
    params = {
        "latitude":  ",".join(f"{x:.4f}" for x in lats),
        "longitude": ",".join(f"{x:.4f}" for x in lons),
        "hourly":    hourly,
        "forecast_days": 2,
        "timezone":  _TZ,
    }
    r = requests.get(_URL, params=params, timeout=_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else [data]


def _series_from_point(point, start_idx):
    hourly = point.get("hourly", {}) or {}
    times = hourly.get("time", [])
    if not times:
        return []
    out = []
    for k in range(start_idx, min(start_idx + _FORECAST_H, len(times))):
        entry = {"valid": times[k], "offset_h": k - start_idx}
        for key, vals in hourly.items():
            if key == "time":
                continue
            entry[key] = vals[k] if k < len(vals) and vals[k] is not None else None
        out.append(entry)
    return out


def _now_hour_iso():
    return datetime.now().astimezone().strftime("%Y-%m-%dT%H:00")


def fetch_outlook_series(force=False):
    if not force and _is_fresh():
        debug_log("[OUTLOOK-SERIES] Cache frisch — kein Request")
        try:
            with open(_OUT_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    os.makedirs(_OUT_DIR, exist_ok=True)
    locs = list(ATM_SNAPSHOT_LOCATIONS)
    all_points = []
    for batch in _batches(locs, _BATCH_SIZE):
        lats = [float(l["lat"]) for l in batch]
        lons = [float(l["lon"]) for l in batch]
        names = [l.get("name", "") for l in batch]
        data = None
        for hourly in (_HOURLY_FULL, _HOURLY_MIN):
            try:
                data = _request(lats, lons, hourly)
                break
            except Exception as exc:
                debug_log(f"[OUTLOOK-SERIES] Request mit '{hourly[:30]}...' fehlgeschlagen: {exc}")
        if data is None:
            log_api_failure("Open-Meteo-Outlook", _URL, "all-param-sets-failed", fallback_used=True)
            continue
        target_hour = _now_hour_iso()
        for name, lat, lon, point in zip(names, lats, lons, data):
            times = (point.get("hourly", {}) or {}).get("time", [])
            start_idx = times.index(target_hour) if target_hour in times else 0
            all_points.append({
                "name": name, "lat": lat, "lon": lon,
                "series": _series_from_point(point, start_idx),
            })

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "horizon_h": _FORECAST_H - 1,
        "points": all_points,
    }
    tmp = _OUT_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    os.replace(tmp, _OUT_FILE)
    debug_log(f"[OUTLOOK-SERIES] {len(all_points)} Punkte x {_FORECAST_H} h -> {_OUT_FILE}")
    return payload


if __name__ == "__main__":
    res = fetch_outlook_series(force=True)
    print("Punkte:", len(res.get("points", [])))
