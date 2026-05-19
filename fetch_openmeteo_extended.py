import math
import requests
from datetime import datetime, timezone

from config import OPEN_METEO_URL
from debug_utils import debug_log, log_api_failure
from api_cache import cache_key, cache_get, cache_set, get_ttl

# icon_d2: Regional-Modell Österreich/Alpen, hat minutely_15, KEINE Druckflächen
_MODEL_15MIN = "icon_d2"
# icon_global: Globales Modell, hat 500/850-hPa-Druckflächen
_MODEL_PRESSURE = "icon_global"
_TIMEZONE = "UTC"
_TIMEOUT = 15
_MINUTELY_PARAMS = "wind_gusts_10m,lightning_potential_index"
_PRESSURE_PARAMS = (
    "wind_speed_500hPa,wind_direction_500hPa,"
    "wind_speed_850hPa,wind_direction_850hPa"
)
_DEFAULT = {
    "wind_gust_10m_kmh": 0.0,
    "lpi": 0.0,
    "wind_speed_500hPa": 0.0,
    "wind_dir_500_cos": 0.0,
    "wind_dir_500_sin": 0.0,
    "wind_speed_850hPa": 0.0,
    "wind_dir_850_cos": 0.0,
    "wind_dir_850_sin": 0.0,
}


def _nearest_quarter_str() -> str:
    now = datetime.now(timezone.utc)
    q = (now.minute // 15) * 15
    return f"{now.strftime('%Y-%m-%dT%H')}:{q:02d}"


def _nearest_hour_str() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:00")


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
    ck_a = cache_key("openmeteo:extended_15min", lats[:60], _nearest_quarter_str())
    data_a = cache_get(ck_a, ttl_seconds=get_ttl("openmeteo_extended", 900))
    if data_a is None:
        try:
            r = requests.get(url_a, timeout=_TIMEOUT)
            r.raise_for_status()
            data_a = r.json()
            cache_set(ck_a, data_a)
        except requests.exceptions.Timeout:
            log_api_failure("openmeteo_extended_15min", url_a, "timeout", fallback_used=True)
            data_a = None
        except Exception as exc:
            log_api_failure("openmeteo_extended_15min", url_a, str(exc)[:80], fallback_used=True)
            data_a = None

    # ── Request B: hourly 500/850 hPa (icon_global) ───────────────────────
    url_b = (
        f"{OPEN_METEO_URL}?latitude={lats}&longitude={lons}"
        f"&hourly={_PRESSURE_PARAMS}"
        f"&models={_MODEL_PRESSURE}&timezone={_TIMEZONE}&forecast_days=1"
    )
    ck_b = cache_key("openmeteo:extended_pressure", lats[:60], _nearest_hour_str())
    data_b = cache_get(ck_b, ttl_seconds=get_ttl("openmeteo_extended", 900))
    if data_b is None:
        try:
            r = requests.get(url_b, timeout=_TIMEOUT)
            r.raise_for_status()
            data_b = r.json()
            cache_set(ck_b, data_b)
        except requests.exceptions.Timeout:
            log_api_failure("openmeteo_extended_pressure", url_b, "timeout", fallback_used=True)
            data_b = None
        except Exception as exc:
            log_api_failure("openmeteo_extended_pressure", url_b, str(exc)[:80], fallback_used=True)
            data_b = None

    _apply(data_a, data_b, valid, objects)
    return objects


def _apply(data_a, data_b, valid: list, objects: list) -> None:
    now_utc = datetime.now(timezone.utc)

    entries_a = (data_a if isinstance(data_a, list) else [data_a]) if data_a else []
    entries_b = (data_b if isinstance(data_b, list) else [data_b]) if data_b else []

    for idx, (_, obj) in enumerate(valid):
        result = dict(_DEFAULT)

        # ── minutely_15 Felder ────────────────────────────────────────────
        if idx < len(entries_a):
            m15 = entries_a[idx].get("minutely_15", {})
            times_15 = m15.get("time", [])
            gusts = m15.get("wind_gusts_10m", [])
            lpis = m15.get("lightning_potential_index", [])
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
            result["lpi"] = round(_val(lpis, best_idx), 4)

        # ── hourly Druckflächen ───────────────────────────────────────────
        if idx < len(entries_b):
            hourly = entries_b[idx].get("hourly", {})
            times_h = hourly.get("time", [])
            ws500 = hourly.get("wind_speed_500hPa", [])
            wd500 = hourly.get("wind_direction_500hPa", [])
            ws850 = hourly.get("wind_speed_850hPa", [])
            wd850 = hourly.get("wind_direction_850hPa", [])
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
                }
            )

        obj.update(result)
