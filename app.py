import glob
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

import config as cfg
from config import SAVE_PATHS
import runtime_config
from accuracy_tracker import evaluate_all, load_history

app = Flask(__name__, static_folder="frontend/dist", static_url_path="")


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


def _latest_location_hits():
    files = sorted(glob.glob(os.path.join(SAVE_PATHS["evaluation"], "locations_*.json")))
    if not files:
        return []
    try:
        with open(files[-1], encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


# ---------- JSON-APIs (von React konsumiert) ----------
@app.route("/api/health")
def api_health():
    return jsonify({"ok": True, "ts": datetime.utcnow().isoformat() + "Z"})


@app.route("/api/git")
def api_git():
    branch, commit = _git_info()
    return jsonify({"branch": branch, "commit": commit})


@app.route("/api/objects")
def api_objects():
    return jsonify(_latest_objects())


@app.route("/api/forecast")
def api_forecast():
    import math as _math
    from config import MIN_MOVEMENT_FOR_ARROW_KMH, FORECAST_ARROW_STYLE
    horizons = runtime_config.get("ML_FORECAST_HORIZONS_MIN", [10, 20, 30, 40, 60])
    colors   = runtime_config.get("FORECAST_ARROW_COLORS", {})
    styles   = runtime_config.get("FORECAST_ARROW_STYLE", FORECAST_ARROW_STYLE)
    min_kmh  = runtime_config.get("MIN_MOVEMENT_FOR_ARROW_KMH", MIN_MOVEMENT_FOR_ARROW_KMH)
    # 1 px/Frame (UPSCALE=3, ~2 min/Frame) ≈ 10 km/h (Näherung Kärnten)
    PX_TO_KMH = 10.0
    feats = []
    for o in _latest_objects():
        if o.get("lat") is None or o.get("lon") is None:
            continue
        vx = float(o.get("vx") or 0.0)
        vy = float(o.get("vy") or 0.0)
        speed_kmh = _math.hypot(vx, vy) * PX_TO_KMH
        has_arrow = speed_kmh >= min_kmh
        for h in horizons:
            fy = o.get(f"forecast_lat_{h}")
            fx = o.get(f"forecast_lon_{h}")
            if fy is None or fx is None:
                continue
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
                    "speed_kmh":       round(speed_kmh, 1),
                },
            })
    return jsonify({"type": "FeatureCollection", "features": feats})


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


@app.route("/api/training")
def api_training():
    return jsonify({
        "TRAINING_SCHEDULE": runtime_config.get("TRAINING_SCHEDULE", {}),
        "DATASET_REBUILD_INTERVAL_MIN": runtime_config.get("DATASET_REBUILD_INTERVAL_MIN"),
        "RETRAIN_INTERVAL_HOURS": runtime_config.get("RETRAIN_INTERVAL_HOURS"),
    })


@app.route("/api/training", methods=["POST"])
def api_training_save():
    try:
        data = request.get_json(force=True)
        assert "TRAINING_SCHEDULE" in data
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    runtime_config.patch(data)
    return jsonify({"ok": True})


@app.route("/api/config")
def api_config():
    return jsonify(runtime_config.all_effective())


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


@app.route("/api/accuracy")
def api_accuracy():
    since = int(request.args.get("hours", "24"))
    horizons = runtime_config.get("ML_FORECAST_HORIZONS_MIN", [10, 20, 30, 40, 60])
    return jsonify({
        "current": evaluate_all(horizons, since_hours=since),
        "history": load_history(since_hours=max(since, 24 * 7)),
    })


@app.route("/api/api_health")
def api_api_health():
    """Liefert API-Failure-Statistik der letzten N Stunden."""
    from debug_utils import api_health_summary
    hours = int(request.args.get("hours", "24"))
    return jsonify(api_health_summary(since_hours=hours))


@app.route("/api/logs")
def api_logs():
    def tail(unit):
        try:
            out = subprocess.check_output(["journalctl", "-u", unit, "-n", "500", "--no-pager"], text=True)
            return out.splitlines()[-500:]
        except Exception as e:
            return [f"Fehler: {e}"]
    return jsonify({
        "wetterprojekt": tail("wetterprojekt"),
        "scheduler": tail("wetterprojekt-scheduler"),
        "admin": tail("wetterprojekt-admin"),
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


@app.route("/api/ai_analysis/run", methods=["POST"])
def api_ai_analysis_run():
    """Manueller Trigger für Sofort-Analyse (ignoriert enabled-Flag)."""
    try:
        from daily_analyzer import run_analysis
        from config import AI_ANALYSIS_CONFIG as _default
        cfg = dict(_default)
        cfg.update(runtime_config.get("AI_ANALYSIS_CONFIG", {}))
        cfg["enabled"] = True
        result = run_analysis(cfg)
        if result is None:
            return jsonify({"ok": False, "error": "Analyse fehlgeschlagen (siehe Logs)"}), 500
        return jsonify({"ok": True, "result": result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=os.getenv("ADMIN_DEBUG") == "1")
