"""
Atmosphärisches Monitoring für feste Referenzpunkte in Kärnten.
Wird alle 30 Minuten vom Scheduler aufgerufen, unabhängig von erkannten Zellen.
Daten werden in train_data/evaluation/atmosphere_latest.json gespeichert
und über /api/atmosphere im Admin-Panel angezeigt.
"""

import json
import os
import requests
from datetime import datetime, timezone
from math import atan2, cos, pi, radians, sin
from zoneinfo import ZoneInfo

from config import LOCATIONS_WATCHLIST, SAVE_PATHS
from debug_utils import debug_log, log_api_failure
import runtime_config

_OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
_TZ             = "Europe/Vienna"
_TIMEOUT        = 15
_OUT_FILE       = os.path.join(
    SAVE_PATHS.get("evaluation", "train_data/evaluation/").rstrip("/"),
    "atmosphere_latest.json",
)

# icon_d2 liefert keinen nativen lifted_index — nur regional verfügbare Parameter
_AROME_PARAMS = ",".join([
    "temperature_2m", "dewpoint_2m",
    "wind_speed_10m", "wind_direction_10m",
    "freezing_level_height",
])
_WIND_PARAMS = "wind_speed_700hPa,wind_direction_700hPa"
# LI kommt von GFS Global — DWD ICON (d2/eu/global) liefert lifted_index nicht
_LI_PARAMS = "lifted_index"
_LI_MODEL  = "gfs_seamless"


def _nearest_hour_str() -> str:
    return datetime.now(ZoneInfo(_TZ)).strftime("%Y-%m-%dT%H:00")


def _extract_slot(hourly: dict, key: str, target: str) -> float:
    times = hourly.get("time", [])
    vals  = hourly.get(key, [])
    idx   = times.index(target) if target in times else 0
    v = vals[idx] if idx < len(vals) else None
    return float(v) if v is not None else 0.0


