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

# --------------------------------------
# Skywarn export snapshot (24h-Debug-Export only)
# --------------------------------------
SKYWARN_EXPORT_URL = "https://www.skywarn.at/arr_for_new.php"
SKYWARN_EXPORT_CRON_HOUR = 12
SKYWARN_EXPORT_CRON_MINUTE = 0
SKYWARN_EXPORT_TIMEOUT_SECONDS = 20
SKYWARN_EXPORT_DIR = "train_data/external_responses/skywarn"

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

# --------------------------------------
# P-S02: Langzeitstatistik-Aggregation
# --------------------------------------
# Nächtlicher Aggregationslauf (Europe/Vienna). Immer aktiv (kein LOCAL_TRAINING nötig).
STATS_AGGREGATE_CRON_HOUR: int = 3
STATS_AGGREGATE_CRON_MINUTE: int = 20
# Ausgabeverzeichnis der Jahres-Aggregate und des Klimatologie-Rasters.
STATS_DIR: str = "train_data/statistics"
# Klimatologie-Raster: Kantenlänge der Gitterzelle in Grad (~0.1° ≈ 8–11 km in Kärnten).
CLIM_GRID_DEG: float = 0.1
# BBOX Kärnten (lat_min, lat_max, lon_min, lon_max) zum Begrenzen des Rasters.
CLIM_BBOX = (46.30, 47.20, 12.55, 15.10)
# Mindestanzahl Tracks je (Gitterzelle, Monat), ab der ein Klimatologie-Wert als
# belastbar gilt. Darunter liefert der spätere ML-Lookup (P-S05) 0.0 (Modell lernt
# "fehlend", B95-Pattern) — verhindert verrauschte Pseudo-Klimatologie bei wenig Daten.
CLIM_MIN_SAMPLES: int = 5
# Histogramm-Ränder.
STATS_LIFETIME_BINS_MIN = [0, 15, 30, 45, 60, 90, 120, 180, 240, 100000]
STATS_SPEED_BINS_KMH = [0, 10, 20, 30, 40, 50, 70, 100, 100000]
# P-S05: Klimatologie-ML-Features. cell_age_min ist davon unabhängig (immer aktiv).
# Bei False liefern clim_*-Features konstant 0.0 (Feature-Anzahl bleibt gleich).
CLIM_FEATURES_ENABLED: bool = True

# --------------------------------------
# P-S01: Track-Lifecycle-Statistik
# --------------------------------------
# Mindest-Segmentlänge (km) damit ein Frame-zu-Frame-Schritt in die
# Richtungsstatistik einfließt (filtert Positionsrauschen quasi-stationärer Zellen).
TRACK_SEG_MIN_KM: float = 0.5
# Obergrenzen der am Track akkumulierten Listen (Speicherschutz auf dem Pi).
TRACK_SEG_DIRS_MAX: int = 500
TRACK_PATH_POINTS_MAX: int = 500

MAX_CONTOUR_DISTANCE = 30  # Maximaler Abstand für Zusammenführen von Konturen (px)
MAX_STATION_DISTANCE_KM = 20  # Wetterstations-Zuordnung
WIND_RASTER_RESOLUTION_KM = 10  # Rasterweite für Höhenwind
MIN_CONTOUR_OVERLAP = 10
MIN_CONTOUR_TOUCH = 5
# B172: Umkreis (km), in dem der mittlere Bewegungsvektor aktiver Zellen des
# letzten Frames als Start-Geschwindigkeit neu entstandener Zellen dient.
NEW_CELL_SEED_RADIUS_KM = 30.0

# --------------------------------------
# Tendenz-Klassifikation (Popup-Anzeige, B92)
# --------------------------------------
# Schwellwerte zur Einteilung der Zell-Entwicklung in stärker/schwächer/stabil.
# Werden im Popup (/karte) als Pfeile/Symbole angezeigt.
#
# Intensität: Basis ist die Änderung von core_ratio (Anteil ≥54 dBZ Kern).
#   ML-Pfad      → delta_core_ratio_pred (absolute Änderung über 20-min-Horizont)
#   Fallback     → trend-Feld (-1/0/+1) aus core_ratio-Verlauf
# Größe: relative Flächenänderung.
#   ML-Pfad      → delta_area_pred (relativer Anteil, z. B. 0.10 = +10 %)
#   Fallback     → richtungsabhängige Wachstumsraten (Halbachsen-Summe)
#
# "stabil"-Korridor (außerhalb → stärker/schwächer bzw. wächst/schrumpft):
TENDENCY_CORE_DELTA_STABLE = 0.05   # |Δcore_ratio| ≤ 0.05 → Intensität stabil
TENDENCY_AREA_PCT_STABLE   = 0.10   # |Δarea_pct|   ≤ 0.10 → Größe stabil

# --------------------------------------
# Risikoalarm-Cooldowns (B97/B98)
# --------------------------------------
RISK_ALERT_REQUIRED_DOMINANTS: list = ["atm"]
RISK_ALERT_COOLDOWN_S: int = 43200   # 12 Stunden

# Gewitterwarnung (Zell-Treffer) — max. 1× pro Zelle + Safety-Cooldown
WARN_COOLDOWN_S: int = 900           # 15 Min Safety-Net (nach per-Zelle-Logik, B98)

