# config.py

# --------------------------------------
# Debugging / Logging
# --------------------------------------

DEBUG_MODE = True  # Globales Flag für Debug-Ausgaben
DEBUG_IMAGE_SAVE = DEBUG_MODE  # Bilder speichern nur bei aktiviertem Debug-Modus

# --------------------------------------
# Geografischer Bereich (Kärnten + Puffer)
# --------------------------------------

BBOX_KAERNTEN_EXTENDEDx = {
    "north": 47.42,
    "south": 44.67,
    "east": 17.44,
    "west": 12.10
}

BBOX_KAERNTEN_EXTENDED = {
    "north": 47.18,
    "south": 46.36,
    "east": 15.20,
    "west": 12.60
}



# ROI (Pixelbereich) – wird bei Start dynamisch gesetzt
ROI = {
    "y1": 50,
    "y2": 1700,
    "x1": 100,
    "x2": 2200
}

# --------------------------------------
# Farbfilter-Konfiguration (für Segmentierung)
# --------------------------------------

FILTER_CONFIG = {
    "allowed_hsv_ranges": [
        ((0, 100, 150), (10, 255, 255)),   # Rot
        ((10, 100, 180), (27, 255, 255)),  # Orange-Gelb
        ((125, 100, 150), (145, 255, 255)) # Violett
    ],
    "min_object_area": 100  # minimale Objektfläche in Pixel
}

# Für Kernerkennung (KI-gestützt, Richtungstracking)
CORE_HSV_RANGES = [
    ([10, 150, 200], [25, 255, 255]),      # Orange
    ([0, 100, 200], [10, 255, 255]),       # Rotbereich 1
    ([160, 100, 200], [180, 255, 255]),    # Rotbereich 2
    ([125, 100, 150], [145, 255, 255])     # Violett
]

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

# --------------------------------------
# Datenquellen
# --------------------------------------

AROME_BASE_URL = "https://dataset.api.hub.geosphere.at/v1/grid/forecast/nwp-v1-1h-2500m"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
LIGHTNING_DATA_URL = "https://www.lightningmaps.org/live_data/geojson/1.json"

# --------------------------------------
# LSTM / ML Konfiguration
# --------------------------------------

LSTM_SEQUENCE_LENGTH = 3
LSTM_NUM_FEATURES = 22
LSTM_IGNORE_FLAG = -1  # Bei fehlenden Werten

# --------------------------------------
# Dateispeicherung (lokale Struktur)
# --------------------------------------

SAVE_PATHS = {
    "radar": "train_data/radar/",
    "objects": "train_data/objects/",
    "weather": "train_data/weather/",
    "wind": "train_data/wind/",
    "cape": "train_data/cape/"
}

MIN_CONTOUR_OVERLAP = 10

MIN_CONTOUR_TOUCH = 5

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