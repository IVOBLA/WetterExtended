import requests
from datetime import datetime, timezone

from debug_utils import debug_log, log_api_failure, log_http_response
from api_cache import cache_key, cache_get, cache_set

_BASE_URL = "https://dataset.api.hub.geosphere.at/v1/timeseries/forecast/nowcast-v1-15min-1km"
_PARAMS = "rr,ff,ffx"
_TIMEOUT = 12
_TTL = 720
_DEFAULT = {"nowcast_rr_mm15":0.0,"nowcast_ff_kmh":0.0,"nowcast_ffx_kmh":0.0,"nowcast_rain_rate_1h":0.0,"gust_warning":False,"heavy_rain_warning":False}
GUST_WARN_KMH = 60.0
HEAVY_RAIN_MM_PER_H = 25.0

def assign_nowcast_to_objects(objects: list, timestamp: str) -> list:
    for obj in objects: obj.update(_DEFAULT)
    valid=[(i,o) for i,o in enumerate(objects) if o.get("lat") is not None and o.get("lon") is not None]
    from datetime import timedelta as _td
    _now   = datetime.now(timezone.utc)
    # Nowcast-API: aktuellen 15-min-Slot abfragen.
    # _floor + 15min → HTTP 422, da der nächste Slot noch nicht berechnet ist.
    # Aktueller Slot (_floor) ist immer verfügbar.
    _floor  = _now.replace(minute=(_now.minute // 15) * 15,
                           second=0, microsecond=0)
    _start  = _floor
    _end    = _floor + _td(minutes=15)
    _start_str  = _start.strftime("%Y-%m-%dT%H:%M:00Z")
    _end_str    = _end.strftime("%Y-%m-%dT%H:%M:00Z")
    _cache_hour = _start.strftime("%Y-%m-%dT%H:%M")   # inkl. Minuten → korrekter Cache-Key
    for _, obj in valid:
        lat, lon = round(float(obj['lat']),3), round(float(obj['lon']),3)
        ck=cache_key("geosphere:nowcast", lat, lon, _cache_hour)
        cached=cache_get(ck, ttl_seconds=_TTL)
        if cached is not None: obj.update(cached); continue
        # GeoSphere FastAPI erwartet WIEDERHOLTE Query-Parameter für "parameters"
        # — NICHT kommasepariert! ?parameters=rr&parameters=ff&parameters=ffx
        # Kommasepariert (?parameters=rr,ff,ffx) liefert HTTP 422 (Validation Error).
        # requests.get(..., params=[(...), (...)]) baut automatisch die korrekte URL.
        # Verifiziert: GeoSphere Nowcast v1 API-Spec (dataset.api.hub.geosphere.at).
        _qparams = [
            ("lat",        lat),
            ("lon",        lon),
            ("parameters", "rr"),
            ("parameters", "ff"),
            ("parameters", "ffx"),
            ("start",      _start_str),
            ("end",        _end_str),
        ]
        url = requests.Request("GET", _BASE_URL, params=_qparams).prepare().url
        try:
            import time as _t_nowcast
            _t0_nowcast = _t_nowcast.monotonic()
            r = requests.get(_BASE_URL, params=_qparams, timeout=_TIMEOUT if '_TIMEOUT' in dir() else 30, headers={"Accept":"application/json"})
            _dur_nowcast = (_t_nowcast.monotonic() - _t0_nowcast) * 1000
            r.raise_for_status()
            data = r.json()
            log_http_response("geosphere_nowcast", "GET", r, _dur_nowcast)
        except requests.exceptions.Timeout:
            log_api_failure("geosphere_nowcast", url, "timeout", fallback_used=True); continue
        except Exception as exc:
            log_api_failure("geosphere_nowcast", str(url), str(exc)[:80], fallback_used=True); continue
        result=_parse_nowcast(data, str(url)); cache_set(ck,result); obj.update(result)
    return objects

def _parse_nowcast(data: dict, url: str = "") -> dict:
    result=dict(_DEFAULT)
    try:
        features=data.get('features',[])
        if not features:
            log_api_failure(
                "geosphere_nowcast", url,
                "features-list-empty: GeoSphere Nowcast liefert keine Gitterpunkte",
                fallback_used=True,
            )
            return result
        params=features[0].get('properties',{}).get('parameters',{})
        def _first(key):
            vals=params.get(key,{}).get('data',[None]); v=vals[0] if vals else None
            return float(v) if v is not None else 0.0
        rr,ff,ffx=_first('rr'),_first('ff'),_first('ffx')
        ff_kmh,ffx_kmh,rate_1h=round(ff*3.6,1),round(ffx*3.6,1),round(rr*4,2)
        result.update({"nowcast_rr_mm15":round(rr,3),"nowcast_ff_kmh":ff_kmh,"nowcast_ffx_kmh":ffx_kmh,"nowcast_rain_rate_1h":rate_1h,"gust_warning":ffx_kmh>=GUST_WARN_KMH,"heavy_rain_warning":rate_1h>=HEAVY_RAIN_MM_PER_H})
    except Exception as exc:
        debug_log(f"[NOWCAST] Parse-Fehler: {exc}")
    return result
