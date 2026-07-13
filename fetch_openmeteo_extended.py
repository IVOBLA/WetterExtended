import math
import requests
from datetime import datetime, timezone

from config import OPEN_METEO_URL

_GFS_URL = "https://api.open-meteo.com/v1/gfs"
# LPI (lightning_potential) ist NUR am DWD-spezifischen Endpoint verfügbar.
# /v1/forecast mit models=icon_eu liefert HTTP 400 für LPI (verifiziert 2026-05).
_DWD_URL = "https://api.open-meteo.com/v1/dwd-icon"
from debug_utils import debug_log, log_api_failure, log_http_response
from api_cache import cache_key, cache_get, cache_set, get_ttl

# icon_d2: Regional-Modell Österreich/Alpen, hat minutely_15, KEINE Druckflächen
_MODEL_15MIN = "icon_d2"
# icon_global: Globales Modell, hat 500/850-hPa-Druckflächen
_MODEL_PRESSURE = "icon_global"
_TIMEZONE = "UTC"
_TIMEOUT = 15
_MINUTELY_PARAMS = "wind_gusts_10m"
_HOURLY_LPI_PARAMS = "lightning_potential"  # DWD-ICON-Endpoint: /v1/dwd-icon
_GFS_CONV_PARAMS = "convective_inhibition,total_column_integrated_water_vapour"
_PRESSURE_PARAMS = (
    "wind_speed_500hPa,wind_direction_500hPa,"
    "wind_speed_850hPa,wind_direction_850hPa,"
    "temperature_500hPa,temperature_700hPa"
)
_DEFAULT = {
    "wind_gust_10m_kmh": 0.0,
    'lpi': 0.0,
    "wind_speed_500hPa": 0.0,
    "wind_dir_500_cos": 0.0,
    "wind_dir_500_sin": 0.0,
    "wind_speed_850hPa": 0.0,
    "wind_dir_850_cos": 0.0,
    "wind_dir_850_sin": 0.0,
    # NEU: konvektive Diagnose-Inputs (rohe API-Werte, Derivate in
    # compute_convective_indices.py).
    "t500_c": 0.0,    # Temperatur 500 hPa (Grad C)
    "t700_c": 0.0,    # Temperatur 700 hPa (Grad C)
    "cin":    0.0,    # Convective Inhibition (J/kg)
    "pw":     0.0,    # Precipitable Water (mm)
}


