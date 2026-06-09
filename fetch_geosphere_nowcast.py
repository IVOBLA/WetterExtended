import requests
from datetime import datetime, timezone

from debug_utils import debug_log, log_api_failure, log_http_response, log_api_call
from api_cache import cache_key, cache_get, cache_set

_BASE_URL = "https://dataset.api.hub.geosphere.at/v1/timeseries/forecast/nowcast-v1-15min-1km"
_PARAMS = "rr,ff,ffx"
_TIMEOUT = 12
_TTL = 720
_DEFAULT = {
    "nowcast_rr_mm15": 0.0, "nowcast_ff_kmh": 0.0, "nowcast_ffx_kmh": 0.0,
    "nowcast_rain_rate_1h": 0.0, "gust_warning": False, "heavy_rain_warning": False,
}
GUST_WARN_KMH = 60.0
HEAVY_RAIN_MM_PER_H = 25.0

# B104: nowcast-v1-15min-1km ist ein FORECAST-Endpunkt (Modus "forecast"),
# KEINE frei abfragbare Vergangenheits-Zeitreihe. start/end ausserhalb des aktuell
# verfuegbaren Forecast-Fensters -> HTTP 400. Korrekt: forecast_offset=0
# (= neuester Forecast), KEIN start/end. Der Parser nimmt den ersten Zeitschritt.
_FORECAST_OFFSET = "0"


def _params_suffix() -> str:
    # Parameter MUESSEN einzeln wiederholt werden (kommasepariert -> HTTP 422).
    return f"parameters=rr&parameters=ff&parameters=ffx&forecast_offset={_FORECAST_OFFSET}"


def _build_nowcast_url(lat: float, lon: float) -> str:
    # lat_lon MUSS literales Komma behalten (lat_lon=46.526,14.548).
    # requests(..., params=...) kodiert das Komma zu %2C -> HTTP 400.
    # Deshalb URL manuell bauen. B104: forecast_offset=0, kein start/end.
    return f"{_BASE_URL}?lat_lon={lat},{lon}&{_params_suffix()}"


def _cache_suffix(now: datetime) -> str:
    # Cache rotiert mit dem 15-min-Raster (Nowcast-Aktualisierung), TTL _TTL s.
    _floor = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
    return _floor.strftime("%Y-%m-%dT%H:%M")


