import glob
import json
import os
import subprocess
import time
import traceback
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory, send_file
from werkzeug.wsgi import ClosingIterator

import config as cfg
from config import SAVE_PATHS
import runtime_config
from debug_utils import debug_log
from accuracy_tracker import evaluate_all, load_history
from auth import auth_bp, init_db, get_current_user, ROLE_LEVEL, require_role
import debug_export

app = Flask(__name__, static_folder="frontend/dist", static_url_path="")
app.register_blueprint(auth_bp)
init_db()


def _resolve_debug_export_base_dir(save_paths):
    """Bestimmt die Projektbasis für den Debug-Export robust für Produktion und Tests."""
    configured = app.config.get("DEBUG_EXPORT_BASE_DIR")
    if configured:
        return Path(configured).expanduser().resolve()

    env_base = os.environ.get("WETTEREXTENDED_EXPORT_BASE_DIR")
    if env_base:
        return Path(env_base).expanduser().resolve()

    for raw_path in (save_paths or {}).values():
        try:
            path = Path(raw_path).expanduser()
            if not path.is_absolute():
                continue
            resolved = path.resolve()
            parts = resolved.parts
            if "train_data" in parts:
                idx = parts.index("train_data")
                if idx > 0:
                    return Path(*parts[:idx]).resolve()
        except Exception:
            continue

    return Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# JWT-Authentifizierung (rollenbasiert)
# ---------------------------------------------------------------------------
# Alle GET-Requests sind öffentlich (kein Token erforderlich).
# POST/PATCH/DELETE/PUT erfordern einen gültigen JWT Access Token.
#
# Rollenhierarchie:
#   viewer(10) < operator(20) < admin(30) < superadmin(40)
#
# Pfade die admin-Level (30) erfordern:
_ADMIN_WRITE_PREFIXES = (
    "/api/config",
    "/api/thresholds",
    "/api/locations",
    "/api/horizons",
    "/api/cell_filters",
    "/api/runtime",
    "/api/ai_analysis/config",
    "/api/log/",
    "/api/system/",
    "/api/drift/",
    "/api/hailo/reload",
    "/api/email_config",
    "/api/sms_config",
    "/api/notification",
)
# Alle anderen POST/PATCH/DELETE erfordern operator-Level (20):
# Training, Scheduler, API-Health-Run, manuelle Trigger usw.


@app.before_request
def _jwt_auth_check():
    """JWT-basierter Authentifizierungs-Hook für alle Schreiboperationen."""
    # OPTIONS (CORS preflight) immer erlauben
    if request.method == "OPTIONS":
        return
    # Auth-Endpunkte selbst benötigen kein Token
    if request.path.startswith("/api/auth/"):
        return
    # Alle GET- und HEAD-Requests sind öffentlich
    if request.method in ("GET", "HEAD"):
        return
    # Statische Assets sind öffentlich
    if request.path.startswith("/assets/") or request.path in ("/favicon.ico",):
        return

    user = get_current_user()
    if user is None:
        return jsonify({"error": "Nicht authentifiziert — JWT Bearer Token erforderlich"}), 401

    user_level = ROLE_LEVEL.get(user.get("role", ""), 0)

    is_admin_path = any(request.path.startswith(p) for p in _ADMIN_WRITE_PREFIXES)

    if is_admin_path and user_level < ROLE_LEVEL["admin"]:
        return jsonify({"error": "Admin-Berechtigung erforderlich (role: admin oder superadmin)"}), 403
    if not is_admin_path and user_level < ROLE_LEVEL["operator"]:
        return jsonify({"error": "Operator-Berechtigung erforderlich"}), 403


# ---------- Helper ----------
def _git_info():
    try:
        b = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True).strip()
    except Exception:
        b = "unknown"
    try:
        c = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        c = "unknown"
    return b, c


