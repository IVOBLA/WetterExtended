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

from config import ATM_SNAPSHOT_LOCATIONS, SAVE_PATHS
from debug_utils import debug_log, log_api_failure, log_http_response
import runtime_config

_OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
_TZ             = "Europe/Vienna"
_TIMEOUT        = 15
_OUT_FILE       = os.path.join(
    SAVE_PATHS.get("evaluation", "train_data/evaluation/").rstrip("/"),
    "atmosphere_latest.json",
)
_QUALITY_FILE   = os.path.join(
    SAVE_PATHS.get("evaluation", "train_data/evaluation/").rstrip("/"),
    "atmosphere_feature_quality.json",
)

# icon_d2 liefert keinen nativen lifted_index — nur regional verfügbare Parameter
# Open-Meteo icon_d2 AROME-Parameter — alle verifiziert, liefern echte Werte
# (sichtbar auf Atmosphäre-Seite /atmosphaere mit realen Messwerten).
# "dewpoint_2m" ist der korrekte Parametername (nicht "dew_point_2m").
_AROME_PARAMS = ",".join([
    "temperature_2m", "dewpoint_2m",
    "wind_speed_10m", "wind_direction_10m",
    "freezing_level_height",
    "cape",          # CAPE (icon_d2) — für Atmosphäre-Seite und Schwere-Proxy
])
# Erweitert um T500/T700/CIN/PW — gleicher HTTP-Request, mehr Parameter.
# Alle 4 sind in icon_global hourly verfuegbar (verifiziert gegen
# Open-Meteo API-Spec, Stand 2026-05).
_WIND_PARAMS = (
    "wind_speed_700hPa,wind_direction_700hPa,"
    "temperature_500hPa,temperature_700hPa,"
    "wind_speed_300hPa,wind_direction_300hPa,geopotential_height_300hPa"
)
_GFS_URL = "https://api.open-meteo.com/v1/gfs"
_GFS_CONV_PARAMS = (
    "lifted_index,"
    "convective_inhibition,"
    "total_column_integrated_water_vapour"
)

# Max. Locations pro Open-Meteo-Bulk-Request.
# Open-Meteo-Antwortzeit steigt überproportional → Batching hält Antwort unter _TIMEOUT.
_BATCH_SIZE = 8


def _nearest_hour_str() -> str:
    return datetime.now(ZoneInfo(_TZ)).strftime("%Y-%m-%dT%H:00")


def _extract_slot_optional(hourly: dict, key: str, target: str) -> float | None:
    times = hourly.get("time", [])
    vals  = hourly.get(key, [])
    idx   = times.index(target) if target in times else 0
    v = vals[idx] if idx < len(vals) else None
    return float(v) if v is not None else None


def _extract_slot(hourly: dict, key: str, target: str) -> float:
    v = _extract_slot_optional(hourly, key, target)
    return float(v) if v is not None else 0.0


def _rounded_or_none(value: float | None, ndigits: int = 1):
    return round(value, ndigits) if value is not None else None


def _missing_flag(value: float | None) -> int:
    return 1 if value is None else 0


def _bulk_get(url: str, label: str) -> list | None:
    """HTTP GET, normalisiert Response zu Liste."""
    import time as _t_bulk
    _t0_bulk = _t_bulk.monotonic()
    try:
        r = requests.get(url, timeout=_TIMEOUT)
        _dur_bulk = (_t_bulk.monotonic() - _t0_bulk) * 1000
        r.raise_for_status()
        data = r.json()
        log_http_response(label.lower().replace("-", "_").replace(" ", "_"),
                          "GET", r, _dur_bulk)
        return [data] if isinstance(data, dict) else data
    except requests.exceptions.Timeout:
        log_api_failure(label, url, "timeout", fallback_used=True)
    except requests.exceptions.HTTPError as exc:
        status = getattr(exc.response, "status_code", None)
        hint = " (möglicherweise ungültige Open-Meteo-Parameter)" if status == 400 else ""
        log_api_failure(
            label,
            url,
            f"http-{status}{hint}",
            fallback_used=True,
            http_status=status,
        )
    except Exception as exc:
        log_api_failure(label, url, f"{type(exc).__name__}: {exc}", fallback_used=True)
    return None