def _bulk_get(url: str, label: str) -> list | None:
    """HTTP GET, normalisiert Response zu Liste."""
    try:
        r = requests.get(url, timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        return [data] if isinstance(data, dict) else data
    except requests.exceptions.Timeout:
        log_api_failure(label, url, "timeout", fallback_used=True)
    except requests.exceptions.HTTPError as exc:
        status = getattr(exc.response, "status_code", None)
        log_api_failure(label, url, f"http-{status}", fallback_used=True, http_status=status)
    except Exception as exc:
        log_api_failure(label, url, f"{type(exc).__name__}: {exc}", fallback_used=True)
    return None


def _gewitterpotenzial(li: float) -> str:
    if li < -3.0:
        return "hoch"
    if li < -1.0:
        return "mäßig"
    return "niedrig"


def fetch_atmospheric_snapshot() -> dict:
    """
    Holt atmosphärische Werte für alle Orte in LOCATIONS_WATCHLIST.
    Gibt das Ergebnis-Dict zurück und speichert es in atmosphere_latest.json.
    """
    locations = runtime_config.get("LOCATIONS_WATCHLIST", LOCATIONS_WATCHLIST)
    if not locations:
        debug_log("[ATMOSPHERE] LOCATIONS_WATCHLIST leer — übersprungen.")
        return {}

    target_time = _nearest_hour_str()
    lats = ",".join(f"{loc['lat']:.4f}" for loc in locations)
    lons = ",".join(f"{loc['lon']:.4f}" for loc in locations)

    # --- AROME bulk (icon_d2) ---
    arome_url = (
        f"{_OPEN_METEO_URL}?latitude={lats}&longitude={lons}"
        f"&hourly={_AROME_PARAMS}&models=icon_d2&timezone={_TZ}&forecast_days=1"
    )
    arome_data = _bulk_get(arome_url, "Open-Meteo-Atmosphere-AROME")

    # --- 700 hPa Wind bulk (icon_global) ---
    wind_url = (
        f"{_OPEN_METEO_URL}?latitude={lats}&longitude={lons}"
        f"&hourly={_WIND_PARAMS}&models=icon_global&timezone={_TZ}&forecast_days=1"
    )
    wind_data = _bulk_get(wind_url, "Open-Meteo-Atmosphere-700hPa")

    # --- Lifted Index bulk (GFS Global) ---
    li_url = (
        f"{_OPEN_METEO_URL}?latitude={lats}&longitude={lons}"
        f"&hourly={_LI_PARAMS}&models={_LI_MODEL}&timezone={_TZ}&forecast_days=1"
    )
    li_data = _bulk_get(li_url, "Open-Meteo-Atmosphere-LI")

    # --- Datenqualitäts-Check: stille None-Fehler sichtbar machen ---
    def _all_none(dataset, key):
        if not dataset:
            return False  # bereits durch _bulk_get als Fehler geloggt
        sample = dataset[0].get("hourly", {}).get(key, [])
        return len(sample) > 0 and all(v is None for v in sample[:6])

    if _all_none(arome_data, "temperature_2m"):
        log_api_failure(
            "Open-Meteo-Atmosphere-AROME",
            arome_url,
            "temperature_2m: alle Werte None — icon_d2 liefert Parameter nicht",
            fallback_used=True,
        )
    if _all_none(wind_data, "wind_speed_700hPa"):
        log_api_failure(
            "Open-Meteo-Atmosphere-700hPa",
            wind_url,
            "wind_speed_700hPa: alle Werte None — icon_global liefert Parameter nicht",
            fallback_used=True,
        )
    if _all_none(li_data, "lifted_index"):
        log_api_failure(
            "Open-Meteo-Atmosphere-LI",
            li_url,
            f"lifted_index: alle Werte None — Modell '{_LI_MODEL}' liefert Parameter nicht",
            fallback_used=True,
        )

    result_locations = []
    for i, loc in enumerate(locations):
        name = loc.get("name", f"Ort_{i}")
        lat  = loc.get("lat",  0.0)
        lon  = loc.get("lon",  0.0)

        # AROME-Werte
        t2m = td2m = ff10m = li = fl_h = 0.0
        if arome_data and i < len(arome_data):
            h = arome_data[i].get("hourly", {})
            t2m   = _extract_slot(h, "temperature_2m",      target_time)
            td2m  = _extract_slot(h, "dewpoint_2m",          target_time)
            ff10m = _extract_slot(h, "wind_speed_10m",       target_time)
            fl_h  = _extract_slot(h, "freezing_level_height",target_time)

        # 700 hPa Wind (ICON Global)
        w_speed = w_dir_cos = w_dir_sin = 0.0
        if wind_data and i < len(wind_data):
            h = wind_data[i].get("hourly", {})
            w_speed = _extract_slot(h, "wind_speed_700hPa",    target_time)
            w_dir   = _extract_slot(h, "wind_direction_700hPa",target_time)
            rad     = radians(w_dir)
            w_dir_cos = round(cos(rad), 4)
            w_dir_sin = round(sin(rad), 4)
        # Lifted Index von GFS Global (icon_d2/eu/global liefern kein LI)
        if li_data and i < len(li_data):
            h_li = li_data[i].get("hourly", {})
            li = _extract_slot(h_li, "lifted_index", target_time)

        result_locations.append({
            "name":             name,
            "lat":              lat,
            "lon":              lon,
            "t2m":              round(t2m,   1),
            "td2m":             round(td2m,  1),
            "spread":           round(t2m - td2m, 1),
            "li":               round(li,    1),
            "fl_height":        round(fl_h,  0),
            "ff10m":            round(ff10m, 1),
            "wind_700hpa":      round(w_speed, 1),
            "wind_dir_cos":     w_dir_cos,
            "wind_dir_sin":     w_dir_sin,
            "potential":        _gewitterpotenzial(li),
        })

    result = {
        "ts_utc":    datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z",
        "locations": result_locations,
    }

    os.makedirs(os.path.dirname(_OUT_FILE), exist_ok=True)
    try:
        with open(_OUT_FILE, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        debug_log(f"[ATMOSPHERE] Snapshot gespeichert: {len(result_locations)} Orte")
    except Exception as exc:
        debug_log(f"[ATMOSPHERE] Speichern fehlgeschlagen: {exc}")

    return result


if __name__ == "__main__":
    import pprint
    pprint.pprint(fetch_atmospheric_snapshot())
