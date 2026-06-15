import json
import os
import time
import requests
from datetime import datetime, timezone

from debug_utils import debug_log, log_api_failure, log_http_response, log_api_call
from api_cache import cache_key, cache_get, cache_set

_BASE_URL = "https://dataset.api.hub.geosphere.at/v1/timeseries/forecast/nowcast-v1-15min-1km"
# B116: 'ffx' existiert im Nowcast-Datensatz NICHT (GeoSphere HTTP 400
# "Parameters {'ffx'} do not exist"). Böen kommen aus TAWES/AROME.
_PARAMS = "rr,ff"
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

# B105: GeoSphere Nowcast-v1-15min-1km Abdeckungsgrenzen (MGI/Austria-Lambert-Raster).
# Quelle: https://data.hub.geosphere.at/dataset/nowcast-v1-15min-1km
# Bbox: 45.5–49.48 °N, 8.1–17.74 °E.
# Zusätzlicher 0.1°-Puffer innen um Randzellen zu vermeiden die trotz Bbox 400 liefern.
_NOWCAST_LAT_MIN: float = 45.6
_NOWCAST_LAT_MAX: float = 49.38
_NOWCAST_LON_MIN: float = 8.2
_NOWCAST_LON_MAX: float = 17.64


def _in_nowcast_bbox(lat: float, lon: float) -> bool:
    """True wenn Koordinaten innerhalb des GeoSphere-Nowcast-Rasters liegen."""
    return (
        _NOWCAST_LAT_MIN <= lat <= _NOWCAST_LAT_MAX
        and _NOWCAST_LON_MIN <= lon <= _NOWCAST_LON_MAX
    )


def _params_suffix() -> str:
    # Parameter MUESSEN einzeln wiederholt werden (kommasepariert -> HTTP 422).
    # B116: KEIN ffx mehr (nicht im nowcast-v1-15min-1km verfuegbar -> HTTP 400).
    return f"parameters=rr&parameters=ff&forecast_offset={_FORECAST_OFFSET}"


def _build_nowcast_url(lat: float, lon: float) -> str:
    # lat_lon MUSS literales Komma behalten (lat_lon=46.526,14.548).
    # requests(..., params=...) kodiert das Komma zu %2C -> HTTP 400.
    # Deshalb URL manuell bauen. B104: forecast_offset=0, kein start/end.
    return f"{_BASE_URL}?lat_lon={lat},{lon}&{_params_suffix()}"


def _cache_suffix(now: datetime) -> str:
    # Cache rotiert mit dem 15-min-Raster (Nowcast-Aktualisierung), TTL _TTL s.
    _floor = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
    return _floor.strftime("%Y-%m-%dT%H:%M")


# B131: Out-of-Coverage-Gedaechtnis.
# Koordinaten, die HTTP-4xx liefern (kein Nowcast-Punkt im 1km-INCA-Raster),
# werden hier mit Epoch-Zeitstempel gemerkt und fuer _OOC_TTL_S Sekunden nicht
# erneut angefragt (zieldefinition.txt: unnoetige Requests vermeiden). Nach Ablauf
# der TTL erfolgt ein erneuter Test (transienter 4xx / Coverage-Aenderung).
_OOC_TTL_S = 86400  # 24 h Re-Test


def _ooc_file() -> str:
    try:
        from config import SAVE_PATHS
        _base = SAVE_PATHS.get("evaluation", "train_data/evaluation")
    except Exception:
        _base = "train_data/evaluation"
    return os.path.join(str(_base).rstrip("/"), "nowcast_out_of_coverage.json")


def _ooc_key(coord: tuple) -> str:
    return f"{round(float(coord[0]), 3)},{round(float(coord[1]), 3)}"


def _ooc_load() -> dict:
    try:
        with open(_ooc_file(), "r", encoding="utf-8") as _f:
            _d = json.load(_f)
        return _d if isinstance(_d, dict) else {}
    except Exception:
        return {}


def _ooc_save(d: dict) -> None:
    try:
        _path = _ooc_file()
        os.makedirs(os.path.dirname(_path), exist_ok=True)
        with open(_path, "w", encoding="utf-8") as _f:
            json.dump(d, _f, ensure_ascii=False)
    except Exception as _exc:
        debug_log(f"[NOWCAST] OOC-Schreibfehler: {_exc}")


def _ooc_mark(coord: tuple) -> None:
    _d = _ooc_load()
    _d[_ooc_key(coord)] = time.time()
    _ooc_save(_d)
    debug_log(
        f"[NOWCAST] Out-of-Coverage gemerkt: {_ooc_key(coord)} "
        f"(kein Request fuer {_OOC_TTL_S // 3600} h)"
    )


