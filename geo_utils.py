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
            debug_log(f"KML LatLonBox gefunden: N={north}, S={south}, E={east}, W={west}")
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

    img_path = "data/latest.png"
    try:
        img = cv2.imread(img_path)
        img_height, img_width = img.shape[:2]
    except:
        img_width, img_height = 512, 512  # fallback

    lon = kml_bounds["west"] + (x / img_width) * (kml_bounds["east"] - kml_bounds["west"])
    lat = kml_bounds["north"] - (y / img_height) * (kml_bounds["north"] - kml_bounds["south"])
    return lat, lon

def geo_to_pixel(lat, lon):
    global kml_bounds
    if not kml_bounds:
        parse_kml_bounds()
    if not kml_bounds:
        return 0, 0

    img_path = "data/latest.png"
    try:
        img = cv2.imread(img_path)
        img_height, img_width = img.shape[:2]
    except:
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

def crop_and_upscale_to_bbox(image_path, bbox, upscale=3.0):
    """
    Schneidet das Bild basierend auf der geografischen BBOX zu und skaliert es anschließend.
    Speichert das Ergebnis in data/radar/ mit gleichem Namen.
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

    # Speichern in data/radar mit gleichem Dateinamen
    os.makedirs("data/radar", exist_ok=True)
    filename = os.path.basename(image_path)
    save_path = os.path.join("data/radar", filename)
    cv2.imwrite(save_path, scaled)

    # Update für spätere Geo-Referenzierung
    kml_bounds["img_width"] = scaled.shape[1]
    kml_bounds["img_height"] = scaled.shape[0]
    kml_bounds["pixel_offset_x"] = x1
    kml_bounds["pixel_offset_y"] = y1
    kml_bounds["upscale"] = upscale

    return scaled

