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

# Einheitliche dunkelblaue Grundfarbe fuer aktuelle Zellpolygone.
CELL_COLOR = "#0b1f5e"

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
# P66: Multi-Core-Split
# --------------------------------------
# Erkennt und trennt Radar-Blobs mit mehreren räumlich getrennten
# Konvektionskernen (rot/violett = ≥54 dBZ). Wartbar via Admin-Panel.
MULTI_CORE_SPLIT_ENABLED: bool = True
# Minimale Fläche eines Kerns in Pixel (bei UPSCALE=3: 80 px ≈ 0.9 km²).
MULTI_CORE_MIN_CORE_AREA_PX: int = 80
# Mindestabstand zwischen Kern-Zentroiden in Pixel (bei UPSCALE=3: 15 px ≈ 2.4 km).
MULTI_CORE_MIN_DIST_PX: int = 15
# Mindestfläche einer Sub-Zelle nach dem Split in Pixel (= min_object_area-Default).
MULTI_CORE_MIN_CHILD_AREA_PX: int = 800
# B275: Mindestlänge (px) einer echten Lücke in der äußeren Zell-Maske entlang der
# Verbindungslinie zwischen zwei Kern-Zentren, damit ein Split überhaupt erlaubt
# ist. Bleibt die Verbindung komplett innerhalb der Maske (gap=0), handelt es sich
# um eine einzige zusammenhängende Wetterstruktur (z. B. eine elongierte Böenlinie
# mit mehreren Reflektivitäts-Maxima) und darf NICHT gesplittet werden — verifiziert
# anhand des Debug-Exports 2026-06-30 17:35 (I45JTRXI/9WMB6Q7Q: 0/100 Samples
# außerhalb der Maske über die volle 18,9-km-Verbindungslinie).
MULTI_CORE_MIN_GAP_PX: float = 2.0

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
# B274: Dilatations-Puffer (px, hochskaliertes Grid) fuer are_contours_touching_edges().
# Ohne Puffer reicht schon eine Luecke von einem einzigen Pixel (~111 m bei
# UPSCALE_FACTOR=3), damit zwei Konturen als "nicht beruehrend" gelten und nie
# zusammengefuehrt werden, obwohl sie im Reflektivitaets-Colormap eine einzige
# zusammenhaengende Zelle bilden (verifiziert: Debug-Export 2026-06-30 17:35,
# Faelle I45JTRXI/9WMB6Q7Q und SKU9AD2B/IHAPWM5M, je 0,140 km = 1 Pixel Luecke).
MERGE_TOUCH_DILATE_PX = 2
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
# Absolute Kernfläche stabil, wenn relative Änderung im ±10-%-Korridor liegt.
TENDENCY_CORE_AREA_PCT_STABLE = 0.10
# Ab dieser negativen Flächenänderung gilt Schrumpfen als Widerspruch zu reiner core_ratio-Intensivierung.
TENDENCY_CONTRADICTION_AREA_SHRINK_PCT = -0.10
# Mindestanstieg des Kernanteils für die Anzeige "Kern konzentriert sich".
TENDENCY_COMPACT_CORE_RATIO_DELTA = 0.05

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
# P59: Maximales Frame-Intervall für Optical-Flow-Nutzung. Lucas-Kanade versagt bei
# Pixelverschiebungen > Suchfenstergröße (große Frame-Lücken durch ARSO-Ausfall).
# Bei _fm_of > Schwellwert → EWMA/History-Fallback statt OF.
OF_MAX_FRAME_INTERVAL_MIN: float = 8.0

# B298: Schwellwerte fuer die Radar-Ingest-Gesundheitsbewertung, als Vielfaches
# von expected_interval_min (aktuell 5 min). Datenbefund 2026-07-04:
# longest_gap_min=20.0 (=4x) bei einer Coverage von nur 59%. "warning" ab mehr
# als einem verpassten Intervall, "critical" ab dem 4-fachen. Admin-/
# runtime-editierbar via runtime_overrides.json.
RADAR_INGEST_GAP_WARN_FACTOR: float = 2.0
RADAR_INGEST_GAP_CRITICAL_FACTOR: float = 4.0

