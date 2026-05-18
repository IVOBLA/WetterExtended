# cloud_height_from_eumetview.py

import os
import requests
import rasterio
import numpy as np
import json
from datetime import datetime
from glob import glob
from rasterio.transform import rowcol
from xml.etree import ElementTree as ET
from config import (
    BBOX_KAERNTEN_EXTENDED,
    WIDTH,
    HEIGHT,
    LAYER,
    FORMAT,
    CRS,
    SAVE_DIR,
    LAPSE_RATE
)
from api_cache import cache_key, cache_get, cache_set, get_ttl

# Bounding Box vorbereiten
BBOX = [
    BBOX_KAERNTEN_EXTENDED["south"],
    BBOX_KAERNTEN_EXTENDED["west"],
    BBOX_KAERNTEN_EXTENDED["north"],
    BBOX_KAERNTEN_EXTENDED["east"]
]

LAST_TIMESTAMP_FILE = os.path.join(SAVE_DIR, "last_cloud_top_time.txt")
os.makedirs(SAVE_DIR, exist_ok=True)

def get_latest_wms_time():
    """
    Liest den aktuellen WMS-Timestamp aus EUMETView-Capabilities.
    Cache (10 Min) — MSG Full Earth Scan aktualisiert nur alle 15 Min.
    """
    url = "https://view.eumetsat.int/geoserver/wms?service=WMS&request=GetCapabilities&version=1.3.0"

    # Cache-Lookup
    ck = cache_key("eumetview:capabilities", LAYER)
    cached_ts = cache_get(ck, ttl_seconds=get_ttl("eumetview_capabilities", 600))
    if cached_ts is not None:
        print(f"[DEBUG] WMS-Timestamp aus Cache: {cached_ts}")
        return cached_ts

    try:
        r = requests.get(url, timeout=10)
        try:
            from debug_utils import log_api_call
            log_api_call("eumetview_wms", url=url, status_code=r.status_code)
        except Exception:
            pass
        if r.ok:
            root = ET.fromstring(r.content)
            for elem in root.iter():
                if elem.tag.endswith('Dimension') and elem.attrib.get('name') == 'time':
                    ts = elem.attrib.get('default')
                    print(f"[DEBUG] WMS-Timestamp gefunden: {ts}")
                    cache_set(ck, ts)
                    return ts
    except Exception as e:
        print(f"[FEHLER] GetCapabilities fehlgeschlagen: {e}")
        try:
            from debug_utils import log_api_failure
            log_api_failure("EUMETView-WMS", url,
                            f"{type(e).__name__}: {e}", fallback_used=True)
        except Exception:
            pass
    return None

def wms_to_filename_timestamp(wms_time: str) -> str:
    dt = datetime.strptime(wms_time, "%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%d_%H-%M-%S")

def read_last_timestamp():
    if os.path.exists(LAST_TIMESTAMP_FILE):
        with open(LAST_TIMESTAMP_FILE, "r") as f:
            return f.read().strip()
    return None

def write_last_timestamp(ts):
    with open(LAST_TIMESTAMP_FILE, "w") as f:
        f.write(ts)
    print(f"[DEBUG] Timestamp gespeichert: {ts}")

def build_tiff_url(timestamp):
    bbox_str = f"{BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]}"
    return (
        f"https://view.eumetsat.int/geoserver/wms?"
        f"service=WMS&version=1.3.0&request=GetMap"
        f"&layers={LAYER}&styles=&format={FORMAT}&transparent=true"
        f"&crs={CRS}&bbox={bbox_str}&width={WIDTH}&height={HEIGHT}"
        f"&time={timestamp}"
    )

def get_adaptive_nan_threshold(utc_hour: int) -> float:
    if 6 <= utc_hour <= 18:
        return 150.0
    elif 3 <= utc_hour < 6 or 18 < utc_hour <= 21:
        return 140.0
    else:
        return 130.0

def find_matching_weather_file(timestamp_wms_str: str, weather_dir: str) -> str | None:
    ts_target = datetime.strptime(timestamp_wms_str, "%Y-%m-%dT%H:%M:%SZ")
    candidates = glob(os.path.join(weather_dir, "*.json"))

    best_match = None
    min_diff = None

    for path in candidates:
        try:
            fname = os.path.basename(path).replace(".json", "")
            fname = fname.replace("wetter_", "")
            ts = datetime.strptime(fname, "%Y-%m-%d_%H-%M-%S")
            if ts <= ts_target:
                diff = (ts_target - ts).total_seconds()
                if min_diff is None or diff < min_diff:
                    best_match = path
                    min_diff = diff
        except:
            continue

    return best_match

