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
    # B92: Letzten abgeschlossenen 15-min-Slot abfragen, nicht den laufenden.
    # Der zweite Eintrag ist ein konservativer Fallback-Slot, falls GeoSphere den
    # letzten abgeschlossenen Slot noch nicht vollständig bereitgestellt hat.
    return [
        {
            "start_str": (_floor - _td15).strftime("%Y-%m-%dT%H:%M"),
            "end_str": _floor.strftime("%Y-%m-%dT%H:%M"),
            "cache_sfx": (_floor - _td15).strftime("%Y-%m-%dT%H:%M"),
        },
        {
            "start_str": (_floor - 2 * _td15).strftime("%Y-%m-%dT%H:%M"),
            "end_str": (_floor - _td15).strftime("%Y-%m-%dT%H:%M"),
            "cache_sfx": (_floor - 2 * _td15).strftime("%Y-%m-%dT%H:%M"),
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


def assign_nowcast_to_objects(objects: list, timestamp: str | None = None) -> list:
    """
    Weist jedem Objekt aktuelle Nowcast-Werte zu (Niederschlag, Wind, Böen).

    B92: Letzten abgeschlossenen 15-min-Slot abfragen (nicht den laufenden).
         GeoSphere berechnet Nowcast erst nach Slot-Abschluss — laufender
         Slot liefert HTTP 400.

    B93: Bulk-Request — alle Zellen in einem einzigen HTTP-Call statt N
         Einzelrequests. GeoSphere gibt features-Array zurück, Reihenfolge
         entspricht der Eingabe-Reihenfolge der lat_lon-Parameter.

    ``timestamp`` bleibt als optionaler Parameter erhalten, weil bestehende
    Aufrufer den Wert weiterhin übergeben; für den Nowcast-Slot ist immer die
    aktuelle UTC-Zeit maßgeblich.
    """
    import time as _t_nowcast_mod
    from datetime import timedelta

    if not objects:
        return objects

    for obj in objects:
        obj.update(_DEFAULT)

    _now = datetime.now(timezone.utc)
    _td15 = timedelta(minutes=15)
    _floor = _now.replace(
        minute=(_now.minute // 15) * 15, second=0, microsecond=0
    )

    # B92: abgeschlossene Slots (nicht laufenden _floor ... _floor+15)
    _slots = [
        {
            "start_str": (_floor - _td15).strftime("%Y-%m-%dT%H:%M"),
            "end_str": _floor.strftime("%Y-%m-%dT%H:%M"),
            "cache_sfx": (_floor - _td15).strftime("%Y-%m-%dT%H:%M"),
        },
        {
            "start_str": (_floor - 2 * _td15).strftime("%Y-%m-%dT%H:%M"),
            "end_str": (_floor - _td15).strftime("%Y-%m-%dT%H:%M"),
            "cache_sfx": (_floor - 2 * _td15).strftime("%Y-%m-%dT%H:%M"),
        },
    ]

    # B93: Koordinaten aller Objekte sammeln (Reihenfolge merken)
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

    for _slot in _slots:
        # Cache-Key für diesen Bulk-Slot
        _coord_cache_component = ";".join(
            f"{_coords[i][0]},{_coords[i][1]}" for i in _valid_indices
        )
        _ck = cache_key(
            "geosphere:nowcast_bulk",
            _coord_cache_component,
            _slot["cache_sfx"],
        )
        _cached = cache_get(_ck, ttl_seconds=_TTL)
        if _cached is not None:
            # Cache-Treffer: Ergebnisse direkt zuweisen
            for list_pos, obj_idx in enumerate(_valid_indices):
                if list_pos < len(_cached):
                    objects[obj_idx].update(_cached[list_pos])
            debug_log(
                f"[NOWCAST] Bulk Cache-HIT — {len(_valid_indices)} Objekte, "
                f"Slot {_slot['start_str']}"
            )
            return objects

        # Bulk-URL aufbauen: alle gültigen Koordinaten als repeated lat_lon
        _lat_lon_parts = "&".join(
            f"lat_lon={_coords[i][0]},{_coords[i][1]}"
            for i in _valid_indices
        )
        _url = (
            f"{_BASE_URL}"
            f"?{_lat_lon_parts}"
            f"&parameters=rr&parameters=ff&parameters=ffx"
            f"&start={_slot['start_str']}&end={_slot['end_str']}"
        )

        try:
            _t0 = _t_nowcast_mod.monotonic()
            _resp = requests.get(
                _url,
                timeout=_TIMEOUT,
                headers={"Accept": "application/json"},
            )
            _dur_ms = (_t_nowcast_mod.monotonic() - _t0) * 1000

            if _resp.status_code == 422:
                _body = (_resp.text or "")[:200]
                debug_log(
                    f"[NOWCAST] Bulk Slot {_slot['start_str']} HTTP 422 "
                    f"({_body}) — Fallback-Slot"
                )
                log_api_failure(
                    "geosphere_nowcast", _url,
                    f"http-422 | {_body}",
                    fallback_used=True, http_status=422,
                )
                log_api_call(
                    "geosphere_nowcast", url=_url, status_code=422,
                    duration_ms=_dur_ms, method="GET",
                    response_text=_body,
                    error=f"http-422 | {_body}",
                )
                continue  # Fallback-Slot versuchen

            _resp.raise_for_status()

            log_api_call(
                "geosphere_nowcast", url=_url, status_code=_resp.status_code,
                duration_ms=_dur_ms, method="GET",
            )

            _data = _resp.json()
            _features = _data.get("features", [])

            if len(_features) != len(_valid_indices):
                debug_log(
                    f"[NOWCAST] Bulk: {len(_features)} Features für "
                    f"{len(_valid_indices)} Objekte — Fallback auf Einzelabfragen"
                )
                # Fallback: Einzelabfragen für alle Objekte
                _results = []
                for i in _valid_indices:
                    _r = _parse_nowcast_single(
                        _coords[i], _slot, _BASE_URL
                    )
                    _results.append(_r)
            else:
                # Normalpfad: Feature i gehört zu _valid_indices[i]
                _results = [
                    _parse_nowcast(_feature_data, url=_url)
                    for _feature_data in _features
                ]

            # Ergebnisse zuweisen und cachen
            _cache_data = []
            for list_pos, obj_idx in enumerate(_valid_indices):
                if list_pos < len(_results):
                    objects[obj_idx].update(_results[list_pos])
                    _cache_data.append(_results[list_pos])
            cache_set(_ck, _cache_data)

            debug_log(
                f"[NOWCAST] Bulk OK — {len(_valid_indices)} Objekte, "
                f"Slot {_slot['start_str']}, {_dur_ms:.0f} ms"
            )
            return objects

        except requests.exceptions.HTTPError as _exc:
            _status = getattr(_exc.response, "status_code", None) or 0
            log_api_failure(
                "geosphere_nowcast", _url,
                str(_exc), fallback_used=True, http_status=_status,
            )
            log_api_call(
                "geosphere_nowcast", url=_url, status_code=_status,
                method="GET", error=str(_exc),
            )
            break
        except Exception as _exc:
            log_api_failure(
                "geosphere_nowcast", _url, str(_exc), fallback_used=True
            )
            break

    return objects


def _parse_nowcast_single(
    coord: tuple,
    slot: dict,
    base_url: str,
) -> dict:
    """
    Fallback-Einzelabfrage wenn Bulk-Response unvollständig ist.
    Wird nur aufgerufen wenn len(features) != len(objects).
    """
    import time as _t_single

    _lat, _lon = coord
    _url = (
        f"{base_url}"
        f"?lat_lon={_lat},{_lon}"
        f"&parameters=rr&parameters=ff&parameters=ffx"
        f"&start={slot['start_str']}&end={slot['end_str']}"
    )
    try:
        _t0 = _t_single.monotonic()
        _r = requests.get(
            _url,
            timeout=_TIMEOUT,
            headers={"Accept": "application/json"},
        )
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
    """
    Parst ein einzelnes GeoJSON-Feature aus der Nowcast-Response.
    Ersetzt den bisherigen _parse_nowcast(data, url) der ein volles
    FeatureCollection-Dict erwartet hatte.
    """
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