# ── Kinematisches Tracking / EWMA (P27) ──────────────────────────────────────
TRACK_HISTORY_LEN: int = 6          # History-Buffer pro Zelle in Frames (min. 2, empfohlen 4–8)
KINEMATIC_EWMA_ALPHA: float = 0.6  # EWMA-Faktor: 0.01=gleichgewichtet · 0.99=nur neuester Frame

# B231: Mindest-Centroid-Displacement je History-Intervall (skalierte px).
# Intervalle mit kleinerer Verschiebung tragen verrauschte Richtung und werden
# aus der EWMA-Mittelung ausgeschlossen. 0.0 = Filter AUS (= Verhalten vor B231).
# Bleiben nach Filterung 0 Intervalle -> ungefilterter Fallback (kein Regress).
# Runtime-ueberschreibbar via runtime_overrides.json (Admin-Panel).
KINEMATIC_MIN_INTERVAL_DISP_PX: float = 0.0

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
# B273: Max. Abweichung (Grad) zwischen der zuletzt beobachteten Zugrichtung
# (direction_deg) und einem einzelnen ML-Forecast-Horizontpunkt. Da jeder
# Horizont (10/20/30/40/60 min) ein unabhaengig trainiertes Modell hat (P58),
# kann ohne diese Pruefung ein Horizont fast entgegengesetzt zur Zugrichtung
# liegen, obwohl die implizite Geschwindigkeit unter MAX_CELL_SPEED_KMH bleibt
# ("Zickzack"-Pfade). Nur relevant fuer mode="ml" in validate_forecast_point();
# kinematische Forecasts sind reine Geradenextrapolation und nicht betroffen.
ML_FORECAST_MAX_BEARING_DEVIATION_DEG: float = 90.0

# Steuerstrom-Abgleich fuer kinematische Forecasts. Windrichtungen aus Wetterdaten
# sind meteorologisch (FROM); prediction.py wandelt sie in Zellbewegung (TO).
STEERING_BLEND_ENABLED: bool = True
STEERING_BLEND_MAX_ACTIVE_FRAMES: int = 3
STEERING_BLEND_MIN_ANGLE_DEG: float = 60.0
STEERING_BLEND_WEIGHT: float = 0.35
STEERING_BLEND_MIN_WIND_KMH: float = 10.0


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
# 1800 s = 30 Minuten.
INACTIVE_CELL_TRACK_DURATION_S: int = 1800

