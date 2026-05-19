import math
import requests
from datetime import datetime, timezone

from config import OPEN_METEO_URL
from debug_utils import debug_log, log_api_failure
from api_cache import cache_key, cache_get, cache_set, get_ttl

_MODEL_15MIN = "icon_d2"
_TIMEZONE = "UTC"
_TIMEOUT = 15
_MINUTELY_PARAMS = "wind_gusts_10m,lightning_potential_index"
_PRESSURE_PARAMS = (
    "wind_speed_500hPa,wind_direction_500hPa,"
    "wind_speed_850hPa,wind_direction_850hPa"
)
_DEFAULT = {"wind_gust_10m_kmh":0.0,"lpi":0.0,"wind_speed_500hPa":0.0,"wind_dir_500_cos":0.0,"wind_dir_500_sin":0.0,"wind_speed_850hPa":0.0,"wind_dir_850_cos":0.0,"wind_dir_850_sin":0.0}

def _nearest_quarter_str() -> str:
    now = datetime.now(timezone.utc)
    q = (now.minute // 15) * 15
    return f"{now.strftime('%Y-%m-%dT%H')}:{q:02d}"

def _dir_to_cos_sin(deg: float) -> tuple:
    rad = math.radians((deg + 180) % 360)
    return round(math.cos(rad), 4), round(math.sin(rad), 4)

def assign_extended_openmeteo(objects: list, timestamp: str) -> list:
    valid = [(i, o) for i, o in enumerate(objects) if o.get("lat") is not None and o.get("lon") is not None]
    for o in objects:
        o.update(_DEFAULT)
    if not valid:
        debug_log("[EXT-OMETEO] Keine Objekte mit Koordinaten.")
        return objects
    lats = ",".join(f"{o['lat']:.4f}" for _, o in valid)
    lons = ",".join(f"{o['lon']:.4f}" for _, o in valid)
    url = (f"{OPEN_METEO_URL}?latitude={lats}&longitude={lons}"
           f"&minutely_15={_MINUTELY_PARAMS}&hourly={_PRESSURE_PARAMS}"
           f"&models={_MODEL_15MIN}&timezone={_TIMEZONE}&forecast_days=1")
    ck = cache_key("openmeteo:extended", lats[:60], _nearest_quarter_str())
    cached = cache_get(ck, ttl_seconds=get_ttl("openmeteo_extended", 900))
    if cached is not None:
        _apply(cached, valid, objects)
        return objects
    try:
        r = requests.get(url, timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        cache_set(ck, data)
    except requests.exceptions.Timeout:
        log_api_failure("openmeteo_extended", url, "timeout", fallback_used=True)
        return objects
    except Exception as exc:
        log_api_failure("openmeteo_extended", url, str(exc)[:80], fallback_used=True)
        return objects
    _apply(data, valid, objects)
    return objects

def _apply(data: dict, valid: list, objects: list) -> None:
    entries = data if isinstance(data, list) else [data]
    now_utc = datetime.now(timezone.utc)
    for idx, (_, obj) in enumerate(valid):
        if idx >= len(entries):
            break
        entry = entries[idx]
        m15 = entry.get("minutely_15", {})
        times_15 = m15.get("time", [])
        gusts = m15.get("wind_gusts_10m", [])
        lpis = m15.get("lightning_potential_index", [])
        best_idx = 0
        min_diff = float("inf")
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
        best_gust = _val(gusts, best_idx)
        best_lpi = _val(lpis, best_idx)
        hourly = entry.get("hourly", {})
        times_h = hourly.get("time", [])
        ws500 = hourly.get("wind_speed_500hPa", [])
        wd500 = hourly.get("wind_direction_500hPa", [])
        ws850 = hourly.get("wind_speed_850hPa", [])
        wd850 = hourly.get("wind_direction_850hPa", [])
        h_idx = 0
        min_diff = float("inf")
        for j, t_str in enumerate(times_h):
            try:
                t = datetime.fromisoformat(t_str.replace("Z", "+00:00"))
                diff = abs((t - now_utc).total_seconds())
                if diff < min_diff:
                    min_diff = diff
                    h_idx = j
            except Exception:
                continue
        spd500, dir500, spd850, dir850 = _val(ws500,h_idx), _val(wd500,h_idx), _val(ws850,h_idx), _val(wd850,h_idx)
        cos500, sin500 = _dir_to_cos_sin(dir500)
        cos850, sin850 = _dir_to_cos_sin(dir850)
        obj.update({"wind_gust_10m_kmh":round(best_gust,1),"lpi":round(best_lpi,4),"wind_speed_500hPa":round(spd500,1),"wind_dir_500_cos":cos500,"wind_dir_500_sin":sin500,"wind_speed_850hPa":round(spd850,1),"wind_dir_850_cos":cos850,"wind_dir_850_sin":sin850})