def _ooc_clear(coord: tuple) -> None:
    _d = _ooc_load()
    if _ooc_key(coord) in _d:
        _d.pop(_ooc_key(coord), None)
        _ooc_save(_d)
        debug_log(
            f"[NOWCAST] Out-of-Coverage aufgehoben (Daten wieder verfuegbar): "
            f"{_ooc_key(coord)}"
        )


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

    # B105: Koordinaten außerhalb des INCA-Rasters überspringen (400-Quelle).
    # B131: zusätzlich Koordinaten überspringen, die im Out-of-Coverage-Gedächtnis
    #       stehen (zuvor HTTP-4xx, TTL nicht abgelaufen) → kein erneuter Request.
    _ooc_now = time.time()
    _ooc_map = _ooc_load()

    def _is_ooc(c) -> bool:
        _ts = _ooc_map.get(_ooc_key(c))
        try:
            return _ts is not None and (_ooc_now - float(_ts)) < _OOC_TTL_S
        except (TypeError, ValueError):
            return False

    _valid_indices = [
        i for i, c in enumerate(_coords)
        if c is not None and _in_nowcast_bbox(c[0], c[1]) and not _is_ooc(c)
    ]
    _outside = [
        i for i, c in enumerate(_coords)
        if c is not None and not _in_nowcast_bbox(c[0], c[1])
    ]
    _ooc_skipped = [
        i for i, c in enumerate(_coords)
        if c is not None and _in_nowcast_bbox(c[0], c[1]) and _is_ooc(c)
    ]
    if _outside:
        debug_log(
            f"[NOWCAST] {len(_outside)} Objekt(e) außerhalb INCA-Bbox "
            f"(45.6–49.38°N, 8.2–17.64°E) → Default-Werte, kein API-Call."
        )
    if _ooc_skipped:
        debug_log(
            f"[NOWCAST] {len(_ooc_skipped)} Objekt(e) im Out-of-Coverage-Gedächtnis "
            f"→ Default-Werte, kein API-Call (Re-Test nach {_OOC_TTL_S // 3600} h)."
        )
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

    _resp = None
    try:
        _t0 = _t_nowcast_mod.monotonic()
        from http_retry import retry_get
        # B151: zentraler retry_get + Circuit-Breaker ("geosphere_nowcast").
        _resp = retry_get(_url, service="geosphere_nowcast",
                          breaker_service="geosphere_nowcast",
                          timeout=_TIMEOUT, headers={"Accept": "application/json"})
        _dur_ms = (_t_nowcast_mod.monotonic() - _t0) * 1000

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

    except Exception as _exc:
        # B151: retry_get hat den Fehler bereits in beiden Logpfaden protokolliert
        # (log_api_failure + log_api_call unter "geosphere_nowcast", inkl. 4xx-Body) und
        # den Breaker bedient. Defaults sind bereits befüllt → nur Fallback zurückgeben.
        # CircuitOpenError (offener Breaker) = bewusster Skip ohne erneutes Fehl-Logging.
        debug_log(f"[NOWCAST] Bulk-Fehler/Fallback: {type(_exc).__name__}: {_exc}")
        return objects


def _parse_nowcast_single(coord: tuple) -> dict:
    """Fallback-Einzelabfrage wenn die Bulk-Response unvollstaendig ist.
    B104: forecast_offset=0, kein start/end.
    B131: HTTP-4xx fuer eine konkrete Koordinate -> dauerhaft keine Nowcast-Daten
    an diesem Punkt (ausserhalb 1km-Raster). Koordinate wird ins
    Out-of-Coverage-Gedaechtnis aufgenommen (kuenftig kein Request) und der Fehler
    konsistent in BEIDEN Logpfaden (Zaehler + Fehler-Log) unter identischem
    Service-Namen 'geosphere_nowcast' protokolliert."""
    import time as _t_single

    _lat, _lon = coord
    _url = _build_nowcast_url(_lat, _lon)
    try:
        _t0 = _t_single.monotonic()
        from http_retry import retry_get
        # B151: zentraler retry_get + Circuit-Breaker ("geosphere_nowcast").
        _r = retry_get(_url, service="geosphere_nowcast",
                       breaker_service="geosphere_nowcast",
                       timeout=_TIMEOUT, headers={"Accept": "application/json"})
        _dur_ms = (_t_single.monotonic() - _t0) * 1000
        log_api_call(
            "geosphere_nowcast", url=_url, status_code=_r.status_code,
            duration_ms=_dur_ms, method="GET",
        )
        # B131: Erfolgreicher Abruf -> evtl. vorhandene OOC-Markierung aufheben.
        _ooc_clear(coord)
        _feat = _r.json().get("features", [{}])
        return _parse_nowcast(_feat[0] if _feat else {}, url=_url)
    except Exception as _exc:
        _exc_resp = getattr(_exc, "response", None)
        _status = getattr(_exc_resp, "status_code", None) or 0
        # B131: Nur echte HTTP-4xx (keine Daten an diesem Punkt) markieren.
        # Timeout/Connection/5xx/CircuitOpen sind transient -> NICHT merken.
        if 400 <= _status < 500:
            _ooc_mark(coord)
        # B151: retry_get hat den Fehler bereits in beiden Logpfaden protokolliert und den
        # Breaker bedient → kein Doppel-Log mehr hier.
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
        ff_kmh = round(ff * 3.6, 1)
        rate_1h = round(rr * 4, 2)
        # B116: nowcast_ffx_kmh bleibt als Feld erhalten (ML-Feature-Konsistenz),
        # wird vom Nowcast aber nicht mehr geliefert -> 0.0. Boeenwarnung kommt
        # in main.py aus TAWES (tawes_max_gust_kmh) bzw. AROME (wind_gust_10m_kmh).
        result.update({
            "nowcast_rr_mm15": round(rr, 3),
            "nowcast_ff_kmh": ff_kmh,
            "nowcast_ffx_kmh": 0.0,
            "nowcast_rain_rate_1h": rate_1h,
            "gust_warning": False,
            "heavy_rain_warning": rate_1h >= HEAVY_RAIN_MM_PER_H,
        })
    except Exception as exc:
        debug_log(f"[NOWCAST] Parse-Fehler: {exc}")
    return result