# Stille Regen-Weiterverfolgung ehemals aktiver Zellen anhand des bereits
# geladenen ARSO-Radarbilds (keine Zusatzrequests). Runtime-overridable.
INACTIVE_RAIN_SUPPORT_ENABLED: bool = True
INACTIVE_RAIN_SUPPORT_MIN_PIXELS: int = 30
INACTIVE_RAIN_SUPPORT_RADIUS_PX: int = 60
INACTIVE_RAIN_SUPPORT_MIN_OVERLAP: float = 0.05
INACTIVE_RAIN_SUPPORT_MAX_DISTANCE_PX: int = 90

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
# P58: Ziel-Encoding der ML-Position. "delta" = Verschiebung relativ zur aktuellen
# Position (leichter lernbar, kein Regress zur Karten-Mitte). "absolute" = alte
# Konvention. NICHT runtime-overridable (definiert das Trainingsziel).
ML_TARGET_ENCODING = "delta"
DATASET_SCHEMA_VERSION = "v1"
ML_ALLOW_LEGACY_SAMPLES = False
ML_ALLOW_SCHEMA_MISMATCH = False
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
# ML-Runtime-Gating
# --------------------------------------
# ML-Forecasts dürfen produktiv nur pro Horizont genutzt werden, wenn die
# jüngste verifizierte ML-MAE mindestens so gut ist wie der kinematische Pfad.
ML_RUNTIME_GATING_ENABLED = True
ML_RUNTIME_GATING_MARGIN = 0.0
ML_RUNTIME_MIN_SAMPLES_PER_MODE = 20
# B314: Adaptiver Fallback-Schwellwert fuer das ML-Runtime-Gate in datenarmen Phasen
# (z. B. Schoenwetter mit wenigen Zellen). Wird die Standard-Schwelle
# (ML_RUNTIME_MIN_SAMPLES_PER_MODE) in KEINER Zeile von accuracy_history.jsonl je
# Horizont erreicht, prueft das Gate zusaetzlich gegen diesen niedrigeren Wert, damit
# ML nicht dauerhaft blockiert bleibt, nur weil zu wenige Zellen aufgetreten sind. Der
# bestehende ML_RUNTIME_GATING_MARGIN-Vergleich bleibt zusaetzlich wirksam. 0 = Fallback
# deaktiviert (altes strenges Verhalten). Runtime-ueberschreibbar (Admin-Panel).
ML_RUNTIME_MIN_SAMPLES_FALLBACK = 5
ML_FORCE_KINEMATIC = False

# P52: ML-Shadow-Scoring (Champion/Challenger). ML wird auch bei Kinematik-Gate im
# Schatten mitberechnet+verifiziert, ohne ausgeliefert zu werden -> bricht den Gate-Deadlock.
# False = exakt heutiges Verhalten (kein Schatten). Runtime-ueberschreibbar.
ML_SHADOW_SCORING_ENABLED = True


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

# B295: Maximale Zeitspanne zwischen zwei realen Radarframes (Sekunden), über die
# noch linear interpoliert werden darf, um einen fehlenden Ziel-Frame für die
# Verifikation zu rekonstruieren. Verhindert Interpolation über echte, längere
# Ingest-Lücken hinweg (siehe radar_ingest_gaps.json). Runtime-überschreibbar
# via runtime_overrides.json (VERIFICATION_INTERPOLATION_MAX_GAP_S).
VERIFICATION_INTERPOLATION_MAX_GAP_S = 1800

# Maximaler Suchradius für Nearest-Neighbor-Match (km).
# Wenn keine Zelle in diesem Radius → "kein Treffer" geloggt, fließt in Hit-Rate ein.
VERIFICATION_MAX_SEARCH_RADIUS_KM = 25.0

# B302: Zeittoleranz (Sekunden) für die Nearest-Target-Frame-Zuordnung in der
# Closed-Loop-Verifikation. Erlaubt, dass 10/20/40-min-Horizonte auch bei
# gröberem Radar-Takt (z. B. 15 min in Ruhephasen) gegen den nächstgelegenen
# real vorhandenen Radar-Frame verifiziert werden, statt als no_target_frame zu
# gelten. 450 s = 7,5 min = halbes 15-min-Intervall. Runtime-überschreibbar via
# runtime_overrides.json (Admin-Panel).
VERIFICATION_NEAREST_FRAME_TOLERANCE_S = 450

# B228: Strenge Akzeptanzschwelle fuer Nearest-Neighbor-Matches (km).
# NN-Treffer (kein ID-/cell_id-Match) jenseits dieser Distanz gelten als
# Fehlzuordnung und fliessen NICHT in MAE/Drift ein (Bucket "nn_rejected").
# ID-/cell_id-Treffer bleiben distanzunabhaengig gueltig (Lineage-Kontinuitaet).
# Runtime-ueberschreibbar via runtime_overrides.json (VERIFICATION_NN_MAX_MATCH_KM).
VERIFICATION_NN_MAX_MATCH_KM = 10.0

