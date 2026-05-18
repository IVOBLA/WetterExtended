# config.py

# --------------------------------------
# Debugging / Logging
# --------------------------------------

DEBUG_MODE = True  # Globales Flag für Debug-Ausgaben
DEBUG_IMAGE_SAVE = DEBUG_MODE  # Bilder speichern nur bei aktiviertem Debug-Modus

# --------------------------------------
# Geografischer Bereich (Kärnten + Puffer)
# --------------------------------------

BBOX_KAERNTEN_EXTENDED = {
    "north": 47.18,
    "south": 46.36,
    "east": 15.20,
    "west": 12.60,
}

# ROI (Pixelbereich) – wird bei Start dynamisch gesetzt
ROI = {
    "y1": 50,
    "y2": 1700,
    "x1": 100,
    "x2": 2200,
}

# --------------------------------------
# Farbfilter-Konfiguration (für Segmentierung)
# --------------------------------------

# ARSO INCA si0zm — Zmzx (dBZ) Farbskala:
# Grün=zmerne/mdm(36-39) → GelbGrün=močne/hgh(42-45) → Orange(48-51)
# → Rot=izjemne/ext(54) → Violett=izjemne/ext(57, höchste Intensität)
# ARSO INCA si0zm — nur konvektive Zellen (48+ dBZ):
# Stratiformer Regen (Grün/Gelb-Grün <45 dBZ) wird bewusst NICHT erfasst.
# Nur Orange/Rot/Violett = diskrete Gewitterzellen.
FILTER_CONFIG = {
    "allowed_hsv_ranges": [
        (( 10, 100,  80), ( 27, 255, 255)),  # Orange      močne/hgh   48–51 dBZ
        ((  0, 100,  80), ( 10, 255, 255)),  # Rot 1       izjemne/ext 54    dBZ
        ((165, 100,  80), (179, 255, 255)),  # Rot 2 wrap  izjemne/ext 54    dBZ
        ((125, 100,  80), (155, 255, 255)),  # Violett     izjemne/ext 57    dBZ
    ],
    "min_object_area": 800,
    "border_mask_px": 10,
}

# Kernbereiche: Rot und Violett = Zellkern
CORE_HSV_RANGES = [
    ([ 10, 120, 100], [ 27, 255, 255]),  # Orange       48–51 dBZ
    ([  0, 100, 120], [ 10, 255, 255]),  # Rot 1        54    dBZ
    ([165, 100, 120], [179, 255, 255]),  # Rot 2 (wrap) 54    dBZ
    ([125, 100, 120], [155, 255, 255]),  # Violett      57    dBZ
]

# Stratiforme Umgebungsbänder (36–47 dBZ).
# Werden NICHT getrackt / angezeigt, nur als ML-Kontext-Features genutzt.
# ARSO INCA Farbskala:
#   Grün      = zmerne  36–41 dBZ  HSV-Hue ~60–90
#   GelbGrün  = močne   42–47 dBZ  HSV-Hue ~40–60
STRATIFORM_HSV_RANGES = [
    (( 55,  50,  60), ( 92, 255, 255)),  # Grün      36–41 dBZ
    (( 38,  50,  60), ( 55, 255, 255)),  # GelbGrün  42–47 dBZ
]
# Suchradius im hochskalierten Bild (UPSCALE_FACTOR=3.0).
# 60 px ≈ 20 km — ausreichend für Umgebungskontext.
STRATIFORM_SEARCH_RADIUS_PX = 60

# --------------------------------------
# Bildverarbeitung
# --------------------------------------

UPSCALE_FACTOR = 3.0  # optionaler Resize-Faktor

# --------------------------------------
# Tracking-Parameter
# --------------------------------------

MAX_CONTOUR_DISTANCE = 30  # Maximaler Abstand für Zusammenführen von Konturen (px)
MAX_STATION_DISTANCE_KM = 20  # Wetterstations-Zuordnung
WIND_RASTER_RESOLUTION_KM = 10  # Rasterweite für Höhenwind
MIN_CONTOUR_OVERLAP = 10
MIN_CONTOUR_TOUCH = 5

# --------------------------------------
# Datenquellen
# --------------------------------------

AROME_BASE_URL = "https://dataset.api.hub.geosphere.at/v1/grid/forecast/nwp-v1-1h-2500m"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
LIGHTNING_DATA_URL = "https://www.lightningmaps.org/live_data/geojson/1.json"

# --------------------------------------
# ML-Konfiguration (Single Source of Truth)
# --------------------------------------