def _latest_objects():
    files = sorted(glob.glob(os.path.join(SAVE_PATHS["objects"], "*.json")))
    if not files:
        return []
    try:
        with open(files[-1], encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _objects_for_ts(ts: str | None) -> list:
    """
    Liest Objekte für einen spezifischen Radar-Frame-Timestamp.
    Gibt [] zurück wenn kein passendes JSON existiert (keine Zellen in diesem Frame).
    Fällt auf _latest_objects() zurück wenn ts=None (Live-Ansicht).
    """
    if not ts:
        return _latest_objects()
    path = os.path.join(SAVE_PATHS["objects"], f"{ts}.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _latest_location_hits():
    files = sorted(glob.glob(os.path.join(SAVE_PATHS["evaluation"], "locations_*.json")))
    if not files:
        return []
    try:
        with open(files[-1], encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _evaluation_dir():
    return SAVE_PATHS.get("evaluation", "train_data/evaluation").rstrip("/")


def _log_clear_state_path():
    return os.path.join(_evaluation_dir(), "log_clear_state.json")


def _utc_now_iso_z():
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _load_log_clear_state():
    path = _log_clear_state_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_log_clear_state(state):
    os.makedirs(_evaluation_dir(), exist_ok=True)
    with open(_log_clear_state_path(), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _get_log_clear_since():
    value = _load_log_clear_state().get("cleared_at_utc")
    return value if isinstance(value, str) and value else None


def _sanitize_for_json(obj, _depth=0):
    """
    Ersetzt float NaN/Inf durch None (JSON-kompatibel).
    Verhindert JSON.parse-Fehler im Frontend bei ML-Accuracy-Daten die
    float('nan') oder float('inf') aus numpy-Statistiken enthalten können.
    Maximale Rekursionstiefe: 50.
    """
    import math as _m
    if _depth > 50:
        return None
    if isinstance(obj, float):
        if _m.isnan(obj) or _m.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v, _depth+1) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(v, _depth+1) for v in obj]
    return obj


_LOGS_DEFAULT_LINES = 1000
_LOGS_DEFAULT_MAX_BYTES = 2 * 1024 * 1024
_LOGS_MAX_LINES = 5000
_LOGS_MAX_BYTES = 5 * 1024 * 1024


def _coerce_log_limit(value, default, minimum, maximum):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(parsed, maximum))


def _truncation_notice(limit, max_bytes):
    return (
        f"[TRUNCATED] Anzeige auf {limit} Zeilen / {max_bytes} Bytes begrenzt. "
        "Vollständige Logs sind im Datenexport enthalten."
    )


def _limit_log_text_for_display(text, *, limit=500, max_bytes=_LOGS_DEFAULT_MAX_BYTES):
    encoded = (text or "").encode("utf-8", errors="replace")
    truncated_by_bytes = len(encoded) > max_bytes
    if truncated_by_bytes:
        text = encoded[-max_bytes:].decode("utf-8", errors="replace")
    all_lines = text.splitlines()
    truncated_by_lines = len(all_lines) > limit
    lines = all_lines[-limit:] if truncated_by_lines else all_lines
    truncated = truncated_by_bytes or truncated_by_lines
    if truncated:
        lines.insert(0, _truncation_notice(limit, max_bytes))
    return lines, truncated


def _tail_readable_file_lines(path, limit=500, label=None, max_bytes=_LOGS_DEFAULT_MAX_BYTES):
    """Liest lokale Logdateien best-effort mit harter Anzeige-Byte-Grenze."""
    log_path = Path(path)
    display = label or str(log_path)
    try:
        with log_path.open("rb") as fh:
            try:
                fh.seek(0, os.SEEK_END)
                size = fh.tell()
                fh.seek(max(0, size - max_bytes))
                data = fh.read(max_bytes)
                text = data.decode("utf-8", errors="replace")
                lines, truncated = _limit_log_text_for_display(text, limit=limit, max_bytes=max_bytes)
                if size > max_bytes and not truncated:
                    lines.insert(0, _truncation_notice(limit, max_bytes))
                return lines
            except OSError:
                fh.seek(0)
                text = fh.read(max_bytes).decode("utf-8", errors="replace")
                return _limit_log_text_for_display(text, limit=limit, max_bytes=max_bytes)[0]
    except PermissionError:
        return [f"[nginx] {display} nicht lesbar"]
    except FileNotFoundError:
        return [f"[nginx] {display} nicht lesbar"]
    except OSError as exc:
        return [f"[nginx] {display} nicht lesbar: {exc}"]


def _journalctl_unit_lines(unit, limit=500, max_bytes=_LOGS_DEFAULT_MAX_BYTES):
    cmd = ["journalctl", "-u", unit, "-n", str(limit), "--no-pager"]
    since = _get_log_clear_since()
    if since:
        # journalctl --since erwartet "YYYY-MM-DD HH:MM:SS", KEIN ISO-8601 mit Z-Suffix.
        # _get_log_clear_since() liefert z.B. "2026-05-26T19:12:36Z" → wird konvertiert.
        try:
            from datetime import datetime as _jdt
            _since_dt = _jdt.fromisoformat(since.replace("Z", "+00:00"))
            _since_jctl = _since_dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            _since_jctl = since  # Fallback: Originalwert übergeben
        cmd = ["journalctl", "-u", unit, "--since", _since_jctl, "-n", str(limit), "--no-pager"]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except Exception as exc:
        return [f"[journalctl] Fehler beim Lesen von {unit}: {exc}"]
    if result.returncode != 0:
        unit_service = f"{unit}.service"
        try:
            unit_check = subprocess.run(
                ["systemctl", "list-unit-files", unit_service],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            unit_missing = unit_service not in unit_check.stdout
        except Exception:
            unit_missing = False
        if unit_missing:
            return [f"[systemd] Unit {unit_service} ist nicht installiert."]
        stderr = (result.stderr or "").strip()
        msg = f"[journalctl] Keine Logs verfügbar oder Unit nicht vorhanden: {unit}"
        if stderr:
            msg += f"\nDetails: {stderr}"
        return [msg]
    return _limit_log_text_for_display(result.stdout, limit=limit, max_bytes=max_bytes)[0]


# ---------- JSON-APIs (von React konsumiert) ----------


@app.route("/api/config/rollback", methods=["POST"])
def api_config_rollback():
    """
    P35: Setzt runtime_overrides.json auf den Stand vor dem letzten Admin-Patch zurück.
    Nützlich wenn eine Konfigurationsänderung das System destabilisiert hat.
    """
    try:
        previous = runtime_config.rollback()
        if "error" in previous:
            return jsonify({"ok": False, "error": previous["error"]}), 500
        if not previous:
            return jsonify({"ok": False, "note": "Kein Backup vorhanden (noch keine Änderungen)"}), 404
        return jsonify({"ok": True, "restored_keys": list(previous.keys())})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/api_health")
def api_api_health():
    """
    P36: Letzter API-Connectivity-Status (aus api_health_latest.json).
    Täglich um 05:15 aktualisiert, manuell via POST auslösbar.
    """
    try:
        from api_health_check import load_status
        return jsonify(load_status())
    except Exception as exc:
        return jsonify({"all_ok": None, "error": str(exc)})


@app.route("/api/api_health/run", methods=["POST"])
def api_api_health_run():
    """Löst manuellen API-Health-Check aus (für Admin-Panel)."""
    try:
        from api_health_check import check_all_apis
        result = check_all_apis()
        return jsonify(result)
    except Exception as exc:
        return jsonify({"all_ok": False, "error": str(exc)}), 500


@app.route("/api/drift")
def api_drift():
    """
    Gibt den letzten Drift-Status zurück (aus drift_status.json).
    Wird vom Admin-Panel Dashboard angezeigt.
    """
    try:
        from drift_detector import load_status

        return jsonify(load_status())
    except Exception as exc:
        return jsonify({"drift_detected": False, "message": f"Fehler: {exc}"})



# ---------------------------------------------------------------------------
# Sicherheits-Hilfsfunktion: Secrets aus Config-Responses entfernen
# ---------------------------------------------------------------------------
_REDACT_KEYS = frozenset({
    "TOKEN", "KEY", "PASS", "PASSWORD", "SECRET",
    "AUTH", "CREDENTIAL", "PRIVATE", "API_KEY",
})


def _redact_secrets(obj, depth: int = 0):
    """
    Entfernt rekursiv alle Secret-Werte aus einem Config-Dict.
    Keys die einen der _REDACT_KEYS-Begriffe enthalten → '***REDACTED***'.
    depth-Limit verhindert endlose Rekursion.
    """
    if depth > 8:
        return obj
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if any(s in str(k).upper() for s in _REDACT_KEYS):
                out[k] = "***REDACTED***"
            else:
                out[k] = _redact_secrets(v, depth + 1)
        return out
    if isinstance(obj, list):
        return [_redact_secrets(i, depth + 1) for i in obj]
    return obj


@app.route("/api/health")
def api_health():
    return jsonify({"ok": True, "ts": datetime.utcnow().isoformat() + "Z"})

@app.route("/api/radar_timing")
def api_radar_timing():
    """Letztes Radarbild-Timestamp + geschätzte nächste Abfrage."""
    import glob as _gl
    from config import LOOP_INTERVAL_CELLS_S, LOOP_INTERVAL_NO_CELLS_S

    obj_dir   = SAVE_PATHS.get("objects", "train_data/objects")
    radar_dir = "data/radar"

    radar_files = sorted(_gl.glob(os.path.join(radar_dir, "radar_*.png")))
    obj_files   = sorted(_gl.glob(os.path.join(obj_dir, "*.json")))

    last_radar_utc = None
    last_radar_dt  = None   # für next_fetch-Berechnung wiederverwenden
    if radar_files:
        try:
            from zoneinfo import ZoneInfo as _ZI
            from datetime import timezone as _tz
            _vienna = _ZI("Europe/Vienna")
            # Zeitstempel aus Dateiname: radar_YYYY-MM-DD_HH-MM-SS.png (lokale Zeit Wien)
            _base     = os.path.basename(radar_files[-1])
            _ts       = _base.replace("radar_", "").replace(".png", "")
            _local_dt = datetime.strptime(_ts, "%Y-%m-%d_%H-%M-%S").replace(tzinfo=_vienna)
            last_radar_dt  = _local_dt.astimezone(_tz.utc)
            last_radar_utc = last_radar_dt.isoformat(timespec="seconds").replace("+00:00", "Z")
        except Exception:
            # Fallback: Datei-Mtime
            try:
                mtime          = os.path.getmtime(radar_files[-1])
                last_radar_dt  = datetime.utcfromtimestamp(mtime)
                last_radar_utc = last_radar_dt.isoformat(timespec="seconds") + "Z"
            except Exception:
                pass

    last_obj_utc = None
    if obj_files:
        try:
            from zoneinfo import ZoneInfo as _ZI_obj
            from datetime import timezone as _tz_obj
            _vienna_obj = _ZI_obj("Europe/Vienna")
            _base_obj = os.path.basename(obj_files[-1]).replace(".json", "")
            _local_obj = datetime.strptime(_base_obj, "%Y-%m-%d_%H-%M-%S").replace(tzinfo=_vienna_obj)
            last_obj_utc = _local_obj.astimezone(_tz_obj.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        except Exception:
            # Fallback: Datei-Mtime wenn Dateiname kein gültiges Datum enthält
            try:
                mtime = os.path.getmtime(obj_files[-1])
                last_obj_utc = datetime.utcfromtimestamp(mtime).isoformat(timespec="seconds") + "Z"
            except Exception:
                pass

    cells_active = False
    if obj_files:
        try:
            with open(obj_files[-1], encoding="utf-8") as _f:
                objs = json.load(_f)
                cells_active = bool(objs and any(o.get("missing", 0) == 0 for o in objs))
        except Exception:
            pass

    interval_s = (
        runtime_config.get("LOOP_INTERVAL_CELLS_S", LOOP_INTERVAL_CELLS_S)
        if cells_active else
        runtime_config.get("LOOP_INTERVAL_NO_CELLS_S", LOOP_INTERVAL_NO_CELLS_S)
    )

    next_fetch_utc = None
    if last_radar_dt is not None:
        try:
            from datetime import timezone as _tz2, timedelta as _td, datetime as _dtnow
            _base_dt = last_radar_dt if last_radar_dt.tzinfo else \
                       last_radar_dt.replace(tzinfo=_tz2.utc)
            _next = _base_dt + _td(seconds=interval_s)
            _now  = _dtnow.now(_tz2.utc)
            # Falls ueberfaellig (ARSO hatte noch kein neues Bild):
            # Zeige "in 20s" damit Frontend bald wieder pollt.
            if _next < _now:
                _next = _now + _td(seconds=20)
            next_fetch_utc = _next.isoformat(timespec="seconds").replace("+00:00", "Z")
        except Exception:
            pass

    return jsonify({
        "last_radar_image_utc":     last_radar_utc,
        "last_objects_utc":         last_obj_utc,
        "next_fetch_estimated_utc": next_fetch_utc,
        "loop_interval_s":          interval_s,
        "cells_active":             cells_active,
    })


@app.route("/api/radar_image")
def api_radar_image():
    """
    Liefert ein Radar-PNG mit transparentem Hintergrund.
    ?ts=YYYY-MM-DD_HH-MM-SS  → spezifisches Frame (für Animation)
    ohne ts                  → neuestes Frame
    """
    import glob as _gl
    from flask import send_file, make_response
    import io

    # Bestimme Pfad zum auszuliefernden Radarbild
    ts_param = request.args.get("ts")
    if ts_param:
        candidate = os.path.join("data", "radar", f"radar_{ts_param}.png")
        latest = candidate if os.path.exists(candidate) else None
    else:
        # Neustes gecroptes Radar-File
        import glob as _rgl
        _rfiles = sorted(_rgl.glob(os.path.join("data", "radar", "radar_*.png")))
        latest = _rfiles[-1] if _rfiles else None
    if not latest:
        # Fallback auf Originalbild (kein gecroptes vorhanden)
        latest = os.path.join("data", "latest.png")

    try:
        from PIL import Image
        import numpy as _np

        img = Image.open(latest).convert("RGBA")
        arr = _np.array(img)

        # Weißer + hellgrauer Hintergrund transparent machen.
        # Schwellwert R,G,B > 230 erfasst den ARSO-Kartenhintergrund.
        # Niederschlagsfarben (Orange, Rot, Violett, Gelb) bleiben opak.
        r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
        # ARSO-Radar nach OpenCV-Crop: Hintergrund = schwarz (0,0,0).
        # Beide Fälle abdecken: schwarz (OpenCV-Default) + weiß (Original-KMZ)
        bg_mask = ((r < 30) & (g < 30) & (b < 30)) | \
                  ((r > 225) & (g > 225) & (b > 225))
        arr[bg_mask, 3] = 0  # Alpha = 0 (vollständig transparent)

        out = Image.fromarray(arr)
        buf = io.BytesIO()
        out.save(buf, format="PNG")
        buf.seek(0)

        resp = make_response(send_file(buf, mimetype="image/png"))
        resp.headers["Cache-Control"] = "no-cache, max-age=120"
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp

    except ImportError:
        # Pillow fehlt → Originalbild ohne Transparenz (Fallback)
        print("[RADAR-IMG] Pillow nicht installiert — Fallback ohne Transparenz")
        resp = make_response(send_file(latest, mimetype="image/png"))
        resp.headers["Cache-Control"] = "no-cache, max-age=120"
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp
    except Exception as exc:
        print(f"[RADAR-IMG] Fehler: {exc}")
        return jsonify({"error": str(exc)}), 500


@app.route("/api/radar_frames")
def api_radar_frames():
    """
    Radar-Frames für die Karten-Animation.

    Liefert eine lückenlose Sequenz: Frames mit Zeitabstand > MAX_FRAME_GAP_MIN
    brechen die Kontinuität — ältere Frames werden verworfen. Das verhindert
    sichtbare Zeitsprünge beim Wechsel von 15-min-Intervall (keine Zellen) auf
    2-min-Intervall (Zellen aktiv).

    Laufzeit-Parameter (runtime_overrides.json):
      RADAR_FRAME_MAX_GAP_MIN  — max. Abstand zwischen zwei Frames (default 20)
      RADAR_FRAME_MAX_AGE_MIN  — max. Alter des ältesten Frames  (default 150)
      RADAR_FRAME_MAX_COUNT    — max. Anzahl Frames in der Liste  (default 12)
    """
    import glob as _gl
    from zoneinfo import ZoneInfo as _ZI
    from datetime import timezone as _tz, timedelta as _tdd

    try:
        _max_gap_min = int(runtime_config.get("RADAR_FRAME_MAX_GAP_MIN", 20))
        _max_age_min = int(runtime_config.get("RADAR_FRAME_MAX_AGE_MIN", 150))
        _max_count   = int(runtime_config.get("RADAR_FRAME_MAX_COUNT",   12))
    except Exception:
        _max_gap_min, _max_age_min, _max_count = 10, 90, 12

    _vienna = _ZI("Europe/Vienna")
    _now_utc = datetime.now(_tz.utc)

    # Alle Frames parsen
    all_frames = []
    for f in sorted(_gl.glob(os.path.join("data", "radar", "radar_*.png"))):
        try:
            base  = os.path.basename(f)
            ts    = base.replace("radar_", "").replace(".png", "")
            ldt   = datetime.strptime(ts, "%Y-%m-%d_%H-%M-%S").replace(tzinfo=_vienna)
            utcdt = ldt.astimezone(_tz.utc)
            # Altersfilter
            if (_now_utc - utcdt).total_seconds() > _max_age_min * 60:
                continue
            all_frames.append({"ts": ts, "utc": utcdt, "ldt": ldt})
        except Exception:
            continue

    if not all_frames:
        return jsonify({"frames": [], "latest_idx": -1})

    # Rückwärts durch sortierte Frames gehen — kontinuierliche Sequenz sammeln
    all_frames.sort(key=lambda x: x["utc"])
    continuous = [all_frames[-1]]
    for frame in reversed(all_frames[:-1]):
        gap_s = (continuous[-1]["utc"] - frame["utc"]).total_seconds()
        if gap_s > _max_gap_min * 60:
            break  # Lücke zu groß — ältere Frames verwerfen
        continuous.append(frame)
        if len(continuous) >= _max_count:
            break

    # Älteste zuerst (Animation läuft vorwärts)
    continuous.reverse()

    # Ausgabe aufbereiten — gap_min für Frontend-Marker
    frames = []
    for i, f in enumerate(continuous):
        gap_min = None
        if i > 0:
            delta_s = (f["utc"] - continuous[i - 1]["utc"]).total_seconds()
            gap_min = round(delta_s / 60, 1)
        frames.append({
            "ts":      f["ts"],
            "utc":     f["utc"].isoformat(timespec="seconds").replace("+00:00", "Z"),
            "label":   f["ldt"].strftime("%H:%M"),
            "gap_min": gap_min,   # Minuten seit Vorgänger-Frame (None beim ersten)
        })

    return jsonify({
        "frames":     frames,
        "latest_idx": len(frames) - 1,
    })


@app.route("/api/radar_bounds")
def api_radar_bounds():
    """
    BBOX des Radarbilds für Leaflet ImageOverlay.
    Format: { "bounds": [[south, west], [north, east]] }

    Berechnet die TATSÄCHLICHEN Crop-Grenzen unter Berücksichtigung der
    Integer-Truncation in geo_to_pixel (int() statt round()).
    Ohne Korrektur: Radar-Overlay bis zu ~1 km südlich der Zellenmarkierungen,
    da BBOX_KAERNTEN_EXTENDED die Sollgrenzen angibt, das Bild aber am
    nächsten ganzzahligen Pixel endet.
    """
    import cv2 as _cv2
    import os as _os
    from xml.etree import ElementTree as _ET
    from config import BBOX_KAERNTEN_EXTENDED

    bbox = runtime_config.get("BBOX_KAERNTEN_EXTENDED", BBOX_KAERNTEN_EXTENDED)

    try:
        kml_path = "data/latest.kml"
        img_path = "data/latest.png"
        if _os.path.exists(kml_path) and _os.path.exists(img_path):
            _ns   = {"kml": "http://www.opengis.net/kml/2.2"}
            _tree = _ET.parse(kml_path)
            _box  = _tree.find(".//kml:LatLonBox", _ns)
            _img  = _cv2.imread(img_path)

            if _box is not None and _img is not None:
                kn = float(_box.find("kml:north", _ns).text)
                ks = float(_box.find("kml:south", _ns).text)
                ke = float(_box.find("kml:east",  _ns).text)
                kw = float(_box.find("kml:west",  _ns).text)
                oh, ow = _img.shape[:2]       # z.B. 537, 1170 (ARSO-Original)
                span_lon = ke - kw            # z.B. 5.34°
                span_lat = kn - ks            # z.B. 2.75°

                # Gleiche Integer-Mathematik wie in geo_to_pixel:
                # Truncation statt Rundung, damit Pixelgrenzen identisch sind.
                _x1 = int((bbox["west"]  - kw) / span_lon * ow)
                _y1 = int((kn - bbox["north"]) / span_lat * oh)
                _x2 = int((bbox["east"]  - kw) / span_lon * ow)
                _y2 = int((kn - bbox["south"]) / span_lat * oh)

                # Tatsächliche Geo-Bounds aus exakten Pixelpositionen
                actual = {
                    "west":  round(kw + (_x1 / ow) * span_lon, 6),
                    "east":  round(kw + (_x2 / ow) * span_lon, 6),
                    "north": round(kn - (_y1 / oh) * span_lat, 6),
                    "south": round(kn - (_y2 / oh) * span_lat, 6),
                }
                return jsonify({
                    "bounds": [
                        [actual["south"], actual["west"]],
                        [actual["north"], actual["east"]],
                    ],
                    "bbox": actual,
                })
    except Exception as _exc:
        pass  # Fallback auf BBOX_KAERNTEN_EXTENDED

    # Fallback: BBOX_KAERNTEN_EXTENDED (sub-km-Fehler durch Truncation sichtbar)
    return jsonify({
        "bounds": [
            [bbox["south"], bbox["west"]],
            [bbox["north"], bbox["east"]],
        ],
        "bbox": bbox,
    })


@app.route("/api/git")
def api_git():
    branch, commit = _git_info()
    return jsonify({"branch": branch, "commit": commit})




@app.route("/api/admin/export/last-24h.zip")
@require_role("admin")
def api_admin_export_last_24h_zip():
    """Geschützter ZIP-Export aller relevanten Debug-Daten der letzten 24 Stunden."""
    hours = 24
    export_base_dir = _resolve_debug_export_base_dir(SAVE_PATHS)
    started = time.perf_counter()
    zip_path = None
    app.logger.info("[ADMIN-EXPORT] start hours=%s base_dir=%s", hours, export_base_dir)
    print(f"[ADMIN-EXPORT] start hours={hours} base_dir={export_base_dir}", flush=True)
    try:
        zip_path, filename, manifest = debug_export.create_debug_export_zip(
            base_dir=export_base_dir,
            save_paths=SAVE_PATHS,
            hours=hours,
        )

        zip_path = Path(zip_path)
        size_bytes = zip_path.stat().st_size
        duration_s = time.perf_counter() - started
        manifest_total_files = manifest.get("total_files", "unknown") if isinstance(manifest, dict) else "unknown"
        app.logger.info(
            "[ADMIN-EXPORT] zip_created file=%s bytes=%s duration_s=%.3f manifest_total_files=%s",
            zip_path,
            size_bytes,
            duration_s,
            manifest_total_files,
        )
        print(
            f"[ADMIN-EXPORT] zip_created file={zip_path} bytes={size_bytes} "
            f"duration_s={duration_s:.3f} manifest_total_files={manifest_total_files}",
            flush=True,
        )
        response = send_file(
            zip_path,
            mimetype="application/zip",
            as_attachment=True,
            download_name=filename,
            max_age=0,
        )
        app.logger.info("[ADMIN-EXPORT] response_ready filename=%s", filename)
        print(f"[ADMIN-EXPORT] response_ready filename={filename}", flush=True)

        cleanup_done = False

        def _cleanup_export_zip(path=zip_path):
            nonlocal cleanup_done
            if cleanup_done:
                return
            cleanup_done = True
            print(f"[ADMIN-EXPORT] cleanup zip_path={path}", flush=True)
            app.logger.info("[ADMIN-EXPORT] cleanup zip_path=%s", path)
            Path(path).unlink(missing_ok=True)

        response.call_on_close(_cleanup_export_zip)
        response.response = ClosingIterator(response.response, _cleanup_export_zip)
        return response
    except Exception as exc:
        duration_s = time.perf_counter() - started
        app.logger.exception(
            "[ADMIN-EXPORT] failed hours=%s base_dir=%s duration_s=%.3f error=%s",
            hours,
            export_base_dir,
            duration_s,
            exc,
        )
        print(
            f"[ADMIN-EXPORT] failed hours={hours} base_dir={export_base_dir} "
            f"duration_s={duration_s:.3f} error={exc}\n{traceback.format_exc()}",
            flush=True,
        )
        if zip_path is not None:
            Path(zip_path).unlink(missing_ok=True)
        return jsonify({"error": f"Debug-Export konnte nicht erstellt werden: {exc}", "type": type(exc).__name__}), 500


@app.route("/api/download/logs")
def api_download_logs():
    """
    Download: Systemlogs aller drei Services als einzelne .txt-Datei.
    Enthält wetterprojekt, scheduler und admin-Logs.
    Kein Auth-Check nötig — liegt hinter nginx Basic-Auth.
    """
    import io as _io_dl
    units = ["wetterprojekt", "wetterprojekt-scheduler", "wetterprojekt-admin"]
    lines = []
    for unit in units:
        lines.append(f"{'='*60}")
        lines.append(f"=== {unit} ===")
        lines.append(f"{'='*60}")
        lines.extend(_journalctl_unit_lines(unit, limit=500))
        lines.append("")
    nginx_logs = {
        "nginx error": "/var/log/nginx/error.log",
        "nginx access": "/var/log/nginx/access.log",
    }
    for label, path in nginx_logs.items():
        lines.append(f"{'='*60}")
        lines.append(f"=== {label} ({path}) ===")
        lines.append(f"{'='*60}")
        lines.extend(_tail_readable_file_lines(path, limit=500))
        lines.append("")
    content = "\n".join(lines)
    buf = _io_dl.BytesIO(content.encode("utf-8", errors="replace"))
    from datetime import datetime as _dl_dt
    fname = f"wetterprojekt_logs_{_dl_dt.utcnow().strftime('%Y%m%d_%H%M%S')}.txt"
    from flask import Response as _FlaskResponse
    return _FlaskResponse(
        buf.getvalue(),
        mimetype="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@app.route("/api/download/objects")
def api_download_objects():
    """
    Download: Aktuelles oder frame-spezifisches Object-JSON als .json-Datei.
    Query-Parameter: ?ts=YYYY-MM-DD_HH-MM-SS (optional, leer = neuester Frame)
    Kein Auth-Check nötig — liegt hinter nginx Basic-Auth.
    """
    ts = request.args.get("ts")
    data = _objects_for_ts(ts)
    import io as _io_dl2
    from datetime import datetime as _dl_dt2
    ts_label = ts if ts else _dl_dt2.utcnow().strftime("%Y%m%d_%H%M%S")
    fname = f"objects_{ts_label}.json"
    content = json.dumps(data, ensure_ascii=False, indent=2)
    buf = _io_dl2.BytesIO(content.encode("utf-8", errors="replace"))
    from flask import Response as _FlaskResponse2
    return _FlaskResponse2(
        buf.getvalue(),
        mimetype="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@app.route("/api/objects")
def api_objects():
    ts = request.args.get("ts")  # z.B. ?ts=2025-05-19_19-21-00
    data = _objects_for_ts(ts)
    # Phase E: IR-Tracks anhängen wenn include_ir=1
    from flask import request as _flask_req_ir
    if _flask_req_ir.args.get("include_ir") == "1":
        try:
            from ir_cell_tracking import load_active_ir_tracks
            ir_tracks = load_active_ir_tracks()
            # IR-Tracks als pseudo-objects mit Typ-Marker
            for t in ir_tracks:
                t["_type"] = "ir_cell"
            if isinstance(data, list):
                data = data + ir_tracks
            elif isinstance(data, dict) and "objects" in data:
                data["objects"] = data["objects"] + ir_tracks
        except Exception as _ir_api_exc:
            debug_log(f"[API/objects] IR-Track-Anhang fehlgeschlagen: {_ir_api_exc}")
    return jsonify(data)


@app.route("/api/forecast")
def api_forecast():
    import math as _math
    from config import MIN_MOVEMENT_FOR_ARROW_KMH, FORECAST_ARROW_STYLE, PX_TO_KMH
    horizons = runtime_config.get("ML_FORECAST_HORIZONS_MIN", [10, 20, 30, 40, 60])
    colors   = runtime_config.get("FORECAST_ARROW_COLORS", {})
    styles   = runtime_config.get("FORECAST_ARROW_STYLE", FORECAST_ARROW_STYLE)
    min_kmh  = runtime_config.get("MIN_MOVEMENT_FOR_ARROW_KMH", MIN_MOVEMENT_FOR_ARROW_KMH)
    # PX_TO_KMH aus config.py — Single Source of Truth
    ts = request.args.get("ts")  # Frame-Sync: gleicher Timestamp wie Radarbild
    feats = []
    for o in _objects_for_ts(ts):
        if o.get("lat") is None or o.get("lon") is None:
            continue
        # B78-FIX: speed_kmh direkt aus Objekt — bereits korrekt mit UPSCALE_FACTOR
        _spd_pre = o.get("speed_kmh")
        if _spd_pre is not None:
            speed_kmh = float(_spd_pre)
        else:
            # B105/P0-1: vx/vy sind ORIGINAL-px/Frame → direkt PX_TO_KMH, kein /UF.
            vx = float(o.get("vx") or 0.0)
            vy = float(o.get("vy") or 0.0)
            try:
                from config import speed_kmh_from_px as _spd_fn_fc
                speed_kmh = _spd_fn_fc(vx, vy)
            except ImportError:
                speed_kmh = _math.hypot(vx, vy) * PX_TO_KMH
        # is_slow_arrow: Zelle bewegt sich < MIN_MOVEMENT_FOR_ARROW_KMH.
        # has_arrow: True wenn Forecast-Position vom Zell-Zentrum abweicht (min 0.001°).
        # Trennung: langsame Zellen werden sichtbar (aber transparent), nicht ausgeblendet.
        is_slow = speed_kmh < min_kmh
        for h in horizons:
            fy = o.get(f"forecast_lat_{h}")
            fx = o.get(f"forecast_lon_{h}")
            if fy is None or fx is None:
                continue
            # Kein Pfeil wenn Forecast-Position identisch mit Zell-Position
            _dist_deg = _math.hypot(float(fx) - o["lon"], float(fy) - o["lat"])
            has_arrow = _dist_deg > 0.001   # < 0.001° ≈ < 100m → kein sinnvoller Pfeil
            color = colors.get(h) or colors.get(str(h))
            style = styles.get(h) or styles.get(str(h)) or {}
            feats.append({
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[o["lon"], o["lat"]], [fx, fy]]},
                "properties": {
                    "cell_id":         o.get("id"),
                    "horizon":         h,
                    "color":           color,
                    "weight":          style.get("weight", 2),
                    "dash":            style.get("dash", ""),
                    "forecast_mode":   o.get("forecast_mode", "kinematic"),
                    "kinematic_source": o.get("kinematic_source"),
                    "has_arrow":       has_arrow,
                    "is_slow_arrow":   is_slow,
                    "speed_kmh":       round(speed_kmh, 1),
                    # q10/q90 Unsicherheitspositionen (F23/F25)
                    "forecast_lat_q10": o.get(f"forecast_lat_{h}_q10"),
                    "forecast_lon_q10": o.get(f"forecast_lon_{h}_q10"),
                    "forecast_lat_q90": o.get(f"forecast_lat_{h}_q90"),
                    "forecast_lon_q90": o.get(f"forecast_lon_{h}_q90"),
                    # Diagnose-Felder für Frontend (F28, F43)
                    "hail_warning":      o.get("hail_warning", False),
                    "hail_prob":         o.get("hail_prob", 0.0),
                    "stationary_marker": o.get("stationary_marker", False),
                    "stationary_risk":   o.get("stationary_risk", 0.0),
                },
            })
    return jsonify({"type": "FeatureCollection", "features": feats})


@app.route("/api/lightning")
def api_lightning():
    """
    Liefert die zuletzt gespeicherten Blitzeinschläge aus dem Blitzortung-Cache.
    Filtert auf die letzten max_age_min Minuten (Default: 15).
    Rückgabe: { "strikes": [...], "count": N, "ts": "...", "max_age_min": 15 }
    """
    # Default: 15 Minuten (überschreibbar per ?max_age_min=N)
    max_age_min = int(request.args.get("max_age_min", 15))
    files = sorted(glob.glob(os.path.join(SAVE_PATHS.get("lightning", "train_data/lightning"), "*.json")))
    if not files:
        return jsonify({"strikes": [], "count": 0, "ts": None, "max_age_min": max_age_min})

    try:
        with open(files[-1], encoding="utf-8") as f:
            all_strikes = json.load(f)
    except Exception:
        return jsonify({"strikes": [], "count": 0, "ts": None, "max_age_min": max_age_min})

    ts_file = os.path.basename(files[-1]).replace(".json", "")

    # Zeitfilter: Datei-Timestamp als Referenz (nicht datetime.now()).
    # Verhindert dass Blitze eines aktiven Gewitters ausgeblendet werden wenn
    # der Verarbeitungszyklus länger als max_age_min her ist.
    # Sicherheits-Gate: Datei älter als max_age_min × 3 → keine Blitze anzeigen
    # (Loop nicht aktiv / System inaktiv).
    from datetime import datetime, timezone, timedelta
    _now_utc = datetime.now(timezone.utc)
    try:
        _file_dt = datetime.strptime(ts_file, "%Y-%m-%d_%H-%M-%S").replace(
            tzinfo=timezone.utc
        )
        _file_age_min = (_now_utc - _file_dt).total_seconds() / 60.0
        if _file_age_min > max_age_min * 3:
            return jsonify({
                "strikes":       [],
                "count":         0,
                "ts":            ts_file,
                "max_age_min":   max_age_min,
                "total_in_file": len(all_strikes),
            })
        ref_time = _file_dt
    except Exception:
        ref_time = _now_utc

    cutoff_ns = int((ref_time - timedelta(minutes=max_age_min)).timestamp() * 1e9)
    recent = [s for s in all_strikes if s.get("timestamp_ns", 0) >= cutoff_ns]

    return jsonify({
        "strikes":       recent,
        "count":         len(recent),
        "ts":            ts_file,
        "max_age_min":   max_age_min,
        "total_in_file": len(all_strikes),
    })


@app.route("/api/locations")
def api_locations():
    return jsonify({
        "watchlist": runtime_config.get("LOCATIONS_WATCHLIST", []),
        "hits": _latest_location_hits(),
        "colors": runtime_config.get("FORECAST_ARROW_COLORS", {}),
    })


@app.route("/api/locations", methods=["POST"])
def api_locations_save():
    try:
        data = request.get_json(force=True)
        assert isinstance(data, list)
        for entry in data:
            assert "name" in entry and "lat" in entry and "lon" in entry and "radius_km" in entry
            # email ist optional — wird bei Vorhandensein als String gespeichert
            if "email" in entry:
                assert isinstance(entry["email"], str), "email muss ein String sein"
            # whatsapp ist optional — Format: "+436991234567:APIKEY;..." pro Ort
            if "whatsapp" in entry:
                assert isinstance(entry["whatsapp"], str), \
                    "whatsapp muss ein String sein"
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    runtime_config.patch({"LOCATIONS_WATCHLIST": data})
    return jsonify({"ok": True})


@app.route("/api/horizons")
def api_horizons():
    return jsonify({
        "horizons": runtime_config.get("ML_FORECAST_HORIZONS_MIN", [10, 20, 30, 40, 60]),
        "colors": runtime_config.get("FORECAST_ARROW_COLORS", {}),
        "styles": runtime_config.get("FORECAST_ARROW_STYLE", {}),
    })


@app.route("/api/horizons", methods=["POST"])
def api_horizons_save():
    try:
        data = request.get_json(force=True)
        assert "horizons" in data and isinstance(data["horizons"], list)
        assert len(data["horizons"]) == 5, "exakt 5 Horizonte erforderlich"
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    payload = {"ML_FORECAST_HORIZONS_MIN": [int(h) for h in data["horizons"]]}
    if "colors" in data:
        payload["FORECAST_ARROW_COLORS"] = {int(k): v for k, v in data["colors"].items()}
    if "styles" in data:
        payload["FORECAST_ARROW_STYLE"] = {int(k): v for k, v in data["styles"].items()}
    runtime_config.patch(payload)
    return jsonify({"ok": True})




@app.route("/api/system_consistency")
def api_system_consistency():
    """Prüft End-to-End Konsistenz: Admin-Horizonte vs. trainiertes Modell."""
    warnings = []

    from config import ML_FORECAST_HORIZONS_MIN as _default_h
    admin_horizons = runtime_config.get("ML_FORECAST_HORIZONS_MIN", _default_h)

    meta_path = os.path.join(SAVE_PATHS.get("models", "train_data/models"), "current", "training_meta.json")
    model_horizons = None
    if os.path.exists(meta_path):
        try:
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
            model_horizons = meta.get("horizons") or meta.get("ML_FORECAST_HORIZONS_MIN")
        except Exception:
            pass

    if model_horizons is None:
        warnings.append({
            "level": "info",
            "message": "Kein trainiertes Modell vorhanden — System läuft im kinematischen Fallback."
        })
    elif sorted(model_horizons) != sorted(admin_horizons):
        warnings.append({
            "level": "warning",
            "message": (
                f"Admin-Horizonte {admin_horizons} weichen vom Modell {model_horizons} ab. "
                "Vorhersage nutzt Fallback für nicht übereinstimmende Horizonte. "
                "Empfehlung: Modell mit aktuellen Horizonten neu trainieren."
            )
        })

    models_dir = os.path.join(SAVE_PATHS.get("models", "train_data/models"), "current")
    missing_models = []
    for h in admin_horizons:
        for axis in ["x", "y"]:
            model_file = os.path.join(models_dir, f"lgbm_h{h}_{axis}.txt")
            if not os.path.exists(model_file):
                missing_models.append(f"lgbm_h{h}_{axis}.txt")
    if missing_models:
        warnings.append({
            "level": "warning",
            "message": f"Fehlende Modell-Dateien für aktuelle Horizonte: {missing_models[:5]}"
                       + (" (und weitere)" if len(missing_models) > 5 else "")
        })

    try:
        from dem_feature import _DEM_TILES, _get_dem_dir
        dem_dir = _get_dem_dir()
        missing_tiles = [
            fn for fn, _ in _DEM_TILES
            if not os.path.exists(os.path.join(dem_dir, fn))
        ]
        if missing_tiles:
            warnings.append({
                "level": "warning",
                "message": f"DEM: {len(missing_tiles)}/{len(_DEM_TILES)} Kacheln fehlen: {missing_tiles}"
            })
    except Exception as e:
        warnings.append({"level": "info", "message": f"DEM-Status: {e}"})

    return jsonify({
        "ok": not any(w["level"] == "error" for w in warnings),
        "admin_horizons": admin_horizons,
        "model_horizons": model_horizons,
        "warnings": warnings,
    })

@app.route("/api/thresholds")
def api_thresholds():
    eff = runtime_config.all_effective()
    return jsonify({
        "FILTER_CONFIG": eff.get("FILTER_CONFIG"),
        "CORE_HSV_RANGES": eff.get("CORE_HSV_RANGES"),
        "HSV_BAND_LABELS": eff.get("HSV_BAND_LABELS"),
    })


@app.route("/api/thresholds", methods=["POST"])
def api_thresholds_save():
    def _check_hsv_band(band, ctx):
        if not (isinstance(band, list) and len(band) == 2):
            raise ValueError(f"{ctx}: braucht [lower, upper]")
        for bound in band:
            if not (isinstance(bound, list) and len(bound) == 3):
                raise ValueError(f"{ctx}: Grenze muss [H,S,V] sein")
            if not all(isinstance(c, (int, float)) and 0 <= c <= 255 for c in bound):
                raise ValueError(f"{ctx}: HSV-Wert außerhalb 0-255: {bound}")

    try:
        data = request.get_json(force=True)
        if not isinstance(data, dict):
            raise ValueError("Payload muss JSON-Objekt sein")
        allowed = {"FILTER_CONFIG", "CORE_HSV_RANGES", "HSV_BAND_LABELS"}
        unknown = set(data.keys()) - allowed
        if unknown:
            raise ValueError(f"Unbekannte Schlüssel: {sorted(unknown)}")
        if "FILTER_CONFIG" in data:
            fc = data["FILTER_CONFIG"]
            if not isinstance(fc, dict):
                raise ValueError("FILTER_CONFIG muss Objekt sein")
            if "min_object_area" in fc:
                v = fc["min_object_area"]
                if not isinstance(v, (int, float)) or not (1 <= v <= 100000):
                    raise ValueError(f"min_object_area ungültig (1-100000): {v}")
            for i, b in enumerate(fc.get("allowed_hsv_ranges", [])):
                _check_hsv_band(b, f"FILTER_CONFIG.allowed_hsv_ranges[{i}]")
        if "CORE_HSV_RANGES" in data:
            if not isinstance(data["CORE_HSV_RANGES"], list):
                raise ValueError("CORE_HSV_RANGES muss Liste sein")
            for i, b in enumerate(data["CORE_HSV_RANGES"]):
                _check_hsv_band(b, f"CORE_HSV_RANGES[{i}]")
        if "HSV_BAND_LABELS" in data:
            lbl = data["HSV_BAND_LABELS"]
            if not isinstance(lbl, list) or not all(isinstance(s, str) for s in lbl):
                raise ValueError("HSV_BAND_LABELS muss String-Liste sein")
    except (ValueError, TypeError, KeyError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    runtime_config.patch(data)
    return jsonify({"ok": True})


@app.route("/api/intensity_bands")
def api_intensity_bands_get():
    """Liefert die aktuellen Intensitätszonen-Konfiguration."""
    from config import INTENSITY_BANDS_DEFAULT
    bands = runtime_config.get("INTENSITY_BANDS", INTENSITY_BANDS_DEFAULT)
    return jsonify({"bands": bands})


@app.route("/api/intensity_bands", methods=["POST"])
def api_intensity_bands_save():
    """Speichert neue Intensitätszonen-Konfiguration."""
    try:
        data = request.get_json(force=True)
        bands = data.get("bands")
        assert isinstance(bands, list) and len(bands) >= 1
        for b in bands:
            assert len(b) == 4, "Jedes Band: [label, [h,s,v], [h,s,v], '#hex']"
            assert isinstance(b[0], str)
            assert len(b[1]) == 3 and len(b[2]) == 3
            assert all(0 <= int(v) <= 255 for v in b[1] + b[2])
            assert isinstance(b[3], str) and b[3].startswith("#")
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    runtime_config.patch({"INTENSITY_BANDS": bands})
    return jsonify({"ok": True})


@app.route("/api/training")
def api_training():
    return jsonify({
        "TRAINING_SCHEDULE": runtime_config.get("TRAINING_SCHEDULE", {}),
        "DATASET_REBUILD_INTERVAL_MIN": runtime_config.get("DATASET_REBUILD_INTERVAL_MIN"),
        "RETRAIN_INTERVAL_HOURS": runtime_config.get("RETRAIN_INTERVAL_HOURS"),
    })


@app.route("/api/training", methods=["POST"])
def api_training_save():
    # P35: Range-Checks für Training-Parameter
    _TRAINING_ALLOWED_KEYS = {
        "TRAINING_SCHEDULE", "DATASET_REBUILD_INTERVAL_MIN",
        "RETRAIN_INTERVAL_HOURS", "LOCAL_TRAINING",
    }
    try:
        data = request.get_json(force=True)
        if not isinstance(data, dict):
            raise ValueError("Payload muss JSON-Objekt sein")
        unknown = set(data.keys()) - _TRAINING_ALLOWED_KEYS
        if unknown:
            raise ValueError(f"Unbekannte Schlüssel: {sorted(unknown)}")
        if "DATASET_REBUILD_INTERVAL_MIN" in data:
            v = int(data["DATASET_REBUILD_INTERVAL_MIN"])
            if not (5 <= v <= 1440):
                raise ValueError(f"DATASET_REBUILD_INTERVAL_MIN muss 5-1440 sein, nicht {v}")
        if "RETRAIN_INTERVAL_HOURS" in data:
            v = int(data["RETRAIN_INTERVAL_HOURS"])
            if not (1 <= v <= 168):
                raise ValueError(f"RETRAIN_INTERVAL_HOURS muss 1-168 sein, nicht {v}")
        if "LOCAL_TRAINING" in data:
            if not isinstance(data["LOCAL_TRAINING"], bool):
                raise ValueError("LOCAL_TRAINING muss bool sein")
        if "TRAINING_SCHEDULE" in data:
            ts = data["TRAINING_SCHEDULE"]
            if not isinstance(ts, dict):
                raise ValueError("TRAINING_SCHEDULE muss Objekt sein")
    except (ValueError, TypeError, KeyError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    runtime_config.patch(data)
    return jsonify({"ok": True})


@app.route("/api/config")
def api_config_get():
    """
    Gibt die vollständige aktive Konfiguration zurück (Secrets entfernt).
    Finding #3 Fix: PX_TO_KMH explizit ergänzen falls nicht in runtime_config.
    Frontend darf keine eigene PX_TO_KMH-Formel haben.
    """
    from config import PX_TO_KMH as _PX_DEFAULT
    raw = runtime_config.all_effective()
    # PX_TO_KMH immer explizit mitliefern — Frontend Single Source of Truth
    if "PX_TO_KMH" not in raw:
        raw["PX_TO_KMH"] = runtime_config.get("PX_TO_KMH", _PX_DEFAULT)
    return jsonify(_redact_secrets(raw))


@app.route("/api/config", methods=["POST"])
def api_config_save():
    try:
        data = request.get_json(force=True)
        assert isinstance(data, dict)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    runtime_config.patch(data)
    return jsonify({"ok": True})


@app.route("/api/progress")
def api_progress():
    rows = []
    for p in sorted(glob.glob(os.path.join(SAVE_PATHS["models"], "v_*/training_meta.json"))):
        try:
            rows.append(json.load(open(p, encoding="utf-8")))
        except Exception:
            continue
    return jsonify({"versions": rows})


@app.route("/api/severity_accuracy")
def api_severity_accuracy():
    try:
        hours = int(request.args.get("hours", 24))
    except (TypeError, ValueError):
        hours = 24
    hours = max(1, min(hours, 168))
    try:
        from severity_verification import evaluate_severity
        return jsonify(evaluate_severity(hours))
    except Exception as exc:
        debug_log(f"[API] /api/severity_accuracy Fehler: {exc}")
        return jsonify({"samples": 0, "error": str(exc)}), 200


@app.route("/api/accuracy")
def api_accuracy():
    since = int(request.args.get("hours", "24"))
    horizons = runtime_config.get("ML_FORECAST_HORIZONS_MIN", [10, 20, 30, 40, 60])
    return jsonify({
        "current": evaluate_all(horizons, since_hours=since),
        "history": load_history(since_hours=max(since, 24 * 7)),
    })


# Öffentliche Browser-URLs pro externer Schnittstelle (konfigurierbar)
_API_PUBLIC_URLS: dict = {
    "geosphere_tawes":        "https://tawes.at/#knt",
    "arso_radar":             "https://meteo.arso.gov.si/uploads/probase/www/nowcast/inca/",
    "openmeteo_icon_d2":      "https://open-meteo.com/en/docs",
    "openmeteo_icon_global":  "https://open-meteo.com/en/docs",
    "geosphere_cape":         "https://dataset.api.hub.geosphere.at/",
    "eumetview_wms":          "https://eumetview.eumetsat.int/",
    "blitzortung":            "https://www.blitzortung.org/",
    "geosphere_nowcast":      "https://dataset.api.hub.geosphere.at/",
    "anthropic_api":          "https://console.anthropic.com/",
}


@app.route("/api/api_calls")
def api_api_calls():
    """Request-Zähler pro externer Schnittstelle für Admin-Panel."""
    from debug_utils import api_call_summary
    hours = int(request.args.get("hours", "24"))
    data = api_call_summary(since_hours=hours)
    # public_url je Service ergänzen (für Dashboard-Link-Anzeige)
    for svc, info in data.get("by_service", {}).items():
        pub = _API_PUBLIC_URLS.get(svc)
        if pub:
            info["public_url"] = pub
    return jsonify(data)


@app.route("/api/api_calls/detail")
def api_api_calls_detail():
    """
    Letzte N Einträge aus api_call_counts.jsonl für einen Service.
    Query-Parameter: service=<name>, n=<int default 20>, hours=<int default 24>
    Liefert auch duration_ms (Fix #10) wenn vom Logger mitgeschrieben.
    Antwort: {service, entries:[{ts, url, status, duration_ms}], total, public_url}
    """
    from datetime import datetime as _dt2, timedelta as _td2
    service = request.args.get("service", "")
    try:
        n = max(1, min(int(request.args.get("n", "20")), 200))
    except (ValueError, TypeError):
        n = 20
    try:
        hours = max(1, min(int(request.args.get("hours", "24")), 720))
    except (ValueError, TypeError):
        hours = 24
    cutoff  = _dt2.utcnow() - _td2(hours=hours)
    clear_since = _get_log_clear_since()
    if clear_since:
        try:
            cutoff = max(cutoff, _dt2.fromisoformat(clear_since.replace("Z", "")))
        except Exception:
            pass
    log_path = os.path.join(
        SAVE_PATHS.get("evaluation", "train_data/evaluation").rstrip("/"),
        "api_call_counts.jsonl",
    )
    entries = []
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        if service and rec.get("service") != service:
                            continue
                        ts = _dt2.fromisoformat(rec.get("ts", "").replace("Z", ""))
                        if ts >= cutoff:
                            entries.append({
                                "ts":          rec.get("ts", ""),
                                "url":         rec.get("url", ""),
                                "status":      rec.get("status", 200),
                                "duration_ms": rec.get("duration_ms"),
                            })
                    except Exception:
                        continue
        except Exception as exc:
            return jsonify({"entries": [], "error": str(exc)})
    entries.sort(key=lambda r: r.get("ts", ""), reverse=True)
    return jsonify({
        "service":    service,
        "entries":    entries[:n],
        "total":      len(entries),
        "public_url": _API_PUBLIC_URLS.get(service),
    })


@app.route("/api/api_calls/last")
def api_api_calls_last():
    """Liefert genau den letzten API-Request (optional gefiltert nach Service/Zeitraum)."""
    from datetime import datetime as _dt2, timedelta as _td2
    service = request.args.get("service", "")
    try:
        hours = max(1, min(int(request.args.get("hours", "24")), 720))
    except (ValueError, TypeError):
        hours = 24
    cutoff = _dt2.utcnow() - _td2(hours=hours)
    clear_since = _get_log_clear_since()
    if clear_since:
        try:
            cutoff = max(cutoff, _dt2.fromisoformat(clear_since.replace("Z", "")))
        except Exception:
            pass
    log_path = os.path.join(
        SAVE_PATHS.get("evaluation", "train_data/evaluation").rstrip("/"),
        "api_call_counts.jsonl",
    )
    latest = None
    if not os.path.exists(log_path):
        return jsonify({"entry": None})
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if service and rec.get("service") != service:
                        continue
                    ts = _dt2.fromisoformat(rec.get("ts", "").replace("Z", ""))
                    if ts < cutoff:
                        continue
                    latest = rec
                except Exception:
                    continue
    except Exception as exc:
        return jsonify({"entry": None, "error": str(exc)})
    if not latest:
        return jsonify({"entry": None})
    _raw_req  = latest.get("request") or {}
    _raw_resp = latest.get("response") or {}
    req = {
        "method":  _raw_req.get("method",  latest.get("method", "GET")),
        "url":     _raw_req.get("url",     latest.get("url", "")),
        # Neues Format: payload; altes Format: payload_preview
        "payload": _raw_req.get("payload", _raw_req.get("payload_preview")),
    }
    resp = {
        "status":         _raw_resp.get("status",       latest.get("status", 200)),
        "content_type":   _raw_resp.get("content_type"),
        # Neues Format: body_json / body_text / binary
        # Altes Format: body_preview — wird als body_text weitergegeben
        "body_json":      _raw_resp.get("body_json"),
        "body_text":      _raw_resp.get("body_text",
                              _raw_resp.get("body_preview") if not _raw_resp.get("body_json") else None),
        "binary":         _raw_resp.get("binary", False),
        "content_length": _raw_resp.get("content_length"),
        "sha256":         _raw_resp.get("sha256"),
        "saved_to":       _raw_resp.get("saved_to"),
        "truncated":      False,   # wird nie mehr True gesetzt
        "error":          _raw_resp.get("error"),
    }
    entry = {
        "ts": latest.get("ts"),
        "service": latest.get("service"),
        "method": latest.get("method", req.get("method", "GET")),
        "url": latest.get("url", req.get("url", "")),
        "status": latest.get("status", resp.get("status", 200)),
        "duration_ms": latest.get("duration_ms"),
        "request": req,
        "response": resp,
        "public_url": _API_PUBLIC_URLS.get(latest.get("service", "")),
    }
    return jsonify({"entry": entry})


@app.route("/api/api_health_summary")
def api_api_health_summary():
    """Liefert API-Failure-Statistik der letzten N Stunden."""
    from debug_utils import api_health_summary
    hours = int(request.args.get("hours", "24"))
    return jsonify(api_health_summary(since_hours=hours))




@app.route("/api/dem_status")
def api_dem_status():
    """
    Prüft den aktuellen Zustand der Copernicus-DEM-Kacheln.
    Rückgabe:
      tiles_total    — Anzahl erwarteter Kacheln (8 für Kärnten)
      tiles_present  — Anzahl vorhandener .tif-Dateien
      tiles_missing  — Liste fehlender Dateinamen
      tiles_sizes_kb — Dict: Dateiname → Größe in KB
      mosaic_loaded  — ob das Mosaic im aktuellen Prozess im RAM ist
      dem_dir        — konfiguriertes Verzeichnis
      training_used  — ob DEM-Features in letztem Training enthalten waren
    """
    try:
        from dem_feature import _DEM_TILES, _get_dem_dir, _mosaic_data

        dem_dir = _get_dem_dir()
        present = []
        missing = []
        sizes = {}
        for fn, _ in _DEM_TILES:
            full = os.path.join(dem_dir, fn)
            if os.path.exists(full):
                present.append(fn)
                sizes[fn] = round(os.path.getsize(full) / 1024, 0)
            else:
                missing.append(fn)

        mosaic_loaded = _mosaic_data is not None
    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e),
            "tiles_total": 8,
            "tiles_present": 0,
            "tiles_missing": [],
            "mosaic_loaded": False,
        })

    # Training-Meta: wurden DEM-Features verwendet?
    dem_in_training = None
    meta_path = os.path.join(
        SAVE_PATHS.get("models", "train_data/models"), "current", "training_meta.json"
    )
    if os.path.exists(meta_path):
        try:
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
            features = meta.get("feature_names") or meta.get("features") or []
            dem_in_training = any("dem_" in str(f) for f in features)
        except Exception:
            dem_in_training = None

    all_present = len(missing) == 0
    return jsonify({
        "ok": all_present,
        "dem_dir": dem_dir,
        "tiles_total": len(_DEM_TILES),
        "tiles_present": len(present),
        "tiles_missing": missing,
        "tiles_sizes_kb": sizes,
        "mosaic_loaded": mosaic_loaded,
        "training_used": dem_in_training,
        "status_label": (
            "Vollständig" if all_present and mosaic_loaded
            else "Kacheln laden…" if all_present and not mosaic_loaded
            else f"{len(missing)} Kachel(n) fehlen"
        ),
    })
@app.route("/api/cache_status")
def api_cache_status():
    """
    Zeigt Cache-Zustand je Service:
    - Letzte gecachte Datei je Namespace
    - Alter in Sekunden
    - Konfigurierter TTL
    - Status: FRESH / STALE / MISSING
    Rückgabe: {services: [{namespace, last_fetch_ts, age_s, ttl_s, status, file}]}
    """
    import time as _t_cache
    try:
        from config import API_CACHE_TTL_SECONDS as _TTL_CFG
        import runtime_config as _rc
        ttl_map = _rc.get("API_CACHE_TTL_SECONDS", _TTL_CFG)
    except Exception:
        ttl_map = {}

    # Standard-TTL-Fallbacks je bekanntem Service
    _DEFAULT_TTLS = {
        # ── Laufend aktive Services (jeder Zyklus) ─────────────────────────
        # cache_key("geosphere:tawes_all") → Namespace geosphere_tawes_all
        "geosphere_tawes_all":          600,
        # cache_key("eumetview:capabilities") → Namespace eumetview_capabilities
        "eumetview_capabilities":        600,
        # cache_key("blitzortung:last_strikes") → Namespace blitzortung_last_strikes
        "blitzortung_last_strikes":       60,
        # ── Per-Objekt-Services (nur gecacht wenn Zellen aktiv) ─────────────
        "geosphere_cape":              1800,   # assign_cape_from_forecast.py
        "geosphere_nowcast":            600,   # fetch_geosphere_nowcast.py
        "openmeteo_icon_d2":           1800,   # fetch_arome_openmeteo.py
        "openmeteo_icon_eu_li":        1800,   # fetch_arome_openmeteo.py (LI-Fallback)
        "openmeteo_icon_global":       3600,   # fetch_700hpa_wind_per_object_slim.py
        "openmeteo_synoptic_500":      3600,   # fetch_synoptic_features.py (500hPa)
        "openmeteo_extended_15min":     900,   # fetch_openmeteo_extended.py
        "openmeteo_extended_pressure":  900,   # fetch_openmeteo_extended.py
        "openmeteo_extended_lpi":       900,   # fetch_openmeteo_extended.py
        "openmeteo_extended_gfs_conv":  900,   # fetch_openmeteo_extended.py
    }

    try:
        from api_cache import _CACHE_DIR
    except Exception:
        _CACHE_DIR = "train_data/api_cache"

    now = _t_cache.time()
    results = []

    # Alle Cache-Dateien lesen und je Namespace aggregieren
    namespace_files = {}
    if os.path.isdir(_CACHE_DIR):
        for fname in os.listdir(_CACHE_DIR):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(_CACHE_DIR, fname)
            # Namespace aus Dateinamen extrahieren (Format: ns_hash.json)
            parts = fname.replace(".json", "").rsplit("_", 1)
            ns = parts[0] if len(parts) == 2 else fname.replace(".json", "")
            try:
                age = now - os.path.getmtime(fpath)
                if ns not in namespace_files or age < namespace_files[ns]["age_s"]:
                    namespace_files[ns] = {
                        "file": fname,
                        "age_s": round(age),
                        "mtime": os.path.getmtime(fpath),
                    }
            except Exception:
                continue

    # Bekannte Services mit TTL-Infos aufbauen
    all_namespaces = set(list(_DEFAULT_TTLS.keys()) + list(namespace_files.keys()))
    for ns in sorted(all_namespaces):
        ttl = int(ttl_map.get(ns, _DEFAULT_TTLS.get(ns, 0)))

        info = namespace_files.get(ns)
        if info:
            age_s = info["age_s"]
            import datetime as _dt_c
            last_ts = _dt_c.datetime.utcfromtimestamp(info["mtime"]).isoformat(timespec="seconds") + "Z"
            next_allowed_s = max(0, ttl - age_s)
            status = "FRESH" if age_s <= ttl else "STALE"
        else:
            age_s = None
            last_ts = None
            next_allowed_s = 0
            status = "MISSING"

        results.append({
            "namespace": ns,
            "last_fetch_ts": last_ts,
            "age_s": age_s,
            "ttl_s": ttl if ttl else None,
            "next_allowed_in_s": next_allowed_s,
            "status": status,
        })

    return jsonify({"services": results, "cache_dir": _CACHE_DIR})


@app.route("/api/forecast_stats")
def api_forecast_stats():
    """
    Aggregiert forecast_mode ('ml' oder 'kinematic') aus den letzten N Objekt-JSONs.
    Zeigt: Anteil ML-Forecasts, Anteil Fallback, letzter gesehener Modus, seit wann.
    Query-Parameter: hours=<int default 24>
    """
    import glob as _gl
    from datetime import datetime as _dt2, timedelta as _td2
    try:
        hours = max(1, min(int(request.args.get("hours", "24")), 720))
    except (ValueError, TypeError):
        hours = 24

    obj_dir = SAVE_PATHS.get("objects", "train_data/objects")
    cutoff  = _dt2.utcnow() - _td2(hours=hours)

    ml_count        = 0
    kinematic_count = 0
    total_objects   = 0
    last_mode       = None
    last_ts         = None
    last_file_ts    = None

    try:
        files = sorted(_gl.glob(os.path.join(obj_dir, "*.json")))
        for fpath in files:
            try:
                # Zeitstempel aus Dateinamen extrahieren
                fname = os.path.basename(fpath).replace(".json", "")
                # Format: YYYY-MM-DD_HH-MM-SS
                file_dt = _dt2.strptime(fname, "%Y-%m-%d_%H-%M-%S")
            except ValueError:
                continue
            if file_dt < cutoff:
                continue
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    objs = json.load(f)
                if not isinstance(objs, list):
                    continue
                for obj in objs:
                    mode = obj.get("forecast_mode")
                    if mode == "ml":
                        ml_count += 1
                    elif mode in ("kinematic", "linear"):
                        kinematic_count += 1
                    total_objects += 1
                    if last_file_ts is None or file_dt > last_file_ts:
                        last_file_ts = file_dt
                        last_mode = mode
                        last_ts   = fname
            except Exception:
                continue
    except Exception as exc:
        return jsonify({"error": str(exc), "ml_count": 0, "kinematic_count": 0})

    total_with_mode = ml_count + kinematic_count
    return jsonify({
        "hours":            hours,
        "total_objects":    total_objects,
        "ml_count":         ml_count,
        "kinematic_count":  kinematic_count,
        "ml_pct":           round(ml_count / total_with_mode * 100, 1) if total_with_mode else None,
        "kinematic_pct":    round(kinematic_count / total_with_mode * 100, 1) if total_with_mode else None,
        "last_mode":        last_mode,
        "last_ts":          last_ts,
        "active_mode":      last_mode or "unbekannt",
    })


@app.route("/api/api_health_raw")
def api_api_health_raw():
    """Einzeleinträge aus api_health.jsonl (neueste zuerst) für Logs-Seite."""
    from datetime import datetime as _dt, timedelta as _td
    hours  = int(request.args.get("hours", "24"))
    limit  = min(int(request.args.get("n", "200")), 1000)
    cutoff = _dt.utcnow() - _td(hours=hours)
    clear_since = _get_log_clear_since()
    if clear_since:
        try:
            cutoff = max(cutoff, _dt.fromisoformat(clear_since.replace("Z", "")))
        except Exception:
            pass
    health_file = os.path.join(
        SAVE_PATHS.get("evaluation", "train_data/evaluation").rstrip("/"),
        "api_health.jsonl",
    )
    entries = []
    if os.path.exists(health_file):
        try:
            with open(health_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        ts  = _dt.fromisoformat(rec.get("ts_utc", "").replace("Z", ""))
                        if ts >= cutoff:
                            entries.append(rec)
                    except Exception:
                        continue
        except Exception as exc:
            return jsonify({"entries": [], "total": 0, "error": str(exc)})
    entries.sort(key=lambda r: r.get("ts_utc", ""), reverse=True)
    return jsonify({"entries": entries[:limit], "total": len(entries)})


@app.route("/api/logs")
def api_logs():
    lines = _coerce_log_limit(request.args.get("lines"), _LOGS_DEFAULT_LINES, 1, _LOGS_MAX_LINES)
    max_bytes = _coerce_log_limit(request.args.get("max_bytes"), _LOGS_DEFAULT_MAX_BYTES, 1024, _LOGS_MAX_BYTES)

    def safe_source(loader, label):
        try:
            return loader()
        except Exception as exc:
            app.logger.exception("[API-LOGS] source failed label=%s", label)
            return [f"[{label}] Fehler beim Lesen dieser Logquelle: {exc}"]

    return jsonify({
        "wetterprojekt": safe_source(lambda: _journalctl_unit_lines("wetterprojekt", limit=lines, max_bytes=max_bytes), "wetterprojekt"),
        "scheduler": safe_source(lambda: _journalctl_unit_lines("wetterprojekt-scheduler", limit=lines, max_bytes=max_bytes), "scheduler"),
        "admin": safe_source(lambda: _journalctl_unit_lines("wetterprojekt-admin", limit=lines, max_bytes=max_bytes), "admin"),
        "nginx_error": safe_source(lambda: _tail_readable_file_lines("/var/log/nginx/error.log", limit=lines, max_bytes=max_bytes), "nginx_error"),
        "nginx_access": safe_source(lambda: _tail_readable_file_lines("/var/log/nginx/access.log", limit=lines, max_bytes=max_bytes), "nginx_access"),
        "limits": {
            "lines": lines,
            "max_bytes": max_bytes,
            "max_lines": _LOGS_MAX_LINES,
            "max_max_bytes": _LOGS_MAX_BYTES,
            "note": "Anzeige kann gekürzt sein. Vollständige Logs befinden sich im Datenexport.",
        },
    })


@app.route("/api/logs/capabilities")
def api_logs_capabilities():
    allow = str(os.getenv("ALLOW_SYSTEM_LOG_PURGE", "false")).lower() == "true"
    return jsonify({"allow_physical_purge": allow})


@app.route("/api/logs/clear", methods=["POST"])
def api_logs_clear():
    """
    Löscht alle JSONL-Log-Dateien in train_data/evaluation/.
    Wird vom Logs-Frontend über den 'Alle Logs löschen'-Button aufgerufen.

    Gelöscht:  api_health.jsonl, api_call_counts.jsonl, cells_log.jsonl, cleanup_log.jsonl
    Erhalten:  Modelle, Trainingsdaten, accuracy_*.json, ai_suggestions/, atmosphere_latest.json
    """
    def _evaluation_dir():
        return SAVE_PATHS.get("evaluation", "train_data/evaluation").rstrip("/")
    def _log_clear_state_path():
        return os.path.join(_evaluation_dir(), "log_clear_state.json")
    def _utc_now_iso_z():
        from datetime import datetime as _dt
        return _dt.utcnow().isoformat(timespec="seconds") + "Z"
    def _write_log_clear_state(state):
        os.makedirs(_evaluation_dir(), exist_ok=True)
        with open(_log_clear_state_path(), "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

    _eval_dir = _evaluation_dir()
    os.makedirs(_eval_dir, exist_ok=True)
    _log_files = [
        "api_health.jsonl",
        "api_call_counts.jsonl",
        "cells_log.jsonl",
        "cleanup_log.jsonl",
        "eumetview_debug.jsonl",
    ]
    deleted = []
    errors  = []
    for fname in _log_files:
        fpath = os.path.join(_eval_dir, fname)
        try:
            if os.path.exists(fpath):
                os.remove(fpath)
                deleted.append(fname)
        except Exception as exc:
            errors.append(f"{fname}: {exc}")

    payload = request.get_json(silent=True) or {}
    physical_requested = bool(payload.get("physical"))
    allow_physical_purge = str(os.getenv("ALLOW_SYSTEM_LOG_PURGE", "false")).lower() == "true"
    cleared_at_utc = _utc_now_iso_z()
    state = {
        "cleared_at_utc": cleared_at_utc,
        "physical_purge_requested": physical_requested,
        "physical_purge_started_at_utc": None,
    }
    try:
        _write_log_clear_state(state)
    except Exception as exc:
        errors.append(f"log_clear_state.json: {exc}")

    physical_purge_started = False
    if physical_requested:
        if not allow_physical_purge:
            errors.append("Physisches Journal-Purge ist deaktiviert (ALLOW_SYSTEM_LOG_PURGE=false).")
        else:
            purge_script = "/usr/local/bin/wetterprojekt-purge-logs.sh"
            if not os.path.exists(purge_script):
                errors.append(f"Purge-Script fehlt: {purge_script}")
            else:
                try:
                    subprocess.Popen(["sudo", purge_script], start_new_session=True)
                    physical_purge_started = True
                    state["physical_purge_started_at_utc"] = _utc_now_iso_z()
                    _write_log_clear_state(state)
                except Exception as exc:
                    errors.append(f"Physisches Journal-Purge konnte nicht gestartet werden: {exc}")

    return jsonify({
        "ok": True,
        "deleted": deleted,
        "cleared_at_utc": cleared_at_utc,
        "system_logs_cleared_from_ui": True,
        "physical_purge_started": physical_purge_started,
        "errors": errors,
    })



# ---------- KI-Analyse-Pipeline ----------
@app.route("/api/ai_analysis/config")
def api_ai_analysis_config_get():
    cfg = runtime_config.get("AI_ANALYSIS_CONFIG", {})
    from config import AI_ANALYSIS_CONFIG as _default
    effective = dict(_default)
    effective.update(cfg)
    return jsonify(effective)


@app.route("/api/ai_analysis/config", methods=["POST"])
def api_ai_analysis_config_save():
    try:
        data = request.get_json(force=True)
        assert isinstance(data, dict)
        if "enabled" in data:
            data["enabled"] = bool(data["enabled"])
        if "cron_hour" in data:
            data["cron_hour"] = int(data["cron_hour"])
        if "cron_minute" in data:
            data["cron_minute"] = int(data["cron_minute"])
        if "max_tokens" in data:
            data["max_tokens"] = int(data["max_tokens"])
        if "since_hours" in data:
            data["since_hours"] = int(data["since_hours"])
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    from config import AI_ANALYSIS_CONFIG as _default
    merged = dict(_default)
    merged.update(runtime_config.get("AI_ANALYSIS_CONFIG", {}))
    merged.update(data)
    runtime_config.patch({"AI_ANALYSIS_CONFIG": merged})
    return jsonify({"ok": True})


@app.route("/api/ai_analysis/suggestions")
def api_ai_analysis_suggestions():
    try:
        from daily_analyzer import load_latest_suggestions
        n = int(request.args.get("n", "10"))
        return jsonify({"suggestions": load_latest_suggestions(n)})
    except Exception as e:
        return jsonify({"suggestions": [], "error": str(e)})


@app.route("/api/ai_analysis/models")
def api_ai_analysis_models():
    """Verfügbare Claude-Modelle für Admin-Dropdown."""
    return jsonify({
        "models": [
            {"id": "claude-haiku-4-5-20251001", "label": "Haiku 4.5 — schnell, günstig"},
            {"id": "claude-sonnet-4-6",          "label": "Sonnet 4.6 — Standard"},
            {"id": "claude-opus-4-6",            "label": "Opus 4.6 — leistungsstark"},
        ]
    })


@app.route("/api/ai_analysis/chat", methods=["POST"])
def api_ai_analysis_chat():
    """
    Freier KI-Chat mit optionalem System-Daten-, Quellcode-Kontext und Bildern.
    Body JSON:
      question       (str)        — Pflichtfeld
      include_data   (bool)       — System-Metriken (default true)
      include_source (bool)       — Quellcode-Kontext (default false)
      source_mode    ("short"|"full")
      model          (str)        — Claude-Modell-ID (default claude-sonnet-4-6)
      images         (list)       — optional, max. 5 Eintraege
                                    [{media_type: "image/png", data: "<base64>"}]
    """
    import base64 as _b64
    try:
        data     = request.get_json(force=True) or {}
        question = str(data.get("question", "")).strip()
        if not question:
            return jsonify({"ok": False, "error": "Feld 'question' fehlt"}), 400

        include_data   = bool(data.get("include_data", True))
        include_source = bool(data.get("include_source", False))
        source_mode    = str(data.get("source_mode", "short"))   # "short"|"full"
        model_id       = str(data.get("model", "claude-sonnet-4-6"))
        images_raw     = data.get("images", [])

        # --- Bild-Validierung ---
        if not isinstance(images_raw, list):
            return jsonify({"ok": False, "error": "'images' muss eine Liste sein"}), 400
        if len(images_raw) > 5:
            return jsonify({"ok": False, "error": "Maximal 5 Bilder erlaubt"}), 400

        _MAX_B64_LEN = 7_000_000  # ~5 MB unkomprimiert
        image_blocks = []
        for idx, img in enumerate(images_raw):
            mt   = str(img.get("media_type", "")).strip()
            b64  = str(img.get("data", "")).strip()
            if not mt.startswith("image/"):
                return jsonify({"ok": False,
                                "error": f"Bild {idx+1}: ungültiger media_type '{mt}'"}), 400
            if len(b64) > _MAX_B64_LEN:
                return jsonify({"ok": False,
                                "error": f"Bild {idx+1} ueberschreitet 5 MB"}), 400
            # Base64-Gueltigkeit pruefen
            try:
                _b64.b64decode(b64, validate=True)
            except Exception:
                return jsonify({"ok": False,
                                "error": f"Bild {idx+1}: ungueltige Base64-Kodierung"}), 400
            image_blocks.append({
                "type": "image",
                "source": {"type": "base64", "media_type": mt, "data": b64},
            })

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return jsonify({"ok": False, "error": "ANTHROPIC_API_KEY nicht gesetzt"}), 500

        import anthropic
        from config import AI_ANALYSIS_CONFIG as _def_cfg

        parts = []

        # Lokale Konfiguration IMMER senden — unabhängig von include_data.
        # Die KI kann nur sinnvolle Empfehlungen machen wenn sie Schwellwerte,
        # Horizonte, Orte und runtime_overrides als ersten Kontext sieht.
        try:
            from daily_analyzer import _sanitize_config
            _local_cfg = _sanitize_config(runtime_config.all_effective())
            parts.append(
                "=== LOKALE KONFIGURATION (runtime_overrides + config.py) ===\n"
                + json.dumps(_local_cfg, ensure_ascii=False, indent=1)
            )
        except Exception as _cfg_exc:
            parts.append(f"=== LOKALE KONFIGURATION (Fehler: {_cfg_exc}) ===")

        if include_data:
            from daily_analyzer import build_system_report
            cfg     = dict(_def_cfg)
            cfg.update(runtime_config.get("AI_ANALYSIS_CONFIG", {}))
            since_h = cfg.get("since_hours", 24)
            report  = build_system_report(since_hours=since_h)
            parts.append(
                f"=== SYSTEM-DATEN (letzte {since_h}h) ===\n"
                + json.dumps(report, ensure_ascii=False, indent=1)
            )
        if include_source:
            from daily_analyzer import _collect_source_context
            import runtime_config as _rc_chat
            from config import GITHUB_VERIFY_CONFIG as _GH_DEF
            _gh_cfg = dict(_rc_chat.get("GITHUB_VERIFY_CONFIG", _GH_DEF))
            _gh_cfg["full_source_mode"] = (source_mode == "full")
            import runtime_config as _rc_tmp
            _rc_tmp.patch({"GITHUB_VERIFY_CONFIG": _gh_cfg})
            ctx = _collect_source_context()
            # Override nach dem Call zurücksetzen
            _gh_cfg["full_source_mode"] = False
            _rc_tmp.patch({"GITHUB_VERIFY_CONFIG": _gh_cfg})
            parts.append(
                "=== QUELLCODE-KONTEXT (GitHub) ===\n"
                + json.dumps(ctx, ensure_ascii=False, indent=1)
            )

        _source_addon = ""
        if include_source:
            _source_addon = (
                "\n\n"
                "ZUSATZREGEL — gilt nur wenn Quellcode-Kontext enthalten ist:\n"
                "Wenn du in dem gezeigten Quellcode einen konkreten Bug oder eine "
                "kritische Schwachstelle erkennst, liefere am Ende deiner Antwort "
                "einen fertigen Claude Code Prompt in folgendem Format:\n"
                "\n"
                "```claudecode\n"
                "Datei: <exakter Dateiname>\n"
                "Aenderung: TEILERSATZ oder VOLLERSATZ\n"
                "\n"
                "SUCHE exakt:\n"
                "    <exakter Such-String aus dem Code, unveraendert>\n"
                "\n"
                "ERSETZE durch:\n"
                "    <exakter Ersatz-String>\n"
                "\n"
                "Verifikation:\n"
                "    <bash-Befehl der den Fix beweist>\n"
                "```\n"
                "\n"
                "Regeln fuer den claudecode-Block:\n"
                "- SUCHE-String muss exakt so im Code vorkommen (kopiere ihn wortwörtlich)\n"
                "- Maximal 1 Bug pro claudecode-Block; mehrere Bugs = mehrere Bloecke\n"
                "- Kein claudecode-Block wenn kein konkreter Bug gefunden wurde\n"
                "- Keine Vermutungen — nur Bugs die du im gezeigten Code siehst"
            )

        system_prompt = (
            "Du bist Experte fuer das WetterExtended-Sturmzell-Tracking-System "
            "in Kaernten/Oesterreich (Raspberry Pi 5, Hailo-8 AI, ARSO-Radar). "
            "Beantworte die Frage praezise auf Basis des bereitgestellten Kontexts. "
            "Antworte auf Deutsch. Sei konkret und praxisnah."
            + _source_addon
        )

        # Kontext-Text aufbauen
        text_prefix = "\n\n".join(parts)
        full_text   = (text_prefix + f"\n\n=== FRAGE ===\n{question}"
                       if text_prefix else question)

        # --- Optionales Radarbild voranstellen ---
        include_radar = bool(data.get("include_radar", False))
        radar_block   = None
        radar_ts_info = ""
        if include_radar:
            import glob as _gl
            radar_files = sorted(_gl.glob(os.path.join("data", "radar", "radar_*.png")))
            if radar_files:
                try:
                    with open(radar_files[-1], "rb") as _rf:
                        _raw = _rf.read()
                    radar_b64   = _b64.b64encode(_raw).decode("ascii")
                    radar_block = {
                        "type": "image",
                        "source": {
                            "type":       "base64",
                            "media_type": "image/png",
                            "data":       radar_b64,
                        },
                    }
                    # Timestamp aus Dateiname extrahieren fuer KI-Kontext
                    _rname     = os.path.basename(radar_files[-1])
                    _rts       = _rname.replace("radar_", "").replace(".png", "")
                    radar_ts_info = f"\n[Radarbild-Zeitstempel: {_rts} (Lokalzeit Wien)]"
                except Exception as _re:
                    debug_log(f"[CHAT] Radarbild konnte nicht gelesen werden: {_re}")
            else:
                debug_log("[CHAT] include_radar=True aber kein Radarbild in data/radar/ vorhanden")

        # Timestamp in Fragetext einbetten wenn Radarbild vorhanden
        if radar_ts_info:
            full_text = full_text + radar_ts_info

        # Content-Array: Radarbild (falls vorhanden) → user-uploads → Text
        leading = ([radar_block] if radar_block else [])
        content: list = leading + image_blocks + [{"type": "text", "text": full_text}]

        client  = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=model_id,
            max_tokens=2000,
            system=system_prompt,
            messages=[{"role": "user", "content": content}],
        )
        answer = message.content[0].text if message.content else "(keine Antwort)"
        # E-Mail-Versand der Chat-Antwort (wenn report_email konfiguriert)
        try:
            from config import AI_ANALYSIS_CONFIG as _ai_cfg_dflt
            _ai_cfg_chat = dict(_ai_cfg_dflt)
            _ai_cfg_chat.update(runtime_config.get("AI_ANALYSIS_CONFIG", {}))
            _chat_mail = _ai_cfg_chat.get("report_email", "").strip()
            if _chat_mail:
                from email_notifier import send_chat_email as _sce
                _sce(question=question, answer=answer,
                     model=model_id, email_str=_chat_mail)
                debug_log(f"[CHAT-EMAIL] Gesendet an: {_chat_mail}")
        except Exception as _em_chat:
            debug_log(f"[CHAT-EMAIL] Versand fehlgeschlagen: {_em_chat}")
        return jsonify({
            "ok":         True,
            "answer":     answer,
            "model":      model_id,
            "image_count": len(image_blocks),
        })

    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/ai_analysis/run", methods=["POST"])
def api_ai_analysis_run():
    """Manueller Trigger für Sofort-Analyse (ignoriert enabled-Flag)."""
    try:
        from daily_analyzer import run_analysis
        from config import AI_ANALYSIS_CONFIG as _default
        cfg = dict(_default)
        cfg.update(runtime_config.get("AI_ANALYSIS_CONFIG", {}))
        cfg["enabled"] = True
        body = request.get_json(force=True, silent=True) or {}
        cfg["full_source_mode"] = (body.get("source_mode", "short") == "full")
        result = run_analysis(cfg)
        if result is None:
            return jsonify({"ok": False, "error": "Analyse fehlgeschlagen (siehe Logs)"}), 500
        # NaN/Inf-Bereinigung: ML-Accuracy-Daten können float('nan') enthalten
        # → ungültiges JSON → JSON.parse-Fehler im Frontend
        result_clean = _sanitize_for_json(result)
        return jsonify({"ok": True, "result": result_clean})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/ai_analysis/test_email", methods=["POST"])
def api_ai_analysis_test_email():
    """Sendet eine Test-E-Mail um SMTP-Konfiguration und report_email zu prüfen."""
    try:
        from email_notifier import _is_configured, _send_smtp
        from config import AI_ANALYSIS_CONFIG as _default
        from datetime import datetime as _dt

        cfg = dict(_default)
        cfg.update(runtime_config.get("AI_ANALYSIS_CONFIG", {}))

        # E-Mail aus Request-Body hat Vorrang (Test vor dem Speichern möglich)
        body = request.get_json(force=True, silent=True) or {}
        report_email = body.get("report_email", "").strip() or cfg.get("report_email", "").strip()
        if not report_email:
            return jsonify({"ok": False,
                            "error": "Keine E-Mail-Adresse konfiguriert (report_email leer)"}), 400
        if not _is_configured():
            return jsonify({"ok": False,
                            "error": "SMTP nicht konfiguriert — SMTP_HOST/USER/PASS in .env prüfen"}), 400

        ts = _dt.utcnow().strftime("%d.%m.%Y %H:%M UTC")
        html = f"""<!DOCTYPE html>
<html lang="de"><head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:520px;margin:0 auto;
             padding:16px;background:#f5f5f5">
  <div style="background:#2563eb;color:white;padding:16px 20px;
              border-radius:8px 8px 0 0">
    <h2 style="margin:0;font-size:18px">✅ SMTP-Test erfolgreich</h2>
    <p style="margin:4px 0 0;opacity:.9">WetterExtended — {ts}</p>
  </div>
  <div style="background:#fff;padding:20px;border:1px solid #ddd;
              border-radius:0 0 8px 8px">
    <p>Die E-Mail-Konfiguration funktioniert korrekt.</p>
    <p style="font-size:13px;color:#6b7280">
      Tägliche KI-Reports werden automatisch an diese Adresse gesendet,
      sobald die KI-Analyse aktiviert ist und eine Analyse abgeschlossen wurde.
    </p>
    <hr style="border:none;border-top:1px solid #eee;margin:16px 0">
    <p style="font-size:11px;color:#aaa;margin:0">
      WetterExtended &bull; Kärnten Radar-Tracking
    </p>
  </div>
</body></html>"""

        ok = _send_smtp([report_email],
                        f"✅ WetterExtended SMTP-Test {ts}", html)
        if ok:
            return jsonify({"ok": True,
                            "message": f"Test-Mail gesendet an {report_email}"})
        return jsonify({"ok": False, "error": "SMTP-Fehler beim Senden — Logs prüfen"}), 500
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/whatsapp/test", methods=["POST"])
def api_whatsapp_test():
    """
    Sendet eine WhatsApp-Testnachricht an alle Empfaenger im uebergebenen wa_str.
    Bypasst den Cooldown — nur fuer manuelle Konfigurationspruefung.

    Request-Body: {"wa_str": "+43699...:KEY1;+43664...:KEY2"}
    Response:     {"ok": bool, "sent_to": [...], "failed": [...], "error": str|None}
    """
    try:
        body    = request.get_json(force=True, silent=True) or {}
        wa_str  = str(body.get("wa_str", "")).strip()
        if not wa_str:
            return jsonify({"ok": False, "sent_to": [], "failed": [],
                            "error": "wa_str fehlt oder leer"}), 400

        from whatsapp_notifier import send_test_wa
        result = send_test_wa(wa_str)

        # Logging fuer Dashboard (analog zu anderen API-Calls)
        try:
            from debug_utils import log_api_call
            _err = result.get("error")
            _body = f"sent={result['sent_to']}, failed={result['failed']}"
            if _err:
                _body += f", error={_err[:300]}"
            log_api_call(
                "callmebot_whatsapp",
                url="https://api.callmebot.com/whatsapp.php",
                status_code=200 if result["ok"] else 400,
                method="POST",
                response_text=_body,
            )
        except Exception:
            pass

        return jsonify(result)
    except Exception as exc:
        return jsonify({"ok": False, "sent_to": [], "failed": [],
                        "error": str(exc)}), 500


@app.route("/api/dataset_stats")
def api_dataset_stats():
    """Statistik über gesammelte Trainingsdaten und Dataset-Größe."""
    import glob as _glob

    obj_files = sorted(_glob.glob(os.path.join(SAVE_PATHS["objects"], "*.json")))
    npz_path  = os.path.join(SAVE_PATHS["dataset"], "dataset.npz")

    # Dataset-Samples aus NPZ
    dataset_samples = 0
    dataset_features = 0
    if os.path.exists(npz_path):
        try:
            import numpy as _np
            ds = _np.load(npz_path, allow_pickle=True)
            if "X" in ds:
                dataset_samples  = int(ds["X"].shape[0])
                dataset_features = int(ds["X"].shape[-1]) if ds["X"].ndim >= 2 else 0
        except Exception:
            pass

    # Objekt-Datei Zeitraum
    first_ts = os.path.basename(obj_files[0]).replace(".json", "") if obj_files else None
    last_ts  = os.path.basename(obj_files[-1]).replace(".json", "") if obj_files else None

    # Letzter Cleanup-Log-Eintrag
    cleanup_log = os.path.join(SAVE_PATHS["evaluation"], "cleanup_log.jsonl")
    last_cleanup = None
    if os.path.exists(cleanup_log):
        try:
            with open(cleanup_log, encoding="utf-8") as f:
                lines = f.readlines()
            if lines:
                last_cleanup = json.loads(lines[-1].strip())
        except Exception:
            pass

    return jsonify({
        "object_files":      len(obj_files),
        "dataset_samples":   dataset_samples,
        "dataset_features":  dataset_features,
        "first_frame":       first_ts,
        "last_frame":        last_ts,
        "last_cleanup":      last_cleanup,
    })


@app.route("/api/cells_log")
def api_cells_log():
    """Letzte N Einträge aus cells_log.jsonl — welche Zellen wurden wann erkannt."""
    import glob as _gl
    n = min(int(request.args.get("n", "50")), 500)
    log_path = os.path.join(SAVE_PATHS.get("evaluation", "train_data/evaluation"), "cells_log.jsonl")
    entries = []
    clear_since = _get_log_clear_since()
    clear_dt = None
    if clear_since:
        try:
            clear_dt = datetime.fromisoformat(clear_since.replace("Z", ""))
        except Exception:
            clear_dt = None
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8") as _f:
                for line in _f:
                    try:
                        rec = json.loads(line.strip())
                        if clear_dt:
                            ts_val = str(rec.get("ts_utc") or rec.get("timestamp_utc") or rec.get("ts") or "").replace("Z", "")
                            if ts_val:
                                try:
                                    if datetime.fromisoformat(ts_val) < clear_dt:
                                        continue
                                except Exception:
                                    pass
                        entries.append(rec)
                    except Exception:
                        continue
        except Exception:
            pass
    return jsonify(entries[-n:])


@app.route("/api/recent_frames")
def api_recent_frames():
    """Letzte N Frame-Dateien mit Timestamp, Objekt-Anzahl und Zell-IDs."""
    import glob as _glob
    n = min(int(request.args.get("n", 30)), 200)
    files = sorted(_glob.glob(os.path.join(SAVE_PATHS["objects"], "*.json")))[-n:]
    rows = []
    for f in reversed(files):
        ts = os.path.basename(f).replace(".json", "")
        try:
            objs = json.load(open(f, encoding="utf-8"))
            rows.append({
                "ts":    ts,
                "count": len(objs),
                "ids":   [o.get("id", "?") for o in objs],
                "modes": list({o.get("forecast_mode", "—") for o in objs}),
            })
        except Exception:
            rows.append({"ts": ts, "count": 0, "ids": [], "modes": []})
    return jsonify(rows)


@app.route("/api/atmosphere_status")
def api_atmosphere_status():
    """
    Liefert Metadaten zum Atmosphären-Snapshot:
    - last_update_ts : ISO-UTC-String des letzten Snapshot-Zeitstempels
    - next_update_in_s : Sekunden bis zur nächsten planmäßigen Aktualisierung
    - interval_min : konfiguriertes Aktualisierungsintervall [min]
    """
    import time as _t_atm
    from config import ATMOSPHERIC_SNAPSHOT_INTERVAL_MIN as _ATM_INTERVAL
    try:
        import runtime_config as _rc_atm
        interval_min = int(_rc_atm.get("ATMOSPHERIC_SNAPSHOT_INTERVAL_MIN", _ATM_INTERVAL))
    except Exception:
        interval_min = int(_ATM_INTERVAL)

    atm_path = os.path.join(
        SAVE_PATHS.get("evaluation", "train_data/evaluation"),
        "atmosphere_latest.json"
    )
    last_ts = None
    next_in_s = 0

    if os.path.exists(atm_path):
        try:
            age_s = _t_atm.time() - os.path.getmtime(atm_path)
            interval_s = interval_min * 60
            next_in_s = max(0, int(interval_s - age_s))
            # Zeitstempel aus Datei-Mtime
            import datetime as _dt_atm
            last_ts = _dt_atm.datetime.utcfromtimestamp(
                os.path.getmtime(atm_path)
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            pass

    return jsonify({
        "last_update_ts":  last_ts,
        "next_update_in_s": next_in_s,
        "interval_min":    interval_min,
    })


@app.route("/api/atmosphere")
def api_atmosphere():
    """Atmosphärischer Zustand für Kärnten-Referenzpunkte (unabhängig von Zellen)."""
    import glob as _glob
    path = os.path.join(SAVE_PATHS["evaluation"], "atmosphere_latest.json")
    if not os.path.exists(path):
        return jsonify({"ts_utc": None, "locations": [], "note": "noch kein Snapshot"})
    try:
        with open(path, encoding="utf-8") as f:
            return jsonify(json.load(f))
    except Exception as exc:
        return jsonify({"error": str(exc), "locations": []}), 500


@app.route("/api/cpu_history")
def api_cpu_history():
    """
    CPU-Auslastungs-Zeitreihe der letzten N Stunden.

    Query-Parameter:
        hours (int, default 24): Zeitfenster in Stunden (max. 48)

    Response:
        {
            "samples": [
                {"ts_utc": "2026-05-28T11:00:00Z", "cores": [12.5, 8.2, 45.1, 6.0], "avg": 17.95},
                ...
            ],
            "core_count": 4,
            "hours": 24
        }
    """
    try:
        hours = min(int(request.args.get("hours", "24")), 48)
    except (ValueError, TypeError):
        hours = 24
    try:
        from cpu_monitor import get_cpu_history
        samples = get_cpu_history(hours=hours)
    except Exception as exc:
        return jsonify({"error": str(exc), "samples": [], "core_count": 0, "hours": hours}), 500
    core_count = len(samples[0]["cores"]) if samples else 0
    return jsonify({"samples": samples, "core_count": core_count, "hours": hours})


@app.route("/api/disk")
def api_disk():
    """Disk-Usage des Raspberry Pi für Dashboard-Monitoring."""
    import shutil
    total, used, free = shutil.disk_usage("/")
    pct = (used / total) * 100 if total else 0
    return jsonify({
        "total_gb":  round(total / 1e9, 1),
        "used_gb":   round(used / 1e9, 1),
        "free_gb":   round(free / 1e9, 1),
        "used_pct":  round(pct, 1),
        "warning":   pct > 80,
        "critical":  pct > 90,
    })


@app.route("/api/local_training")
def api_local_training():
    """Gibt an ob lokales Training aktiv ist (für Training.jsx Banner)."""
    return jsonify({
        "local_training": runtime_config.get("LOCAL_TRAINING", True),
    })


@app.route("/api/training_readiness")
def api_training_readiness():
    """
    B99: Trainingsbereitschaft — wieviele Sequenzen noch fehlen.
    Liest die aktuelle Sequenzzahl aus dataset.npz und vergleicht mit
    den konfigurierten Mindestschwellen (MIN_SEQUENCES_LSTM/LGBM).
    """
    try:
        from config import MIN_SEQUENCES_LSTM as _lstm_def, MIN_SEQUENCES_LGBM as _lgbm_def
    except ImportError:
        _lstm_def, _lgbm_def = 50, 30

    lstm_min = int(runtime_config.get("MIN_SEQUENCES_LSTM", _lstm_def))
    lgbm_min = int(runtime_config.get("MIN_SEQUENCES_LGBM", _lgbm_def))

    dataset_path = os.path.join(
        SAVE_PATHS.get("dataset", "train_data/dataset"), "dataset.npz"
    )
    current = 0
    dataset_exists = os.path.exists(dataset_path)
    if dataset_exists:
        try:
            import numpy as _np_rd
            _d = _np_rd.load(dataset_path, allow_pickle=True)
            current = int(_d["X"].shape[0])
        except Exception as _exc:
            debug_log(f"[API] training_readiness: dataset.npz lesen fehlgeschlagen: {_exc}")

    return jsonify({
        "current_sequences":  current,
        "dataset_exists":     dataset_exists,
        "lstm": {
            "required": lstm_min,
            "missing":  max(0, lstm_min - current),
            "ready":    current >= lstm_min,
        },
        "lgbm": {
            "required": lgbm_min,
            "missing":  max(0, lgbm_min - current),
            "ready":    current >= lgbm_min,
        },
        "all_ready": current >= lstm_min,
    })


@app.route("/api/hailo/reload", methods=["POST"])
def api_hailo_reload():
    """
    Leert den Hailo-Modell-Cache. Wird nach rsync neuer HEF-Dateien aufgerufen
    (sync_models_to_pi.sh). Graceful fallback wenn hailo_inference nicht verfügbar.
    """
    try:
        from hailo_inference import reload_models
        result = reload_models()
        return jsonify(result)
    except ImportError:
        return jsonify({"ok": True, "note": "hailo_inference nicht verfügbar (Phase A)"})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


# ---------------------------------------------------------------------------
# HitL Cell Filters — REST-Endpunkte
# ---------------------------------------------------------------------------

@app.route("/api/cell_filters", methods=["GET"])
def api_cell_filters_list():
    """Liefert alle aktiven Filter + KI-Vorschläge + Padding-Wert."""
    try:
        from cell_filters import load_filters, get_padding_px
        doc = load_filters()
        return jsonify({
            "ok":              True,
            "version":         doc.get("version", 2),
            "active_filters":  doc.get("active_filters", []),
            "ai_suggestions":  doc.get("ai_suggestions", []),
            "padding_px":      get_padding_px(),
            "padding_default": getattr(_cfg_mod_safe(),
                                       "HITL_PADDING_PX_DEFAULT", 50),
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/cell_filters/<filter_id>", methods=["DELETE"])
def api_cell_filters_delete(filter_id):
    try:
        from cell_filters import remove_filter
        ok = remove_filter(filter_id)
        return jsonify({"ok": bool(ok)})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/cell_filters/<filter_id>", methods=["PATCH"])
def api_cell_filters_patch(filter_id):
    """Body: {"active": true/false}"""
    try:
        from cell_filters import set_filter_active
        data = request.get_json(force=True) or {}
        if "active" not in data:
            return jsonify({"ok": False, "error": "active fehlt"}), 400
        ok = set_filter_active(filter_id, bool(data["active"]))
        return jsonify({"ok": bool(ok)})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/cell_filters/<filter_id>/png", methods=["GET"])
def api_cell_filters_png(filter_id):
    """Liefert die PNG-Datei eines Filters."""
    import os as _os
    try:
        from cell_filters import load_filters
        from config import CELL_FILTERS_DIR
        doc = load_filters()
        target = next((e for e in doc.get("active_filters", [])
                       if e.get("id") == filter_id), None)
        if not target or not target.get("polygon_png"):
            return jsonify({"ok": False, "error": "PNG nicht vorhanden"}), 404
        abs_path = _os.path.join(CELL_FILTERS_DIR.rstrip("/"),
                                 target["polygon_png"])
        if not _os.path.exists(abs_path):
            return jsonify({"ok": False, "error": "PNG-Datei fehlt"}), 404
        directory = _os.path.dirname(abs_path)
        fname = _os.path.basename(abs_path)
        return send_from_directory(directory, fname, mimetype="image/png")
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/cell_filters/padding", methods=["GET"])
def api_cell_filters_padding_get():
    try:
        from cell_filters import get_padding_px
        return jsonify({
            "ok":         True,
            "padding_px": get_padding_px(),
            "default":    getattr(_cfg_mod_safe(),
                                  "HITL_PADDING_PX_DEFAULT", 50),
            "min":        5,
            "max":        500,
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/cell_filters/padding", methods=["POST"])
def api_cell_filters_padding_set():
    """Body: {"padding_px": int}"""
    try:
        data = request.get_json(force=True) or {}
        val = int(data.get("padding_px", 50))
        if not (5 <= val <= 500):
            return jsonify({"ok": False,
                            "error": "padding_px muss 5–500 sein"}), 400
        runtime_config.patch({"HITL_PADDING_PX": val})
        return jsonify({"ok": True, "padding_px": val})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/cell_filters/ai_analyze", methods=["POST"])
def api_cell_filters_ai_analyze():
    """
    Sendet die aktiven Filter + die letzten N Polygon-PNGs an die Anthropic API
    mit der Bitte, NEUE breitere HSV-Bereiche vorzuschlagen
    (HITL_AI_MODE = 'expand_only').

    Body (alles optional):
      {"model": str, "max_pngs": int}
    """
    import base64 as _b64
    import json as _json
    import os as _os
    try:
        from cell_filters import (
            list_active_polygon_pngs, load_filters, add_ai_suggestion,
        )
        from config import HITL_MAX_PNGS_FOR_AI, HITL_AI_MODE

        data = request.get_json(force=True) or {}
        model_id = str(data.get("model") or "claude-sonnet-4-6")[:60]
        max_pngs = int(data.get("max_pngs") or HITL_MAX_PNGS_FOR_AI)
        max_pngs = max(1, min(20, max_pngs))

        api_key = _os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return jsonify({"ok": False,
                            "error": "ANTHROPIC_API_KEY nicht gesetzt"}), 400

        # Letzte N Polygon-PNGs sammeln
        items = list_active_polygon_pngs(max_count=max_pngs)
        if not items:
            return jsonify({
                "ok": False,
                "error": ("Keine Polygon-PNGs vorhanden. Markiere zuerst "
                          "Zellen auf der Karte, dann erneut versuchen.")
            }), 400

        # Aktuelle aktive Filter zusammenstellen
        doc = load_filters()
        active = [{
            "id":         e["id"],
            "label":      e.get("label"),
            "hsv_range":  e.get("hsv_range"),
            "source":     e.get("source"),
        } for e in doc.get("active_filters", []) if e.get("active")]

        # Bilder als base64 anhängen
        image_blocks = []
        for it in items:
            try:
                with open(it["polygon_png_abs"], "rb") as f:
                    b64 = _b64.b64encode(f.read()).decode("ascii")
                image_blocks.append({
                    "type": "image",
                    "source": {"type": "base64",
                               "media_type": "image/png",
                               "data": b64},
                })
            except Exception as _e:
                debug_log(f"[HITL-AI] PNG nicht lesbar: {_e}")

        system_prompt = (
            "Du bist ein Experte für Radarbild-Segmentierung mit HSV-Farbräumen. "
            "Du erhältst eine Liste der aktuell aktiven HSV-Filter und mehrere "
            "Bildausschnitte mit markierten Sturmzellen (gelbe Umrandung). "
            "Deine Aufgabe: schlage AUSSCHLIESSLICH NEUE, breitere HSV-Bereiche "
            "vor, die ähnliche Zellen in Zukunft erkennen sollen. "
            "Modus: " + HITL_AI_MODE + " — keine bestehenden Bereiche verändern, "
            "nur ergänzen. Maximal 3 Vorschläge. "
            "Antworte AUSSCHLIESSLICH mit gültigem JSON in folgendem Format, "
            "kein Markdown, kein Vorwort:\n"
            "{\n"
            '  "suggestions": [\n'
            '    {\n'
            '      "hsv_range": [[h_lo,s_lo,v_lo],[h_hi,s_hi,v_hi]],\n'
            '      "label": "kurz_unique_name",\n'
            '      "rationale": "kurze Begründung (max 200 Zeichen)"\n'
            '    }\n'
            '  ]\n'
            "}\n"
            "Wertebereiche: H 0-179, S 0-255, V 0-255. "
            "Wenn keine sinnvolle Erweiterung möglich ist, "
            'gib {"suggestions": []} zurück.'
        )

        prompt_text = (
            "Aktive Filter:\n"
            + _json.dumps(active, ensure_ascii=False, indent=2)
            + f"\n\nAngehängt: {len(image_blocks)} Polygon-Ausschnitte "
              "mit gelb umrandeten Zellbereichen."
        )

        try:
            import anthropic
        except Exception:
            return jsonify({"ok": False,
                            "error": "anthropic-Modul nicht installiert"}), 500

        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=model_id,
            max_tokens=1500,
            system=system_prompt,
            messages=[{
                "role": "user",
                "content": image_blocks + [{"type": "text", "text": prompt_text}],
            }],
        )
        try:
            from debug_utils import log_api_call
            log_api_call("anthropic_api",
                         url="https://api.anthropic.com/v1/messages",
                         status_code=200)
        except Exception:
            pass

        raw = message.content[0].text if message.content else ""
        # Robustes JSON-Parsing — Antwort soll reines JSON sein
        try:
            parsed = _json.loads(raw)
        except Exception:
            # Notfall: JSON-Block extrahieren
            import re as _re
            m = _re.search(r"\{.*\}", raw, _re.DOTALL)
            parsed = _json.loads(m.group(0)) if m else {"suggestions": []}

        suggestions = parsed.get("suggestions") or []
        sug_id = add_ai_suggestion(
            model=model_id,
            based_on_filter_ids=[it["id"] for it in items],
            suggested_ranges=suggestions,
        )
        # E-Mail-Versand der Filter-Vorschläge (wenn report_email konfiguriert)
        try:
            from config import AI_ANALYSIS_CONFIG as _ai_cfg_dflt
            _ai_cfg_flt = dict(_ai_cfg_dflt)
            _ai_cfg_flt.update(runtime_config.get("AI_ANALYSIS_CONFIG", {}))
            _filter_mail = _ai_cfg_flt.get("report_email", "").strip()
            if _filter_mail:
                from email_notifier import send_filter_suggestion_email as _sfse
                _sfse(suggestions=suggestions, model=model_id,
                      suggestion_id=sug_id, email_str=_filter_mail)
                debug_log(f"[FILTER-EMAIL] Gesendet an: {_filter_mail}")
        except Exception as _em_flt:
            debug_log(f"[FILTER-EMAIL] Versand fehlgeschlagen: {_em_flt}")
        return jsonify({
            "ok":              True,
            "suggestion_id":   sug_id,
            "model":           model_id,
            "pngs_sent":       len(image_blocks),
            "suggestions":     suggestions,
            "raw_response":    raw[:2000],
        })

    except Exception as exc:
        import traceback
        return jsonify({"ok": False, "error": str(exc),
                        "trace": traceback.format_exc()}), 500


@app.route("/api/cell_filters/ai_suggestions", methods=["GET"])
def api_cell_filters_ai_suggestions():
    try:
        from cell_filters import load_filters
        doc = load_filters()
        return jsonify({"ok": True,
                        "suggestions": doc.get("ai_suggestions", [])})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/cell_filters/ai_suggestions/<suggestion_id>/accept",
           methods=["POST"])
def api_cell_filters_ai_suggestions_accept(suggestion_id):
    try:
        from cell_filters import accept_ai_suggestion
        new_ids = accept_ai_suggestion(suggestion_id)
        return jsonify({"ok": bool(new_ids),
                        "created_filter_ids": new_ids,
                        "count": len(new_ids)})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


def _cfg_mod_safe():
    """Lazy-Import von config, robust gegen Reload-Probleme."""
    try:
        import config as _c
        return _c
    except Exception:
        class _Stub: pass
        return _Stub()


# ---------- React-Frontend serven ----------
@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_react(path):
    """Serviert das gebaute React-Frontend aus frontend/dist/.
    Fallback: 404 wenn Build noch nicht da ist.
    """
    dist_dir = os.path.join(os.path.dirname(__file__), "frontend", "dist")
    if os.path.isdir(dist_dir):
        if path and os.path.exists(os.path.join(dist_dir, path)):
            return send_from_directory(dist_dir, path)
        return send_from_directory(dist_dir, "index.html")
    return jsonify({"ok": False, "error": "frontend build missing"}), 404

# ---------------------------------------------------------------------------
# Manuelles Zell-Markieren — Human-in-the-Loop
# ---------------------------------------------------------------------------

@app.route("/api/analyze_cell_polygon", methods=["POST"])
def api_analyze_cell_polygon():
    """
    Analysiert HSV-Werte im verarbeiteten Radarbild innerhalb eines vom Benutzer
    gezeichneten Polygons und schlägt einen neuen FILTER_CONFIG-Eintrag vor.

    Eingabe (JSON):
      { "coordinates": [[lon, lat], ...],  // GeoJSON-Reihenfolge (lon zuerst!)
        "label": "optional_name" }

    Ausgabe:
      { "ok": true,
        "pixel_count": int,
        "radar_path": str,
        "hsv_stats":  { h_min, h_max, h_mean, s_min, s_max, v_min, v_max },
        "suggested_range": [[h_lo, s_lo, v_lo], [h_hi, s_hi, v_hi]],
        "suggested_label": str,
        "already_covered": bool,
        "preview_rgb": [r, g, b] }
    """
    import glob as _glob
    import numpy as _np
    import cv2 as _cv2

    try:
        data = request.get_json(force=True)
        coords = data.get("coordinates", [])   # [[lon, lat], ...]
        label  = str(data.get("label", "manuell"))[:40]

        if len(coords) < 3:
            return jsonify({"ok": False,
                            "error": "Mindestens 3 Punkte erforderlich"}), 400

        # Aktuellstes verarbeitetes Radarbild (bereits gecroppt + upgeskaliert)
        _radar_dir = SAVE_PATHS.get("radar", "data/radar")
        radar_files = sorted(_glob.glob(os.path.join(_radar_dir, "radar_*.png")))
        if not radar_files:
            # Fallback: Originalbild (unkonsistente Pixelkoordinaten möglich)
            radar_files = [os.path.join("data", "latest.png")]
        radar_path = radar_files[-1]

        img_bgr = _cv2.imread(radar_path)
        if img_bgr is None:
            return jsonify({"ok": False,
                            "error": f"Radarbild nicht lesbar: {radar_path}"}), 500

        h_img, w_img = img_bgr.shape[:2]
        hsv_img = _cv2.cvtColor(img_bgr, _cv2.COLOR_BGR2HSV)
        img_rgb = _cv2.cvtColor(img_bgr, _cv2.COLOR_BGR2RGB)

        # Geo → Pixel (auf gecroptes+upgeskaliertes Bild)
        from geo_utils import geo_to_pixel_in_bbox
        from config import BBOX_KAERNTEN_EXTENDED as _BBOX

        px_points = []
        for lon, lat in coords:
            px, py = geo_to_pixel_in_bbox(float(lat), float(lon),
                                          _BBOX, w_img, h_img)
            px_points.append([px, py])

        # Polygon-Maske
        pts = _np.array(px_points, dtype=_np.int32).reshape(-1, 1, 2)
        poly_mask = _np.zeros((h_img, w_img), dtype=_np.uint8)
        _cv2.fillPoly(poly_mask, [pts], 255)

        # Weißen/schwarzen Hintergrund ausschließen
        r_ch = img_rgb[:, :, 0]
        g_ch = img_rgb[:, :, 1]
        b_ch = img_rgb[:, :, 2]
        bg = ((r_ch > 225) & (g_ch > 225) & (b_ch > 225)) |              ((r_ch < 20)  & (g_ch < 20)  & (b_ch < 20))
        valid_mask = (poly_mask == 255) & (~bg)

        valid_count = int(_np.sum(valid_mask))
        if valid_count < 5:
            return jsonify({
                "ok": False,
                "error": ("Zu wenige Vordergrundpixel im Polygon "
                          "(Hintergrund oder leeres Gebiet?)")
            }), 400

        h_vals = hsv_img[:, :, 0][valid_mask].astype(int)
        s_vals = hsv_img[:, :, 1][valid_mask].astype(int)
        v_vals = hsv_img[:, :, 2][valid_mask].astype(int)

        # 5./95.-Perzentil statt absolutem Min/Max (Ausreißer-robust)
        h_lo_raw = int(_np.percentile(h_vals, 5))
        h_hi_raw = int(_np.percentile(h_vals, 95))
        s_lo_raw = int(_np.percentile(s_vals, 10))
        v_lo_raw = int(_np.percentile(v_vals, 10))

        # ±5 Hue-Toleranz, Mindest-Sättigung 40, Mindest-Helligkeit 50
        h_lo = max(0,   h_lo_raw - 5)
        h_hi = min(179, h_hi_raw + 5)
        s_lo = max(40,  s_lo_raw - 10)
        v_lo = max(50,  v_lo_raw - 10)

        suggested = [[h_lo, s_lo, v_lo], [h_hi, 255, 255]]

        # Prüfen ob Range bereits abgedeckt
        fc_now = runtime_config.get("FILTER_CONFIG",
                                    {"allowed_hsv_ranges": []})
        already_covered = False
        for lo_ex, hi_ex in fc_now.get("allowed_hsv_ranges", []):
            if (int(lo_ex[0]) <= h_lo and int(hi_ex[0]) >= h_hi and
                    int(lo_ex[1]) <= s_lo and int(lo_ex[2]) <= v_lo):
                already_covered = True
                break

        # Durchschnitts-RGB für Farbvorschau im Dialog
        r_mean = int(_np.mean(img_rgb[:, :, 0][valid_mask]))
        g_mean = int(_np.mean(img_rgb[:, :, 1][valid_mask]))
        b_mean = int(_np.mean(img_rgb[:, :, 2][valid_mask]))

        # Automatisches Label aus Hue-Schwerpunkt
        h_center = int(_np.mean(h_vals))
        def _auto_label(hc: int) -> str:
            if hc <= 10 or hc >= 165: return "rot_manuell"
            if hc <= 27:              return "orange_manuell"
            if hc <= 55:              return "gelb_manuell"
            if hc <= 92:              return "gruen_manuell"
            if hc <= 124:             return "cyan_manuell"
            if hc <= 155:             return "violett_manuell"
            return "unbekannt_manuell"

        auto_label = label if label != "manuell" else _auto_label(h_center)

        return jsonify({
            "ok": True,
            "pixel_count":     valid_count,
            "radar_path":      os.path.basename(radar_path),
            "radar_filename":  os.path.basename(radar_path),
            "polygon_px":      [[int(p[0]), int(p[1])] for p in px_points],
            "hsv_stats": {
                "h_min":  int(h_vals.min()),  "h_max":  int(h_vals.max()),
                "h_mean": round(float(_np.mean(h_vals)), 1),
                "s_min":  int(s_vals.min()),  "s_max":  int(s_vals.max()),
                "v_min":  int(v_vals.min()),  "v_max":  int(v_vals.max()),
            },
            "suggested_range":  suggested,
            "suggested_label":  auto_label,
            "already_covered":  already_covered,
            "preview_rgb":      [r_mean, g_mean, b_mean],
        })

    except Exception as exc:
        import traceback
        return jsonify({"ok": False, "error": str(exc),
                        "trace": traceback.format_exc()}), 500


@app.route("/api/thresholds/add_range", methods=["POST"])
def api_thresholds_add_range():
    """
    Fügt einen HSV-Bereich als neuen Filter in cell_filters.json hinzu.
    Wenn polygon_px + radar_filename mitgegeben werden, wird zusätzlich
    ein PNG-Ausschnitt mit Maskenoverlay gespeichert.

    Eingabe:
      {
        "range":          [[h_lo, s_lo, v_lo], [h_hi, s_hi, v_hi]],
        "label":          "name",
        "polygon_px":     [[x, y], ...],     // optional, aus analyze-Response
        "radar_filename": "radar_YYYY-...png", // optional, aus analyze-Response
        "zoom_level":     11,                  // optional, Karten-Zoom
        "map_bounds":     {...}                // optional, Karten-Bounds
      }

    Rückgabe: {"ok": true, "filter_id": str, "total_active": int,
               "polygon_png": str | null}
    """
    import os as _os
    import cv2 as _cv2
    from cell_filters import (
        add_manual_filter, save_polygon_png, get_padding_px, load_filters,
    )
    try:
        data = request.get_json(force=True) or {}
        new_range = data.get("range")
        label = str(data.get("label", "manuell"))[:40]
        polygon_px = data.get("polygon_px") or []
        radar_filename = str(data.get("radar_filename") or "").strip()
        zoom_level = data.get("zoom_level")

        if not new_range or len(new_range) != 2:
            return jsonify({"ok": False,
                            "error": "range muss [[lo],[hi]] sein"}), 400
        for bound in new_range:
            if not (isinstance(bound, list) and len(bound) == 3):
                return jsonify({"ok": False,
                                "error": "Jede Grenze muss [H,S,V] sein"}), 400
            if not all(isinstance(c, (int, float)) and 0 <= c <= 255
                       for c in bound):
                return jsonify({"ok": False,
                                "error": f"HSV-Wert außerhalb 0-255: {bound}"}), 400

        # 1) Filter-Eintrag anlegen (ohne PNG)
        polygon_meta = {
            "zoom_level":     int(zoom_level) if zoom_level is not None else None,
            "radar_filename": radar_filename or None,
            "map_bounds":     data.get("map_bounds"),
        }
        filter_id = add_manual_filter(
            label=label,
            hsv_range=new_range,
            polygon_meta=polygon_meta,
            polygon_png=None,
            source="manual_polygon",
        )

        # 2) Optional: PNG erstellen
        png_rel = None
        if polygon_px and len(polygon_px) >= 3 and radar_filename:
            _radar_dir = SAVE_PATHS.get("radar", "data/radar")
            radar_path = _os.path.join("data", "radar", radar_filename)
            if not _os.path.exists(radar_path):
                radar_path = _os.path.join(_radar_dir, radar_filename)
            if _os.path.exists(radar_path):
                img = _cv2.imread(radar_path)
                if img is not None:
                    try:
                        png_rel = save_polygon_png(
                            filter_id=filter_id,
                            processed_img_bgr=img,
                            polygon_pixels_xy=polygon_px,
                            padding_px=get_padding_px(zoom_level),
                        )
                        # PNG-Pfad in den Filter-Eintrag nachtragen
                        from cell_filters import load_filters as _lf, save_filters as _sf
                        doc = _lf()
                        for entry in doc.get("active_filters", []):
                            if entry.get("id") == filter_id:
                                entry["polygon_png"] = png_rel
                                break
                        _sf(doc)
                    except Exception as _png_exc:
                        debug_log(f"[HITL] PNG-Erstellung fehlgeschlagen: {_png_exc}")

        # 3) Label in HSV_BAND_LABELS ergänzen (Backward-Compat für /thresholds-Seite)
        labels = list(runtime_config.get("HSV_BAND_LABELS", []))
        if label not in labels:
            labels.append(label)
            runtime_config.patch({"HSV_BAND_LABELS": labels})

        doc = load_filters()
        active_count = sum(1 for e in doc.get("active_filters", []) if e.get("active"))
        return jsonify({
            "ok":           True,
            "filter_id":    filter_id,
            "total_active": active_count,
            "polygon_png":  png_rel,
        })

    except Exception as exc:
        import traceback
        return jsonify({"ok": False, "error": str(exc),
                        "trace": traceback.format_exc()}), 500


# ── KMZ-Export ────────────────────────────────────────────────────────────────

@app.route("/api/export/forecast.kmz")
def api_export_forecast_kmz():
    """
    Liefert die zuletzt erzeugte Forecast-KMZ zum Download.
    Erzeugt von save_forecast_as_kmz() in jedem Live-Loop-Zyklus.
    Zieldefinition: Vorhersagepositionen + Pfeile als KMZ exportierbar.
    """
    kmz_path = os.path.join(os.getcwd(), "forecast.kmz")
    if not os.path.exists(kmz_path):
        return jsonify({"error": "Noch keine KMZ vorhanden — Live-Loop muss zuerst laufen"}), 404
    return send_file(
        kmz_path,
        mimetype="application/vnd.google-earth.kmz",
        as_attachment=True,
        download_name="forecast.kmz",
    )


# ── Outlook Risk Grid (12h atmosphärische Risikoschätzung) ───────────────────
_OUTLOOK_12H_PATH = Path("train_data/forecast/outlook_12h.json")
_OUTLOOK_RISK_CACHE = {"data": None, "mtime": 0.0}


def _outlook_float(pt: dict, *keys: str) -> float:
    """Liest numerische Outlook-Werte aus direkten und verschachtelten Feldern."""
    if not isinstance(pt, dict):
        return 0.0
    nested = []
    for key in keys:
        val = pt.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
        nested.append(key)
    for container in (pt.get("info"), pt.get("severity"), pt.get("weather"), pt.get("data")):
        if not isinstance(container, dict):
            continue
        for key in nested:
            val = container.get(key)
            if val is not None:
                try:
                    return float(val)
                except (TypeError, ValueError):
                    pass
    return 0.0


def _outlook_hour_value(pt: dict, default=0):
    """Ermittelt den Stunden-Offset aus den bekannten Outlook-Schemata."""
    for key in ("hour", "offset_h", "step_h"):
        val = pt.get(key) if isinstance(pt, dict) else None
        if val is not None:
            return val
    return default


def _risk_score_from_point(pt: dict) -> float:
    """
    Berechnet einen Risikoscore [0.0 – 1.0] aus atmosphärischen Werten.

    Unterstützte Felder in outlook_12h.json:
      - direkt: cape_jkg/cape, wind_speed_kmh/wind_speed/wind_kmh
      - aktuell erzeugtes Outlook-Schema: info.cape und severity.gust_kmh
    """
    cape = _outlook_float(pt, "cape_jkg", "cape")
    wind = _outlook_float(pt, "wind_speed_kmh", "wind_speed", "wind_kmh", "gust_kmh")

    if cape < 200:
        score = 0.0
    elif cape < 500:
        score = 0.1 + (cape - 200) / 300 * 0.2
    elif cape < 1000:
        score = 0.3 + (cape - 500) / 500 * 0.3
    elif cape < 1500:
        score = 0.6 + (cape - 1000) / 500 * 0.2
    else:
        score = 0.8 + min((cape - 1500) / 1000 * 0.2, 0.2)

    if wind > 40:
        score = min(score + 0.1, 1.0)

    return round(score, 3)


def _risk_level(score: float) -> str:
    """Konvertiert Score zu Label (identisch mit bestehendem Risk-Grid)."""
    if score < 0.1:
        return "none"
    if score < 0.3:
        return "low"
    if score < 0.6:
        return "medium"
    if score < 0.8:
        return "high"
    return "extreme"


def _outlook_hour_entry(hour_val, item: dict) -> dict:
    score = _risk_score_from_point(item)
    return {
        "hour": hour_val,
        "score": score,
        "level": _risk_level(score),
        "cape_jkg": round(_outlook_float(item, "cape_jkg", "cape"), 1),
        "wind_kmh": round(_outlook_float(item, "wind_speed_kmh", "wind_speed", "wind_kmh", "gust_kmh"), 1),
    }


def _append_outlook_point(grid_map: dict, hours_set: set, lat, lon, hour_val, item: dict) -> None:
    if lat is None or lon is None:
        return
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return
    key = (round(lat_f, 5), round(lon_f, 5))
    hours_set.add(hour_val)
    grid_map.setdefault(key, {"lat": lat_f, "lon": lon_f, "hourly": []})["hourly"].append(
        _outlook_hour_entry(hour_val, item)
    )


def _normalise_outlook_risk_grid(raw) -> tuple[list[dict], list]:
    """Normalisiert bekannte outlook_12h.json-Formate auf Punkt→Stunden-Struktur."""
    grid_map = {}
    hours_set = set()

    if isinstance(raw, dict) and isinstance(raw.get("hours"), list):
        # Aktuelles convective_outlook-Format:
        # {generated_at, grid_step, hours:[{offset_h, valid, cells:[{lat, lon, info, severity}]}]}
        for hour_block in raw.get("hours", []):
            if not isinstance(hour_block, dict):
                continue
            hour_val = _outlook_hour_value(hour_block, len(hours_set))
            for cell in hour_block.get("cells", []) or []:
                if isinstance(cell, dict):
                    enriched = dict(cell)
                    enriched.setdefault("hour", hour_val)
                    enriched.setdefault("valid_time", hour_block.get("valid"))
                    _append_outlook_point(grid_map, hours_set, cell.get("lat"), cell.get("lon"), hour_val, enriched)
    elif isinstance(raw, list):
        if raw and isinstance(raw[0], dict) and ("hours" in raw[0] or "hourly" in raw[0]):
            for pt in raw:
                hourly_raw = pt.get("hours") or pt.get("hourly") or []
                for h in hourly_raw:
                    if not isinstance(h, dict):
                        continue
                    hour_val = _outlook_hour_value(h, 0)
                    _append_outlook_point(grid_map, hours_set, pt.get("lat"), pt.get("lon"), hour_val, h)
        else:
            for item in raw:
                if not isinstance(item, dict):
                    continue
                hour_val = _outlook_hour_value(item, 0)
                _append_outlook_point(grid_map, hours_set, item.get("lat"), item.get("lon"), hour_val, item)
    elif isinstance(raw, dict):
        for items in raw.values():
            if not isinstance(items, list) or not items:
                continue
            for h in items:
                if not isinstance(h, dict):
                    continue
                hour_val = _outlook_hour_value(h, 0)
                _append_outlook_point(grid_map, hours_set, h.get("lat"), h.get("lon"), hour_val, h)

    grid_out = []
    for point in grid_map.values():
        point["hourly"].sort(key=lambda h: h.get("hour", 0))
        max_score = max((h["score"] for h in point["hourly"]), default=0.0)
        point["max_score"] = round(max_score, 3)
        point["max_level"] = _risk_level(max_score)
        grid_out.append(point)

    grid_out.sort(key=lambda p: (p.get("lat") or 0, p.get("lon") or 0))
    return grid_out, sorted(hours_set)


@app.route("/api/outlook_risk_grid")
def api_outlook_risk_grid():
    """
    Gibt das atmosphärische Risk-Grid für die nächsten 12 Stunden zurück.
    Basiert auf outlook_12h.json (CAPE + Wind pro Gridpunkt × Stunde).
    """
    if not _OUTLOOK_12H_PATH.is_file():
        return jsonify({"error": "outlook_12h.json nicht vorhanden", "grid": []}), 404

    mtime = _OUTLOOK_12H_PATH.stat().st_mtime
    if _OUTLOOK_RISK_CACHE["data"] is not None and _OUTLOOK_RISK_CACHE["mtime"] == mtime:
        return jsonify(_OUTLOOK_RISK_CACHE["data"])

    try:
        with _OUTLOOK_12H_PATH.open(encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as exc:
        return jsonify({"error": str(exc), "grid": []}), 500

    grid_out, hours = _normalise_outlook_risk_grid(raw)
    response = {
        "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "hours": hours,
        "grid": grid_out,
        "n_points": len(grid_out),
    }
    _OUTLOOK_RISK_CACHE["data"] = response
    _OUTLOOK_RISK_CACHE["mtime"] = mtime
    return jsonify(response)
# ─────────────────────────────────────────────────────────────────────────────

# ── Gewitterrisiko-Grid ───────────────────────────────────────────────────────

@app.route("/api/risk_grid")
def api_risk_grid():
    """
    Berechnet ein Gewitterrisiko-Raster fuer Kaernten aus mehreren Quellen:
      1. Aktive Sturmzellen + Forecast-Zugbahn (Punkt-zu-Linie-Distanz)
      2. Blitzdichte der letzten 20 Minuten (aus Blitzortung-Cache)
      3. Atmosphaerische Instabilitaet (LI, SHIP-Proxy, CIN, PW)

    Das Grid ist UNABHAENGIG von erkannten Zellen.
    Jede Grid-Zelle enthaelt Detail-Werte fuer Hover-Tooltip im Frontend.

    Returns:
      {
        "grid_step": 0.05,
        "cells": [{
            "lat":..., "lon":..., "risk":1-3, "color":"#...",
            "info": {
              "dominant": "cell|track|lightning|atm",
              "cell_id":  <id oder null>,
              "ship":     <float|null>,
              "cape":     <float|null>,
              "li":       <float|null>,
              "cin":      <float|null>,
              "pw":       <float|null>,
              "lapse_700_500": <float|null>,
              "lightning_count": <int>,
              "in_forecast_track": <bool>
            }
        }],
        "ts": "YYYY-MM-DD_HH-MM-SS",
        "sources": {"active_cells":N, "lightning":N, "atm_locations":N}
      }
    """
    import math as _m
    import glob as _g
    from datetime import datetime, timezone, timedelta
    from debug_utils import debug_log

    def _safe_float(val, default=0.0):
        try:
            out = float(val)
            if _m.isnan(out) or _m.isinf(out):
                return default
            return out
        except (TypeError, ValueError):
            return default

    def _bbox_to_limits(bbox):
        """Konvertiert BBOX aus dict {north,south,east,west} oder list/tuple [s,n,w,e]."""
        if isinstance(bbox, dict):
            return (
                _safe_float(bbox.get("south"), 46.36),
                _safe_float(bbox.get("north"), 47.18),
                _safe_float(bbox.get("west"),  12.60),
                _safe_float(bbox.get("east"),  15.20),
            )
        if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            return (
                _safe_float(bbox[0], 46.36),
                _safe_float(bbox[1], 47.18),
                _safe_float(bbox[2], 12.60),
                _safe_float(bbox[3], 15.20),
            )
        return 46.36, 47.18, 12.60, 15.20

    from config import BBOX_KAERNTEN_EXTENDED as _DEFAULT_RISK_BBOX
    GRID_STEP  = _safe_float(runtime_config.get("RISK_GRID_STEP_DEG", 0.05), 0.05)
    _bbox = runtime_config.get("BBOX_KAERNTEN_EXTENDED", _DEFAULT_RISK_BBOX)
    LAT_MIN, LAT_MAX, LON_MIN, LON_MAX = _bbox_to_limits(_bbox)
    CELL_RANGE  = _safe_float(runtime_config.get("RISK_CELL_RANGE_KM",  20.0), 20.0)
    TRACK_RANGE = _safe_float(runtime_config.get("RISK_TRACK_RANGE_KM", 10.0), 10.0)
    BOLT_RANGE  = _safe_float(runtime_config.get("RISK_BOLT_RANGE_KM",  10.0), 10.0)
    ATM_RANGE   = _safe_float(runtime_config.get("RISK_ATM_RANGE_KM",   20.0), 20.0)
    IR_RANGE    = _safe_float(runtime_config.get("RISK_IR_RANGE_KM",    15.0), 15.0)
    # Geschwindigkeitsbasierte Risikogewichtung:
    # Stationäre Zellen (Dauergewitter, Starkregen) sind gefährlicher.
    # Ab FAST_CELL_KMH gibt es keinen Extra-Boost mehr.
    _FAST_CELL_KMH    = _safe_float(runtime_config.get("RISK_FAST_CELL_KMH", 30.0), 30.0)
    _STATIONARY_BOOST = _safe_float(runtime_config.get("RISK_STATIONARY_BOOST", 0.8), 0.8)
    RISK_COLORS     = {1: "#facc15", 2: "#f97316", 3: "#dc2626"}
    IR_CELL_COLOR   = "#a855f7"   # Violett für IR-Vorläuferzellen
    INT_WEIGHT  = {"leicht": 1.0, "maessig": 2.0, "stark": 3.0, "extrem": 4.0}
    INT_WEIGHT_ALT = {"leicht": 1.0, "mäßig": 2.0, "stark": 3.0, "extrem": 4.0}

    def _hav(la1, lo1, la2, lo2):
        R    = 6371.0
        dlat = _m.radians(la2 - la1)
        dlon = _m.radians(lo2 - lo1)
        a    = (_m.sin(dlat / 2) ** 2 +
                _m.cos(_m.radians(la1)) * _m.cos(_m.radians(la2)) *
                _m.sin(dlon / 2) ** 2)
        return R * 2 * _m.atan2(_m.sqrt(a), _m.sqrt(1 - a))

    def _point_to_segment_km(plat, plon, alat, alon, blat, blon):
        """Naeherung Punkt-zu-Segment-Distanz in km (kleine Distanzen).
        Lokale aequidistante Projektion ist hier ausreichend."""
        if None in (alat, alon, blat, blon):
            return _hav(plat, plon, alat or plat, alon or plon)
        # cos(mean_lat) fuer Laengen-Korrektur
        mean_lat = _m.radians((plat + alat + blat) / 3.0)
        kx = 111.32 * _m.cos(mean_lat)
        ky = 110.57
        ax = (alon - plon) * kx; ay = (alat - plat) * ky
        bx = (blon - plon) * kx; by = (blat - plat) * ky
        # Punkt P liegt im Ursprung. Segment A→B in (a,b).
        seg_dx = bx - ax; seg_dy = by - ay
        seg_len2 = seg_dx * seg_dx + seg_dy * seg_dy
        if seg_len2 < 1e-9:
            return _m.hypot(ax, ay)
        # Projektion P-A auf A-B normiert
        t = -(ax * seg_dx + ay * seg_dy) / seg_len2
        t = max(0.0, min(1.0, t))
        cx = ax + t * seg_dx
        cy = ay + t * seg_dy
        return _m.hypot(cx, cy)

    # ── Quelle 1: Aktive Sturmzellen ──────────────────────────────────────────
    obj_dir   = SAVE_PATHS.get("objects", "train_data/objects")
    obj_files = sorted(_g.glob(os.path.join(obj_dir, "*.json")))
    active_cells = []
    last_ts = None
    if obj_files:
        last_ts = os.path.basename(obj_files[-1]).replace(".json", "")
        try:
            with open(obj_files[-1], encoding="utf-8") as _f:
                all_objs = json.load(_f)
            active_cells = [
                o for o in all_objs
                if o.get("missing", 0) == 0
                and o.get("lat") is not None
                and o.get("lon") is not None
            ]
        except Exception as exc:
            debug_log(f"[risk_grid] active_cells load failed: {exc}")

    # ── Quelle 2: Blitze der letzten 20 Min ──────────────────────────────────
    bolt_dir   = SAVE_PATHS.get("lightning", "train_data/lightning")
    bolt_files = sorted(_g.glob(os.path.join(bolt_dir, "*.json")))
    strikes = []
    now_utc = datetime.now(timezone.utc)
    cutoff_utc = now_utc - timedelta(minutes=20)
    for path in reversed(bolt_files[-12:]):
        try:
            ts_str = os.path.basename(path).replace(".json", "")
            ts = datetime.strptime(ts_str, "%Y-%m-%d_%H-%M-%S").replace(tzinfo=timezone.utc)
            if ts < cutoff_utc:
                break
            with open(path, encoding="utf-8") as _f:
                payload = json.load(_f)
                if isinstance(payload, list):
                    strikes.extend(payload)
        except Exception as exc:
            debug_log(f"[risk_grid] lightning parse failed path={path}: {exc}")
            continue

    # ── Quelle 3: Atmosphaere-Snapshot (mit neuen Feldern) ───────────────────
    atm_locs = []
    atm_file = os.path.join(SAVE_PATHS.get("evaluation", "train_data/evaluation"),
                            "atmosphere_latest.json")
    if os.path.exists(atm_file):
        try:
            with open(atm_file, encoding="utf-8") as _f:
                atm_data = json.load(_f)
            for aloc in atm_data.get("locations", []):
                if aloc.get("lat") is not None and aloc.get("lon") is not None:
                    atm_locs.append(aloc)
        except Exception as exc:
            debug_log(f"[risk_grid] atmosphere load failed: {exc}")

    # ── Forecast-Pfad-Segmente fuer jede aktive Zelle vorbereiten ────────────
    # Segmente: now → +10, +10 → +20, +20 → +30, +30 → +40
    # Fix #8: Runtime-Horizonte aus runtime_config (default: alle 5 konfiguriert)
    _rg_horizons = sorted(runtime_config.get("ML_FORECAST_HORIZONS_MIN", [10, 20, 30, 40, 60]))
    # Gewichte: linear abnehmend mit Horizont (kürzere Horizonte = sicherer)
    _max_hz = max(_rg_horizons) if _rg_horizons else 60
    _rg_weights = {hz: max(0.1, 1.0 - (hz / _max_hz) * 0.8) for hz in _rg_horizons}

    forecast_segments = []  # list of (cell_dict, [(lat0,lon0,lat1,lon1), ...])
    for cell in active_cells:
        segs = []
        prev_lat = cell.get("lat")
        prev_lon = cell.get("lon")
        for hz in _rg_horizons:   # Fix #8: alle konfigurierten Horizonte inkl. 60 min
            flat = cell.get(f"forecast_lat_{hz}")
            flon = cell.get(f"forecast_lon_{hz}")
            if flat is None or flon is None:
                continue
            try:
                _seg_km = _hav(float(prev_lat), float(prev_lon),
                               float(flat), float(flon))
                if _seg_km >= 2.0:  # Nur Segmente >= 2 km (echte Bewegung)
                    segs.append((float(prev_lat), float(prev_lon),
                                 float(flat),     float(flon)))
                prev_lat = flat
                prev_lon = flon
            except Exception:
                continue
        if segs:
            forecast_segments.append((cell, segs))

    # ── IR-Tracks einmal laden (nicht pro Grid-Zelle) ─────────────────────────
    try:
        from ir_cell_tracking import load_active_ir_tracks as _load_ir_once
        _ir_tracks_all = _load_ir_once()
    except Exception as _ir_load_exc:
        debug_log(f"[risk_grid] IR-Track-Vorladen fehlgeschlagen: {_ir_load_exc}")
        _ir_tracks_all = []

    cells_out = []
    lat = LAT_MIN
    while lat <= LAT_MAX:
        lon = LON_MIN
        while lon <= LON_MAX:
            score = 0.0
            # Detail-Tracking fuer Hover
            best_ship = None
            best_cape = None
            best_cloud_top_m = None
            nearest_cell_id = None
            nearest_cell_dist_km = None
            nearest_cell_speed_kmh = None
            in_track = False
            bolt_count = 0
            _ir_cell_id_near = None
            _ir_bt_min_k_near = None
            _ir_cell_dist_km_near = None

            # 1) Aktive Zellen — Distanz-gewichtet (wie vorher)
            for cell in active_cells:
                clabel = cell.get("intensity_label", "leicht")
                wt = INT_WEIGHT.get(clabel, INT_WEIGHT_ALT.get(clabel, 1.0))
                # aktuelle Position
                cell_lat = _safe_float(cell.get("lat"), None)
                cell_lon = _safe_float(cell.get("lon"), None)
                if cell_lat is None or cell_lon is None:
                    continue
                d_now = _hav(lat, lon, cell_lat, cell_lon)
                if d_now < CELL_RANGE:
                    # Geschwindigkeitsbasierter Faktor:
                    # Stationäre Zellen erhalten bis zu (1 + _STATIONARY_BOOST)-fachen Score.
                    _cell_vx = float(cell.get("vx", 0.0))
                    _cell_vy = float(cell.get("vy", 0.0))
                    try:
                        # B78-FIX: speed_kmh aus Objekt verwenden (bereits korrekt skaliert)
                        _precomp = cell.get("speed_kmh")
                        if _precomp is not None:
                            _cell_speed_kmh = float(_precomp)
                        else:
                            from config import PX_TO_KMH as _ptk_rg, UPSCALE_FACTOR as _uf_rg
                            _cell_speed_kmh = (
                                (_cell_vx ** 2 + _cell_vy ** 2) ** 0.5
                                * float(_ptk_rg) / max(float(_uf_rg), 1.0)
                            )
                    except Exception:
                        _cell_speed_kmh = 0.0
                    _speed_factor = 1.0 + max(
                        0.0, 1.0 - _cell_speed_kmh / max(_FAST_CELL_KMH, 1.0)
                    ) * _STATIONARY_BOOST
                    contrib = wt * (1.0 - d_now / CELL_RANGE) ** 1.5 * _speed_factor
                    score += contrib
                    if nearest_cell_id is None or d_now < (nearest_cell_dist_km if nearest_cell_dist_km is not None else float("inf")):
                        nearest_cell_id = cell.get("id")
                        nearest_cell_dist_km = round(d_now, 1)
                        nearest_cell_speed_kmh = round(_cell_speed_kmh, 1)
                        sh = cell.get("ship_index")
                        cp = cell.get("cape")
                        if sh is not None and (best_ship is None or sh > best_ship):
                            best_ship = sh
                        if cp is not None and (best_cape is None or cp > best_cape):
                            best_cape = cp
                        _ch = cell.get("cloud_top_height_msl")
                        if _ch is not None:
                            try:
                                _ch_f = float(_ch)
                                if _ch_f > 0 and (best_cloud_top_m is None or _ch_f > best_cloud_top_m):
                                    best_cloud_top_m = _ch_f
                            except (TypeError, ValueError):
                                pass
                # Fix #8: Runtime-Horizonte verwenden statt hardcoded Liste
                for hz, iw in [(h, _rg_weights.get(h, 0.2)) for h in _rg_horizons]:
                    flat = cell.get(f"forecast_lat_{hz}")
                    flon = cell.get(f"forecast_lon_{hz}")
                    if flat is None or flon is None:
                        continue
                    d = _hav(lat, lon, _safe_float(flat, lat), _safe_float(flon, lon))
                    if d < CELL_RANGE:
                        score += iw * wt * (1.0 - d / CELL_RANGE) ** 1.5

            # 1b) NEU: Forecast-ZUGBAHN — Punkt-zu-Linie-Distanz
            # Pixel in den Linien-Korridoren bekommen Zusatz-Score.
            for cell, segs in forecast_segments:
                clabel = cell.get("intensity_label", "leicht")
                wt = INT_WEIGHT.get(clabel, INT_WEIGHT_ALT.get(clabel, 1.0))
                for (a_lat, a_lon, b_lat, b_lon) in segs:
                    d_seg = _point_to_segment_km(lat, lon, a_lat, a_lon, b_lat, b_lon)
                    if d_seg < TRACK_RANGE:
                        track_contrib = 0.6 * wt * (1.0 - d_seg / TRACK_RANGE) ** 2
                        score += track_contrib
                        if d_seg < 10.0:
                            in_track = True
                            if nearest_cell_id is None:
                                nearest_cell_id = cell.get("id")

            # 2) Blitzdichte
            for bolt in strikes:
                b_lat = _safe_float(bolt.get("lat"), None)
                b_lon = _safe_float(bolt.get("lon"), None)
                if b_lat is None or b_lon is None:
                    continue
                d = _hav(lat, lon, b_lat, b_lon)
                if d < BOLT_RANGE:
                    score += 0.15 * (1.0 - d / BOLT_RANGE)
                    if d < 10.0:
                        bolt_count += 1

            # 3) Atmosphaerische Instabilitaet (LI/SHIP-Proxy/CIN-Daempfung)
            li_val = cin_val = pw_val = lapse_val = fl_val = cloud_h_val = None
            for aloc in atm_locs:
                a_lat = _safe_float(aloc.get("lat"), None)
                a_lon = _safe_float(aloc.get("lon"), None)
                if a_lat is None or a_lon is None:
                    continue
                d = _hav(lat, lon, a_lat, a_lon)
                if d < ATM_RANGE:
                    li = _safe_float(aloc.get("li", 0.0), 0.0)
                    cin_l = _safe_float(aloc.get("cin", 0.0), 0.0)
                    w  = 1.0 - d / ATM_RANGE
                    li_contrib = 0.0
                    if li < -3.0:
                        li_contrib = 0.80 * w
                    elif li < -1.0:
                        li_contrib = 0.40 * w
                    # CIN-Dämpfung bei starker Deckelung
                    if cin_l < -100.0:
                        li_contrib *= 0.5
                    score += li_contrib
                    # Gefriergrenze: hohe 0°C-Isotherme = tiefes Einfrieren im Aufwind
                    fl_h = _safe_float(aloc.get("fl_height", 0.0) or 0.0, 0.0)
                    if fl_h > 4000.0:
                        score += 0.15 * w
                    elif fl_h > 3500.0:
                        score += 0.08 * w
                    # Wolkenhöhe: tiefe Konvektion (>9000 m) = starkes Aufwindssignal
                    cloud_h_atm = _safe_float(aloc.get("cloud_height_m", 0.0) or 0.0, 0.0)
                    if cloud_h_atm > 9000.0:
                        score += 0.25 * w
                    elif cloud_h_atm > 7000.0:
                        score += 0.10 * w
                    # B86 — CAPE/SHIP/PW/CIN/cloud_height aus ATM-Snapshot für Tooltip
                    # best_cape / best_ship kamen bisher nur aus Zell-Objekten →
                    # bei dominant='atm' (keine aktiven Zellen) blieben alle null.
                    # Jetzt: ATM-Snapshot-Werte befüllen die Tooltip-Felder auch ohne Zellen.
                    _atm_cape = _safe_float(aloc.get("cape", 0.0) or 0.0, 0.0)
                    if _atm_cape > 0 and (best_cape is None or _atm_cape > best_cape):
                        best_cape = _atm_cape
                    # SHIP-Proxy aus ATM-Daten: cape * lapse / 14000 (dimensionslos, ~0..4)
                    _atm_lapse = _safe_float(aloc.get("lapse_700_500", 0.0) or 0.0, 0.0)
                    if _atm_cape > 0 and _atm_lapse > 0:
                        _atm_ship = round(min(_atm_cape * _atm_lapse / 14000.0, 4.0), 2)
                        if best_ship is None or _atm_ship > best_ship:
                            best_ship = _atm_ship
                    # cloud_height_m aus ATM-Snapshot
                    if cloud_h_atm > 0 and (best_cloud_top_m is None or cloud_h_atm > best_cloud_top_m):
                        best_cloud_top_m = cloud_h_atm
                    # Detail-Tracking
                    if li_val is None or li < li_val:
                        li_val = li
                        cin_val = cin_l
                        pw_val = aloc.get("pw")
                        lapse_val = aloc.get("lapse_700_500")
                        fl_val = aloc.get("fl_height")
                        cloud_h_val = aloc.get("cloud_height_m")

            # Dominierende Quelle bestimmen (fuer Hover)
            dominant = "atm"
            if nearest_cell_id is not None and not in_track:
                dominant = "cell"
            elif in_track:
                dominant = "track"
            # ── IR-Score VOR Risk-Klassifikation addieren ────────────────────
            _score_without_ir = score   # Score vor IR-Beitrag merken
            _ir_cell_near = False
            for _ir in _ir_tracks_all:
                _ir_d2 = _hav(
                    lat, lon,
                    _safe_float(_ir.get("lat", 0), 0.0),
                    _safe_float(_ir.get("lon", 0), 0.0),
                )
                if _ir_d2 <= IR_RANGE and _ir.get("ir_only_precursor", 0) == 1.0:
                    _ir_cell_near = True
                    _ir_cell_id_near = _ir.get("ir_id")
                    _ir_bt_min_k_near = _ir.get("bt_min_k")
                    _ir_cell_dist_km_near = round(_ir_d2, 1)
                    if score < 1.0:
                        score += 0.5  # leichter Risikobeitrag ohne Radar-Echo
                    break

            # ── IR-Only-Unterdrückung ─────────────────────────────────────────
            # IR-Vorläufer darf kein alleiniger Grund für eine Risikozone sein.
            # War der Score vor dem IR-Beitrag < 0.05 (praktisch null, d.h. keine
            # andere Quelle aktiv), wird der Punkt übersprungen — ein reiner
            # IR-Vorläufer ohne jede weitere Quelle erzeugt damit keine Risikozone.
            if _ir_cell_near and _score_without_ir < 0.05:
                lon = round(lon + GRID_STEP, 6)
                continue

            # ── Risk-Klassifikation (nach IR-Score-Beitrag) ───────────────────
            if score >= 2.5:
                risk = 3
            elif score >= 1.0:
                risk = 2
            elif score >= 0.3:
                risk = 1
            else:
                lon = round(lon + GRID_STEP, 6)
                continue

            # ── Dominante Quelle bestimmen ────────────────────────────────────
            if _ir_cell_near and dominant not in ("cell", "track"):
                dominant = "ir_cell"
            elif dominant not in ("cell", "track", "ir_cell"):
                if bolt_count >= 2:
                    dominant = "lightning"
                else:
                    dominant = "atm"

            cells_out.append({
                "lat":   round(lat, 4),
                "lon":   round(lon, 4),
                "risk":  risk,
                "color": RISK_COLORS[risk],
                "info": {
                    "dominant":         dominant,
                    "cell_id":          nearest_cell_id,
                    "ship":             round(best_ship, 2) if best_ship is not None else None,
                    "cape":             round(best_cape, 0) if best_cape is not None else None,
                    "li":               round(li_val, 2) if li_val is not None else None,
                    "cin":              round(cin_val, 1) if cin_val is not None else None,
                    "pw":               round(pw_val, 1) if pw_val is not None else None,
                    "lapse_700_500":    round(lapse_val, 2) if lapse_val is not None else None,
                    "fl_height":        round(fl_val, 0) if fl_val else None,
                    "cloud_height_m":   round(max(
                        x for x in [
                            float(cloud_h_val) if cloud_h_val else 0.0,
                            best_cloud_top_m if best_cloud_top_m else 0.0,
                        ] if x > 0
                    ), 0) if any(
                        x and float(x) > 0 for x in [cloud_h_val, best_cloud_top_m]
                    ) else None,
                    "lightning_count":  int(bolt_count),
                    "in_forecast_track": bool(in_track),
                    "cell_dist_km":     nearest_cell_dist_km,
                    "cell_speed_kmh":   nearest_cell_speed_kmh,
                    "ir_cell_id":       _ir_cell_id_near,
                    "ir_bt_min_k":      round(float(_ir_bt_min_k_near), 0) if _ir_bt_min_k_near is not None else None,
                    "ir_cell_dist_km":  _ir_cell_dist_km_near,
                    "score":            round(score, 2),
                },
            })

            lon = round(lon + GRID_STEP, 6)
        lat = round(lat + GRID_STEP, 6)

    return jsonify({
        "grid_step": GRID_STEP,
        "cells":     cells_out,
        "ts":        last_ts,
        "meta": {
            "grid_bbox": [LAT_MIN, LAT_MAX, LON_MIN, LON_MAX],
            "grid_resolution": GRID_STEP,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": "empty" if not cells_out else ("atmosphere_only" if not active_cells else "mixed"),
        },
        "sources": {
            "active_cells":  len(active_cells),
            "lightning":     len(strikes),
            "atm_locations": len(atm_locs),
        },
    })


@app.route("/api/outlook")
def api_outlook():
    """12-h-Konvektions-Ausblick. Optional ?hour=N filtert eine Stunde."""
    try:
        from convective_outlook import load_outlook
        data = load_outlook()
        hour = request.args.get("hour", type=int)
        if hour is not None:
            data = dict(data)
            data["hours"] = [h for h in data.get("hours", []) if h.get("offset_h") == hour]
        return jsonify(data)
    except Exception as exc:
        return jsonify({"hours": [], "error": str(exc)}), 200


@app.route("/api/size_regressor_status")
def api_size_regressor_status():
    """Gibt Status und Metriken des Size-Regressers zurück."""
    import size_regressor as sr

    r = sr.get_size_regressor()
    meta_path = sr.SIZE_META_PATH
    meta = {}
    if os.path.isfile(meta_path):
        try:
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            pass
    return jsonify({
        "trained": r.is_trained(),
        "n_labels": sr.count_size_labels(),
        "min_samples": sr.SIZE_MIN_SAMPLES,
        "model_meta": meta,
        "labels_path": sr.SIZE_LABELS_PATH,
        "model_path": sr.SIZE_MODEL_PATH,
    })


if __name__ == "__main__":
    # Fix P04: Standardmäßig nur auf 127.0.0.1 lauschen.
    # nginx reverse-proxyt von außen auf diesen Port — direkter LAN-Zugriff
    # auf Port 5000 würde die Basic-Auth umgehen.
    # Override via Env-Var ADMIN_BIND_HOST nur für Sonderfälle (z. B. Dev-Container).
    import watchdog_heartbeat
    watchdog_heartbeat.start()          # systemd READY=1 + Watchdog-Ping alle 25 s
    _bind_host = os.getenv("ADMIN_BIND_HOST", "127.0.0.1").strip() or "127.0.0.1"
    _bind_port = int(os.getenv("ADMIN_BIND_PORT", "5000"))
    app.run(host=_bind_host, port=_bind_port, debug=os.getenv("ADMIN_DEBUG") == "1")