# B279/B296: horizontabhängige NN-Maxdistanz (enger bei kurzen, weiter bei
# langen Horizonten). Harte Obergrenze bleibt VERIFICATION_NN_MAX_MATCH_KM.
# B296: h30/h40/h60 verschärft — Datenbefund (Export 2026-07-04, Zelle
# WX-20260703-0002) zeigte akzeptierte NN-Treffer von 5.0-7.3 km, obwohl das
# Qualitätsziel dieser Horizonte nur 1.0-2.0 km ist (drift_status.json
# quality_target_by_horizon). Neue Werte ~2.5-3x Zielwert. h10/h20 unverändert,
# da dort MAE bereits im Ziel liegt. Runtime-überschreibbar via
# runtime_overrides.json (VERIFICATION_NN_MAX_MATCH_KM).
VERIFICATION_NN_MAX_MATCH_KM_BY_HORIZON = {
    "10": 4.0, "20": 6.0, "30": 3.0, "40": 4.0, "60": 5.0,
}

# B247: Maximale implizite Ist-Geschwindigkeit für einen gültigen Verifikations-Match (km/h).
# Actual-Speed = haversine(Origin, Actual) / horizon_min * 60. Überschreitet ein ID-/NN-Match
# diesen Wert, wird er als id_lost/nn_rejected gewertet und der nächstbessere Kandidat gesucht.
# Physikalisch: Gewitterzellen bewegen sich < MAX_CELL_SPEED_KMH. 120 km/h ist konservativ.
# Runtime-überschreibbar via runtime_overrides.json (VERIFICATION_MATCH_MAX_ACTUAL_SPEED_KMH).
VERIFICATION_MATCH_MAX_ACTUAL_SPEED_KMH: float = 120.0

# B247: Mindest-core_ratio des gematchten Zielobjekts für einen gültigen ID-/NN-Match,
# wenn das Origin-Objekt konvektiv ist (core_ratio > 0). 0.0 = Anforderung deaktiviert.
# >0 = nur konvektive Zellen (Rot/Violett ≥54 dBZ) dürfen gematcht werden.
# Verhindert Match auf rein stratiforme Zellen nach Merge-Auflösung.
# Runtime-überschreibbar via runtime_overrides.json (VERIFICATION_CORE_MIN_RATIO).
VERIFICATION_CORE_MIN_RATIO: float = 0.0

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
    "hydro": "train_data/hydro/live/",              # Kärnten Hydro-Livedaten
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

# B253: Mindest-Konfidenz der Wolkenhöhe, damit eine Zelle als pre_cb/cb/severe_cb
# eingestuft werden darf. Bei cloud_height_source="default_fallback" liefert
# _height_context() 0.35; echte Messung liefert 0.65. Default 0.5 = nur
# bei echter Messung (0.65 > 0.5) wird pre_cb freigegeben.
# Runtime-überschreibbar; regressionsneutral wenn auf 0.0 gesetzt.
IR_CB_MIN_HEIGHT_CONFIDENCE: float = 0.5

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
# B259: Maximaler zulässiger Skew zwischen ARSO-KML-Timestamp und Systemzeit (min).
# Übersteigt die Differenz diesen Wert, wird die Systemzeit als Dateiname-Basis
# verwendet (verhindert Überschreiben einer einzigen Datei bei eingefrorenem Timestamp).
# 0 = Skew-Check deaktiviert.
RADAR_TIMESTAMP_MAX_SKEW_MIN: float = 30.0


