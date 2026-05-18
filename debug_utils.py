# debug_utils.py

import cv2
import os
import utils
from utils import log

from config import DEBUG_MODE  # Ein-/Ausschalten über config.py

def save_debug_image(path, image, message=None):
    if DEBUG_MODE:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        cv2.imwrite(path, image)
        if message:
            debug_log(f"[DEBUG] {message}: {path}")

def debug_log(message):
    if DEBUG_MODE:
        from datetime import datetime
        print(f"[{datetime.now().isoformat(timespec='seconds')}] DEBUG: {message}")

# --- API-Failure-Logging (einheitliches Schema) ---
import json as _json
import os as _os
from datetime import datetime as _dt

try:
    from config import SAVE_PATHS as _SAVE_PATHS_DU
    _API_HEALTH_FILE = _os.path.join(
        _SAVE_PATHS_DU.get("evaluation", "train_data/evaluation/").rstrip("/"),
        "api_health.jsonl",
    )
except Exception:
    _API_HEALTH_FILE = "train_data/evaluation/api_health.jsonl"

def log_api_failure(service: str, url: str, reason: str,
                    fallback_used: bool = False, http_status: int = None):
    """
    Loggt eine fehlgeschlagene API-Anfrage strukturiert.
    service: Name der Quelle (z. B. "GeoSphere-AROME", "Open-Meteo-icon_d2",
             "GeoSphere-TAWES", "GeoSphere-CAPE", "ARSO-Radar")
    url: Vollständige URL des fehlgeschlagenen Aufrufs
    reason: Knappe technische Ursache (Timeout, HTTPError, JSONDecodeError,
            no-data-for-timestamp, missing-field, ...)
    fallback_used: True wenn auf Default-Werte / letzten Cache zurückgefallen
    http_status: HTTP-Statuscode falls verfügbar (z. B. 404, 500, 503)
    """
    rec = {
        "ts_utc": _dt.utcnow().isoformat(timespec="seconds") + "Z",
        "service": service,
        "url": url,
        "reason": reason,
        "fallback_used": bool(fallback_used),
    }
    if http_status is not None:
        rec["http_status"] = int(http_status)
    debug_log(f"[API-FAIL] {service}: {reason} "
              f"(fallback={fallback_used}, http={http_status}) URL={url}")
    try:
        _os.makedirs(_os.path.dirname(_API_HEALTH_FILE), exist_ok=True)
        with open(_API_HEALTH_FILE, "a", encoding="utf-8") as f:
            f.write(_json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as exc:
        debug_log(f"[API-FAIL] Konnte api_health.jsonl nicht schreiben: {exc}")

def api_health_summary(since_hours: int = 24) -> dict:
    """Aggregiert API-Fehler der letzten N Stunden für das Admin-Panel."""
    from datetime import timedelta as _td
    summary = {}
    if not _os.path.exists(_API_HEALTH_FILE):
        return {"since_hours": since_hours, "total": 0, "by_service": {}}
    cutoff = _dt.utcnow() - _td(hours=since_hours)
    total = 0
    try:
        with open(_API_HEALTH_FILE, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    rec = _json.loads(line.strip())
                    ts = _dt.fromisoformat(rec.get("ts_utc", "").replace("Z", ""))
                    if ts < cutoff:
                        continue
                    svc = rec.get("service", "unknown")
                    entry = summary.setdefault(svc, {
                        "count": 0, "reasons": {}, "fallback_count": 0,
                        "last_ts": None, "last_url": None,
                    })
                    entry["count"] += 1
                    reason = rec.get("reason", "unknown")
                    entry["reasons"][reason] = entry["reasons"].get(reason, 0) + 1
                    if rec.get("fallback_used"):
                        entry["fallback_count"] += 1
                    entry["last_ts"] = rec.get("ts_utc")
                    entry["last_url"] = rec.get("url")
                    total += 1
                except Exception:
                    continue
    except Exception as exc:
        debug_log(f"[API-FAIL] api_health_summary Lesefehler: {exc}")
    return {"since_hours": since_hours, "total": total, "by_service": summary}

# ── API-Request-Zähler ────────────────────────────────────────────────────────
import threading as _rq_threading
_rq_lock = _rq_threading.Lock()


def log_api_call(service: str, url: str = "", status_code: int = 200) -> None:
    """
    Zählt jeden API-Aufruf (Erfolg + Fehler) pro Service in JSONL-Datei.
    Thread-sicher. Nie blockierend — Fehler werden still ignoriert.

    Servicenamen (einheitlich verwenden):
      "arso_radar"           — radar_download.py
      "openmeteo_icon_d2"   — fetch_arome_openmeteo.py
      "openmeteo_icon_global"— fetch_synoptic_features.py / 700hPa
      "geosphere_cape"      — assign_cape_from_forecast.py
      "eumetview_wms"       — cloud_height_from_eumetview.py
      "blitzortung"         — blitzortung.py / lightning-Loader
      "anthropic_api"       — daily_analyzer.py
    """
    import datetime as _dt, json as _jc, os as _oc
    from config import SAVE_PATHS
    entry = {
        "ts":      _dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "service": service,
        "url":     (url or "")[:120],
        "status":  status_code,
    }
    log_path = _oc.path.join(
        SAVE_PATHS.get("evaluation", "train_data/evaluation"),
        "api_call_counts.jsonl",
    )
    try:
        _oc.makedirs(_oc.path.dirname(log_path), exist_ok=True)
        with _rq_lock:
            with open(log_path, "a", encoding="utf-8") as _f:
                _jc.dump(entry, _f, ensure_ascii=False)
                _f.write("\n")
    except Exception:
        pass  # Nie den Hauptprozess blockieren


def api_call_summary(since_hours: int = 24) -> dict:
    """Liest api_call_counts.jsonl und aggregiert Counts + Fehler pro Service."""
    import datetime as _dt, json as _jc, os as _oc
    from config import SAVE_PATHS
    log_path = _oc.path.join(
        SAVE_PATHS.get("evaluation", "train_data/evaluation"),
        "api_call_counts.jsonl",
    )
    if not _oc.path.exists(log_path):
        return {"by_service": {}, "since_hours": since_hours}
    cutoff = _dt.datetime.utcnow() - _dt.timedelta(hours=since_hours)
    by_service: dict = {}
    try:
        with open(log_path, "r", encoding="utf-8") as _f:
            for line in _f:
                try:
                    rec = _jc.loads(line.strip())
                    ts  = _dt.datetime.fromisoformat(rec.get("ts", "").replace("Z", ""))
                    if ts < cutoff:
                        continue
                    svc = rec.get("service", "unknown")
                    if svc not in by_service:
                        by_service[svc] = {"calls": 0, "errors": 0}
                    by_service[svc]["calls"] += 1
                    if int(rec.get("status", 200)) >= 400:
                        by_service[svc]["errors"] += 1
                except Exception:
                    continue
    except Exception:
        pass
    return {"by_service": by_service, "since_hours": since_hours}