# Entwarnung
ALLCLEAR_COOLDOWN_S: int = 300       # 5 Min

# Drift-Alert (E-Mail)
DRIFT_ALERT_COOLDOWN_H: int = 6      # 6 Stunden

# --------------------------------------
# Trainings-Mindestsequenzen (B99)
# --------------------------------------
# Anzahl gültiger LSTM-Sequenzen die für ein Training mindestens vorliegen müssen.
# Werte entsprechen den Schwellen in model_training.py (train_lstm/train_lgbm).
# Werden auch vom /api/training_readiness-Endpoint und der Training-Seite genutzt.
MIN_SEQUENCES_LSTM: int = 50    # LSTM benötigt mind. 50 Sequenzen
MIN_SEQUENCES_LGBM: int = 30    # LightGBM benötigt mind. 30 Sequenzen (gesamt)
# P-T08: Mindestanzahl gültiger (nicht-maskierter) Samples PRO Horizont, ab der
# für diesen Horizont ein LightGBM-Modell trainiert wird. Kürzere Horizonte
# (+10/+20) erreichen die Schwelle früher → partielle Horizont-Abdeckung.
# Runtime-überschreibbar via runtime_overrides.json.
MIN_SEQUENCES_LGBM_PER_HORIZON: int = 15

# Minimale Zell-Geschwindigkeit für Pfeil-Darstellung in der Karte (km/h).
# Zellen langsamer als dieser Wert erhalten KEINEN Bewegungspfeil.
# 0 = alle Zellen bekommen Pfeil (altes Verhalten).
# Empfehlung: 5 km/h ≈ 0,5 px/Frame bei UPSCALE=3, Frame ~2 min.
# Überschreibbar via runtime_overrides.json: "MIN_MOVEMENT_FOR_ARROW_KMH": 8.0
MIN_MOVEMENT_FOR_ARROW_KMH = 5.0

# Risikozonen-Grid — IR-Vorläufer
RISK_IR_RANGE_KM = 15


# --------------------------------------
# 1L.2 IR↔Radar Score-Matching
# --------------------------------------
# Runtime-überschreibbar via runtime_overrides.json. Keine externen Requests;
# Score nutzt nur bereits vorhandene Radar-/IR-/Weather-Kontextfelder.
IR_RADAR_MATCH_SCORE_MIN = 0.70
IR_RADAR_MATCH_SCORE_WEAK_MIN = 0.55
IR_RADAR_MATCH_MAX_KM = 40.0
IR_RADAR_MATCH_STRONG_KM = 15.0
IR_RADAR_MATCH_LOOKBACK_MIN = 45.0
IR_RADAR_MATCH_MAX_IR_AGE_MIN = 20.0
IR_RADAR_MATCH_USE_PREDICTED_POSITION = True
IR_RADAR_MATCH_USE_STEERING_WIND = True
IR_RADAR_MATCH_USE_GROWTH_SIGNALS = True
IR_RADAR_MATCH_USE_METPOT = True
IR_PRECURSOR_HIDE_WHEN_RADAR_MATCHED = True
IR_PRECURSOR_RESHOW_COOLDOWN_MIN = 15.0


# --------------------------------------
# B213: Split-/Merge-Lineage über cell_id
# --------------------------------------
# Runtime-überschreibbar via runtime_overrides.json. Dokumentiert technische
# Radar-Lineage (parents/children/lineage) zusätzlich auf fachlicher cell_id-Ebene.
CELL_LINEAGE_SPLIT_MERGE_ENABLED = True
CELL_LINEAGE_PRIMARY_CHILD_POLICY = "strongest_core"
CELL_LINEAGE_PRIMARY_MERGE_POLICY = "highest_core_ratio"
CELL_LINEAGE_KEEP_PARENT_CELL_ID_ON_SPLIT_PRIMARY = True
CELL_LINEAGE_CREATE_CHILD_CELL_IDS = True
CELL_LINEAGE_RECORD_ALIAS_IDS = True

# --------------------------------------
# Weggefährten-Korridor (B94, ML-Feature)
# --------------------------------------
NEIGHBOR_AHEAD_RANGE_KM   = 40.0   # Reichweite des Korridors nach vorne (km)
NEIGHBOR_AHEAD_HALF_ANGLE = 45.0   # halber Öffnungswinkel des Keils (Grad)
NEIGHBOR_MIN_SPEED_KMH    = 5.0    # darunter keine Richtung → Feature neutral

# --------------------------------------
# Pfad-Wetter (B95, ML-Feature)
# --------------------------------------
# Max. Distanz Forecast-Punkt → nächster Atmosphären-Snapshot-Gitterpunkt (km).
# Snapshot-Raster hat ~24-28 km Abstand → 30 km deckt jeden Pfadpunkt ab.
PATH_ATM_MAX_DIST_KM = 30.0

# px/Frame → km/h. ARSO INCA si0zm liefert alle 5 min ein neues Bild; der
# Kalman-Filter wird nur bei echten neuen Bildern aktualisiert → 1 Frame = 5 min.
# Geometrie-Invariante: PX_TO_KMH == (1/UPSCALE_FACTOR) / (FRAME_INTERVAL_MIN/60)
#   (1/3 km/px) / (5 min / 60) = 4.0 km/h pro Original-px/Frame.
# B115: von 10.0 (2-min-Annahme) auf 4.0 korrigiert — reale Messung Median 5,0 min
# (PF-3 lokal nicht erneut messbar: keine data/radar/radar_*.png im Checkout).
# Einzige Quelle der Wahrheit — app.py, locations_check.py, object_tracking.py
# (_clamp_kalman_velocity), LiveDaten.jsx.
PX_TO_KMH: float = 4.0