# Mehrstufige IR-Frühphasen-/CB-Vorläufer-Erkennung (runtime-überschreibbar)
IR_WATCH_ENABLED = True
IR_PUBLIC_WATCH_VISIBLE = True
IR_WATCH_BT_THRESHOLD_K = 245.0
IR_PRE_CB_BT_THRESHOLD_K = 238.0
IR_CB_BT_THRESHOLD_K = 230.0
IR_WATCH_CLOUD_HEIGHT_MIN_M = 6500.0
IR_PRE_CB_CLOUD_HEIGHT_MIN_M = 7500.0
IR_CB_CLOUD_HEIGHT_MIN_M = 9000.0
IR_SEVERE_CB_CLOUD_HEIGHT_MIN_M = 11000.0
IR_WATCH_MIN_CELL_AREA_PX = 80
IR_PRE_CB_MIN_CELL_AREA_PX = 150
IR_CB_MIN_CELL_AREA_PX = 300
IR_WATCH_MIN_SCORE = 0.45
IR_PRE_CB_MIN_SCORE = 0.60
IR_CB_MIN_SCORE = 0.75
IR_CLOUD_HEIGHT_GROWTH_M_PER_MIN_MIN = 60.0
IR_BT_COOLING_K_PER_MIN_MIN = -0.15
IR_AREA_GROWTH_PX_PER_MIN_MIN = 2.0
IR_MAX_DATA_AGE_MIN = 25.0
IR_WATCH_MAX_PUBLIC_AGE_MIN = 20.0
IR_REQUIRE_CONVECTIVE_SIGNAL_FOR_PUBLIC = True
IR_REQUIRE_COOLING_OR_GROWTH_FOR_WATCH = True

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
# B256: Maximale Zeichenzahl für body_json/body_text in api_call_counts.jsonl.
# Überschreitung → Eintrag gekürzt + "truncated": true.
# 0 = keine Begrenzung (nicht empfohlen: unkontrolliertes Wachstum).
LOG_API_RESPONSE_MAX_CHARS: int = 4000
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
    # B248: externe API-Responses als Debug-Archiv; kurze Retention um Disk-Druck auf Pi 5 zu begrenzen.
    # 2079 Dateien/Tag × ~2 KB = ~4 MB/Tag unkomprimiert; 2 Tage reichen für Debug-Exports.
    "train_data/external_responses/": 2,
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
    # B248: externe API-Response-Logs (2079 Dateien/Tag; 2 Tage Retention via Override oben).
    "train_data/external_responses/",
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

# --------------------------------------
# Hydrologie / Hydro-Impact
# --------------------------------------
HYDRO_ENABLED = True
HYDRO_STATIC_DIR = "train_data/hydro/static"
HYDRO_LIVE_DIR = "train_data/hydro/live"
HYDRO_IMPACT_DIR = "train_data/hydro/impact"
HYDRO_STATIONS_URL = "https://info.ktn.gv.at/asp/hydro/daten/json/hdkaernten_abfluss_lite.json"
HYDRO_API_TTL_SECONDS = 600
HYDRO_MIN_OVERLAP_AREA_KM2 = 1.0
HYDRO_MIN_CELL_OVERLAP_RATIO = 0.05
HYDRO_MIN_OVERLAP_RATIO_CELL = HYDRO_MIN_CELL_OVERLAP_RATIO
HYDRO_MIN_DURATION_MIN = 5
HYDRO_RELEVANT_INTENSITIES = ["strong", "severe", "extreme", "rot", "violett", "red", "purple", "heavy"]
HYDRO_DEFAULT_LAG_MIN = [20, 180]
HYDRO_LAG_WINDOW_MIN = [20, 180]
HYDRO_VERIFY_MIN_DELTA_Q_M3S = 0.2
HYDRO_VERIFY_MIN_DELTA_W_CM = 5
HYDRO_VERIFY_MIN_RELATIVE_DELTA_PCT = 10
HYDRO_VERIFY_MAX_GAP_MIN = 90
HYDRO_STATION_OVERRIDES = {}
HYDRO_STATION_OVERRIDES_PATH = "data/config/hydro_station_overrides.json"
HYDRO_STATIC_REQUIRED = False
HYDRO_STATIC_AUTO_DOWNLOAD = True
HYDRO_STATIC_AUTO_INSTALL = True
HYDRO_STATIC_DOWNLOAD_TTL_DAYS = 365
HYDRO_STATIC_DOWNLOAD_DIR = "train_data/hydro/static/source/_downloads"
HYDRO_DRAINAGEBASIN_GDB_URL = "https://inspire.lfrz.gv.at/000801/ds/AT_DRAINAGEBASIN_GDB.zip"
HYDRO_FLOWLINES_GDB_URL = "https://inspire.lfrz.gv.at/000801/ds/AT_WATERCOURSELINK_GDB.zip"
HYDRO_STATIC_BASINS_URL = HYDRO_DRAINAGEBASIN_GDB_URL
HYDRO_STATIC_FLOWLINES_URL = HYDRO_FLOWLINES_GDB_URL
HYDRO_STATIC_WATERCOURSE_URL = "https://inspire.lfrz.gv.at/000801/ds/AT_WATERCOURSE_GML.zip"
HYDRO_STATIC_BBOX = BBOX_KAERNTEN_EXTENDED

