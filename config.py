# config.py

# --------------------------------------
# Debugging / Logging
# --------------------------------------

import os as _os
try:
    from dotenv import load_dotenv as _load_dotenv
    # Expliziter Pfad relativ zu config.py — funktioniert unabhängig vom Arbeitsverzeichnis.
    # override=True: .env-Wert überschreibt Shell-Variablen aus derselben Session.
    # Systemd Environment= hat trotzdem Vorrang, da es den Prozess-Env VOR
    # dem Python-Start setzt — load_dotenv() läuft erst danach und würde
    # override=True den systemd-Wert überschreiben. Deshalb:
    # Priorität: systemd Environment= > .env > Default "0"
    # Um systemd-Vorrang zu wahren: override=False; für .env-Vorrang: override=True.
    # override=True gewählt: .env ist die primäre Konfigurationsquelle auf dem Pi.
    _load_dotenv(
        dotenv_path=_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), ".env"),
        override=True,
    )
except ImportError:
    pass  # python-dotenv nicht installiert — nur os.environ gilt
# Aktivierung: WETTER_DEBUG=1 in .env  ODER  export WETTER_DEBUG=1 vor dem Start
DEBUG_MODE = _os.environ.get("WETTER_DEBUG", "0") == "1"
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

# Kernbereiche: NUR Rot + Violett (≥54 dBZ) = echter konvektiver Kern.
# Orange (48–51 dBZ) bewusst ausgeschlossen: starker Regen, aber kein
# Hagelkern — würde core_ratio für reine Orange-Zellen auf 1.0 setzen
# und hail_prob fälschlicherweise maximieren.
# WAS_ACTIVE_CORE_RATIO_THRESHOLD=0.25 ist auf diese 3-Range-Definition kalibriert.
CORE_HSV_RANGES = [
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
    (( 55,  50,  60), ( 92, 255, 255)),  # Grün          36–41 dBZ  (H:55-92)
    (( 28,  50,  60), ( 55, 255, 255)),  # Gelb/GelbGrün 42–48 dBZ  (H:28-55)
    # H:28-37 war Lücke zwischen Orange-Konvektiv (endet H:27) und GelbGrün (begann H:38).
    # 594 Pixel/Frame betroffen → strat_area_px für Zellen mit gelbem Rand systematisch
    # zu niedrig. Fix: Band beginnt jetzt bei H:28 (nahtlos an Orange anschließend).
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

# Minimale Zell-Geschwindigkeit für Pfeil-Darstellung in der Karte (km/h).
# Zellen langsamer als dieser Wert erhalten KEINEN Bewegungspfeil.
# 0 = alle Zellen bekommen Pfeil (altes Verhalten).
# Empfehlung: 5 km/h ≈ 0,5 px/Frame bei UPSCALE=3, Frame ~2 min.
# Überschreibbar via runtime_overrides.json: "MIN_MOVEMENT_FOR_ARROW_KMH": 8.0
MIN_MOVEMENT_FOR_ARROW_KMH = 5.0

# px/Frame → km/h (UPSCALE=3, ~2 km/px orig., Zyklus 120 s).
# Einzelne Quelle der Wahrheit — wird von app.py, locations_check.py
# und LiveDaten.jsx verwendet. Empirisch kalibriert auf Kärnten-Gitter.
PX_TO_KMH: float = 10.0

# Langsam ziehende Zellen: höheres Unwetterpotential durch längere
# Verweilzeit → erweiterter Warnradius und eigenständiger Bedrohungstyp.
# Meteorologische Grundlage: Zellen < 15 km/h verursachen den Großteil
# der Überflutungs- und Hagelereignisse in Kärnten (kurze Verlagerung,
# hohe Niederschlagssumme am Ort).
SLOW_CELL_MAX_KMH: float = 15.0          # Obergrenze "langsam ziehend"
SLOW_CELL_RADIUS_FACTOR: float = 1.5     # Ortsradius-Faktor für slow_approach

# --------------------------------------
# Datenquellen
# --------------------------------------

AROME_BASE_URL = "https://dataset.api.hub.geosphere.at/v1/grid/forecast/nwp-v1-1h-2500m"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
# LIGHTNING_DATA_URL entfernt (Bug B12) — lightningmaps.org ist inoffiziell
# und nicht produktionsreif. Blitzdaten kommen ausschließlich über blitz_api.py
# (Blitzortung.org, HTTP Basic Auth). Gespeichert in SAVE_PATHS["lightning"].

GEOSPHERE_NOWCAST_URL = "https://dataset.api.hub.geosphere.at/v1/timeseries/forecast/nowcast-v1-15min-1km"
GEOSPHERE_TAWES_URL = "https://dataset.api.hub.geosphere.at/v1/station/current/tawes-v1-10min"
TAWES_STATION_IDS_KAERNTEN = "11330,11301,11315,11320,11350"

# --------------------------------------
# API-Cache TTLs (Sekunden) — vermeidet unnötige Requests an Fremdsysteme.
# TTL ≈ 50 % der natürlichen Update-Frequenz des Anbieters (Sicherheitsmarge
# gegen Modell-Lauf-Verzögerungen).
#
# Update-Intervalle der Anbieter (Stand 2026-05):
#   - ARSO INCA si0zm KMZ:          5 Min   → If-Modified-Since (kein TTL nötig)
#   - Open-Meteo icon_d2 (AROME):   3 h Modell-Run, stündliche Werte
#   - Open-Meteo icon_global 700hPa: 6 h Modell-Run, stündliche Werte
#   - GeoSphere AROME CAPE:         3 h Modell-Run, stündliche Werte
#   - EUMETView MSG IR108 (FES):   15 Min Full-Earth-Scan
#   - Blitzortung last_strikes:     1 Min
#
# Überschreibbar über runtime_overrides.json.
# --------------------------------------
API_CACHE_TTL_SECONDS: dict = {
    "openmeteo_icon_d2":      1800,  # 30 Min (Modell alle 3 h)
    "openmeteo_icon_global":  3600,  # 60 Min (Modell alle 6 h)
    "openmeteo_synoptic":     3600,  # 60 Min (500-hPa, icon_global alle 6 h)
    "geosphere_cape":         1800,  # 30 Min (Modell alle 3 h)
    "eumetview_capabilities":  600,  # 10 Min (Scan alle 15 Min)
    "blitzortung":              60,  # 60 s   (Update alle 1 Min)
    "openmeteo_extended":      900,
    "geosphere_nowcast":       720,
    "geosphere_tawes":         600,
}

# Räumliche Rundung beim Cache-Schlüssel: 0,02° ≈ 2 km — kleine Zellbewegungen
# treffen denselben Cache-Eintrag und sparen so weitere Requests.
API_CACHE_GRID_ROUND_DEG: float = 0.02

# ── Warnschwellwerte ──────────────────────────────────────────────────────────
# Hagelwarnung wird ausgelöst wenn hail_prob diesen Wert überschreitet.
HAIL_WARN_THRESHOLD: float = 0.45
# Stationärrisiko-Marker auf Karte wird angezeigt ab diesem Schwellwert.
STATIONARY_RISK_MARKER_THRESHOLD: float = 0.60
GUST_WARN_KMH: float = 60.0
HEAVY_RAIN_WARN_MM_PER_H: float = 25.0
# Maximale physikalisch plausible Zellgeschwindigkeit (km/h). Kalman-Werte
# über diesem Limit werden auf diesen Wert geclampt (Plausibilitätsprüfung F14).
MAX_CELL_SPEED_KMH: float = 150.0
# Maximale Geschwindigkeitsänderung pro 5-min-Zyklus (km/h). Verhindert
# Kalman-Sprünge bei Mess-Artefakten (Plausibilitätsprüfung F14).
MAX_SPEED_CHANGE_PER_CYCLE_KMH: float = 60.0

# was_active Flag: True sobald core_ratio diesen Schwellwert je überschritten hat.
# Sticky — bleibt True bis Zelle aus Tracking fällt. Missing-Limit bleibt 10.
# core_ratio = Anteil Rot+Violett (≥54 dBZ) Pixel an Gesamtzelle.
# Orange (48-51 dBZ) ist NICHT im Kern — siehe CORE_HSV_RANGES (3 Einträge).
# 0.25 = 25% echter Kern → eindeutig konvektiv-intensiv, kein reiner Regen.
# Bei nur Rot+Violett ist 0.25 realistisch für Gewitterzellen (früher war
# Orange eingeschlossen → threshold konnte leichter erreicht werden).
WAS_ACTIVE_CORE_RATIO_THRESHOLD: float = 0.25

# Wie lange inaktive Zellen (missing > 0) weitergetrackt werden.
# Zeitbasiert — unabhängig vom aktuellen Loop-Intervall.
# 1200 s = 20 Minuten.
INACTIVE_CELL_TRACK_DURATION_S: int = 1200

# Wie lange der kurze Loop-Intervall (LOOP_INTERVAL_CELLS_S) nach der letzten
# aktiven Zelle beibehalten wird, bevor auf LOOP_INTERVAL_NO_CELLS_S umgeschaltet.
# 3600 s = 60 Minuten.
NO_CELLS_SLOW_INTERVAL_TIMEOUT_S: int = 3600

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
    # ── Stratiforme Umgebung (36–47 dBZ) ─────────────────────────────────
    "strat_area_px",
    "strat_intensity_mean",
    "strat_dbz_gradient",
    # ── DEM erweitert (Mosaic E013+E014+E015) ────────────────────────────
    "dem_barrier_ahead",       # Höhendiff. 10-20 km voraus (m, pos=Barriere)
    # ── Talkanalisierung ─────────────────────────────────────────────────
    "valley_alignment",        # |cos(angle)| Zell-Bewegung vs. Tal (0-1)
    "valley_distance_km",      # Abstand Talmitte (km)
    "valley_confinement",      # 1.0 wenn im Talquerschnitt
    # ── Großwetterlage 500 hPa ───────────────────────────────────────────
    "z500_dam",                # Geopotential 500 hPa in dam
    "wind_500_speed",          # Steuerströmung 500 hPa (km/h)
    "wind_500_dir_cos",
    "wind_500_dir_sin",
    # ── Orographische Risk-Scores ────────────────────────────────────────
    "terrain_blocking_score",  # Gelände blockiert Zugbahn (0-1)
    "orographic_lift_score",   # Staulage/Hebung (0-1)
    "stationary_risk",         # Stationärrisiko (0-1)
    # ── Windscherung (F16) ───────────────────────────────────────────────────
    "wind_shear_speed",        # Betrag Scherung 10m→700hPa (km/h)
    "wind_shear_dir_cos",      # cos(Scherungsvektor-Richtung)
    "wind_shear_dir_sin",      # sin(Scherungsvektor-Richtung)
    # ── Hagelindikator (F06/F43) ─────────────────────────────────────────────
    "hail_prob",               # Hagelwahrscheinlichkeit 0.0-1.0
    "wind_gust_10m_kmh",
    "lpi",
    "wind_speed_500hPa",
    "wind_dir_500_cos",
    "wind_dir_500_sin",
    "wind_speed_850hPa",
    "wind_dir_850_cos",
    "wind_dir_850_sin",
    "nowcast_rr_mm15",
    "nowcast_ffx_kmh",
    "nowcast_rain_rate_1h",
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
# Hinweis: Wird durch config.py zur Laufzeit berechnet. Bei Feature-Änderungen
# müssen Modelle neu trainiert werden (model_training.py).
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
    {"name": "Feldkirchen", "lat": 46.7233, "lon": 14.0992, "radius_km": 5.0},
]