def assign_cloud_top_height(objects: list, weather_data: list | None = None, timestamp: str | None = None) -> list:
    timestamp_wms = get_latest_wms_time()
    if not timestamp_wms:
        print("[FEHLER] Kein gültiger WMS-Timestamp.")
        for obj in objects:
            obj["cloud_top_height_msl"] = -1.0
            obj["cloud_height_missing"] = 1.0
        return objects

    timestamp_file = wms_to_filename_timestamp(timestamp_wms)
    print(f"[INFO] Starte Wolkenhöhenzuweisung für {timestamp_file}...")

    if read_last_timestamp() == timestamp_wms:
        print("[INFO] Kein neues TIFF verfügbar – bestehende Wolkenhöhenwerte bleiben erhalten.")
        return objects

    tif_url = build_tiff_url(timestamp_wms)
    tif_path = os.path.join(SAVE_DIR, f"ir108_{timestamp_file.replace('-', '').replace('_', '')}.tif")
    print(f"[DEBUG] Lade TIFF von {tif_url}")

    try:
        r = requests.get(tif_url, timeout=20)
        try:
            from debug_utils import log_api_call
            log_api_call("eumetview_wms", url=tif_url, status_code=r.status_code)
        except Exception:
            pass
        r.raise_for_status()
        with open(tif_path, "wb") as f:
            f.write(r.content)
        print(f"[OK] TIFF gespeichert: {tif_path}")
    except Exception as e:
        print(f"[FEHLER] TIFF konnte nicht geladen werden: {e}")
        for obj in objects:
            obj["cloud_top_height_msl"] = -1.0
            obj["cloud_height_missing"] = 1.0
        return objects

    from config import SAVE_PATHS as _SP
    weather_path = find_matching_weather_file(
        timestamp_wms,
        _SP["weather"].rstrip("/")
    )
    T_surface = 290.15
    altitude_m = 600.0
    if weather_data:
        try:
            stations = weather_data if isinstance(weather_data, list) else [weather_data]
            tl_values = [
                float(s["TL"]) for s in stations
                if isinstance(s, dict) and s.get("TL") not in (None, 0)
            ]
            if tl_values:
                mean_temp = sum(tl_values) / len(tl_values)
                T_surface = mean_temp + 273.15
        except Exception as e:
            print(f"[WARNUNG] Übergebene Wetterdaten konnten nicht gelesen werden: {e}")
    elif weather_path:
        try:
            with open(weather_path) as f:
                raw = json.load(f)
            # weather_api.py liefert eine Liste von Stationsdicts
            stations = raw if isinstance(raw, list) else [raw]
            # Mittelwert TL (Lufttemperatur) über alle Stationen bilden
            tl_values = [
                float(s["TL"]) for s in stations
                if isinstance(s, dict) and s.get("TL") not in (None, 0)
            ]
            if tl_values:
                mean_temp = sum(tl_values) / len(tl_values)
                T_surface = mean_temp + 273.15
            # Standardhöhe beibehalten (600 m für Kärnten)
            altitude_m = 600.0
        except Exception as e:
            print(f"[WARNUNG] Wetterdaten-Parsing fehlgeschlagen: {e}")
    else:
        print(f"[WARNUNG] Keine passende Wetterdatei gefunden.")

    pipeline_ts = timestamp if timestamp else timestamp_file
    json_path = os.path.join(SAVE_DIR, f"cloud_height_{pipeline_ts}.json")

    try:
        with rasterio.open(tif_path) as src:
            bt = src.read(1).astype(np.float32)
            threshold = get_adaptive_nan_threshold(datetime.utcnow().hour)
            bt[bt < threshold] = np.nan
            height_km = (T_surface - bt) / LAPSE_RATE
            height_msl = altitude_m + (height_km * 1000)

            with open(json_path, "w") as f:
                json.dump({
                    "bbox": BBOX,
                    "unit": "m MSL",
                    "surface_temperature_K": round(T_surface, 2),
                    "station_altitude_m": round(altitude_m, 1),
                    "grid": height_msl.tolist()
                }, f)
            print(f"[OK] Wolkenhöhen-Raster gespeichert: {json_path}")

            for obj in objects:
                lat, lon = obj.get("lat"), obj.get("lon")
                if lat is not None and lon is not None:
                    try:
                        row, col = rowcol(src.transform, lon, lat)
                        value = height_msl[row, col]
                        if np.isnan(value):
                            raise ValueError("NaN")
                        obj["cloud_top_height_msl"] = round(float(value), 1)
                        obj["cloud_height_missing"] = 0.0
                        obj["cloud_top_height_timestamp"] = timestamp_file
                    except:
                        obj["cloud_top_height_msl"] = -1.0
                        obj["cloud_height_missing"] = 1.0
    except Exception as e:
        print(f"[FEHLER] TIFF-Verarbeitung fehlgeschlagen: {e}")
        for obj in objects:
            obj["cloud_top_height_msl"] = -1.0
            obj["cloud_height_missing"] = 1.0

    write_last_timestamp(timestamp_wms)
    return objects