HYDRO_FORECAST_IMPACT_ENABLED = False
HYDRO_FORECAST_HORIZONS_MIN = [10, 20, 30, 40, 60]
HYDRO_FORECAST_PRECIP_REF_MM = 15.0
HYDRO_FORECAST_MIN_PRECIP_MM_H = 1.0
HYDRO_FORECAST_SINGLE_HIT_DWELL_MIN = 10.0
# P60: Rational-Method-Parameter fuer prognostizierten Abfluss q_forecast (m3/s).
# Abflussbeiwert (Anteil 0..1 des Niederschlags, der oberflaechlich abfliesst) und
# grobe Routing-Daempfung. Konfigurierbar via runtime_overrides.json. Grobe Schaetzung,
# kein Ersatz fuer amtliche Hochwasserwarnungen.
HYDRO_FORECAST_RUNOFF_COEFF = 0.4
HYDRO_FORECAST_ROUTING_ATTENUATION = 1.0
# P63: Pufferradius (km) um den betroffenen Flussabschnitt, in dem Watchlist-Orte als
# betroffen markiert werden.
HYDRO_IMPACT_PLACE_BUFFER_KM = 1.0
HYDRO_MAP_MIN_Q_M3S = 0.0
HYDRO_MAP_MARK_Q_M3S = None
HYDRO_KMZ_INCLUDE_CATCHMENTS = False
# P67a: Q-Trend-Berechnung aus lokaler Hydro-Historie. Runtime-overridable.
HYDRO_TREND_MIN_DELTA_M3S = 0.02
HYDRO_TREND_MIN_DELTA_REL_PCT = 0.03

# Eigenständige Hydro-Flood-ML-Features; strikt getrennt von ML_CELL_FEATURES.
HYDRO_FLOOD_ML_FEATURES = [
    "current_q_m3s", "current_q_missing", "station_q_threshold_m3s",
    "station_q_threshold_missing", "station_q_threshold_source",
    "current_q_ratio_threshold", "current_q_distance_to_threshold_m3s",
    "current_q_above_threshold", "current_q_trend_10min",
    "current_q_trend_30min", "current_q_trend_60min", "q_trend_per_hour",
    "already_rising_flag", "current_data_age_min", "hydro_data_stale",
    "station_lat", "station_lon", "catchment_area_km2",
    "upstream_catchment_count", "impact_eligible", "source_quality",
    "topology_source", "upstream_source_quality",
    "observed_catchment_precip_sum_mm",
    "observed_catchment_precip_max_rate_mm_h",
    "observed_catchment_precip_mean_rate_mm_h",
    "observed_catchment_precip_area_km2", "observed_precip_source_quality",
    "observed_precip_data_age_min", "observed_precip_available",
    "cell_catchment_precip_sum_mm", "cell_catchment_precip_weighted_sum_mm",
    "cell_catchment_count", "cell_catchment_max_intensity",
    "cell_catchment_max_core_ratio", "cell_catchment_area_km2_sum",
    "cell_catchment_overlap_area_km2_sum", "cell_catchment_overlap_ratio_max",
    "cell_catchment_overlap_ratio_weighted",
    "effective_catchment_precip_sum_mm",
    "effective_catchment_precip_weighted_sum_mm",
    "effective_catchment_precip_max_rate_mm_h",
    "effective_catchment_precip_mean_rate_mm_h",
    "effective_precip_source_type", "effective_precip_source_quality",
    "effective_precip_is_proxy", "effective_precip_missing",
]