ML_CELL_FEATURES = [
    # Zellgeometrie & Kalman-Kinematik
    "x", "y",
    "vx", "vy",
    "size", "area", "eccentricity", "core_ratio", "trend",
    # Höhenwind (700 hPa) via Open-Meteo
    "wind_speed_700hPa", "wind_dir_cos", "wind_dir_sin",
    # Thermodynamik (GeoSphere AROME)
    "cape", "cloud_top_height_msl",
    # Topographie
    "dem_elevation_m",        # mittlere Geländehöhe im 5-km-Umkreis (Copernicus DEM)
    "dem_slope_toward_cell",  # Hangneigung in Bewegungsrichtung der Zelle
    # Blitze
    "lightning_count_10km",   # Blitze < 10 km in den letzten 10 Minuten
    # ── NEU: Optical Flow (pysteps Lucas-Kanade) ──────────────────────────────
    "of_vx",          # Flow-Vektor x am Objektzentrum (px/Frame, orig. Koord.)
    "of_vy",          # Flow-Vektor y am Objektzentrum
    "of_speed",       # Betrag des Flow-Vektors
    "of_divergence",  # lok. Divergenz (∂u/∂x + ∂v/∂y) — pos. = divergent
    # ── NEU: AROME icon_d2 direkt auf Gitterpunkt (Open-Meteo, 2,2 km) ───────
    "arome_t2m",       # Temperatur 2 m (°C)
    "arome_td2m",      # Taupunkt 2 m (°C)
    "arome_ff10m",     # Windgeschwindigkeit 10 m (km/h)
    "arome_dd_cos",    # cos(Windrichtung 10 m)
    "arome_dd_sin",    # sin(Windrichtung 10 m)
    "arome_li",        # Lifted Index (°C, neg. = instabil)
    "arome_fl_height", # Gefriergrenze MSL (m)
    # ── Stratiforme Umgebung (36–47 dBZ, nicht auf Karte) ──────────────────
    "strat_area_px",        # Pixel-Fläche stratif. Bereich im Suchradius
    "strat_intensity_mean", # Mittlere HSV-Helligkeit stratif. Pixel (0–1)
    "strat_dbz_gradient",   # dBZ-Gradient in Bewegungsrichtung (relativ)
]

ML_STATION_FEATURES = [
    "RR", "DD", "FF", "FFX", "GLOW", "P", "RF", "TL", "TP",
]

ML_TIME_FEATURES = [
    "hour_sin",
    "hour_cos",
    "month_sin",
    "month_cos",
]

ML_NUM_FEATURES = len(ML_CELL_FEATURES) + len(ML_STATION_FEATURES) + len(ML_TIME_FEATURES)
ML_SEQUENCE_LENGTH = 6
ML_FORECAST_HORIZONS_MIN = [10, 20, 30, 40, 60]
# Pfeilfarben pro Forecast-Horizont (HEX inkl. #).
FORECAST_ARROW_COLORS = {
    10: "#00cc44",
    20: "#3399ff",
    30: "#ff9900",
    40: "#cc00cc",
    60: "#cc0000",
}

# Linienstärke und Strichmuster pro Horizont (für Karte und KMZ).
FORECAST_ARROW_STYLE = {
    10: {"weight": 2, "dash": "4,4"},
    20: {"weight": 2, "dash": ""},
    30: {"weight": 3, "dash": ""},
    40: {"weight": 3, "dash": "8,4"},
    60: {"weight": 4, "dash": ""},
}

# Vom Benutzer definierbare Orte mit Umkreis (km). Default für Kärnten.
LOCATIONS_WATCHLIST = [
    {"name": "Klagenfurt", "lat": 46.6228, "lon": 14.3050, "radius_km": 5.0},
    {"name": "Villach",    "lat": 46.6111, "lon": 13.8558, "radius_km": 5.0},
    {"name": "Wolfsberg",  "lat": 46.8403, "lon": 14.8408, "radius_km": 5.0},
    {"name": "Spittal",    "lat": 46.7956, "lon": 13.4978, "radius_km": 5.0},
    {"name": "St. Veit",   "lat": 46.7700, "lon": 14.3614, "radius_km": 5.0},
]

# Beschriftungen der HSV-Bänder, damit das Adminpanel sie zeigen kann.
HSV_BAND_LABELS = ["leichter_regen", "regen", "starkregen"]

# Pfad für Runtime-Overrides aus dem Adminpanel.
RUNTIME_OVERRIDES_PATH = "train_data/runtime_overrides.json"

# --------------------------------------
# KI-Analyse-Pipeline (Anthropic API)
# --------------------------------------
# Default: deaktiviert. Aktivierung über Admin-Panel oder runtime_overrides.json.
AI_ANALYSIS_CONFIG = {
    "enabled": False,           # Master-Schalter
    "cron_hour": 6,             # Uhrzeit des täglichen Analyselaufs
    "cron_minute": 0,
    "model": "claude-sonnet-4-20250514",
    "max_tokens": 1500,
    "since_hours": 24,          # Datenfenster für den Report
    "save_suggestions": True,   # Vorschläge als JSON persistieren
}
AI_SUGGESTIONS_DIR = "train_data/evaluation/ai_suggestions"

# Trainings-Schedule (Cron-Stil). Wird vom Scheduler gelesen, kann per
# Adminpanel über runtime_overrides.json überschrieben werden.
TRAINING_SCHEDULE = {
    "retrain_interval_hours": 6,
    "retrain_cron_hour": 3,
    "retrain_cron_minute": 0,
    "convlstm_cron_day_of_week": "mon",
    "convlstm_cron_hour": 2,
    "convlstm_cron_minute": 0,
}
ML_IGNORE_FLAG = -1