# Nominales ARSO-INCA-Scan-Intervall in Minuten (= Kalman-Step-Dauer).
# Fallback-Zeitbasis, wenn die timestamp-basierte Velocity nicht greift.
# B115: von 2.0 auf 5.0 korrigiert (gemessener Median-Abstand 5,0 min).
# Fehlende Frames (Lücken 10–20 min) werden über die echten History-Timestamps
# korrigiert (object_tracking.py speed_kmh, prediction.py _actual_frame_min).
FRAME_INTERVAL_MIN: float = 5.0

# ── Kinematisches Tracking / EWMA (P27) ──────────────────────────────────────
TRACK_HISTORY_LEN: int = 6          # History-Buffer pro Zelle in Frames (min. 2, empfohlen 4–8)
KINEMATIC_EWMA_ALPHA: float = 0.6  # EWMA-Faktor: 0.01=gleichgewichtet · 0.99=nur neuester Frame

# Langsam ziehende Zellen: höheres Unwetterpotential durch längere
# Verweilzeit → erweiterter Warnradius und eigenständiger Bedrohungstyp.
# Meteorologische Grundlage: Zellen < 15 km/h verursachen den Großteil
# der Überflutungs- und Hagelereignisse in Kärnten (kurze Verlagerung,
# hohe Niederschlagssumme am Ort).
SLOW_CELL_MAX_KMH: float = 15.0          # Obergrenze "langsam ziehend"
SLOW_CELL_RADIUS_FACTOR: float = 1.5     # Ortsradius-Faktor für slow_approach

# Vorwarnzeit-Schwelle für E-Mail/WhatsApp-Alarm.
# Alarm wird nur gesendet wenn der früheste treffende Forecast-Horizont
# (kleinster Horizont-Key > 0) <= diesem Wert liegt.
# Horizon-Key 0 (Zelle JETZT im Ort) löst immer sofort Alarm aus.
# Konfigurierbar über Admin-Panel → runtime_overrides.json.
WARN_MAX_HORIZON_MIN: int = 20

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
    "blitzortung_last_strikes": 60,  # 60 s   (Update alle 1 Min)
    "openmeteo_extended":      900,
    "geosphere_nowcast":       720,
    "geosphere_tawes_all":     600,
}

# Räumliche Rundung beim Cache-Schlüssel: 0,02° ≈ 2 km — kleine Zellbewegungen
# treffen denselben Cache-Eintrag und sparen so weitere Requests.
API_CACHE_GRID_ROUND_DEG: float = 0.02

# --------------------------------------
# 1E: Tagesbudget je externer Schnittstellen-Gruppe (Free-only-Durchsetzung).
# Gruppen ohne Eintrag haben KEIN Limit. Open-Meteo: providerweites Free-Limit
# 10.000/Tag → konservativ 9.000 als Gruppe "openmeteo" (alle openmeteo_*-Dienste).
# Runtime-überschreibbar über runtime_overrides.json.
# --------------------------------------
API_DAILY_BUDGET: dict = {
    "openmeteo": 9000,
}

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