# --- P68: Signierte Bias-Korrektur des kinematischen Fallbacks ---
FORECAST_BIAS_CORRECTION_ENABLED = False          # Default AUS, admin-umschaltbar
FORECAST_BIAS_MIN_SAMPLES = 20                    # Mindest-Samples je Horizont für Korrektur
FORECAST_BIAS_MAX_OFFSET_KM = 2.0                 # harte Obergrenze für Positions-Korrektur
FORECAST_BIAS_MAX_SPEED_FACTOR = 1.3              # harte Obergrenze für Speed-Korrekturfaktor (max +30%)

# --- B307: 2nd-Order-Beschleunigungsterm der kinematischen Extrapolation ---
KINEMATIC_ACCELERATION_ENABLED = False            # Default AUS, admin-umschaltbar
KINEMATIC_ACCEL_MAX_FRACTION = 0.3                # Beschleunigungsanteil <= 30% der linearen Verschiebung

# --- B278: Verifikations-Coverage-Warnschwelle ---
MIN_VERIFICATION_COVERAGE_RATIO = 0.5


# --- P70: Horizontabhängige Qualitätsziele. Die <=30-Min-Vorgabe (<1km) ist
# durch die Zieldefinition FEST vorgegeben und NICHT admin-änderbar. Nur
# zusätzliche Horizonte (h40/h60) sind administrierbar konfigurierbar. ---
QUALITY_TARGET_MAE_KM_FIXED = {
    "10": 1.0, "20": 1.0, "30": 1.0,
}
QUALITY_TARGET_MAE_KM_CONFIGURABLE_DEFAULT = {
    "40": 1.5, "60": 2.0,
}

# --- B292: Steering-Seed für brandneue Zellen ohne Bewegungshistorie ---
# Anteil des 700/500-hPa-Steuerstroms, der als initiale Zuggeschwindigkeit
# angesetzt wird, wenn eine Zelle im ersten Frame (kalman_only) sonst 0 km/h
# prognostiziert bekaeme. Konvektive Zellen ziehen typisch mit ~50-70% des
# Steuerstroms; konservativer Default 0.6.
STEERING_NEW_CELL_SPEED_FRAC = 0.6

# --- P71: Richtungs-/Geschwindigkeits-Drift-Schwellwerte (admin-editierbar) ---
# Ausgewertet auf Kurzhorizonten (<= DRIFT_SHORT_HORIZON_MAX_MIN). Alarm, wenn
# der p90-Wert ueber dem Schwellwert liegt UND genug Messpunkte vorliegen.
DRIFT_DIRECTION_P90_MAX_DEG = 90.0      # p90-Richtungsfehler-Alarmschwelle
DRIFT_SPEED_P90_MAX_KMH = 30.0          # p90-Geschwindigkeitsfehler-Alarmschwelle
DRIFT_DIRECTION_SPEED_MIN_POINTS = 20   # Mindest-Samples je Horizont fuer Auswertung
# --- B293: Diagnose-Status-Gating bei kleiner Stichprobe ---
DIAGNOSIS_MIN_VERIFIED_FORECASTS = 30      # darunter: insufficient_data
DIAGNOSIS_MAX_MISSING_TARGET_RATIO = 0.4   # darüber: insufficient_data
