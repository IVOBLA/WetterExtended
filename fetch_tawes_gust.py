import math
import requests
from debug_utils import debug_log, log_api_failure
from api_cache import cache_key, cache_get, cache_set

_BASE_URL="https://dataset.api.hub.geosphere.at/v1/station/current/tawes-v1-10min"
_PARAMS="FFX,FF,RR,TL"
_STATION_IDS="11330,11301,11315,11320,11350"
_TIMEOUT=10
_TTL=600

def fetch_tawes_stations() -> list:
    ck=cache_key("geosphere:tawes", _STATION_IDS)
    cached=cache_get(ck, ttl_seconds=_TTL)
    if cached is not None: return cached
    url=f"{_BASE_URL}?parameters={_PARAMS}&station_ids={_STATION_IDS}"
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
        station_meta = props.get('station', {})
        out.append({
            "station_id": str(station_meta.get('id', '?')),
            "name":       str(station_meta.get('name', '?')),
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