def speed_kmh_from_px(vx, vy) -> float:
    """B105/P0-1: Zellgeschwindigkeit [km/h] aus vx/vy in ORIGINAL-px/Frame.

    Invariante: Der Kalman-Filter wird mit original_cx/original_cy gefuettert
    (object_tracking.py), daher sind vx/vy Original-px/Frame. PX_TO_KMH ist
    km/h pro Original-px/Frame. KEINE Division durch UPSCALE_FACTOR.
    Single Source of Truth fuer object_tracking.py, locations_check.py und app.py.
    """
    import math as _m
    try:
        _vx = float(vx or 0.0)
        _vy = float(vy or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return _m.hypot(_vx, _vy) * float(PX_TO_KMH)

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

# Nachbeobachtungs-Intervall: Wird nach dem Verschwinden aktiver Zellen verwendet,
# bis NO_CELLS_SLOW_INTERVAL_TIMEOUT_S abgelaufen ist.
# 300 s = 5 Minuten.
LOOP_INTERVAL_NACHBEOBACHTUNG_S: int = 300

# Wie lange der Nachbeobachtungs-Intervall nach der letzten aktiven Zelle
# beibehalten wird, bevor auf LOOP_INTERVAL_NO_CELLS_S umgeschaltet wird.
# 7200 s = 120 Minuten (2 Stunden).
NO_CELLS_SLOW_INTERVAL_TIMEOUT_S: int = 7200

# --------------------------------------
# Risk-Watch-Polling (Gewitterpotenzial / CB-IR-Vorläuferzelle)
# --------------------------------------
# Auch OHNE aktive Radar-Zelle wird der kurze Loop-Intervall (LOOP_INTERVAL_CELLS_S)
# verwendet, wenn Gewitterpotenzial herrscht ODER eine CB-IR-Vorläuferzelle existiert.
# Beide Werte runtime-überschreibbar via runtime_overrides.json (Admin-Panel).
RISK_WATCH_ENABLED: bool = True
# Mindest-Risikostufe im /api/risk_grid (1=niedrig, 2=mäßig, 3=hoch), ab der
# Risk-Watch den kurzen Intervall erzwingt.
RISK_WATCH_MIN_RISK_LEVEL: int = 2
# Maximales Alter (min) der zugrunde liegenden Daten (neueste Objekt-Datei / IR-State),
# bis zu dem Risk-Watch den kurzen Intervall erzwingen darf. Verhindert, dass nach einem
# Radar-Ausfall veraltete Zellen/IR-Tracks den kurzen Intervall unbegrenzt halten.
RISK_WATCH_MAX_DATA_AGE_MIN: float = 20.0

# --------------------------------------
# P-T06: Zell-Überleben bis zum Ort
# --------------------------------------
# Schwächer/schrumpfende Zellen lösen sich evtl. auf, bevor sie einen Ort
# erreichen. Forecast-/Slow-Treffer werden unterdrückt, wenn die geschätzte
# Überlebensfraktion bei +Horizont unter CELL_SURVIVAL_MIN_FRAC fällt.
# current-Treffer (Zelle JETZT im Radius) sind davon NICHT betroffen.
CELL_DECAY_SUPPRESS_ENABLED: bool = True
# Halbwertszeit (min) der "Lebenskraft" wenn Zelle schwächer UND kleiner wird.
# Nur eines von beidem → doppelte Halbwertszeit (langsamerer Zerfall).
CELL_DECAY_HALF_LIFE_MIN: float = 25.0
# Mindest-Überlebensfraktion (0..1), ab der ein Forecast-/Slow-Treffer noch gilt.
CELL_SURVIVAL_MIN_FRAC: float = 0.35

# --------------------------------------
# P-M05: Stationäres Wachstum (Orts-Treffer durch Flächenausdehnung)
# --------------------------------------
# Eine stationäre Zelle (Geschwindigkeit < MIN_MOVEMENT_FOR_ARROW_KMH) kann einen
# Ort durch reine Flächenausdehnung erreichen. Ist dies aktiviert, wird das
# wachstums-projizierte Polygon (Zentrum ortsfest) gegen den Ortsradius geprüft
# und als Treffertyp "growth_approach" gewarnt. Beide Werte runtime-überschreibbar.
LOCATION_GROWTH_APPROACH_ENABLED: bool = True
# Mindest-Wachstumsrate der HALBEN Ausdehnung (km/min), ab der eine stationäre
# Zelle als wachsend gilt. 0.02 km/min ≈ +1,2 km Halbausdehnung über 60 min.
LOCATION_GROWTH_MIN_RATE_KM_PER_MIN: float = 0.02

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
    # ── B94: Weggefährten-Einfluss im Bewegungs-Zielkorridor ──────────────
    "neighbor_count_ahead",       # Anzahl anderer konvektiver Zellen voraus
    "neighbor_max_core_ahead",    # max. core_ratio dieser Nachbarzellen
    "neighbor_min_dist_km_ahead", # Distanz zur nächsten Zelle voraus (km; 999=keine)
    "strat_area_ahead_px",        # stratiforme Fläche voraus (Nachschub-Proxy)
    # ── B95: Atmosphäre entlang des berechneten Pfades (Forecast-Positionen) ─
    # Werte am Pfad-Ende (spätester Horizont) + Mittel über alle Horizonte.
    # Quelle: atmosphere_latest.json (kein neuer API-Call, Z.28).
    "path_cape_end",          # CAPE am letzten Forecast-Punkt (J/kg)
    "path_li_end",            # Lifted Index am letzten Forecast-Punkt (°C)
    "path_cape_mean",         # mittleres CAPE über alle Forecast-Punkte
    "path_li_min",            # min. (instabilster) LI über alle Forecast-Punkte
    "path_cin_end",           # CIN am letzten Forecast-Punkt (J/kg)
    "path_lapse_end",         # Lapse-Rate 700→500 am letzten Forecast-Punkt
    "path_wind700_end",       # 700-hPa-Windgeschwindigkeit am letzten Punkt (km/h)
    "path_cape_trend",        # CAPE(Ende) − CAPE(Start) — zieht Zelle in instabilere Luft?
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
    "hail_prob",               # Hagelwahrscheinlichkeit 0.0-1.0 (alte Heuristik)
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
    # ── NEU: Konvektive Diagnose-Indizes (compute_convective_indices.py) ────
    "t500_c",                  # Temperatur 500 hPa (Grad C)
    "t700_c",                  # Temperatur 700 hPa (Grad C)
    "cin",                     # Convective Inhibition (J/kg) — Deckelung
    "pw",                      # Precipitable Water (mm) — Starkregenpotenzial
    "lapse_700_500",           # Lapse Rate 700-500 hPa (Grad C/km)
    "shear_0_6km_speed",       # 0-6-km-Scherung (km/h) — Literatur-Standard
    "shear_0_6km_dir_cos",     # cos(Richtung 0-6-km-Scherung)
    "shear_0_6km_dir_sin",     # sin(Richtung 0-6-km-Scherung)
    "ship_index",              # Significant Hail Parameter (Stull)
    "lightning_jump",          # Blitzraten-Anstieg (>2 = Intensivierung)
    "hail_prob2",              # SHIP-basierte Hagel-Wahrscheinlichkeit
    # ── Lineage-Features (P17) ───────────────────────────────────────────────
    # Lebensdauer und Entstehungstyp der Zelle als ML-Signal.
    # Junge Zellen (frames_norm ≈ 0) haben unsichere Zugbahnen.
    # Merge-/Split-Produkte sind richtungsmäßig instabiler.
    "active_frames_norm",      # frames in history / 20 → [0..1] (gekappt)
    "total_active_frames_norm",# total_active_frames / 100 → [0..1] (gekappt)
    "is_merged",               # 1.0 wenn lineage=="merged", sonst 0.0
    "is_split",                # 1.0 wenn lineage=="split", sonst 0.0
    # ── Phase E: IR-Sat Features ──────────────────────────────────────────────
    "bt_min_k",             # Hellstes/kältestes IR-Pixel der zugeordneten IR-Cell [K]
    "bt_mean_k",            # Mittlere Brightness Temperature der IR-Cell [K]
    "bt_trend_k_per_min",   # BT-Änderungsrate [K/min] — negativ = wachsend
    "cloud_age_min",        # Alter des IR-Tracklets [min]
    "anvil_extension_km",   # Geschätzte Anvil-Ausdehnung [km]
    "overshooting_top",     # 1.0 wenn BT < 215 K (Overshooting Top erkannt)
    "ir_only_precursor",    # 1.0 wenn IR-Cell ohne Radar-Match (Vorläufer)
    # ── Phase E: 300-hPa-Höhenwind ───────────────────────────────────────────
    "wind_speed_300hPa",    # Windgeschwindigkeit 300 hPa [km/h]
    "wind_dir_300_cos",     # cos(Windrichtung 300 hPa)
    "wind_dir_300_sin",     # sin(Windrichtung 300 hPa)
    # ── NEU: Erweiterte konvektive Features (compute_extra_features.py) ───────
    # Rein rechnerische Approximationen aus bereits geholten Daten — kein API-Call.
    "dcape",                # Downdraft-CAPE-Proxy [J/kg]
    "shear_0_1km_speed",    # 0-1 km Scherung [km/h]
    "shear_0_3km_speed",    # 0-3 km Scherung [km/h]
    "srh_0_3km",            # Storm-Relative-Helicity-Proxy [m^2/s^2]
    "cape_trend_30min",     # ΔCAPE ueber ~30 min [J/kg]
    "li_trend_30min",       # ΔLifted-Index ueber ~30 min [Grad C]
    "vil_proxy",            # VIL-Proxy (core_ratio x Flaeche) [dimensionslos]
    # ── P-S05: Zellalter + Klimatologie-Prior (Langzeitstatistik) ──────────────
    "cell_age_min",            # physisches Alter der Zelle seit first_seen (min)
    "clim_cell_freq",          # normierte Zellhäufigkeit Gitterzelle×Monat (0..1)
    "clim_dir_cos",            # cos der klimatolog. Vorzugs-Zugrichtung (0 wenn unzuverlässig)
    "clim_dir_sin",            # sin der klimatolog. Vorzugs-Zugrichtung
    "clim_mean_lifetime_min",  # mittlere Lebensdauer in Gitterzelle×Monat (0 wenn unzuverlässig)
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
    10: "#ff00ff",
    20: "#ff0000",
    30: "#ff9900",
    40: "#f9fd53",
    60: "#00ff40",
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
    {"name": "Feldkirchen", "lat": 46.7233, "lon": 14.0992, "radius_km": 2.0},
    {"name": "Poitschach", "lat": 46.75158, "lon": 14.09417, "radius_km": 2.0},
]