# Beschriftungen der HSV-Bänder, damit das Adminpanel sie zeigen kann.
HSV_BAND_LABELS = ["leichter_regen", "regen", "starkregen"]

# Pfad für Runtime-Overrides aus dem Adminpanel.
RUNTIME_OVERRIDES_PATH = "train_data/runtime_overrides.json"

# --------------------------------------
# KI-Analyse-Pipeline (Anthropic API)
# --------------------------------------
# Default: deaktiviert. Aktivierung über Admin-Panel oder runtime_overrides.json.
# ---------------------------------------------------------------------------
# GitHub-Konfiguration — Quellcode-Quelle für KI-Analyse
# ---------------------------------------------------------------------------
GITHUB_VERIFY_CONFIG = {
    "repo":   "IVOBLA/WetterExtended",
    "branch": "main",
    "token":  _os.environ.get("GITHUB_TOKEN", ""),   # leer = public repo
    "files": [
        "config.py",
        "main.py",
        "object_tracking.py",
        "prediction.py",
        "accuracy_tracker.py",
        "dataset_builder.py",
        "scheduler.py",
        "daily_analyzer.py",
        "blitz_api.py",
        "fetch_arome_openmeteo.py",
        "model_training.py",
        "radar_convlstm.py",
        "assign_cape_from_forecast.py",
        "cloud_height_from_eumetview.py",
    ],
    "max_lines_per_file": 120,
}

