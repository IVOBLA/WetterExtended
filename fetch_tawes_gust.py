import math
import requests
from debug_utils import debug_log, log_api_failure
from api_cache import cache_key, cache_get, cache_set

_BASE_URL="https://dataset.api.hub.geosphere.at/v1/station/current/tawes-v1-10min"
_PARAMS="FFX,FF,RR,TL"
_TIMEOUT=10
_TTL=600

def _get_station_ids() -> str:
    """Station-IDs aus runtime_config (überschreibbar im Admin-Panel)."""
    try:
        import runtime_config
        from config import TAWES_GUST_STATION_IDS
        return runtime_config.get("TAWES_GUST_STATION_IDS", TAWES_GUST_STATION_IDS)
    except Exception:
        return "11330,11301,11315,11320,11350"

def fetch_tawes_stations() -> list:
    _station_ids = _get_station_ids()
    ck=cache_key("geosphere:tawes", _station_ids)
    cached=cache_get(ck, ttl_seconds=_TTL)
    if cached is not None: return cached
    url=f"{_BASE_URL}?parameters={_PARAMS}&station_ids={_station_ids}"
    try:
        r=requests.get(url, timeout=_TIMEOUT, headers={"Accept":"application/json"})
        r.raise_for_status(); data=r.json()
    except requests.exceptions.Timeout:
        log_api_failure("geosphere_tawes", url, "timeout", fallback_used=True); return []
    except Exception as exc:
        log_api_failure("geosphere_tawes", url, str(exc)[:80], fallback_used=True); return []
    out=[]
    for feat in data.get('features',[]):
        props=feat.get('properties',{}); geom=feat.get('geometry',{}); coords=geom.get('coordinates',[0,0])
        params_raw = props.get('parameters', {})
        def _p(key):
            entry = params_raw.get(key, {})
            if isinstance(entry, dict):
                data = entry.get('data', [None])
                v = data[0] if data else None
            else:
                v = entry
            return float(v) if v is not None else 0.0
        station_id_raw   = props.get('station', '?')
        station_name_raw = props.get('name', f'Station {station_id_raw}')
        out.append({
            "station_id": str(station_id_raw),
            "name":       str(station_name_raw),
            "lat":        float(coords[1]) if len(coords) > 1 else 0.0,
            "lon":        float(coords[0]) if coords else 0.0,
            "ffx_kmh":    round(_p('FFX') * 3.6, 1),
            "ff_kmh":     round(_p('FF')  * 3.6, 1),
            "rr_mm":      round(_p('RR'),  3),
            "tl_c":       round(_p('TL'),  1),
        })
    cache_set(ck,out); return out

def max_gust_near(lat: float, lon: float, stations: list, radius_km: float = 30.0) -> float:
    max_gust=0.0
    for s in stations:
        slat,slon=s.get('lat',0.0),s.get('lon',0.0)
        dlat=math.radians(slat-lat); dlon=math.radians(slon-lon)
        a=(math.sin(dlat/2)**2+math.cos(math.radians(lat))*math.cos(math.radians(slat))*math.sin(dlon/2)**2)
        dist_km=6371*2*math.asin(math.sqrt(a))
        if dist_km<=radius_km: max_gust=max(max_gust,s.get('ffx_kmh',0.0))
    return max_gust
