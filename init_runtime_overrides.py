#!/usr/bin/env python3
"""
init_runtime_overrides.py
Initialisiert train_data/runtime_overrides.json mit allen bekannten
Default-Werten. Vorhandene Einträge werden NIE überschrieben (merge-only).
Wird von install.sh für --mode=full und --mode=upgrade aufgerufen.
Kann auch manuell ausgeführt werden: python3 init_runtime_overrides.py
"""
import json
import os
import sys

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

    # ── Orts-Watchlist (5 Kärntner Orte als Defaults) ──────────────────────
    "LOCATIONS_WATCHLIST": [
        {"name": "Klagenfurt", "lat": 46.6228, "lon": 14.3050, "radius_km": 5.0},
        {"name": "Villach",    "lat": 46.6111, "lon": 13.8558, "radius_km": 5.0},
        {"name": "Wolfsberg",  "lat": 46.8403, "lon": 14.8408, "radius_km": 5.0},
        {"name": "Spittal",    "lat": 46.7956, "lon": 13.4978, "radius_km": 5.0},
        {"name": "St. Veit",   "lat": 46.7700, "lon": 14.3614, "radius_km": 5.0},
    ],

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
    "CONVLSTM_MODEL_PATH": "",  # leer = automatisch aus SAVE_PATHS["models"]/current/

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
        "icon_d2":             1800,
        "icon_global":         3600,
        "openmeteo_synoptic":  3600,
        "openmeteo_extended":   900,
        "openmeteo_icon_eu":   3600,
        "cloud_height":         900,
        "eumetview_capabilities": 600,
        "tawes":                600,
        "blitzortung":           60,
        "geosphere_cape":      1800,
        "geosphere_nowcast":    720,
    },

    # ── Forecast-Pfeile (Farben und Stil je Horizont) ───────────────────────
    # JSON-Keys müssen Strings sein (JSON-Spec: keine Integer-Keys)
    "FORECAST_ARROW_COLORS": {
        "10": "#00cc44",
        "20": "#3399ff",
        "30": "#ff9900",
        "40": "#cc00cc",
        "60": "#cc0000",
    },
    "FORECAST_ARROW_STYLE": {
        "10": {"weight": 2, "dash": "4,4"},
        "20": {"weight": 2, "dash": ""},
        "30": {"weight": 3, "dash": ""},
        "40": {"weight": 3, "dash": "8,4"},
        "60": {"weight": 4, "dash": ""},
    },

    # ── KI-Tagesanalyse ─────────────────────────────────────────────────────
    "AI_ANALYSIS_CONFIG": {
        "enabled":          False,
        "cron_hour":        6,
        "cron_minute":      0,
        "cron_days":        "mon,tue,wed,thu,fri,sat,sun",
        "only_if_cells":    False,
        "model":            "claude-sonnet-4-6",
        "max_tokens":       3000,
        "since_hours":      24,
        "save_suggestions": True,
        "email_report":     False,
    },

    # ── Kinematisches Tracking / EWMA (P27) ──────────────────────────────────
    "TRACK_HISTORY_LEN":    6,
    "KINEMATIC_EWMA_ALPHA": 0.6,
}

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OVERRIDES_PATH = os.path.join(_SCRIPT_DIR, "train_data", "runtime_overrides.json")


def init_overrides(overrides_path: str = OVERRIDES_PATH) -> list[str]:
    """
    Ergänzt runtime_overrides.json um fehlende Default-Werte.
    Vorhandene Einträge bleiben unverändert.
    Gibt die neu eingetragenen Keys zurück.
    """
    os.makedirs(os.path.dirname(overrides_path), exist_ok=True)

    existing: dict = {}
    if os.path.exists(overrides_path):
        try:
            with open(overrides_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if not isinstance(existing, dict):
                print(f"[WARN] {overrides_path} enthält kein JSON-Objekt — wird als leer behandelt.")
                existing = {}
        except json.JSONDecodeError as exc:
            print(f"[WARN] {overrides_path} ist ungültiges JSON ({exc}) — wird als leer behandelt.")
            existing = {}

    added: list[str] = []
    for key, default_value in DEFAULTS.items():
        if key not in existing:
            existing[key] = default_value
            added.append(key)

    with open(overrides_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return added


if __name__ == "__main__":
    added = init_overrides()
    if added:
        print(f"[INIT] {len(added)} Defaults in runtime_overrides.json eingetragen:")
        for k in added:
            print(f"       + {k}")
    else:
        print("[INIT] runtime_overrides.json bereits vollständig — keine Änderungen.")
    sys.exit(0)