# --------------------------------------
# Vorhersage-Verifikation (Closed-Loop)
# --------------------------------------
# Räumliche Toleranz: Vorhersage gilt als Treffer wenn tatsächliche Zelle
# innerhalb dieses Radius zur vorhergesagten Position liegt (Haversine, km).
VERIFICATION_TOLERANCE_KM = 5.0

# Zeitliche Toleranz beim Suchen des Frames T+horizon (Sekunden).
# ARSO liefert ca. alle 2-5 Min ein Bild → 90 s sind robust.
VERIFICATION_TIME_TOLERANCE_S = 90

# Maximaler Suchradius für Nearest-Neighbor-Match (km).
# Wenn keine Zelle in diesem Radius → "kein Treffer" geloggt, fließt in Hit-Rate ein.
VERIFICATION_MAX_SEARCH_RADIUS_KM = 25.0

# Backward-Compatibility für bestehende Module
LSTM_SEQUENCE_LENGTH = ML_SEQUENCE_LENGTH
LSTM_NUM_FEATURES = ML_NUM_FEATURES
LSTM_IGNORE_FLAG = ML_IGNORE_FLAG

# --------------------------------------
# Scheduler / Pipeline-Takte
# --------------------------------------

RETRAIN_INTERVAL_HOURS = 6
DATASET_REBUILD_INTERVAL_MIN = 60
LIVE_LOOP_INTERVAL_S = 120

# --------------------------------------
# Dateispeicherung (lokale Struktur)
# --------------------------------------

SAVE_PATHS = {
    "radar": "train_data/radar/",
    "objects": "train_data/objects/",
    "weather": "train_data/weather/",
    "wind": "train_data/wind/",
    "cape": "train_data/cape/",
    "dataset": "train_data/dataset/",
    "models": "train_data/models/",
    "ir": "train_data/ir/",
    "lightning": "train_data/lightning/",
    "evaluation": "train_data/evaluation/",
    "dem": "train_data/dem/",
    "arome": "train_data/arome/",   # NEU: AROME icon_d2 Gitterpunktdaten
    "ir_cells": "train_data/ir_cells/",
}
# Ausgabeauflösung in Pixeln (z. B. für GeoTIFF via WMS)
WIDTH = 1600
HEIGHT = 600

# Layer-Konfiguration für EUMETView
LAYER = "msg_fes:ir108"
FORMAT = "image/geotiff"
CRS = "EPSG:4326"

# Dateispeicherpfad
SAVE_DIR = "train_data/cloud/"

# Temperaturgradient für Wolkenhöhenberechnung
LAPSE_RATE = 6.5  # K/km
DEFAULT_SURFACE_TEMP_K = 290.0
DEFAULT_ALTITUDE_M = 600.0

# -------------------------------------------------------
# Daten-Rotation (Task A4)
# -------------------------------------------------------
# Dateien älter als N Tage werden täglich gelöscht.
DATA_RETENTION_DAYS: int = 90
DATA_CLEANUP_CRON_HOUR: int = 4
DATA_CLEANUP_CRON_MINUTE: int = 30
# Verzeichnisse die rotiert werden (relative Pfade vom Projektstamm).
# NICHT rotiert: train_data/models/, train_data/evaluation/, train_data/dataset/
DATA_CLEANUP_PATHS: list = [
    "train_data/radar/",
    "train_data/objects/",
    "train_data/weather/",
    "train_data/wind/",
    "train_data/cape/",
    "train_data/lightning/",
    "train_data/ir/",
    "train_data/ir_cells/",
    "train_data/cloud/",
    "train_data/arome/",
]

# -------------------------------------------------------
# Multi-Rechner-Vorbereitung (Task A8)
# -------------------------------------------------------
# True  = Scheduler startet retrain_*, rebuild_dataset, convlstm_weekly Jobs
# False = Diese Jobs werden übersprungen; Modelle kommen extern per rsync
#         vom Linux-Trainer-Rechner (Phase B).
# Kann überschrieben werden via:
#   - runtime_overrides.json  (zur Laufzeit)
#   - install.sh --no-training (setzt runtime_overrides.json automatisch)
LOCAL_TRAINING: bool = True

# -------------------------------------------------------
# Statische Ausschlusszonen (Segmentierung — False-Positive-Filter)
# -------------------------------------------------------
# Bekannte Quellen von Falschdetektionen im ARSO-Radarbild.
# Objekte deren Schwerpunkt innerhalb von radius_km liegt werden verworfen.
#
# Format je Eintrag:
#   name      — Beschreibung (für Logs und Admin-Panel)
#   lat/lon   — WGS84-Koordinaten des Zentrums
#   radius_km — Ausschlussradius in Kilometern
#
# Konfigurierbar zur Laufzeit via runtime_overrides.json:
#   {"STATIC_EXCLUSION_ZONES": [{"name": "...", "lat": ..., "lon": ..., "radius_km": ...}]}
STATIC_EXCLUSION_ZONES: list = [
    {
        "name": "Radarstation Koralpe (Reinischkogel)",
        "lat": 46.874,
        "lon": 14.963,
        "radius_km": 5.0,
    },
]
