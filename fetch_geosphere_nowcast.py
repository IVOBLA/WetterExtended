import requests
from datetime import datetime, timezone

from debug_utils import debug_log, log_api_failure, log_http_response, log_api_call
from api_cache import cache_key, cache_get, cache_set

_BASE_URL = "https://dataset.api.hub.geosphere.at/v1/timeseries/forecast/nowcast-v1-15min-1km"
_PARAMS = "rr,ff,ffx"
_TIMEOUT = 12
_TTL = 720
_DEFAULT = {"nowcast_rr_mm15":0.0,"nowcast_ff_kmh":0.0,"nowcast_ffx_kmh":0.0,"nowcast_rain_rate_1h":0.0,"gust_warning":False,"heavy_rain_warning":False}
GUST_WARN_KMH = 60.0
HEAVY_RAIN_MM_PER_H = 25.0

def _build_nowcast_slots(now: datetime) -> list[dict[str, str]]:
    from datetime import timedelta as _td

    _floor = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
    _td15 = _td(minutes=15)
    # B88: Nur aktuellen Slot abfragen — Fallback-Slot lag in der Vergangenheit
    # und lieferte HTTP 400 (GeoSphere Forecast-API akzeptiert nur aktuelle/zukünftige Slots).
    # Wenn der aktuelle Slot noch nicht berechnet ist → HTTP 422 → _slot_result bleibt None
    # → Felder bleiben auf DEFAULT (0.0) → kein falscher Wert.
    return [
        {
            "start_str":  _floor.strftime("%Y-%m-%dT%H:%M"),
            "end_str":    (_floor + _td15).strftime("%Y-%m-%dT%H:%M"),
            "cache_sfx":  _floor.strftime("%Y-%m-%dT%H:%M"),
        },
    ]


def _build_nowcast_url(lat: float, lon: float, slot: dict[str, str]) -> str:
    # GeoSphere Nowcast erwartet lat_lon als kombinierten Parameter MIT
    # LITERAL-Komma: lat_lon=46.526,14.548
    # requests.get(..., params=[("lat_lon","46.526,14.548")]) kodiert das
    # Komma zu %2C → HTTP 400 "Bad Request".
    # Lösung: URL vollständig manuell bauen — kein params=-Argument.
    _lat_lon_raw = f"{lat},{lon}"
    _url_params = (
        f"lat_lon={_lat_lon_raw}"
        f"&parameters=rr&parameters=ff&parameters=ffx"
        f"&start={slot['start_str']}&end={slot['end_str']}"
    )
    return f"{_BASE_URL}?{_url_params}"


def assign_nowcast_to_objects(objects: list, timestamp: str) -> list:
    for obj in objects: obj.update(_DEFAULT)
    valid=[(i,o) for i,o in enumerate(objects) if o.get("lat") is not None and o.get("lon") is not None]
    _now = datetime.now(timezone.utc)
    _nowcast_slots = _build_nowcast_slots(_now)
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
        # B88: aktuellen Slot abfragen, keinen vergangenen Fallback-Slot mehr versuchen.
        _slot_result = None
        for _slot in _nowcast_slots:
            _ck = cache_key("geosphere:nowcast", lat, lon, _slot["cache_sfx"])
            _cached = cache_get(_ck, ttl_seconds=_TTL)
            if _cached is not None:
                _slot_result = _cached
                break
            import time as _t_nowcast
            from http_retry import retry_get
            url = _build_nowcast_url(lat, lon, _slot)
            try:
                _t0_nowcast = _t_nowcast.monotonic()
                r = retry_get(
                    url,          # URL enthält bereits alle Parameter — kein params=
                    service="geosphere_nowcast",
                    timeout=_TIMEOUT,
                    max_retries=1,
                    headers={"Accept": "application/json"},
                )
                _dur_nowcast = (_t_nowcast.monotonic() - _t0_nowcast) * 1000
                r.raise_for_status()
                data = r.json()
                log_http_response("geosphere_nowcast", "GET", r, _dur_nowcast)
                _slot_result = _parse_nowcast(data, str(url))
                cache_set(_ck, _slot_result)
                break
            except requests.exceptions.HTTPError as _nc_exc:
                _nc_status = getattr(_nc_exc.response, "status_code", None)
                _nc_body   = ""
                try:
                    _nc_body = (_nc_exc.response.json().get("detail") or "")
                    if isinstance(_nc_body, list):
                        _nc_body = str(_nc_body[0].get("msg", ""))
                except Exception:
                    pass
                if _nc_status == 422:
                    debug_log(
                        f"[NOWCAST] Slot {_slot['start_str'][:16]} HTTP 422 "
                        f"({_nc_body}) — kein Fallback-Slot"
                    )
                    log_api_failure(
                        "geosphere_nowcast", str(url),
                        f"http-422 | {_nc_body}",
                        fallback_used=True, http_status=422,
                    )
                    log_api_call(
                        "geosphere_nowcast", url=str(url), status_code=422,
                        duration_ms=(_t_nowcast.monotonic() - _t0_nowcast) * 1000,
                        method="GET",
                        response_text=_nc_body[:200],
                        error=f"http-422 | {_nc_body}",
                    )
                    continue  # weitere Slots nur falls künftig wieder konfiguriert
                # Anderer HTTP-Fehler → abbrechen
                log_api_failure("geosphere_nowcast", str(url),
                                str(_nc_exc), fallback_used=True,
                                http_status=_nc_status)
                break
            except Exception as exc:
                log_api_failure("geosphere_nowcast", str(url), str(exc),
                                fallback_used=True)
                break
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
