# geo_utils.py

import os
import cv2
from xml.etree import ElementTree as ET
from debug_utils import debug_log

LAT, LON = 46.05, 14.51  # Fallback-Koordinaten
kml_bounds = {}

def parse_kml_bounds():
    global kml_bounds
    kml_path = "data/latest.kml"

    if not os.path.exists(kml_path):
        debug_log("KML Datei fehlt für Georeferenzierung.")
        return

    try:
        tree = ET.parse(kml_path)
        ns = {'kml': 'http://www.opengis.net/kml/2.2'}
        for overlay in tree.findall(".//kml:GroundOverlay", ns):
            box = overlay.find("kml:LatLonBox", ns)
            north = float(box.find("kml:north", ns).text)
            south = float(box.find("kml:south", ns).text)
            east = float(box.find("kml:east", ns).text)
            west = float(box.find("kml:west", ns).text)
            kml_bounds = {
                "north": north, "south": south,
                "east": east, "west": west
            }
            # Originaldimensionen einmalig einlesen und cachen.
            # pixel_to_geo liest diese Werte direkt statt cv2.imread bei jedem Aufruf.
            _img_check = cv2.imread("data/latest.png")
            if _img_check is not None:
                kml_bounds["orig_height"], kml_bounds["orig_width"] = _img_check.shape[:2]
                debug_log(
                    f"KML LatLonBox: N={north}, S={south}, E={east}, W={west} "
                    f"| Bilddims: {kml_bounds['orig_width']}x{kml_bounds['orig_height']}px"
                )
            else:
                debug_log(
                    f"KML LatLonBox: N={north}, S={south}, E={east}, W={west} "
                    f"| WARNUNG: data/latest.png nicht lesbar — orig_width/height noch unbekannt"
                )
            return
    except Exception as e:
        debug_log(f"KML Parsing Fehler: {e}")

def pixel_to_geo(x, y):
    global kml_bounds
    if not kml_bounds:
        parse_kml_bounds()
    if not kml_bounds:
        return LAT, LON

    # Korrektur für zugeschnittenes & skaliertes Bild
    x = (x / kml_bounds.get("upscale", 1.0)) + kml_bounds.get("pixel_offset_x", 0)
    y = (y / kml_bounds.get("upscale", 1.0)) + kml_bounds.get("pixel_offset_y", 0)

    # Gecachte Originaldimensionen verwenden — kein cv2.imread bei jedem Aufruf.
    # cv2.imread gibt None zurück (keine Exception) wenn Datei fehlt →
    # None.shape → AttributeError → 512×512-Fallback → 125km Positionsfehler.
    img_width  = kml_bounds.get("orig_width")
    img_height = kml_bounds.get("orig_height")
    if img_width is None or img_height is None:
        # Einmalig nachlesen (z.B. direkt nach parse_kml_bounds ohne crop)
        _img_fallback = cv2.imread("data/latest.png")
        if _img_fallback is not None:
            img_height, img_width = _img_fallback.shape[:2]
            kml_bounds["orig_width"] = img_width
            kml_bounds["orig_height"] = img_height
        else:
            debug_log("[GEO] WARNUNG: data/latest.png nicht lesbar — Fallback 512x512 aktiv, Positionen ungenau!")
            img_width, img_height = 512, 512

    lon = kml_bounds["west"] + (x / img_width) * (kml_bounds["east"] - kml_bounds["west"])
    lat = kml_bounds["north"] - (y / img_height) * (kml_bounds["north"] - kml_bounds["south"])
    return lat, lon

