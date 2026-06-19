# geo_utils.py

import os

try:
    import cv2
except Exception:
    cv2 = None
from xml.etree import ElementTree as ET
from debug_utils import debug_log

LAT, LON = 46.05, 14.51  # Fallback-Koordinaten
kml_bounds = {}
_FALLBACK_IMG_WIDTH = 800
_FALLBACK_IMG_HEIGHT = 600


def _safe_imread(path):
    """Liest ein Bild nur, wenn cv2 echt/nutzbar ist; sonst None."""
    imread = getattr(cv2, "imread", None)
    if imread is None:
        debug_log(f"[GEO] WARNUNG: cv2.imread nicht verfügbar — Bild kann nicht gelesen werden: {path}")
        return None
    try:
        return imread(path)
    except Exception as exc:
        debug_log(f"[GEO] WARNUNG: cv2.imread fehlgeschlagen für {path}: {exc}")
        return None


def _image_dimensions_or_fallback(path="data/latest.png"):
    img_width = kml_bounds.get("orig_width")
    img_height = kml_bounds.get("orig_height")
    if img_width is not None and img_height is not None:
        return img_width, img_height

    img = _safe_imread(path)
    if img is not None:
        img_height, img_width = img.shape[:2]
        kml_bounds["orig_width"] = img_width
        kml_bounds["orig_height"] = img_height
        return img_width, img_height

    debug_log(
        f"[GEO] WARNUNG: {path} nicht lesbar oder cv2 nicht nutzbar — "
        f"Fallback {_FALLBACK_IMG_WIDTH}x{_FALLBACK_IMG_HEIGHT} aktiv, Positionen ungenau!"
    )
    return _FALLBACK_IMG_WIDTH, _FALLBACK_IMG_HEIGHT

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
            _img_check = _safe_imread("data/latest.png")
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

def _geo_to_pixel_raw(lat, lon, bounds, width, height):
    x = int((lon - bounds["west"]) / (bounds["east"] - bounds["west"]) * width)
    y = int((bounds["north"] - lat) / (bounds["north"] - bounds["south"]) * height)
    return x, y


def _pixel_to_geo_raw(x, y, bounds, width, height):
    lon = bounds["west"] + (x / width) * (bounds["east"] - bounds["west"])
    lat = bounds["north"] - (y / height) * (bounds["north"] - bounds["south"])
    return lat, lon


def _ensure_processed_transform():
    """Initialisiert die Crop+Upscale-Transformation für öffentliche Pixel-APIs."""
    global kml_bounds
    if not kml_bounds:
        parse_kml_bounds()
    if not kml_bounds:
        try:
            from config import BBOX_KAERNTEN_EXTENDED as _BBOX_DEFAULT
            kml_bounds = dict(_BBOX_DEFAULT)
            debug_log("[GEO] WARNUNG: KML-Bounds fehlen — verwende BBOX_KAERNTEN_EXTENDED als Fallback.")
        except Exception:
            return False

    img_width, img_height = _image_dimensions_or_fallback("data/latest.png")
    kml_bounds["orig_width"] = img_width
    kml_bounds["orig_height"] = img_height

    missing = [
        key for key in ("pixel_offset_x", "pixel_offset_y", "upscale", "img_width", "img_height")
        if key not in kml_bounds
    ]
    if missing:
        try:
            from config import BBOX_KAERNTEN_EXTENDED as _BBOX_DEFAULT, UPSCALE_FACTOR as _UPSCALE_DEFAULT
            x1, y2 = _geo_to_pixel_raw(_BBOX_DEFAULT["south"], _BBOX_DEFAULT["west"], kml_bounds, img_width, img_height)
            x2, y1 = _geo_to_pixel_raw(_BBOX_DEFAULT["north"], _BBOX_DEFAULT["east"], kml_bounds, img_width, img_height)
            x1, x2 = sorted((max(0, x1), min(img_width, x2)))
            y1, y2 = sorted((max(0, y1), min(img_height, y2)))
            upscale = float(_UPSCALE_DEFAULT or 1.0)
            kml_bounds["pixel_offset_x"] = x1
            kml_bounds["pixel_offset_y"] = y1
            kml_bounds["upscale"] = upscale
            kml_bounds["img_width"] = max(0, int((x2 - x1) * upscale))
            kml_bounds["img_height"] = max(0, int((y2 - y1) * upscale))
            debug_log(
                "[GEO] WARNUNG: Verarbeitete Geo-Transformation war nicht initialisiert — "
                "Crop+Upscale-Parameter aus KML/BBOX/Bilddimensionen abgeleitet."
            )
        except Exception as exc:
            debug_log(f"[GEO] WARNUNG: Verarbeitete Geo-Transformation konnte nicht initialisiert werden: {exc}")
            return False
    return True


