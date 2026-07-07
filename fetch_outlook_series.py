# fetch_outlook_series.py
"""
Holt die stuendliche Zeitreihe (+0..+12 h) der konvektiven Felder fuer die
Kaernten-Rasterpunkte (ATM_SNAPSHOT_LOCATIONS) und schreibt sie als
train_data/forecast/atmosphere_timeseries.json.

Schonend: Frische-Guard (kein Request wenn Datei juenger als TTL) + Batching.
Robuste Parameter-Fallback-Logik gegen Open-Meteo-400 bei unbekanntem Param.
"""

import os
import json
import time
import time as _time_outlook
import importlib.util
from datetime import datetime, timezone

import requests

import api_circuit_breaker
from config import ATM_SNAPSHOT_LOCATIONS, SAVE_PATHS
from debug_utils import debug_log, log_api_failure, log_http_response
import runtime_config

_URL          = "https://api.open-meteo.com/v1/forecast"
_TZ           = "Europe/Vienna"
_TIMEOUT      = (5, 15)
_BATCH_SIZE   = 4
_FORECAST_H   = 13          # +0..+12 h => 13 Stundenwerte
_DEFAULT_TTL  = 60          # Minuten

_OUT_DIR = os.path.join(
    os.path.dirname(SAVE_PATHS.get("evaluation", "train_data/evaluation/").rstrip("/")),
    "forecast",
)
_OUT_FILE = os.path.join(_OUT_DIR, "atmosphere_timeseries.json")
OUTLOOK_SERVICE = "open_meteo_outlook"
MAX_REQUESTS_PER_RUN = int(os.getenv("OUTLOOK_SERIES_MAX_REQUESTS_PER_RUN", "9"))
# B313: Hartes Wall-Time-Budget fuer den GESAMTEN Lauf (alle Batches zusammen),
# deutlich unter systemd WatchdogSec (60s Default). Verhindert, dass ein
# haengender/langsamer Open-Meteo-Endpoint ueber mehrere Batches hinweg den
# Scheduler-Prozess per Watchdog-Timeout abschiesst.
OUTLOOK_SERIES_MAX_WALLTIME_S = float(os.getenv("OUTLOOK_SERIES_MAX_WALLTIME_S", "25"))

# Vollsatz und Minimalsatz (Fallback). Reihenfolge unwichtig.
# convective_inhibition und precipitable_water sind für ICON (Default-Modell für AT)
# nicht verfügbar → HTTP 400. Beide werden per Zelle über fetch_openmeteo_extended.py
# (GFS-Endpoint) korrekt geliefert. Im Grid-Outlook fehlen sie — Fallback in
# convective_outlook.py._cell_severity() kompensiert dies.
_HOURLY_FULL = ",".join([
    "cape", "lifted_index", "freezing_level_height",
    "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m",
    "wind_speed_700hPa", "wind_direction_700hPa",
    "temperature_500hPa", "temperature_700hPa",
])
_HOURLY_MIN = ",".join([
    "cape", "lifted_index", "wind_speed_10m", "wind_direction_10m", "freezing_level_height",
])


def _load_fallback(status="circuit_open_no_fallback"):
    try:
        with open(_OUT_FILE, encoding="utf-8") as f:
            payload = json.load(f)
        if isinstance(payload, dict):
            payload.setdefault("status", "stale_fallback")
            return payload
    except Exception:
        pass
    return {"points": [], "status": status}


def _retry_after_from(exc):
    try:
        value = exc.response.headers.get("Retry-After")
        return int(value) if value else None
    except Exception:
        return None


def _ttl_min():
    try:
        return int(runtime_config.get("OUTLOOK_SERIES_TTL_MIN", _DEFAULT_TTL))
    except Exception:
        return _DEFAULT_TTL


def _is_fresh():
    if not os.path.exists(_OUT_FILE):
        return False
    age_min = (time.time() - os.path.getmtime(_OUT_FILE)) / 60.0
    return age_min < _ttl_min()