def _nearest_quarter_str(ref_ts_str: str | None = None) -> str:
    """
    Gibt das nächste 15-Minuten-Intervall des Referenz-Zeitstempels zurück.
    Falls ref_ts_str angegeben: Aufnahme-Zeitstempel parsen und auf Viertelstunde runden.
    Fallback: aktuelle UTC-Systemzeit.
    Beispiel-Rückgabe: '2026-05-28T13:45'
    """
    _FORMATS = (
        "%Y-%m-%d_%H-%M-%S",
        "%Y%m%d_%H%M%S",
        "%Y-%m-%dT%H:%M:%S",
    )
    if ref_ts_str:
        for fmt in _FORMATS:
            try:
                from zoneinfo import ZoneInfo as _ZI_q
                dt = datetime.strptime(ref_ts_str, fmt).replace(tzinfo=_ZI_q("Europe/Vienna"))
                dt_utc = dt.astimezone(timezone.utc)
                q = (dt_utc.minute // 15) * 15
                return f"{dt_utc.strftime('%Y-%m-%dT%H')}:{q:02d}"
            except ValueError:
                continue
    now = datetime.now(timezone.utc)
    q = (now.minute // 15) * 15
    return f"{now.strftime('%Y-%m-%dT%H')}:{q:02d}"


def _nearest_hour_str(ref_ts_str: str | None = None) -> str:
    """
    Gibt die volle Stunde des Referenz-Zeitstempels zurück (UTC).
    Falls ref_ts_str angegeben: Aufnahme-Zeitstempel parsen und auf volle Stunde runden.
    Fallback: aktuelle UTC-Systemzeit.
    Beispiel-Rückgabe: '2026-05-28T13:00'
    """
    _FORMATS = (
        "%Y-%m-%d_%H-%M-%S",
        "%Y%m%d_%H%M%S",
        "%Y-%m-%dT%H:%M:%S",
    )
    if ref_ts_str:
        for fmt in _FORMATS:
            try:
                from zoneinfo import ZoneInfo as _ZI_h
                dt = datetime.strptime(ref_ts_str, fmt).replace(tzinfo=_ZI_h("Europe/Vienna"))
                dt_utc = dt.astimezone(timezone.utc)
                return dt_utc.strftime("%Y-%m-%dT%H:00")
            except ValueError:
                continue
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:00")


def _dir_to_cos_sin(deg: float) -> tuple:
    rad = math.radians((deg + 180) % 360)
    return round(math.cos(rad), 4), round(math.sin(rad), 4)


def assign_extended_openmeteo(objects: list, timestamp: str) -> list:
    valid = [
        (i, o) for i, o in enumerate(objects) if o.get("lat") is not None and o.get("lon") is not None
    ]
    for o in objects:
        o.update(_DEFAULT)
    if not valid:
        debug_log("[EXT-OMETEO] Keine Objekte mit Koordinaten.")
        return objects

    lats = ",".join(f"{o['lat']:.4f}" for _, o in valid)
    lons = ",".join(f"{o['lon']:.4f}" for _, o in valid)

    # ── Request A: minutely_15 (icon_d2) ──────────────────────────────────
    url_a = (
        f"{OPEN_METEO_URL}?latitude={lats}&longitude={lons}"
        f"&minutely_15={_MINUTELY_PARAMS}"
        f"&models={_MODEL_15MIN}&timezone={_TIMEZONE}&forecast_days=1"
    )
    ck_a = cache_key("openmeteo:extended_15min", lats[:60], _nearest_quarter_str(timestamp))
    data_a = cache_get(ck_a, ttl_seconds=get_ttl("openmeteo_extended", 900))
    if data_a is None:
        import time as _ta_ext
        from http_retry import retry_get
        _t0_a = _ta_ext.monotonic()
        try:
            r = retry_get(url_a, service="openmeteo_extended_15min", timeout=_TIMEOUT, breaker_service="openmeteo_forecast")
            _dur_a = (_ta_ext.monotonic() - _t0_a) * 1000
            data_a = r.json()
            log_http_response("openmeteo_extended_arome", "GET", r, _dur_a)
            cache_set(ck_a, data_a)
        except Exception as exc:
            # retry_get hat bereits log_api_failure aufgerufen — hier nur Stale-Fallback.
            from api_cache import cache_get_stale
            data_a = cache_get_stale(ck_a, max_stale_seconds=24*3600)
            if data_a is not None:
                debug_log(f"[openmeteo_extended_15min] STALE-Cache-Fallback verwendet ({type(exc).__name__})")
            else:
                data_a = None

    # ── Request B: hourly 500/850 hPa (icon_global) ───────────────────────
    url_b = (
        f"{OPEN_METEO_URL}?latitude={lats}&longitude={lons}"
        f"&hourly={_PRESSURE_PARAMS}"
        f"&models={_MODEL_PRESSURE}&timezone={_TIMEZONE}&forecast_days=1"
    )
    ck_b = cache_key("openmeteo:extended_pressure", lats[:60], _nearest_hour_str(timestamp))
    data_b = cache_get(ck_b, ttl_seconds=get_ttl("openmeteo_extended", 900))
    if data_b is None:
        import time as _tb_ext
        from http_retry import retry_get
        _t0_b = _tb_ext.monotonic()
        try:
            r = retry_get(url_b, service="openmeteo_extended_pressure", timeout=_TIMEOUT, breaker_service="openmeteo_forecast")
            _dur_b = (_tb_ext.monotonic() - _t0_b) * 1000
            data_b = r.json()
            log_http_response("openmeteo_extended_pressure", "GET", r, _dur_b)
            cache_set(ck_b, data_b)
        except Exception as exc:
            from api_cache import cache_get_stale
            data_b = cache_get_stale(ck_b, max_stale_seconds=24*3600)
            if data_b is not None:
                debug_log(f"[openmeteo_extended_pressure] STALE-Cache-Fallback verwendet ({type(exc).__name__})")
            else:
                data_b = None

    # ── Request C: Lightning Potential Index (nur über DWD-Endpoint verfügbar) ──
    # /v1/forecast mit lpi → HTTP 400; korrekt: /v1/dwd-icon + lightning_potential
    url_c = (
        f"{_DWD_URL}?latitude={lats}&longitude={lons}"
        f"&hourly={_HOURLY_LPI_PARAMS}"
        f"&forecast_days=1&timezone={_TIMEZONE}"
    )
    ck_c = cache_key("openmeteo:extended_lpi", lats[:60], _nearest_hour_str(timestamp))
    data_c = cache_get(ck_c, ttl_seconds=get_ttl("openmeteo_extended", 900))
    if data_c is None:
        import time as _tc_ext
        from http_retry import retry_get
        _t0_c = _tc_ext.monotonic()
        try:
            r = retry_get(url_c, service="openmeteo_extended_lpi", timeout=_TIMEOUT, breaker_service="openmeteo_forecast")
            _dur_c = (_tc_ext.monotonic() - _t0_c) * 1000
            data_c = r.json()
            # Antwort normalisieren: minutely_15 → hourly-kompatible Struktur für Parser
            if isinstance(data_c, dict) and "minutely_15" in data_c and "hourly" not in data_c:
                data_c["hourly"] = data_c["minutely_15"]
                data_c["hourly"]["time"] = data_c["minutely_15"].get("time", [])
            elif isinstance(data_c, list):
                for _d in data_c:
                    if isinstance(_d, dict) and "minutely_15" in _d and "hourly" not in _d:
                        _d["hourly"] = _d["minutely_15"]
            log_http_response("openmeteo_extended_lpi", "GET", r, _dur_c)
            cache_set(ck_c, data_c)
        except Exception as exc:
            from api_cache import cache_get_stale
            data_c = cache_get_stale(ck_c, max_stale_seconds=24*3600)
            if data_c is not None:
                debug_log(f"[openmeteo_extended_lpi] STALE-Cache-Fallback verwendet ({type(exc).__name__})")
            else:
                data_c = None

    # ── Request D: hourly CIN/PW (GFS) ─────────────────────────────────────
    url_d = (
        f"{_GFS_URL}?latitude={lats}&longitude={lons}"
        f"&hourly={_GFS_CONV_PARAMS}"
        f"&timezone={_TIMEZONE}&forecast_days=1"
    )
    ck_d = cache_key("openmeteo:extended_gfs_conv", lats[:60], _nearest_hour_str(timestamp))
    data_d = cache_get(ck_d, ttl_seconds=get_ttl("openmeteo_extended", 900))
    if data_d is None:
        import time as _td_ext
        from http_retry import retry_get
        _t0_d = _td_ext.monotonic()
        try:
            r = retry_get(url_d, service="openmeteo_extended_gfs_conv", timeout=_TIMEOUT, breaker_service="openmeteo_forecast")
            _dur_d = (_td_ext.monotonic() - _t0_d) * 1000
            data_d = r.json()
            log_http_response("openmeteo_extended_gfs", "GET", r, _dur_d)
            cache_set(ck_d, data_d)
        except Exception as exc:
            from api_cache import cache_get_stale
            data_d = cache_get_stale(ck_d, max_stale_seconds=24*3600)
            if data_d is not None:
                debug_log(f"[openmeteo_extended_gfs_conv] STALE-Cache-Fallback verwendet ({type(exc).__name__})")
            else:
                data_d = None

    _apply(data_a, data_b, data_c, data_d, valid, objects)
    return objects


def _apply(data_a, data_b, data_c, data_d, valid: list, objects: list) -> None:
    now_utc = datetime.now(timezone.utc)

    entries_a = (data_a if isinstance(data_a, list) else [data_a]) if data_a else []
    entries_b = (data_b if isinstance(data_b, list) else [data_b]) if data_b else []
    entries_c = (data_c if isinstance(data_c, list) else [data_c]) if data_c else []
    entries_d = (data_d if isinstance(data_d, list) else [data_d]) if data_d else []

    for idx, (_, obj) in enumerate(valid):
        result = dict(_DEFAULT)

        # ── minutely_15 Felder ────────────────────────────────────────────
        if idx < len(entries_a):
            m15 = entries_a[idx].get("minutely_15", {})
            times_15 = m15.get("time", [])
            gusts = m15.get("wind_gusts_10m", [])
            best_idx, min_diff = 0, float("inf")
            for j, t_str in enumerate(times_15):
                try:
                    t = datetime.fromisoformat(t_str.replace("Z", "+00:00"))
                    diff = abs((t - now_utc).total_seconds())
                    if diff < min_diff:
                        min_diff = diff
                        best_idx = j
                except Exception:
                    continue

            def _val(lst, i):
                return float(lst[i]) if i < len(lst) and lst[i] is not None else 0.0

            result["wind_gust_10m_kmh"] = round(_val(gusts, best_idx), 1)

        # ── hourly Druckflächen ───────────────────────────────────────────
        if idx < len(entries_b):
            hourly = entries_b[idx].get("hourly", {})
            times_h = hourly.get("time", [])
            ws500 = hourly.get("wind_speed_500hPa", [])
            wd500 = hourly.get("wind_direction_500hPa", [])
            ws850 = hourly.get("wind_speed_850hPa", [])
            wd850 = hourly.get("wind_direction_850hPa", [])
            t500 = hourly.get("temperature_500hPa", [])
            t700 = hourly.get("temperature_700hPa", [])
            h_idx, min_diff = 0, float("inf")
            for j, t_str in enumerate(times_h):
                try:
                    t = datetime.fromisoformat(t_str.replace("Z", "+00:00"))
                    diff = abs((t - now_utc).total_seconds())
                    if diff < min_diff:
                        min_diff = diff
                        h_idx = j
                except Exception:
                    continue

            def _v(lst, i):
                return float(lst[i]) if i < len(lst) and lst[i] is not None else 0.0

            spd500, dir500 = _v(ws500, h_idx), _v(wd500, h_idx)
            spd850, dir850 = _v(ws850, h_idx), _v(wd850, h_idx)
            cos500, sin500 = _dir_to_cos_sin(dir500)
            cos850, sin850 = _dir_to_cos_sin(dir850)
            result.update(
                {
                    "wind_speed_500hPa": round(spd500, 1),
                    "wind_dir_500_cos": cos500,
                    "wind_dir_500_sin": sin500,
                    "wind_speed_850hPa": round(spd850, 1),
                    "wind_dir_850_cos": cos850,
                    "wind_dir_850_sin": sin850,
                    # NEU: konvektive Indizes-Inputs
                    "t500_c": round(_v(t500, h_idx), 2),
                    "t700_c": round(_v(t700, h_idx), 2),
                }
            )
        else:
            # B344: kein Response-Slot fuer Request B (icon_global 500/850hPa)
            # -> result bleibt bei _DEFAULT (0.0). Marker fuer Monitoring und
            # nachgeschaltete Verbraucher (siehe B345, prediction.py Steering).
            result["wind_speed_500hPa_fallback"] = 1

        # ── CIN/PW aus hourly GFS (Request D) ───────────────────────────
        if idx < len(entries_d):
            h_gfs = entries_d[idx].get("hourly", {})
            times_g = h_gfs.get("time", [])
            cin_vals = h_gfs.get("convective_inhibition", [])
            pw_vals = h_gfs.get("total_column_integrated_water_vapour", [])
            g_idx, min_diff = 0, float("inf")
            for j, t_str in enumerate(times_g):
                try:
                    t = datetime.fromisoformat(t_str.replace("Z", "+00:00"))
                    diff = abs((t - now_utc).total_seconds())
                    if diff < min_diff:
                        min_diff = diff
                        g_idx = j
                except Exception:
                    continue
            result["cin"] = round(float(cin_vals[g_idx]) if g_idx < len(cin_vals) and cin_vals[g_idx] is not None else 0.0, 2)
            result["pw"] = round(float(pw_vals[g_idx]) if g_idx < len(pw_vals) and pw_vals[g_idx] is not None else 0.0, 2)

        # ── LPI aus hourly DWD-ICON (Request C) ──────────────────────────
        if idx < len(entries_c):
            h_lpi = entries_c[idx].get("hourly", {})
            lpi_times = h_lpi.get("time", [])
            lpi_vals = h_lpi.get("lightning_potential", [])
            now_hour = now_utc.strftime("%Y-%m-%dT%H:00")
            lpi_idx = 0
            if now_hour in lpi_times:
                lpi_idx = lpi_times.index(now_hour)
            result['lpi'] = round(float(lpi_vals[lpi_idx]) if lpi_idx < len(lpi_vals) and lpi_vals[lpi_idx] is not None else 0.0, 2)

        obj.update(result)