def assign_nowcast_to_objects(objects: list, timestamp: str | None = None) -> list:
    """
    Weist jedem Objekt aktuelle Nowcast-Werte zu (Niederschlag, Wind, Boeen).

    B104: GeoSphere-Nowcast als FORECAST-Endpunkt (forecast_offset=0, kein
          start/end). Ersetzt die fruehere B92/B93-Slot-Logik (abgeschlossene
          Vergangenheits-Slots), die gegen den Forecast-Endpunkt HTTP 400 erzeugte.

    Bulk-Request: alle Zellen in EINEM HTTP-Call (wiederholte lat_lon-Parameter).
    GeoSphere gibt features-Array in Eingabe-Reihenfolge zurueck.

    ``timestamp`` bleibt als optionaler Parameter erhalten (Aufrufer uebergeben
    ihn weiterhin); fuer forecast_offset=0 ist immer die aktuelle UTC-Zeit
    massgeblich (nur fuer den Cache-Suffix).
    """
    import time as _t_nowcast_mod

    if not objects:
        return objects

    for obj in objects:
        obj.update(_DEFAULT)

    _coords = []
    for obj in objects:
        try:
            if obj.get("lat") is None or obj.get("lon") is None:
                _coords.append(None)
                continue
            _lat = round(float(obj.get("lat", 0)), 3)
            _lon = round(float(obj.get("lon", 0)), 3)
            _coords.append((_lat, _lon))
        except (TypeError, ValueError):
            _coords.append(None)

    _valid_indices = [i for i, c in enumerate(_coords) if c is not None]
    if not _valid_indices:
        return objects

    _now = datetime.now(timezone.utc)
    _sfx = _cache_suffix(_now)

    _coord_cache_component = ";".join(
        f"{_coords[i][0]},{_coords[i][1]}" for i in _valid_indices
    )
    _ck = cache_key("geosphere:nowcast_bulk", _coord_cache_component, _sfx)
    _cached = cache_get(_ck, ttl_seconds=_TTL)
    if _cached is not None:
        for list_pos, obj_idx in enumerate(_valid_indices):
            if list_pos < len(_cached):
                objects[obj_idx].update(_cached[list_pos])
        debug_log(f"[NOWCAST] Bulk Cache-HIT — {len(_valid_indices)} Objekte")
        return objects

    _lat_lon_parts = "&".join(
        f"lat_lon={_coords[i][0]},{_coords[i][1]}" for i in _valid_indices
    )
    _url = f"{_BASE_URL}?{_lat_lon_parts}&{_params_suffix()}"

    try:
        _t0 = _t_nowcast_mod.monotonic()
        _resp = requests.get(_url, timeout=_TIMEOUT, headers={"Accept": "application/json"})
        _dur_ms = (_t_nowcast_mod.monotonic() - _t0) * 1000
        _resp.raise_for_status()

        _headers = getattr(_resp, "headers", {}) or {}
        _content_type = _headers.get("content-type") if hasattr(_headers, "get") else None
        log_api_call(
            "geosphere_nowcast", url=_url, status_code=_resp.status_code,
            duration_ms=_dur_ms, method="GET", response_text=_resp.text,
            content_type=_content_type,
        )

        _data = _resp.json()
        _features = _data.get("features", [])

        if len(_features) != len(_valid_indices):
            debug_log(
                f"[NOWCAST] Bulk: {len(_features)} Features fuer "
                f"{len(_valid_indices)} Objekte — Fallback Einzelabfragen"
            )
            _results = [_parse_nowcast_single(_coords[i]) for i in _valid_indices]
        else:
            _results = [_parse_nowcast(_f, url=_url) for _f in _features]

        _cache_data = []
        for list_pos, obj_idx in enumerate(_valid_indices):
            if list_pos < len(_results):
                objects[obj_idx].update(_results[list_pos])
                _cache_data.append(_results[list_pos])
        cache_set(_ck, _cache_data)
        debug_log(f"[NOWCAST] Bulk OK — {len(_valid_indices)} Objekte, {_dur_ms:.0f} ms")
        return objects

    except requests.exceptions.HTTPError as _exc:
        _status = getattr(getattr(_exc, "response", None), "status_code", None) or 0
        log_api_failure("geosphere_nowcast", _url, str(_exc), fallback_used=False, http_status=_status)
        log_api_call("geosphere_nowcast", url=_url, status_code=_status, method="GET", error=str(_exc))
        return objects
    except Exception as _exc:
        log_api_failure("geosphere_nowcast", _url, str(_exc), fallback_used=False)
        return objects


def _parse_nowcast_single(coord: tuple) -> dict:
    """Fallback-Einzelabfrage wenn die Bulk-Response unvollstaendig ist.
    B104: forecast_offset=0, kein start/end."""
    import time as _t_single

    _lat, _lon = coord
    _url = _build_nowcast_url(_lat, _lon)
    try:
        _t0 = _t_single.monotonic()
        _r = requests.get(_url, timeout=_TIMEOUT, headers={"Accept": "application/json"})
        _dur_ms = (_t_single.monotonic() - _t0) * 1000
        _r.raise_for_status()
        log_api_call(
            "geosphere_nowcast", url=_url, status_code=_r.status_code,
            duration_ms=_dur_ms, method="GET",
        )
        _feat = _r.json().get("features", [{}])
        return _parse_nowcast(_feat[0] if _feat else {}, url=_url)
    except Exception as _exc:
        log_api_failure("geosphere_nowcast", _url, str(_exc), fallback_used=True)
        return dict(_DEFAULT)


def _parse_nowcast(feature: dict, url: str = "") -> dict:
    """Parst ein einzelnes GeoJSON-Feature. Nimmt den ersten Zeitschritt
    (= jetzt, forecast_offset=0)."""
    result = dict(_DEFAULT)
    try:
        params = feature.get("properties", {}).get("parameters", {})

        def _first(key):
            vals = params.get(key, {}).get("data", [None])
            v = vals[0] if vals else None
            return float(v) if v is not None else 0.0

        rr = _first("rr")
        ff = _first("ff")
        ffx = _first("ffx")
        ff_kmh = round(ff * 3.6, 1)
        ffx_kmh = round(ffx * 3.6, 1)
        rate_1h = round(rr * 4, 2)
        result.update({
            "nowcast_rr_mm15": round(rr, 3),
            "nowcast_ff_kmh": ff_kmh,
            "nowcast_ffx_kmh": ffx_kmh,
            "nowcast_rain_rate_1h": rate_1h,
            "gust_warning": ffx_kmh >= GUST_WARN_KMH,
            "heavy_rain_warning": rate_1h >= HEAVY_RAIN_MM_PER_H,
        })
    except Exception as exc:
        debug_log(f"[NOWCAST] Parse-Fehler: {exc}")
    return result