def _batches(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _request(lats, lons, hourly):
    params = {
        "latitude":  ",".join(f"{x:.4f}" for x in lats),
        "longitude": ",".join(f"{x:.4f}" for x in lons),
        "hourly":    hourly,
        "forecast_days": 2,
        "timezone":  _TZ,
    }
    _t0 = _time_outlook.monotonic()
    from http_retry import retry_get as _rg_outlook
    # B313: max_retries=1 statt Default 2 — reduziert die maximale Blockierzeit
    # eines einzelnen Requests bei haengendem/langsamem Endpoint um die Haelfte;
    # kombiniert mit dem Wall-Time-Budget oben schuetzt das zuverlaessig gegen
    # den systemd-Watchdog (WatchdogSec=60s).
    r = _rg_outlook(_URL, params=params, timeout=_TIMEOUT,
                    service="Open-Meteo-Outlook", max_retries=1)
    _dur = (_time_outlook.monotonic() - _t0) * 1000
    r.raise_for_status()
    log_http_response("openmeteo_outlook", "GET", r, _dur)
    data = r.json()
    return data if isinstance(data, list) else [data]


def _series_from_point(point, start_idx):
    hourly = point.get("hourly", {}) or {}
    times = hourly.get("time", [])
    if not times:
        return []
    out = []
    for k in range(start_idx, min(start_idx + _FORECAST_H, len(times))):
        entry = {"valid": times[k], "offset_h": k - start_idx}
        for key, vals in hourly.items():
            if key == "time":
                continue
            entry[key] = vals[k] if k < len(vals) and vals[k] is not None else None
        out.append(entry)
    return out


def _now_hour_iso():
    return datetime.now().astimezone().strftime("%Y-%m-%dT%H:00")


def fetch_outlook_series(force=False):
    if api_circuit_breaker.is_open(OUTLOOK_SERVICE):
        debug_log("[OUTLOOK-SERIES] Circuit offen — Fallback wird genutzt")
        return _load_fallback()
    if not force and _is_fresh():
        debug_log("[OUTLOOK-SERIES] Cache frisch — kein Request")
        try:
            with open(_OUT_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    os.makedirs(_OUT_DIR, exist_ok=True)
    locs = list(ATM_SNAPSHOT_LOCATIONS)
    all_points = []
    requests_used = 0
    _t_run_start = _time_outlook.monotonic()
    for batch in _batches(locs, _BATCH_SIZE):
        if api_circuit_breaker.is_open(OUTLOOK_SERVICE):
            return _load_fallback()
        if requests_used >= MAX_REQUESTS_PER_RUN:
            log_api_failure("Open-Meteo-Outlook", _URL, "request-budget-exceeded", fallback_used=True)
            break
        # B313: Hartes Wall-Time-Budget — schuetzt den systemd-Watchdog unabhaengig
        # davon, wie viele Retries/Batches theoretisch noch erlaubt waeren.
        if (_time_outlook.monotonic() - _t_run_start) >= OUTLOOK_SERIES_MAX_WALLTIME_S:
            log_api_failure("Open-Meteo-Outlook", _URL, "walltime-budget-exceeded", fallback_used=True)
            break
        lats = [float(l["lat"]) for l in batch]
        lons = [float(l["lon"]) for l in batch]
        names = [l.get("name", "") for l in batch]
        data = None
        _conn_fail = False   # B127: True bei Verbindungsfehler (Host-weit)
        for hourly in (_HOURLY_FULL, _HOURLY_MIN):
            # B124: Budget vor jedem Einzelrequest prüfen — nicht nur am Batch-Anfang.
            # Ohne diesen Guard würden bei MAX_REQUESTS_PER_RUN=N beide hourly-Varianten
            # des letzten erlaubten Batches gemacht, auch wenn nach dem ersten Versuch
            # das Budget bereits erschöpft ist.
            if requests_used >= MAX_REQUESTS_PER_RUN:
                break
            # B318: Wall-Time-Budget zusaetzlich VOR dem zweiten hourly-Versuch pruefen,
            # nicht nur am Batch-Anfang. Sonst kann im HTTP-400-dann-Minimalparameter-
            # Pfad der erste Request das Budget bereits ausschoepfen, und der zweite
            # Request (_HOURLY_MIN) startet trotzdem noch ein komplettes neues
            # Timeout-Fenster — das hebelt das harte Wall-Time-Budget aus B313 aus.
            if (_time_outlook.monotonic() - _t_run_start) >= OUTLOOK_SERIES_MAX_WALLTIME_S:
                log_api_failure("Open-Meteo-Outlook", _URL, "walltime-budget-exceeded", fallback_used=True)
                break
            try:
                requests_used += 1
                data = _request(lats, lons, hourly)
                api_circuit_breaker.record_success(OUTLOOK_SERVICE)
                break
            except requests.exceptions.HTTPError as exc:
                _status = getattr(exc.response, "status_code", None)
                log_api_failure(
                    "Open-Meteo-Outlook", _URL,
                    f"http-{_status} (params: {hourly[:40]}...)",
                    fallback_used=True, http_status=_status,
                )
                if _status == 429:
                    api_circuit_breaker.open_circuit(OUTLOOK_SERVICE, _retry_after_from(exc) or api_circuit_breaker.CIRCUIT_COOLDOWN_429, "http-429")
                    return _load_fallback("http_429_fallback")
                api_circuit_breaker.record_failure(OUTLOOK_SERVICE, f"http-{_status}", http_status=_status)
            except (requests.exceptions.Timeout,
                    requests.exceptions.SSLError,
                    requests.exceptions.ConnectionError) as exc:
                # B127: Verbindungsproblem betrifft den gesamten Host — die zweite
                # hourly-Variante (MIN) würde identisch scheitern. Inneren Loop
                # abbrechen statt sinnlos erneut gegen einen toten Host zu rufen.
                api_circuit_breaker.record_failure(OUTLOOK_SERVICE, type(exc).__name__)
                log_api_failure(
                    "Open-Meteo-Outlook", _URL,
                    f"{type(exc).__name__}: {str(exc)[:80]}",
                    fallback_used=True,
                )
                _conn_fail = True
                break
            except Exception as exc:
                log_api_failure(
                    "Open-Meteo-Outlook", _URL,
                    f"{type(exc).__name__}: {str(exc)[:80]}",
                    fallback_used=True,
                )
                _conn_fail = True
                break
        # B127: Nach einem Verbindungsfehler Circuit prüfen — offen → sofort Fallback,
        # nicht weitere Orte/Batches gegen einen nicht erreichbaren Host feuern.
        if _conn_fail and api_circuit_breaker.is_open(OUTLOOK_SERVICE):
            return _load_fallback()
        if data is None:
            # "all-param-sets-failed" nur bei echten Parameter-/HTTP-Fehlern loggen,
            # nicht bei reinen Verbindungsproblemen (B127).
            if not _conn_fail:
                log_api_failure("Open-Meteo-Outlook", _URL,
                                "all-param-sets-failed", fallback_used=True)
            continue
        target_hour = _now_hour_iso()
        for name, lat, lon, point in zip(names, lats, lons, data):
            times = (point.get("hourly", {}) or {}).get("time", [])
            start_idx = times.index(target_hour) if target_hour in times else 0
            all_points.append({
                "name": name, "lat": lat, "lon": lon,
                "series": _series_from_point(point, start_idx),
            })

    if not all_points:
        return _load_fallback("all_param_sets_failed_fallback")
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "horizon_h": _FORECAST_H - 1,
        "points": all_points,
    }
    tmp = _OUT_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    os.replace(tmp, _OUT_FILE)
    debug_log(f"[OUTLOOK-SERIES] {len(all_points)} Punkte x {_FORECAST_H} h -> {_OUT_FILE}")
    return payload


if __name__ == "__main__":
    res = fetch_outlook_series(force=True)
    print("Punkte:", len(res.get("points", [])))
