"""
Täglicher Connectivity- und Spec-Check für alle externen APIs.

Prüft:
  ARSO       — KMZ-Radar-URL antwortet mit gültiger ZIP-Antwort
  Open-Meteo — icon_d2 Forecast-URL antwortet mit JSON
  GeoSphere  — Nowcast v1 API antwortet mit JSON
  EUMETView  — WMS GetCapabilities antwortet mit XML
  Blitzortung — Protected endpoint erreichbar (Basic-Auth-Check)

Ergebnis: train_data/evaluation/api_health_latest.json
"""

import json
import os
import time
from datetime import datetime, timezone

from config import SAVE_PATHS
from debug_utils import debug_log

_EVAL_DIR = SAVE_PATHS.get("evaluation", "train_data/evaluation").rstrip("/")
_STATUS_FILE = os.path.join(_EVAL_DIR, "api_health_latest.json")

# Timeout je Request
_TIMEOUT = 15


def _check_arso() -> dict:
    """ARSO KMZ-Radar: gibt gültigen ZIP zurück."""
    import io
    import zipfile

    try:
        from radar_download import KMZ_URL as url
    except Exception:
        url = os.getenv(
            "ARSO_KMZ_URL",
            "https://meteo.arso.gov.si/uploads/probase/www/nowcast/inca/inca_si0zm_latest.kmz",
        )
    t0 = time.monotonic()
    try:
        from http_retry import retry_get

        r = retry_get(url, service="ARSO-Health", timeout=_TIMEOUT, max_retries=1)
        elapsed = time.monotonic() - t0
        # Zip-Signatur prüfen
        ok = zipfile.is_zipfile(io.BytesIO(r.content))
        return {
            "ok": ok,
            "status": r.status_code,
            "latency_ms": round(elapsed * 1000),
            "note": "ZIP gültig" if ok else "ZIP ungültig",
        }
    except Exception as exc:
        return {"ok": False, "status": None, "latency_ms": None, "note": str(exc)[:100]}


def _check_openmeteo() -> dict:
    """Open-Meteo icon_d2: antwortet mit JSON-Objekt."""
    url = (
        "https://api.open-meteo.com/v1/forecast"
        "?latitude=46.62&longitude=14.31"
        "&hourly=temperature_2m&models=icon_d2&forecast_days=1"
    )
    t0 = time.monotonic()
    try:
        from http_retry import retry_get

        r = retry_get(url, service="OpenMeteo-Health", timeout=_TIMEOUT, max_retries=1)
        elapsed = time.monotonic() - t0
        data = r.json()
        ok = "hourly" in data
        return {
            "ok": ok,
            "status": r.status_code,
            "latency_ms": round(elapsed * 1000),
            "note": "hourly-Key vorhanden" if ok else "hourly fehlt in Response",
        }
    except Exception as exc:
        return {"ok": False, "status": None, "latency_ms": None, "note": str(exc)[:100]}