# 9×4-Raster-Gitterpunkte für den atmosphärischen Snapshot.
# Verwendet ausschließlich von fetch_atmospheric_snapshot.py für das Risk-Grid
# (LI/CAPE/CIN-Einfluss). NICHT für Alarm-Prüfungen (kein radius_km).
# 36 Punkte mit ~24×28 km Abstand → lückenlose Abdeckung bei ATM_RANGE 20 km.
# Zur Laufzeit überschreibbar via runtime_config "ATM_SNAPSHOT_LOCATIONS".
ATM_SNAPSHOT_LOCATIONS: list = [
    # ── Süd-Kärnten / Karawanken (lat = 46.40) ────────────────────────────────
    {"name": "Ploeckenpass",       "lat": 46.40, "lon": 12.65},
    {"name": "Nassfeld",           "lat": 46.40, "lon": 12.96},
    {"name": "Arnoldstein",        "lat": 46.40, "lon": 13.28},
    {"name": "Faakersee",          "lat": 46.40, "lon": 13.59},
    {"name": "Rosegg",             "lat": 46.40, "lon": 13.90},
    {"name": "Ferlach",            "lat": 46.40, "lon": 14.21},
    {"name": "Eisenkappel",        "lat": 46.40, "lon": 14.53},
    {"name": "Lavamuend",          "lat": 46.40, "lon": 14.84},
    {"name": "Bleiburg-Sued",      "lat": 46.40, "lon": 15.15},
    # ── Zentral-Süd / Klagenfurter Becken (lat = 46.65) ───────────────────────
    {"name": "Lesachtal",          "lat": 46.65, "lon": 12.65},
    {"name": "Hermagor",           "lat": 46.65, "lon": 12.96},
    {"name": "Finkenstein",        "lat": 46.65, "lon": 13.28},
    {"name": "Villach",            "lat": 46.65, "lon": 13.59},
    {"name": "Velden",             "lat": 46.65, "lon": 13.90},
    {"name": "Klagenfurt",         "lat": 46.65, "lon": 14.21},
    {"name": "Grafenstein",        "lat": 46.65, "lon": 14.53},
    {"name": "Voelkermarkt",       "lat": 46.65, "lon": 14.84},
    {"name": "Bleiburg",           "lat": 46.65, "lon": 15.15},
    # ── Zentral-Nord / oberes Drautal + Krappfeld (lat = 46.91) ───────────────
    {"name": "Oberdrauburg",       "lat": 46.91, "lon": 12.65},
    {"name": "Greifenburg",        "lat": 46.91, "lon": 12.96},
    {"name": "Spittal",            "lat": 46.91, "lon": 13.28},
    {"name": "Paternion",          "lat": 46.91, "lon": 13.59},
    {"name": "Ossiach",            "lat": 46.91, "lon": 13.90},
    {"name": "Feldkirchen",        "lat": 46.91, "lon": 14.21},
    {"name": "St-Veit",            "lat": 46.91, "lon": 14.53},
    {"name": "Wolfsberg",          "lat": 46.91, "lon": 14.84},
    {"name": "St-Andrae",          "lat": 46.91, "lon": 15.15},
    # ── Nord-Kärnten / Nockberge + Gurktaler Alpen (lat = 47.16) ──────────────
    {"name": "Karnische-Nord",     "lat": 47.16, "lon": 12.65},
    {"name": "Obervellach",        "lat": 47.16, "lon": 12.96},
    {"name": "Gmuend",             "lat": 47.16, "lon": 13.28},
    {"name": "Radenthein",         "lat": 47.16, "lon": 13.59},
    {"name": "Bad-Kleinkirchheim", "lat": 47.16, "lon": 13.90},
    {"name": "Gurk",               "lat": 47.16, "lon": 14.21},
    {"name": "Friesach",           "lat": 47.16, "lon": 14.53},
    {"name": "Huettenberg",        "lat": 47.16, "lon": 14.84},
    {"name": "Bad-St-Leonhard",    "lat": 47.16, "lon": 15.15},
]