def _bulk_get_batched(url_base: str, label: str, locations: list) -> list | None:
    """
    Splittet *locations* in Batches à _BATCH_SIZE, sendet je einen Bulk-Request
    und konkateniert die Ergebnisse in der Reihenfolge der Eingabeliste.

    url_base  : URL ohne latitude= und longitude= Parameter.
    label     : Logging-Label (Batch-Nummer wird angehängt).
    locations : Liste von Dicts mit Feldern 'lat' und 'lon'.

    Rückgabe  : Konkatenierte Ergebnisliste oder None, wenn alle Batches fehlschlagen.
    """
    results: list = []
    any_ok = False
    n_batches = (len(locations) + _BATCH_SIZE - 1) // _BATCH_SIZE
    for b in range(n_batches):
        batch = locations[b * _BATCH_SIZE: (b + 1) * _BATCH_SIZE]
        lats = ",".join(f"{loc['lat']:.4f}" for loc in batch)
        lons = ",".join(f"{loc['lon']:.4f}" for loc in batch)
        url = f"{url_base}&latitude={lats}&longitude={lons}"
        data = _bulk_get(url, f"{label}-B{b + 1}")
        if data is None:
            # Einzelner Batch fehlgeschlagen → mit leeren Dicts auffüllen,
            # damit die übrigen Batches erhalten bleiben und die Index-Treue
            # zu locations[i] gewahrt ist. Leere Dicts liefern downstream 0.0.
            results.extend({} for _ in batch)
            continue
        # Weniger Antworten als Locations im Batch → mit leeren Dicts auffüllen.
        if len(data) < len(batch):
            data = list(data) + [{} for _ in range(len(batch) - len(data))]
        results.extend(data[:len(batch)])
        any_ok = True
    # Nur bei Totalausfall (kein einziger Batch ok) None — wie bisheriges Verhalten.
    return results if any_ok else None


def _gewitterpotenzial(li: float) -> str:
    if li < -3.0:
        return "hoch"
    if li < -1.0:
        return "mäßig"
    return "niedrig"



def _build_feature_quality(locations: list[dict]) -> dict:
    numeric_keys = sorted({
        k for loc in locations for k, v in loc.items()
        if isinstance(v, (int, float)) and not isinstance(v, bool) and not k.endswith("_missing")
    })
    constant_zero = []
    for key in numeric_keys:
        vals = [loc.get(key) for loc in locations if loc.get(key) is not None]
        if vals and all(float(v) == 0.0 for v in vals):
            constant_zero.append(key)
    return {
        "ts_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "constant_zero_features": constant_zero,
        "missing_counts": {
            k: sum(1 for loc in locations if loc.get(k) in (1, 1.0, True))
            for k in sorted({mk for loc in locations for mk in loc if mk.endswith("_missing")})
        },
    }