def _check_geosphere() -> dict:
    """
    GeoSphere Nowcast v1: JSON mit features-Array.
    URL nutzt lat_lon=46.62,14.31 mit literalem Komma.
    WICHTIG: Parameter müssen EINZELN wiederholt werden, NICHT kommasepariert.
    ?parameters=rr&parameters=ff&parameters=ffx → OK
    ?parameters=rr,ff,ffx                       → HTTP 422
    Zeitformat: %Y-%m-%dT%H:%M (Minutenauflösung, ohne Sekunden/Z-Suffix).
    """
    from datetime import timedelta, timezone as _tz

    _now = datetime.now(_tz.utc)
    # Vorherigen Slot abfragen — immer vollständig berechnet.
    # Identisch zu fetch_geosphere_nowcast.py (Prompt-15-Fix):
    # _floor selbst (= aktueller Slot) → HTTP 422 bis Nowcast berechnet ist.
    _floor = _now.replace(minute=(_now.minute // 15) * 15, second=0, microsecond=0)
    _start = (_floor - timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M")
    _end   = _floor.strftime("%Y-%m-%dT%H:%M")
    # URL manuell bauen — kein params=-Argument, sonst kodiert requests das
    # Komma in lat_lon=46.62,14.31 zu %2C → HTTP 400 "Bad Request".
    # Identische Lösung wie fetch_geosphere_nowcast.py (B58).
    _base = "https://dataset.api.hub.geosphere.at/v1/timeseries/forecast/nowcast-v1-15min-1km"
    url = (
        f"{_base}?lat_lon=46.62,14.31"
        f"&parameters=rr&parameters=ff&parameters=ffx"
        f"&start={_start}&end={_end}"
    )
    t0 = time.monotonic()
    try:
        from http_retry import retry_get

        r = retry_get(
            url,                    # URL enthält alle Parameter — kein params=
            service="GeoSphere-Health",
            timeout=_TIMEOUT,
            max_retries=1,
            headers={"Accept": "application/json"},
        )
        elapsed = time.monotonic() - t0
        data = r.json()
        ok = "features" in data and len(data["features"]) > 0
        return {
            "ok": ok,
            "status": r.status_code,
            "latency_ms": round(elapsed * 1000),
            "note": f"features: {len(data.get('features', []))} Einträge" if ok else "features leer oder fehlt",
        }
    except Exception as exc:
        return {"ok": False, "status": None, "latency_ms": None, "note": str(exc)[:100]}


def _check_eumetview() -> dict:
    """EUMETView WMS GetCapabilities: antwortet mit XML."""
    url = (
        "https://view.eumetsat.int/geoserver/wms"
        "?SERVICE=WMS&REQUEST=GetCapabilities&VERSION=1.3.0"
    )
    t0 = time.monotonic()
    try:
        from http_retry import retry_get

        r = retry_get(url, service="EUMETView-Health", timeout=_TIMEOUT, max_retries=1)
        elapsed = time.monotonic() - t0
        ok = b"<WMS_Capabilities" in r.content[:500] or b"WMS_Capabilities" in r.content[:500]
        return {
            "ok": ok,
            "status": r.status_code,
            "latency_ms": round(elapsed * 1000),
            "note": "WMS_Capabilities vorhanden" if ok else "kein WMS_Capabilities-Tag",
        }
    except Exception as exc:
        return {"ok": False, "status": None, "latency_ms": None, "note": str(exc)[:100]}


def _check_blitzortung() -> dict:
    """Blitzortung: Basic-Auth-Endpoint erreichbar."""
    blitz_user = os.getenv("BLITZ_USERNAME", "")
    blitz_pass = os.getenv("BLITZ_PASSWORD", "")
    if not blitz_user or not blitz_pass:
        return {
            "ok": None,
            "status": None,
            "latency_ms": None,
            "note": "BLITZ_USERNAME/PASSWORD nicht gesetzt — übersprungen",
        }
    url = (
        "https://data.blitzortung.org/Data/Protected/last_strikes.php"
        "?number=1&west=12&east=16&north=47.5&south=46"
    )
    t0 = time.monotonic()
    try:
        from http_retry import retry_get

        r = retry_get(
            url,
            service="Blitzortung-Health",
            timeout=_TIMEOUT,
            max_retries=1,
            auth=(blitz_user, blitz_pass),
            abort_on_4xx=False,
        )
        elapsed = time.monotonic() - t0
        ok = r.status_code in (200, 204)
        return {
            "ok": ok,
            "status": r.status_code,
            "latency_ms": round(elapsed * 1000),
            "note": f"HTTP {r.status_code}",
        }
    except Exception as exc:
        return {"ok": False, "status": None, "latency_ms": None, "note": str(exc)[:100]}


def check_all_apis() -> dict:
    """
    Führt Health-Checks für alle externen APIs durch.
    Schreibt Ergebnis in api_health_latest.json.
    Gibt das Ergebnis-Dict zurück.
    """
    debug_log("[API-HEALTH] Starte täglichen Connectivity-Check...")
    checks = {
        "arso": _check_arso,
        "open_meteo": _check_openmeteo,
        "geosphere": _check_geosphere,
        "eumetview": _check_eumetview,
        "blitzortung": _check_blitzortung,
    }
    results = {}
    for name, fn in checks.items():
        try:
            results[name] = fn()
        except Exception as exc:
            results[name] = {"ok": False, "note": f"Exception: {exc}"}
        status = results[name].get("ok")
        icon = "✅" if status is True else ("⚠" if status is None else "❌")
        debug_log(f"[API-HEALTH] {icon} {name}: {results[name].get('note', '')}")

    all_ok = all(v.get("ok") is not False for v in results.values())
    summary = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z",
        "all_ok": all_ok,
        "results": results,
    }
    os.makedirs(_EVAL_DIR, exist_ok=True)
    try:
        with open(_STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        debug_log(f"[API-HEALTH] Schreibfehler: {exc}")
    return summary


def load_status() -> dict:
    """Letzten Health-Status laden (für API-Endpoint)."""
    if not os.path.exists(_STATUS_FILE):
        return {"all_ok": None, "note": "Noch kein Check durchgeführt"}
    try:
        with open(_STATUS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"all_ok": None, "note": "Status nicht lesbar"}