# TAWES-Stationen für Böen-Monitoring (GeoSphere Austria).
# IDs entsprechen Kärntner Stationen: Klagenfurt, Villach, Wolfsberg, Spittal, Feldkirchen.
# Alle Kärntner TAWES-Stationen (GeoSphere Austria, tawes-v1-10min).
# Vereinigung aus fetch_tawes_gust.py (5 Stationen, Böen-Fokus) und
# weather_api.py (31 Stationen, alle Parameter).
# Überschreibbar via runtime_overrides.json (Key: TAWES_GUST_STATION_IDS).
TAWES_GUST_STATION_IDS = (
    "11275,11218,11234,11206,11227,11235,11222,11273,"
    "11232,11259,11216,11349,11086,11255,11331,8989078,"
    "11217,11260,11215,11262,11278,11272,11229,11237,"
    "11213,11265,11257,11225,11228,8989076,11214,"
    "11330,11301,11315,11320,11350"
)

# TAWES-Parameter: Superset aus beiden bisherigen Modulen.
# Überschreibbar via runtime_overrides.json (Key: TAWES_PARAMS).
TAWES_PARAMS = "RR,DD,FF,FFX,GLOW,P,RF,TL,TP"

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
    "max_lines_per_file": 120,       # Zeilen pro Datei bei gekürztem Modus
    "full_source_mode":   False,      # True = gesamter Source ohne Kürzung (mehr Token!)
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
    "report_email": "bla@uniquare.com",         # E-Mail-Empfänger für täglichen KI-Report (leer = kein Versand)
}
AI_SUGGESTIONS_DIR = "train_data/evaluation/ai_suggestions"

# ---------------------------------------------------------------------------
# Claude-Code-Analyse-Report (vollständig unabhängig von AI_ANALYSIS_CONFIG)
# ---------------------------------------------------------------------------
# Versendet täglich analysis_result.json vom Branch debug-export-latest per E-Mail.
# Runtime-overridable: runtime_config.patch({"CLAUDE_CODE_REPORT_CONFIG": {...}})
CLAUDE_CODE_REPORT_CONFIG: dict = {
    "enabled":     True,   # Master-Schalter
    "cron_hour":   4,      # Versand-Uhrzeit (Europe/Vienna)
    "cron_minute": 0,
    "branch":      "debug-export-latest",  # GitHub-Branch mit analysis_result.json
    "report_email": "bla@uniquare.com",    # Empfänger (leer = kein Versand)
}

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
# Zieldefinition (zieldefinition.txt): Trefferabweichung ≤30 min muss < 1 km sein
# (Zielwert 0 km Drift). Die frühere 5-km-Toleranz ist damit aufgehoben.
# HINWEIS: Forschungsziel — der aktuelle kinematische Fallback erreicht es noch nicht;
# die Hit-Rate fällt mit dieser strengen Toleranz niedrig aus, bis die Positionsgenauigkeit
# (B207/B208 u. a.) verbessert ist.
VERIFICATION_TOLERANCE_KM = 1.0

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
    "statistics": "train_data/statistics/",
    "cell_filters": "train_data/cell_filters/",   # HitL: Filter + Polygon-PNGs
    "system": "train_data/system/",               # CPU/System-Monitoring
    "cell_lineage": "train_data/cell_lineage/",     # 1L.1: stabile fachliche Zell-IDs
}

