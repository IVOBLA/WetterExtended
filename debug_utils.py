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
from urllib.parse import urlsplit as _urlsplit, urlunsplit as _urlunsplit, parse_qsl as _parse_qsl, urlencode as _urlencode

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
    # API-Fehler immer ausgeben — unabhängig von DEBUG_MODE
    # Produktionsfehler müssen in journalctl sichtbar sein
    print(
        f"[{_dt.utcnow().isoformat(timespec='seconds')}Z] [API-FAIL] "
        f"{service}: {reason} (fallback={fallback_used}, http={http_status})",
        flush=True,
    )
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


def log_api_call(service: str, url: str = "", status_code: int = 200,
                 duration_ms: float | None = None, method: str = "GET",
                 request_payload=None, response_payload=None,
                 response_text: str | None = None, content_type: str | None = None,
                 error: str | None = None) -> None:
    """
    Zählt jeden API-Aufruf (Erfolg + Fehler) pro Service in JSONL-Datei.
    Thread-sicher. Nie blockierend — Fehler werden still ignoriert.

    Servicenamen (einheitlich verwenden):
      "arso_radar"           — radar_download.py
      "openmeteo_icon_d2"   — fetch_arome_openmeteo.py
      "openmeteo_icon_global"— fetch_synoptic_features.py / 700hPa
      "geosphere_cape"      — assign_cape_from_forecast.py
      "geosphere_tawes"     — weather_api.py (Stationsdaten TAWES)
      "eumetview_wms"       — cloud_height_from_eumetview.py
      "blitzortung"         — blitz_api.py
      "anthropic_api"       — daily_analyzer.py
    """
    import datetime as _dt, json as _jc, os as _oc
    from config import SAVE_PATHS
    _MAX_URL = 2000
    _MAX_PREVIEW = 8000
    _SENSITIVE_KEYS = {"api_key", "apikey", "token", "access_token", "refresh_token", "password", "passwd", "secret", "authorization", "auth"}
    def _truncate(v: str, n: int):
        if v is None:
            return None, False
        s = str(v)
        return (s[:n] + "…", True) if len(s) > n else (s, False)
    def _mask_dict(d):
        if isinstance(d, dict):
            out = {}
            for k, v in d.items():
                if any(sk in str(k).lower() for sk in _SENSITIVE_KEYS):
                    out[k] = "***"
                else:
                    out[k] = _mask_dict(v)
            return out
        if isinstance(d, list):
            return [_mask_dict(x) for x in d]
        if isinstance(d, str) and ("bearer " in d.lower() or "token" in d.lower()):
            return "***"
        return d
    def _sanitize_url(raw_url: str) -> str:
        if not raw_url:
            return ""
        try:
            p = _urlsplit(str(raw_url))
            q = []
            for k, v in _parse_qsl(p.query, keep_blank_values=True):
                q.append((k, "***" if any(sk in k.lower() for sk in _SENSITIVE_KEYS) else v))
            clean = _urlunsplit((p.scheme, p.netloc, p.path, _urlencode(q, doseq=True), p.fragment))
        except Exception:
            clean = str(raw_url)
        return _truncate(clean, _MAX_URL)[0]
    def _payload_preview(payload):
        if payload is None:
            return None, False
        try:
            masked = _mask_dict(payload)
            text = _jc.dumps(masked, ensure_ascii=False, indent=2)
        except Exception:
            text = str(payload)
        return _truncate(text, _MAX_PREVIEW)
    def _response_preview():
        ctype = (content_type or "").lower()
        if response_payload is not None:
            return _payload_preview(response_payload)
        if response_text is None:
            if any(x in ctype for x in ("image/", "application/octet-stream", "application/vnd.google-earth.kmz", "application/zip", "application/x-tiff", "application/geotiff")):
                return (f"[binary response: content-type={content_type or 'unknown'}, size=unknown]", False)
            return None, False
        try:
            if "json" in ctype:
                parsed = _jc.loads(response_text)
                return _payload_preview(parsed)
        except Exception:
            pass
        masked_text = str(_mask_dict(response_text))
        return _truncate(masked_text, _MAX_PREVIEW)
    s_url = _sanitize_url(url or "")
    req_preview, req_trunc = _payload_preview(request_payload)
    resp_preview, resp_trunc = _response_preview()
    entry = {
        "ts":          _dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "service":     service,
        "method":      (method or "GET").upper(),
        "url":         s_url,
        "status":      status_code,
        "duration_ms": round(duration_ms, 1) if duration_ms is not None else None,
        "request": {
            "method": (method or "GET").upper(),
            "url": s_url,
            "payload_preview": req_preview,
            "truncated": req_trunc,
        },
        "response": {
            "status": status_code,
            "content_type": content_type,
            "body_preview": resp_preview,
            "truncated": resp_trunc,
            "error": error,
        },
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
                        by_service[svc] = {
                            "calls": 0, "errors": 0,
                            "last_ts": None, "last_url": None, "last_status": None,
                        }
                    by_service[svc]["calls"] += 1
                    if int(rec.get("status", 200)) >= 400:
                        by_service[svc]["errors"] += 1
                    # Letzten Request merken (JSONL ist chronologisch → letzter = aktuellster)
                    by_service[svc]["last_ts"]     = rec.get("ts")
                    by_service[svc]["last_url"]    = rec.get("url", "")
                    by_service[svc]["last_status"] = rec.get("status", 200)
                except Exception:
                    continue
    except Exception:
        pass
    return {"by_service": by_service, "since_hours": since_hours}
