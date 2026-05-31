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
    _floor  = _now.replace(minute=(_now.minute // 15) * 15,
                           second=0, microsecond=0)
    _td15  = _td(minutes=15)
    # 2-Slot-Strategie: aktuellen Slot bevorzugen — erfasst neue Stürme die gerade
    # begonnen haben. Fallback auf vorherigen Slot wenn aktueller noch berechnet
    # wird (HTTP 422, typisch in den ersten 2–3 min nach Slot-Beginn).
    #   Slot 0 (bevorzugt): _floor     … _floor+15min  — Niederschlag JETZT
    #   Slot 1 (Fallback):  _floor-15min … _floor       — Niederschlag VOR 15 min
    _nowcast_slots = [
        {
            "start_str":  _floor.strftime("%Y-%m-%dT%H:%M:00Z"),
            "end_str":    (_floor + _td15).strftime("%Y-%m-%dT%H:%M:00Z"),
            "cache_sfx":  _floor.strftime("%Y-%m-%dT%H:%M"),
        },
        {
            "start_str":  (_floor - _td15).strftime("%Y-%m-%dT%H:%M:00Z"),
            "end_str":    _floor.strftime("%Y-%m-%dT%H:%M:00Z"),
            "cache_sfx":  (_floor - _td15).strftime("%Y-%m-%dT%H:%M"),
        },
    ]
    # GeoSphere Nowcast-Domain: Österreich + 0.2° Puffer.
    # Koordinaten außerhalb dieses Bereichs liefern HTTP 422 (Unprocessable Content).
    # BBOX_KAERNTEN_EXTENDED reicht bis lat 45.5 (Norditalien/Slowenien) — diese überspringen.
    # Verifiziert: GeoSphere Dataset API nowcast-v1-15min-1km Domäne.
    _NC_LAT_MIN, _NC_LAT_MAX = 46.2, 49.2
    _NC_LON_MIN, _NC_LON_MAX =  9.3, 17.3

    for _, obj in valid:
        lat, lon = round(float(obj['lat']),3), round(float(obj['lon']),3)
        # Domain-Check: Koordinate außerhalb Österreich → Default-Werte, kein HTTP-Call.
        if not (_NC_LAT_MIN <= lat <= _NC_LAT_MAX and _NC_LON_MIN <= lon <= _NC_LON_MAX):
            debug_log(
                f"[NOWCAST] lat={lat},lon={lon} außerhalb GeoSphere-Domain "
                f"({_NC_LAT_MIN}–{_NC_LAT_MAX}N, {_NC_LON_MIN}–{_NC_LON_MAX}E) — übersprungen."
            )
            obj.update(_DEFAULT)
            continue
        # 2-Slot-Strategie: aktuellen Slot zuerst, Fallback auf vorherigen bei 422.
        _slot_result = None
        for _slot in _nowcast_slots:
            _ck = cache_key("geosphere:nowcast", lat, lon, _slot["cache_sfx"])
            _cached = cache_get(_ck, ttl_seconds=_TTL)
            if _cached is not None:
                _slot_result = _cached
                break
            _qparams = [
                ("lat",        lat),
                ("lon",        lon),
                ("parameters", "rr"),
                ("parameters", "ff"),
                ("parameters", "ffx"),
                ("start",      _slot["start_str"]),
                ("end",        _slot["end_str"]),
            ]
            url = requests.Request("GET", _BASE_URL, params=_qparams).prepare().url
            try:
                import time as _t_nowcast
                _t0_nowcast = _t_nowcast.monotonic()
                from http_retry import retry_get
                r = retry_get(
                    _BASE_URL,
                    service="geosphere_nowcast",
                    timeout=_TIMEOUT,
                    params=_qparams,
                    abort_on_4xx=False,   # 422 abfangen statt Exception
                    headers={"Accept": "application/json"},
                )
                _dur_nowcast = (_t_nowcast.monotonic() - _t0_nowcast) * 1000
                if r.status_code == 422:
                    # Response-Body loggen — enthält exakten GeoSphere-Fehlergrund
                    try:
                        _body = r.json()
                        _detail = (
                            _body.get("detail")
                            or _body.get("message")
                            or str(_body)[:200]
                        )
                    except Exception:
                        _detail = r.text[:200]
                    debug_log(
                        f"[NOWCAST-422] Slot {_slot['start_str'][:16]}–"
                        f"{_slot['end_str'][:16]} "
                        f"lat={lat} lon={lon} | GeoSphere: {_detail}"
                    )
                    log_api_failure(
                        "geosphere_nowcast",
                        str(url),
                        f"http-422 | {_detail[:120]}",
                        fallback_used=True,
                        http_status=422,
                    )
                    continue
                r.raise_for_status()
                data = r.json()
                log_http_response("geosphere_nowcast", "GET", r, _dur_nowcast)
                _slot_result = _parse_nowcast(data, str(url))
                cache_set(_ck, _slot_result)
                break
            except Exception as exc:
                log_api_failure("geosphere_nowcast", str(url), str(exc)[:80],
                                fallback_used=True)
                break  # Netzwerk-/Parse-Fehler → kein weiterer Versuch
        if _slot_result is not None:
            obj.update(_slot_result)
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