# --------------------------------------
# Zell-Lineage (1L.1)
# --------------------------------------
IR_LINEAGE_ENABLED = True
CELL_ID_PREFIX = "WX"
CELL_LINEAGE_STATE_DIR = "train_data/cell_lineage"
CELL_LINEAGE_STATE_FILE = "cell_lineage_state.json"
CELL_LINEAGE_EVENTS_FILE = "cell_lineage_events.jsonl"

# 1L.4 ML-Lead-Time-Labels: offline Trainingslabels aus IR→Radar-Lineage.
IR_LEAD_TIME_LABELS_ENABLED = True
IR_LEAD_TIME_LABELS_FILE = "ir_lead_time_labels.jsonl"
IR_LEAD_TIME_LABELS_MAX_OPEN_MIN = 90.0
IR_LEAD_TIME_LABELS_MIN_FINAL_AGE_MIN = 20.0
IR_LEAD_TIME_LABELS_INCLUDE_NEGATIVES = True
IR_LEAD_TIME_LABELS_DEDUP_BY_CELL_ID = True

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
EUMETVIEW_NODATA_PIXEL: int = 5

# --------------------------------------
# CB-Höhengrenze (Karten-Anzeige „CB > …")
# --------------------------------------
# Grenze (m MSL), ab der ein IR-Cluster auf der Karte als „CB > …" statt
# „IR-Vorläufer" beschriftet wird (B204). Runtime-überschreibbar; an die
# öffentliche Karte via /api/objects?include_ir=1 ausgeliefert.
CLOUD_HEIGHT_ALERT_THRESHOLD_M: float = 7000.0

# ── Phase E: IR-Sat Pre-Convection Detection ──────────────────────────────────
# Alle Schwellwerte runtime-überschreibbar via runtime_overrides.json.
# --------------------------------------
# EUMETView Scan-Modus (Rapid Scan / Full Earth Scan) — Free-only
# --------------------------------------
# Nur freie EUMETView-WMS-Layer. Kein API-Key, keine kostenpflichtige Schnittstelle.
FREE_ONLY_API_POLICY: bool = True
EUMETVIEW_PAID_ALLOWED: bool = False
# Scan-Modus: "FES" (Full Earth Scan, ~15 min, Default) | "RSS" (Rapid Scan, ~5 min).
EUMETVIEW_SCAN_MODE: str = "FES"
EUMETVIEW_FES_LAYER_IR108: str = "msg_fes:ir108"
# RSS-IR108 ist auf EUMETView NICHT verfügbar (verifiziert am Pi via GetCapabilities,
# 2026-06): RSS bietet nur msg_rss:ir039_nrt + RGB-Produkte, KEIN msg_rss:ir108.
# IR108 existiert nur als FES (msg_fes:ir108), EPS (Metop, polar), IODC und MUMI.
# get_active_ir108_layer() validiert weiterhin gegen GetCapabilities → bleibt dauerhaft FES.
# None = kein RSS-IR108-Kandidat; bei künftiger Verfügbarkeit hier explizit setzen.
EUMETVIEW_RSS_LAYER_IR108 = None
# RSS nur aktiv, wenn die Lizenz technisch als frei bestätigt ist.
EUMETVIEW_LICENSE_STATUS: str = "unconfirmed"   # unconfirmed | free_confirmed | disabled
# Max. Alter (min) eines wiederverwendeten WMS-Timestamps im RSS-Modus (kürzer als FES).
EUMETVIEW_RSS_FALLBACK_MAX_AGE_MIN: float = 12.0

IR_CONVECTION_BT_THRESHOLD_K: float = 230.0  # BT < Wert = konvektiver Wolkentop
IR_OVERSHOOTING_TOP_BT_K:     float = 215.0  # BT < Wert = Overshooting Top (Hagelpotenzial)
IR_MIN_CELL_AREA_PX:          int   = 300    # Mindestgröße Cluster (Pixel im TIFF)
                                              # Bei 0.12 km/Pixel ≈ 4 km² ≈ echter CB-Kern
IR_MIN_CAPE_J_KG:             float = 200.0  # CAPE-Filter für IR-Cell (0 = kein Filter)
IR_MAX_LI_C:                  float = -0.5   # LI-Filter für IR-Cell (0 = kein Filter)
IR_TRACK_MAX_MISSING:         int   = 2      # 15-min-Slots ohne Detektion bis Tracking endet