def pixel_to_geo(x, y):
    if not _ensure_processed_transform():
        return LAT, LON

    raw_x = (float(x) / float(kml_bounds.get("upscale", 1.0))) + float(kml_bounds.get("pixel_offset_x", 0))
    raw_y = (float(y) / float(kml_bounds.get("upscale", 1.0))) + float(kml_bounds.get("pixel_offset_y", 0))
    img_width = int(kml_bounds.get("orig_width") or _FALLBACK_IMG_WIDTH)
    img_height = int(kml_bounds.get("orig_height") or _FALLBACK_IMG_HEIGHT)
    return _pixel_to_geo_raw(raw_x, raw_y, kml_bounds, img_width, img_height)


def geo_to_pixel(lat, lon):
    if not _ensure_processed_transform():
        return 0, 0

    img_width = int(kml_bounds.get("orig_width") or _FALLBACK_IMG_WIDTH)
    img_height = int(kml_bounds.get("orig_height") or _FALLBACK_IMG_HEIGHT)
    raw_x, raw_y = _geo_to_pixel_raw(lat, lon, kml_bounds, img_width, img_height)
    x = int((raw_x - kml_bounds.get("pixel_offset_x", 0)) * kml_bounds.get("upscale", 1.0))
    y = int((raw_y - kml_bounds.get("pixel_offset_y", 0)) * kml_bounds.get("upscale", 1.0))
    return x, y


def get_roi_from_bbox(bbox, image_width=800, image_height=600):
    if not kml_bounds:
        parse_kml_bounds()
    bounds = kml_bounds or bbox
    x1, y2 = _geo_to_pixel_raw(bbox["south"], bbox["west"], bounds, image_width, image_height)
    x2, y1 = _geo_to_pixel_raw(bbox["north"], bbox["east"], bounds, image_width, image_height)
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

    img = _safe_imread(image_path)
    if img is None:
        raise FileNotFoundError(f"Bild nicht gefunden: {image_path}")
    original_height, original_width = img.shape[:2]
    if not kml_bounds:
        kml_bounds = dict(bbox)
        debug_log("[GEO] WARNUNG: KML-Bounds fehlen beim Crop — verwende Ziel-BBOX als Fallback.")

    x1, y2 = _geo_to_pixel_raw(bbox["south"], bbox["west"], kml_bounds, original_width, original_height)
    x2, y1 = _geo_to_pixel_raw(bbox["north"], bbox["east"], kml_bounds, original_width, original_height)
    x1, x2 = sorted((max(0, x1), min(original_width, x2)))
    y1, y2 = sorted((max(0, y1), min(original_height, y2)))

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


def haversine_distance(lat1, lon1, lat2, lon2):
    """Kilometer-Distanz zwischen zwei WGS84-Punkten (kompatibler Test-/Fallback-Helfer)."""
    import math
    r = 6371.0
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dp = math.radians(float(lat2) - float(lat1))
    dl = math.radians(float(lon2) - float(lon1))
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))