def geo_to_pixel(lat, lon):
    global kml_bounds
    if not kml_bounds:
        parse_kml_bounds()
    if not kml_bounds:
        return 0, 0

    img_width  = kml_bounds.get("orig_width")
    img_height = kml_bounds.get("orig_height")
    if img_width is None or img_height is None:
        _img_fallback = cv2.imread("data/latest.png")
        if _img_fallback is not None:
            img_height, img_width = _img_fallback.shape[:2]
            kml_bounds["orig_width"] = img_width
            kml_bounds["orig_height"] = img_height
        else:
            img_width, img_height = 512, 512

    x = int((lon - kml_bounds["west"]) / (kml_bounds["east"] - kml_bounds["west"]) * img_width)
    y = int((kml_bounds["north"] - lat) / (kml_bounds["north"] - kml_bounds["south"]) * img_height)

    # Anpassung für zugeschnittenes & skaliertes Bild
    x = int((x - kml_bounds.get("pixel_offset_x", 0)) * kml_bounds.get("upscale", 1.0))
    y = int((y - kml_bounds.get("pixel_offset_y", 0)) * kml_bounds.get("upscale", 1.0))
    return x, y

def get_roi_from_bbox(bbox, image_width=800, image_height=600):
    parse_kml_bounds()
    x1, y2 = geo_to_pixel(bbox["south"], bbox["west"])
    x2, y1 = geo_to_pixel(bbox["north"], bbox["east"])
    return {
        "x1": min(x1, x2),
        "x2": max(x1, x2),
        "y1": min(y1, y2),
        "y2": max(y1, y2)
    }

def crop_and_upscale_to_bbox(image_path, bbox, upscale=3.0, save_path=None):
    """
    Schneidet das Bild basierend auf der geografischen BBOX zu und skaliert es anschließend.
    Optional: Speichert das Ergebnis, wenn save_path übergeben wird.
    """
    global kml_bounds
    parse_kml_bounds()

    img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(f"Bild nicht gefunden: {image_path}")
    original_height, original_width = img.shape[:2]

    x1, y2 = geo_to_pixel(bbox["south"], bbox["west"])
    x2, y1 = geo_to_pixel(bbox["north"], bbox["east"])
    x1, x2 = sorted((x1, x2))
    y1, y2 = sorted((y1, y2))

    cropped = img[y1:y2, x1:x2]
    scaled = cv2.resize(cropped, (0, 0), fx=upscale, fy=upscale, interpolation=cv2.INTER_NEAREST)

    # Optional speichern
    if save_path:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        cv2.imwrite(save_path, scaled)
        debug_log(f"[DEBUG] Hochskaliertes Bild gespeichert: {save_path}")

    # Update für Geo-Referenzierung
    kml_bounds["img_width"] = scaled.shape[1]  # skaliertes Bild (Referenz)
    kml_bounds["img_height"] = scaled.shape[0]
    kml_bounds["orig_width"] = original_width  # Original ARSO-Dims für pixel_to_geo
    kml_bounds["orig_height"] = original_height
    kml_bounds["pixel_offset_x"] = x1
    kml_bounds["pixel_offset_y"] = y1
    kml_bounds["upscale"] = upscale

    return scaled


def haversine_distance(lat1: float, lon1: float,
                       lat2: float, lon2: float) -> float:
    """Gibt die Distanz in km zwischen zwei WGS84-Koordinaten zurück."""
    import math
    R = 6371.0088
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))

def geo_to_pixel_in_bbox(lat: float, lon: float,
                          bbox: dict,
                          img_width: int,
                          img_height: int) -> tuple:
    """
    Wandelt (lat, lon) in Pixelkoordinaten des verarbeiteten (gecropten +
    upgeskalten) Radarbilds um. Inverse von pixel_to_geo() für das
    BBOX-gecropte Bild.

    bbox : {"north": float, "south": float, "east": float, "west": float}
           == BBOX_KAERNTEN_EXTENDED
    img_width, img_height : Dimensionen des verarbeiteten Bildes
                            (nach crop_and_upscale_to_bbox())
    Rückgabe: (px_x, px_y) als int, geclampt auf [0, img_width/height - 1]
    """
    north = float(bbox["north"])
    south = float(bbox["south"])
    east  = float(bbox["east"])
    west  = float(bbox["west"])

    x = int((lon  - west)  / (east  - west)  * img_width)
    y = int((north - lat)  / (north - south) * img_height)
    x = max(0, min(img_width  - 1, x))
    y = max(0, min(img_height - 1, y))
    return x, y