# -------------------------------------------------------
# Daten-Rotation (Task A4)
# -------------------------------------------------------
# Dateien älter als N Tage werden täglich gelöscht.
DATA_RETENTION_DAYS: int = 90
# B147: ConvLSTM-Training speicherschonend (Streaming) + isoliert.
# Sicherheits-Obergrenze der je Lauf berücksichtigten (jüngsten) Radar-Frames gegen
# RAM-Spitzen. INNERHALB des Caps werden via Streaming ALLE Frames je Epoche genutzt
# (keine Qualitätseinbuße). 0 = unbegrenzt.
CONVLSTM_MAX_FRAMES: int = 6000
# Timeout (Sekunden) für den isolierten ConvLSTM-Trainings-Subprozess.
CONVLSTM_TRAIN_TIMEOUT_S: int = 7200
# Adressraum-Limit (GB) des Trainings-Subprozesses → planbares Scheitern statt
# system-weitem OOM-Kill (schützt die übrigen Dienste auf dem Pi).
CONVLSTM_TRAIN_MEM_LIMIT_GB: int = 12
# B146: Kulanzfenster für verpasste Scheduler-Jobs (Sekunden). Wird ein Cron-Job zum
# geplanten Zeitpunkt verpasst (Scheduler-Neustart/Downtime), läuft er bis zu so vielen
# Sekunden später noch nach (coalesced) statt erst am Folgetag. Default 1 h.
SCHEDULER_MISFIRE_GRACE_S: int = 3600
# B143: Alters-Rotation für append-only JSONL-Logs in train_data/evaluation/
# (api_call_counts.jsonl, api_health.jsonl). Zeilen älter als N Stunden werden im
# täglichen Cleanup verworfen. Default 48 h (> 24h-Export-Fenster) → der 24h-Export
# behält IMMER alle Daten; gestoppt wird nur unbegrenztes Wachstum. 0 = keine Rotation.
EVAL_LOG_RETENTION_HOURS: int = 48
# Cleanup nur ausfuehren wenn freier Speicher unter diesen Wert faellt.
# Solange genug Platz vorhanden ist, bleiben Daten erhalten (wertvoll fuer
# Hailo-Calibration und Retraining). 0 = immer loeschen (altes Verhalten).
MIN_FREE_GB_BEFORE_CLEANUP: float = 5.0
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
        # Radar-Komplex auf dem Großen Speikkogel (2.140 m MSL), höchster
        # Gipfel der Koralpe, Grenze Kärnten/Steiermark.
        # Betreiber: Austro Control (Sekundärradar Flugsicherung) +
        #            Bundesheer (Goldhaube-Luftraumüberwachung).
        # Die Antennenanlagen reflektieren das ARSO-Niederschlagsradar und
        # erzeugen einen permanenten Falsch-Echo im Radarbild.
        "name": "Großer Speikkogel – Radaranlagen Koralpe",
        "lat": 46.824,
        "lon": 14.968,
        # Reduziert von 15.0 → 8.0 km: 15 km umschloss ~707 km², bei dem echte
        # Sturmzellen östlich Wolfsberg fälschlich gefiltert wurden.
        # 8 km Radius entspricht ~200 km² — nur der direkte Radarschatten-
        # Bereich. Bei Bedarf via runtime_overrides.json wieder erhöhbar.
        "radius_km": 8.0,
    },
]


# -------------------------------------------------------
# HitL — Manuelles Zell-Markieren (Human-in-the-Loop)
# -------------------------------------------------------
# Single Source of Truth für manuell ergänzte und KI-vorgeschlagene HSV-Bereiche.
# Wird von cell_filters.py verwaltet, von object_tracking.py gelesen
# und von app.py über REST-Endpunkte bearbeitet.
CELL_FILTERS_DIR: str         = "train_data/cell_filters/"
CELL_FILTERS_PATH: str        = "train_data/cell_filters/cell_filters.json"
CELL_FILTERS_POLYGON_DIR: str = "train_data/cell_filters/polygons/"

# Padding (in Pixeln) um das markierte Polygon beim PNG-Crop.
# Im Admin-Panel über runtime_overrides.json überschreibbar
# (Schlüssel: HITL_PADDING_PX). Empfohlener Bereich: 10–150 px.
HITL_PADDING_PX_DEFAULT: int = 50

# Maximale Anzahl Polygon-PNGs, die pro KI-Lauf an Anthropic geschickt werden.
# Begrenzt API-Kosten und Token-Budget. Untergrenze für nützliche Analyse: 3.
HITL_MAX_PNGS_FOR_AI: int = 5

# KI-Modus für /api/cell_filters/ai_analyze:
#   "expand_only"        — KI darf NUR neue, breitere Bereiche vorschlagen
#                          (bestehende Filter bleiben unverändert).
#   "expand_and_refine"  — KI darf zusätzlich engere Bereiche vorschlagen.
# Default "expand_only" ist die sichere Voreinstellung.
HITL_AI_MODE: str = "expand_only"

# ── Intensitätszonen (Farbzonen innerhalb Sturmzellen) ────────────────────────
# Format: (Label, HSV-Lower-Tuple, HSV-Upper-Tuple, Hex-Farbe)
# Wartbar über Admin-Panel / runtime_config unter dem Key "INTENSITY_BANDS".
INTENSITY_BANDS_DEFAULT = [
    ["orange",   [10,  100,  80], [27,  255, 255], "#ff8800"],
    ["rot",      [0,   100,  80], [10,  255, 255], "#cc0000"],
    ["rot_wrap", [165, 100,  80], [179, 255, 255], "#cc0000"],
    ["violett",  [125, 100,  80], [155, 255, 255], "#9900cc"],
]