AI_ANALYSIS_CONFIG = {
    "enabled": False,           # Master-Schalter
    "cron_hour": 6,             # Uhrzeit des täglichen Analyselaufs
    "cron_minute": 0,
    "cron_days": "mon,tue,wed,thu,fri,sat,sun",  # Wochentage (APScheduler-Format, leer = alle)
    "only_if_cells": False,  # True = Analyse nur wenn heute Sturmzellen erkannt wurden
    "model": "claude-sonnet-4-6",
    "max_tokens": 3000,         # mind. 2500 fuer vollstaendiges JSON mit 8 Suggestions
    "since_hours": 24,          # Datenfenster für den Report
    "save_suggestions": True,   # Vorschläge als JSON persistieren
    "report_email": "",         # E-Mail-Empfänger für täglichen KI-Report (leer = kein Versand)
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
LIVE_LOOP_INTERVAL_S = 120          # Rückwärtskompatibilität

# Adaptiver Loop-Intervall (main.py)
# Wenn Zellen aktiv: kurzer Intervall für schnelle Reaktion
# Wenn keine Zellen: langer Intervall spart Ressourcen
LOOP_INTERVAL_CELLS_S: int   = 120   # 2 Min  — Zellen aktiv
LOOP_INTERVAL_NO_CELLS_S: int = 900  # 15 Min — keine Zellen (konfigurierbar)

# Atmosphären-Snapshot (unabhängig von erkannten Zellen)
ATMOSPHERIC_SNAPSHOT_INTERVAL_MIN: int = 30   # alle 30 Min

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
    "ir": "train_data/cloud/",       # FIX: TIFFs landen in cloud/, nicht ir/
    "lightning": "train_data/lightning/",
    "evaluation": "train_data/evaluation/",
    "dem": "train_data/dem/",
    "arome": "train_data/arome/",
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

# EUMETView IR108 uint8-Kalibrierung → Brightness Temperature Kelvin
# EUMETView liefert image/geotiff als visualisiertes uint8-RGBA-Farbbild.
# Standardskala (invertiert linear):
#   Pixelwert   0 → EUMETVIEW_BT_MAX_K (warme Oberfläche, wolkenfrei)
#   Pixelwert 255 → EUMETVIEW_BT_MIN_K (sehr hohe, kalte Wolke)
#   BT_K = EUMETVIEW_BT_MAX_K - ((MAX_K - MIN_K) / 255.0) * pixel
EUMETVIEW_BT_MAX_K: float = 330.0   # Kelvin bei Pixelwert 0
EUMETVIEW_BT_MIN_K: float = 180.0   # Kelvin bei Pixelwert 255
EUMETVIEW_NODATA_PIXEL: int = 5     # Pixelwerte <= 5 = nodata (EUMETView Randbereiche)

# -------------------------------------------------------
# Daten-Rotation (Task A4)
# -------------------------------------------------------
# Dateien älter als N Tage werden täglich gelöscht.
DATA_RETENTION_DAYS: int = 90
DATA_CLEANUP_CRON_HOUR: int = 4
DATA_CLEANUP_CRON_MINUTE: int = 30
# Verzeichnisse die rotiert werden (relative Pfade vom Projektstamm).
# NICHT rotiert: train_data/models/, train_data/evaluation/, train_data/dataset/
# Verzeichnisse mit abweichender Aufbewahrungszeit (ueberschreiben DATA_RETENTION_DAYS).
# data/radar/ braucht nur 2 Tage — Frontend-Animation nutzt max. 24h.
DATA_CLEANUP_RETENTION_OVERRIDE: dict = {
    "data/radar/": 2,          # 2 Tage — ~580 Dateien × 10 KB = ~6 MB/Tag
}
DATA_CLEANUP_PATHS: list = [
    "data/radar/",             # Live-Radarbilder fuer Frontend-Animation (kurze Retention!)
    "train_data/radar/",
    "train_data/objects/",
    "train_data/weather/",
    "train_data/wind/",
    "train_data/cape/",
    "train_data/lightning/",
    "train_data/ir_cells/",
    "train_data/cloud/",      # enthält sowohl TIFFs (ir108_*.tif) als auch JSONs
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
