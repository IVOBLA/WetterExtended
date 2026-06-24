#!/usr/bin/env python3
"""
init_runtime_overrides.py
Initialisiert train_data/runtime_overrides.json mit allen bekannten
Default-Werten. Vorhandene Einträge werden NIE überschrieben (merge-only).
Wird von install.sh für --mode=full und --mode=upgrade aufgerufen.
Kann auch manuell ausgeführt werden: python3 init_runtime_overrides.py
"""
import argparse
import copy
import fcntl
import json
import os
import sys
import tempfile
import time

import config as _config


def _json_safe(value):
    return json.loads(json.dumps(value, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Vollständige Default-Map — Single Source of Truth für runtime_overrides.json
# Entspricht den Code-Defaults aus config.py / app.py (Stand: Mai 2026).
# Reihenfolge = Anzeigereihenfolge im Admin-Panel (Configuration.jsx).
# ---------------------------------------------------------------------------
DEFAULTS: dict = {

    # ── Risikozonen-Grid ────────────────────────────────────────────────────
    "RISK_CELL_RANGE_KM":    20,
    "RISK_TRACK_RANGE_KM":   10,
    "RISK_BOLT_RANGE_KM":    10,
    "RISK_ATM_RANGE_KM":     20,
    "RISK_GRID_STEP_DEG":    0.05,
    "RISK_FAST_CELL_KMH":    30,
    "RISK_STATIONARY_BOOST": 0.8,
    "RISK_IR_RANGE_KM":      15,
    "IR_MIN_CELL_AREA_PX":   300,
    "IR_MIN_CAPE_J_KG":      200.0,
    "IR_MAX_LI_C":           -0.5,
    "IR_LEAD_TIME_LABELS_ENABLED": True,
    "IR_LEAD_TIME_LABELS_FILE": "ir_lead_time_labels.jsonl",
    "IR_LEAD_TIME_LABELS_MAX_OPEN_MIN": 90.0,
    "IR_LEAD_TIME_LABELS_MIN_FINAL_AGE_MIN": 20.0,
    "IR_LEAD_TIME_LABELS_INCLUDE_NEGATIVES": True,
    "IR_LEAD_TIME_LABELS_DEDUP_BY_CELL_ID": True,

    # ── Hydrologie / Hydro-Impact ───────────────────────────────────────────
    "HYDRO_ENABLED": True,
    "HYDRO_API_TTL_SECONDS": 600,
    "HYDRO_MIN_OVERLAP_AREA_KM2": 1.0,
    "HYDRO_MIN_CELL_OVERLAP_RATIO": 0.05,
    "HYDRO_MIN_OVERLAP_RATIO_CELL": 0.05,
    "HYDRO_MIN_DURATION_MIN": 5,
    "HYDRO_RELEVANT_INTENSITIES": ["strong", "severe", "extreme", "rot", "violett", "red", "purple", "heavy"],
    "HYDRO_DEFAULT_LAG_MIN": [20, 180],
    "HYDRO_LAG_WINDOW_MIN": [20, 180],
    "HYDRO_VERIFY_MIN_DELTA_Q_M3S": 0.2,
    "HYDRO_VERIFY_MIN_DELTA_W_CM": 5,
    "HYDRO_VERIFY_MIN_RELATIVE_DELTA_PCT": 10,
    "HYDRO_VERIFY_MAX_GAP_MIN": 90,
    "HYDRO_STATION_OVERRIDES": {},
    "HYDRO_FORECAST_IMPACT_ENABLED": False,
    "HYDRO_FORECAST_HORIZONS_MIN": [10, 20, 30, 40, 60],
    "HYDRO_FORECAST_PRECIP_REF_MM": 15.0,
    "HYDRO_FORECAST_MIN_PRECIP_MM_H": 1.0,
    "HYDRO_FORECAST_SINGLE_HIT_DWELL_MIN": 10.0,
    "HYDRO_FORECAST_RUNOFF_COEFF": 0.4,
    "HYDRO_FORECAST_ROUTING_ATTENUATION": 1.0,
    "HYDRO_MAP_MIN_Q_M3S": 0.0,
    "HYDRO_MAP_MARK_Q_M3S": None,
    "HYDRO_STATIC_REQUIRED": False,

    # ── Orts-Watchlist aus config.py ableiten (Single Source of Truth) ──────
    "LOCATIONS_WATCHLIST": _json_safe(_config.LOCATIONS_WATCHLIST),

    # ── Warnungsschwellen ───────────────────────────────────────────────────
    "HAIL_WARN_THRESHOLD":              0.45,
    "STATIONARY_RISK_MARKER_THRESHOLD": 0.60,
    "GUST_WARN_KMH":                    60,
    "HEAVY_RAIN_WARN_MM_PER_H":         25,
    "MIN_MOVEMENT_FOR_ARROW_KMH":       5,
    "SLOW_CELL_MAX_KMH":                15,
    "SLOW_CELL_RADIUS_FACTOR":          1.5,

    # ── Live-Loop / Timing ──────────────────────────────────────────────────
    "LOOP_INTERVAL_CELLS_S":            120,
    "LOOP_INTERVAL_NO_CELLS_S":         900,
    "ATMOSPHERIC_SNAPSHOT_INTERVAL_MIN": 30,
    "DATA_CLEANUP_CRON_HOUR":           4,
    "DATA_CLEANUP_CRON_MINUTE":         30,
    "DATA_RETENTION_DAYS":              90,

    # ── ML & Training ───────────────────────────────────────────────────────
    "ML_FORECAST_HORIZONS_MIN":         [10, 20, 30, 40, 60],
    "LOCAL_TRAINING":                   True,
    "DATASET_REBUILD_INTERVAL_MIN":     60,
    "RETRAIN_INTERVAL_HOURS":           24,
    "TRAINING_SCHEDULE": {
        "retrain_interval_hours":       24,
        "retrain_cron_hour":            3,
        "retrain_cron_minute":          0,
        "convlstm_cron_day_of_week":    "mon",
        "convlstm_cron_hour":           2,
        "convlstm_cron_minute":         0,
    },
    "CONVLSTM_MODEL_PATH": "",

    # ── TAWES-Wetterstationen ───────────────────────────────────────────────
    "TAWES_GUST_STATION_IDS": (
        "11275,11218,11234,11206,11227,11235,11222,11273,"
        "11232,11259,11216,11349,11086,11255,11331,8989078,"
        "11217,11260,11215,11262,11278,11272,11229,11237,"
        "11213,11265,11257,11225,11228,8989076,11214,"
        "11330,11301,11315,11320,11350"
    ),
    "TAWES_PARAMS": "RR,DD,FF,FFX,GLOW,P,RF,TL,TP",

    # ── API-Cache TTL (Sekunden je Service) ─────────────────────────────────
    "API_CACHE_TTL_SECONDS": {
        "icon_d2": 1800, "icon_global": 3600, "openmeteo_synoptic": 3600,
        "openmeteo_extended": 900, "openmeteo_icon_eu": 3600,
        "cloud_height": 900, "eumetview_capabilities": 600, "tawes": 600,
        "blitzortung": 60, "geosphere_cape": 1800, "geosphere_nowcast": 720,
    },

    # ── Forecast-Pfeile (Farben und Stil je Horizont) ───────────────────────
    "FORECAST_ARROW_COLORS": _json_safe(_config.FORECAST_ARROW_COLORS),
    "FORECAST_ARROW_STYLE": _json_safe(_config.FORECAST_ARROW_STYLE),

    # ── KI-Tagesanalyse ─────────────────────────────────────────────────────
    "AI_ANALYSIS_CONFIG": {
        "enabled": False, "cron_hour": 6, "cron_minute": 0,
        "cron_days": "mon,tue,wed,thu,fri,sat,sun", "only_if_cells": False,
        "model": "claude-sonnet-4-6", "max_tokens": 3000, "since_hours": 24,
        "save_suggestions": True, "email_report": False,
    },

    # ── Kinematisches Tracking / EWMA (P27) ──────────────────────────────────
    "TRACK_HISTORY_LEN":    6,
    "KINEMATIC_EWMA_ALPHA": 0.6,
    "KINEMATIC_MIN_INTERVAL_DISP_PX": 0.0,
}

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OVERRIDES_PATH = os.path.join(_SCRIPT_DIR, "train_data", "runtime_overrides.json")


class RuntimeOverridesInvalidError(RuntimeError):
    pass


def _corrupt_copy_path(path: str) -> str:
    return f"{path}.corrupt_{time.strftime('%Y%m%d_%H%M%S')}"


def _atomic_write_json(path: str, data: dict) -> None:
    directory = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".runtime_overrides.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
        dir_fd = os.open(directory, os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _load_existing(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        corrupt_path = _corrupt_copy_path(path)
        with open(path, "rb") as src, open(corrupt_path, "wb") as dst:
            dst.write(src.read())
            dst.flush()
            os.fsync(dst.fileno())
        raise RuntimeOverridesInvalidError(
            f"{path} enthält ungültiges JSON ({exc}). Datei wurde NICHT überschrieben. "
            f"Kopie zur manuellen Reparatur: {corrupt_path}"
        ) from exc
    if not isinstance(data, dict):
        raise RuntimeOverridesInvalidError(
            f"{path} enthält kein JSON-Objekt. Datei wurde NICHT überschrieben; bitte manuell reparieren."
        )
    return data


def init_overrides(overrides_path: str = OVERRIDES_PATH) -> list[str]:
    """
    Ergänzt runtime_overrides.json um fehlende Default-Werte.
    Vorhandene Einträge bleiben unverändert; ohne fehlende Keys wird nicht geschrieben.
    Gibt die neu eingetragenen Keys zurück.
    """
    os.makedirs(os.path.dirname(overrides_path) or ".", exist_ok=True)
    lock_path = f"{overrides_path}.lock"
    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        existing = _load_existing(overrides_path)
        merged = copy.deepcopy(existing)
        added: list[str] = []
        for key, default_value in DEFAULTS.items():
            if key not in merged:
                merged[key] = default_value
                added.append(key)
        if added or not os.path.exists(overrides_path):
            _atomic_write_json(overrides_path, merged)
        return added


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Initialisiert runtime_overrides.json merge-only.")
    parser.add_argument("--path", default=OVERRIDES_PATH, help="Expliziter Pfad zu runtime_overrides.json")
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args(sys.argv[1:])
    try:
        added = init_overrides(args.path)
    except RuntimeOverridesInvalidError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(2)
    if added:
        print(f"[INIT] {len(added)} Defaults in runtime_overrides.json eingetragen:")
        for k in added:
            print(f"       + {k}")
    else:
        print("[INIT] runtime_overrides.json bereits vollständig — keine Änderungen.")
    sys.exit(0)