def fetch_atmospheric_snapshot() -> dict:
    """
    Holt atmosphärische Werte für alle Orte in ATM_SNAPSHOT_LOCATIONS.
    Gibt das Ergebnis-Dict zurück und speichert es in atmosphere_latest.json.
    """
    locations = runtime_config.get("ATM_SNAPSHOT_LOCATIONS", ATM_SNAPSHOT_LOCATIONS)
    if not locations:
        debug_log("[ATMOSPHERE] ATM_SNAPSHOT_LOCATIONS leer — übersprungen.")
        return {}

    target_time = _nearest_hour_str()

    # --- AROME bulk (icon_d2) — batched à _BATCH_SIZE Locations ---
    _arome_base = (
        f"{_OPEN_METEO_URL}?hourly={_AROME_PARAMS}&models=icon_d2"
        f"&timezone={_TZ}&forecast_days=1"
    )
    arome_data = _bulk_get_batched(_arome_base, "Open-Meteo-Atmosphere-AROME", locations)

    # --- 700 hPa Wind bulk (icon_global) — batched ---
    _wind_base = (
        f"{_OPEN_METEO_URL}?hourly={_WIND_PARAMS}&models=icon_global"
        f"&timezone={_TZ}&forecast_days=1"
    )
    wind_data = _bulk_get_batched(_wind_base, "Open-Meteo-Atmosphere-Pressure", locations)

    # --- GFS bulk (LI/CIN/PW) — batched ---
    _gfs_base = (
        f"{_GFS_URL}?hourly={_GFS_CONV_PARAMS}"
        f"&timezone={_TZ}&forecast_days=1"
    )
    gfs_data = _bulk_get_batched(_gfs_base, "Open-Meteo-Atmosphere-GFS", locations)

    # --- Datenqualitäts-Check: stille None-Fehler sichtbar machen ---
    def _all_none(dataset, key):
        if not dataset:
            return False  # bereits durch _bulk_get als Fehler geloggt
        sample = dataset[0].get("hourly", {}).get(key, [])
        return len(sample) > 0 and all(v is None for v in sample[:6])

    if _all_none(arome_data, "temperature_2m"):
        log_api_failure(
            "Open-Meteo-Atmosphere-AROME",
            _arome_base,
            "temperature_2m: alle Werte None — icon_d2 liefert Parameter nicht",
            fallback_used=True,
        )
    if _all_none(wind_data, "wind_speed_700hPa"):
        log_api_failure(
            "Open-Meteo-Atmosphere-Pressure",
            _wind_base,
            "wind_speed_700hPa: alle Werte None — icon_global liefert Parameter nicht",
            fallback_used=True,
        )
    # Datenqualitaets-Check Pressure-Parameter (700hPa + 300hPa)
    for _p in ("temperature_500hPa", "temperature_700hPa",
               "wind_speed_300hPa", "wind_direction_300hPa", "geopotential_height_300hPa"):
        if _all_none(wind_data, _p):
            log_api_failure(
                "Open-Meteo-Atmosphere-Pressure",
                _wind_base,
                f"{_p}: alle Werte None — pressure request liefert Parameter nicht",
                fallback_used=True,
            )
    for _p in ("lifted_index", "convective_inhibition", "total_column_integrated_water_vapour"):
        if _all_none(gfs_data, _p):
            log_api_failure(
                "Open-Meteo-Atmosphere-GFS",
                _gfs_base,
                f"{_p}: alle Werte None — GFS liefert Parameter nicht",
                fallback_used=True,
            )

    result_locations = []
    for i, loc in enumerate(locations):
        name = loc.get("name", f"Ort_{i}")
        lat  = loc.get("lat",  0.0)
        lon  = loc.get("lon",  0.0)

        # AROME-Werte
        t2m = td2m = ff10m = li = fl_h = cape_jkg = 0.0
        if arome_data and i < len(arome_data):
            h = arome_data[i].get("hourly", {})
            t2m      = _extract_slot(h, "temperature_2m",       target_time)
            td2m     = _extract_slot(h, "dewpoint_2m",           target_time)
            ff10m    = _extract_slot(h, "wind_speed_10m",        target_time)
            fl_h     = _extract_slot(h, "freezing_level_height", target_time)
            cape_jkg = _extract_slot(h, "cape",                  target_time)

        # 700 hPa Wind + T500/T700 + 300 hPa Wind aus Pressure-Response
        w_speed = w_dir_cos = w_dir_sin = 0.0
        t500_c = t700_c = cin_jkg = pw_mm = 0.0
        w_speed_300 = w_dir_300_raw = geo_300 = None
        w_dir_300_cos = w_dir_300_sin = None
        if wind_data and i < len(wind_data):
            h = wind_data[i].get("hourly", {})
            w_speed = _extract_slot(h, "wind_speed_700hPa",    target_time)
            w_dir   = _extract_slot(h, "wind_direction_700hPa",target_time)
            t500_c  = _extract_slot(h, "temperature_500hPa",   target_time)
            t700_c  = _extract_slot(h, "temperature_700hPa",   target_time)

            rad       = radians(w_dir)
            w_dir_cos = round(cos(rad), 4)
            w_dir_sin = round(sin(rad), 4)

            # 300 hPa Level (Höhenwinde für IR-Cell-Tracking)
            w_speed_300   = _extract_slot_optional(h, "wind_speed_300hPa",       target_time)
            w_dir_300_raw = _extract_slot_optional(h, "wind_direction_300hPa",   target_time)
            geo_300       = _extract_slot_optional(h, "geopotential_height_300hPa", target_time)
            if w_dir_300_raw is not None:
                rad_300       = radians(w_dir_300_raw)
                w_dir_300_cos = round(cos(rad_300), 4)
                w_dir_300_sin = round(sin(rad_300), 4)
        # LI/CIN/PW von GFS
        if gfs_data and i < len(gfs_data):
            h_gfs = gfs_data[i].get("hourly", {})
            li = _extract_slot(h_gfs, "lifted_index", target_time)
            cin_jkg = _extract_slot(h_gfs, "convective_inhibition", target_time)
            pw_mm = _extract_slot(h_gfs, "total_column_integrated_water_vapour", target_time)

        # NEU: lapse_700_500 als abgeleitete Groesse mitspeichern (kein zusaetzlicher
        # API-Call). Annahme: Druckdifferenz 700→500 hPa entspricht ~3.0 km in
        # mittleren Breiten (hypsometrische Faustregel).
        lapse_700_500 = (t700_c - t500_c) / 3.0 if (t700_c and t500_c) else 0.0

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
            "wind_300hpa":      _rounded_or_none(w_speed_300, 1),
            "wind_300hpa_missing": _missing_flag(w_speed_300),
            "wind_dir_300_cos": w_dir_300_cos,
            "wind_dir_300_sin": w_dir_300_sin,
            "wind_dir_300_missing": _missing_flag(w_dir_300_raw),
            "geopotential_300hpa": _rounded_or_none(geo_300, 0),
            "geopotential_300hpa_missing": _missing_flag(geo_300),
            "potential":        _gewitterpotenzial(li),
            # NEU: konvektive Diagnose
            "t500_c":           round(t500_c, 1),
            "t700_c":           round(t700_c, 1),
            "cin":              round(cin_jkg, 1),
            "pw":               round(pw_mm,   1),
            "lapse_700_500":    round(lapse_700_500, 2),
            "cape":             round(cape_jkg, 0),
        })

    # Wolkenhöhen für alle Snapshot-Orte aus EUMETView TIFF (kein neuer API-Call
    # wenn TIFF aktuell — nutzt Cache von cloud_height_from_eumetview.py)
    try:
        from cloud_height_from_eumetview import fetch_cloud_height_for_points
        _latlons = [(loc["lat"], loc["lon"]) for loc in result_locations]
        _cloud_heights = fetch_cloud_height_for_points(_latlons)
        for loc in result_locations:
            _cloud_height = _cloud_heights.get((loc["lat"], loc["lon"]))
            loc["cloud_height_m"] = _cloud_height if _cloud_height is not None else None
            loc["cloud_height_missing"] = _missing_flag(_cloud_height)
        debug_log(f"[ATMOSPHERE] Wolkenhöhe: {[loc['cloud_height_m'] for loc in result_locations]} m")
    except Exception as _ch_exc:
        debug_log(f"[ATMOSPHERE] Wolkenhöhe fehlgeschlagen: {_ch_exc}")
        for loc in result_locations:
            loc.setdefault("cloud_height_m", None)
            loc["cloud_height_missing"] = 1

    quality = _build_feature_quality(result_locations)
    result = {
        "ts_utc":    datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "locations": result_locations,
    }

    os.makedirs(os.path.dirname(_OUT_FILE), exist_ok=True)
    try:
        with open(_OUT_FILE, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        with open(_QUALITY_FILE, "w", encoding="utf-8") as f:
            json.dump(quality, f, indent=2, ensure_ascii=False)
        debug_log(f"[ATMOSPHERE] Snapshot gespeichert: {len(result_locations)} Orte")
    except Exception as exc:
        debug_log(f"[ATMOSPHERE] Speichern fehlgeschlagen: {exc}")

    return result


if __name__ == "__main__":
    import pprint
    pprint.pprint(fetch_atmospheric_snapshot())
