# cloud_height_from_eumetview.py
# Lädt MSG IR108 GeoTIFF von EUMETView (uint8 RGBA-Farbbild),
# kalibriert uint8-Pixelwerte auf Brightness Temperature (Kelvin)
# und berechnet Wolkenhöhe MSL via Temperaturgradient.

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
    LAPSE_RATE,
    EUMETVIEW_BT_MAX_K,
    EUMETVIEW_BT_MIN_K,
    EUMETVIEW_NODATA_PIXEL,
    SAVE_PATHS,
)
from api_cache import cache_key, cache_get, cache_set, get_ttl

# Bounding Box: [south, west, north, east]
BBOX = [
    BBOX_KAERNTEN_EXTENDED["south"],
    BBOX_KAERNTEN_EXTENDED["west"],
    BBOX_KAERNTEN_EXTENDED["north"],
    BBOX_KAERNTEN_EXTENDED["east"],
]

LAST_TIMESTAMP_FILE = os.path.join(SAVE_DIR, "last_cloud_top_time.txt")
os.makedirs(SAVE_DIR, exist_ok=True)


def get_latest_wms_time() -> str | None:
    """
    Liest den aktuellen WMS-Timestamp aus EUMETView GetCapabilities.
    Cache 10 Min (MSG Full Earth Scan aktualisiert alle 15 Min).
    """
    url = (
        "https://view.eumetsat.int/geoserver/wms"
        "?service=WMS&request=GetCapabilities&version=1.3.0"
    )
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
                if elem.tag.endswith("Dimension") and elem.attrib.get("name") == "time":
                    ts = elem.attrib.get("default")
                    if ts:
                        print(f"[DEBUG] WMS-Timestamp gefunden: {ts}")
                        cache_set(ck, ts)
                        return ts
    except Exception as e:
        print(f"[FEHLER] GetCapabilities fehlgeschlagen: {e}")
        try:
            from debug_utils import log_api_failure

            log_api_failure(
                "EUMETView-WMS", url, f"{type(e).__name__}: {e}", fallback_used=True
            )
        except Exception:
            pass
    return None


def wms_to_filename_timestamp(wms_time: str) -> str:
    dt = datetime.strptime(wms_time, "%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%d_%H-%M-%S")


def read_last_timestamp() -> str | None:
    if os.path.exists(LAST_TIMESTAMP_FILE):
        with open(LAST_TIMESTAMP_FILE, "r") as f:
            return f.read().strip()
    return None


def write_last_timestamp(ts: str) -> None:
    with open(LAST_TIMESTAMP_FILE, "w") as f:
        f.write(ts)
    print(f"[DEBUG] Timestamp gespeichert: {ts}")


def build_tiff_url(timestamp: str) -> str:
    bbox_str = f"{BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]}"
    return (
        f"https://view.eumetsat.int/geoserver/wms?"
        f"service=WMS&version=1.3.0&request=GetMap"
        f"&layers={LAYER}&styles=&format={FORMAT}&transparent=true"
        f"&crs={CRS}&bbox={bbox_str}&width={WIDTH}&height={HEIGHT}"
        f"&time={timestamp}"
    )


def find_matching_weather_file(timestamp_wms_str: str, weather_dir: str) -> str | None:
    ts_target = datetime.strptime(timestamp_wms_str, "%Y-%m-%dT%H:%M:%SZ")
    candidates = glob(os.path.join(weather_dir, "*.json"))
    best_match = None
    min_diff = None
    for path in candidates:
        try:
            fname = os.path.basename(path).replace(".json", "").replace("wetter_", "")
            ts = datetime.strptime(fname, "%Y-%m-%d_%H-%M-%S")
            if ts <= ts_target:
                diff = (ts_target - ts).total_seconds()
                if min_diff is None or diff < min_diff:
                    best_match = path
                    min_diff = diff
        except Exception:
            continue
    return best_match


def _uint8_to_bt_kelvin(bt_uint8: np.ndarray) -> np.ndarray:
    """
    Kalibriert EUMETView uint8-Pixelwerte auf Brightness Temperature in Kelvin.
    EUMETView liefert image/geotiff als visualisiertes RGBA-Farbbild:
      Pixelwert 0   → EUMETVIEW_BT_MAX_K (warme Oberfläche)
      Pixelwert 255 → EUMETVIEW_BT_MIN_K (hohe, kalte Wolke)
    Nodata-Pixel (Wert <= EUMETVIEW_NODATA_PIXEL) werden auf NaN gesetzt.
    """
    bt = bt_uint8.copy().astype(np.float32)
    bt[bt <= EUMETVIEW_NODATA_PIXEL] = np.nan
    scale = (EUMETVIEW_BT_MAX_K - EUMETVIEW_BT_MIN_K) / 255.0
    bt_k = EUMETVIEW_BT_MAX_K - scale * bt
    return bt_k


def assign_cloud_top_height(
    objects: list,
    weather_data: list | None = None,
    timestamp: str | None = None,
) -> list:
    """
    Weist jedem Objekt eine Wolkenhöhe MSL zu.
    Lädt EUMETView IR108 TIFF nur wenn neuer Timestamp oder TIFF fehlt lokal.
    Bei vorhandenem TIFF (Cache-Hit) wird TIFF trotzdem verarbeitet,
    da die Objekte des aktuellen Frames noch keine Wolkenhöhe haben.
    """
    timestamp_wms = get_latest_wms_time()
    if not timestamp_wms:
        print("[FEHLER] Kein gültiger WMS-Timestamp – setze cloud_top_height_msl=-1")
        for obj in objects:
            obj["cloud_top_height_msl"] = -1.0
            obj["cloud_height_missing"] = 1.0
        return objects

    timestamp_file = wms_to_filename_timestamp(timestamp_wms)
    pipeline_ts = timestamp if timestamp else timestamp_file
    tif_path = os.path.join(
        SAVE_DIR,
        f"ir108_{timestamp_file.replace('-', '').replace('_', '')}.tif",
    )
    json_path = os.path.join(SAVE_DIR, f"cloud_height_{pipeline_ts}.json")

    # ── Download: nur wenn neuer Timestamp ODER TIFF fehlt lokal ────────────
    need_download = (read_last_timestamp() != timestamp_wms) or (
        not os.path.exists(tif_path)
    )

    if need_download:
        tif_url = build_tiff_url(timestamp_wms)
        print(f"[INFO] Lade neues TIFF: {tif_url}")
        try:
            r = requests.get(tif_url, timeout=20)
            try:
                from debug_utils import log_api_call

                log_api_call("eumetview_wms", url=tif_url, status_code=r.status_code)
            except Exception:
                pass
            r.raise_for_status()

            # BUG 4 FIX: WMS ServiceException kommt als "200 OK + XML"
            content_type = r.headers.get("Content-Type", "")
            if "tiff" not in content_type.lower() and "image" not in content_type.lower():
                print(f"[FEHLER] WMS lieferte kein Bild (Content-Type={content_type})")
                print(f"[DEBUG] Server-Antwort: {r.text[:300]}")
                try:
                    from debug_utils import log_api_failure

                    log_api_failure(
                        "EUMETView-WMS",
                        tif_url,
                        f"Content-Type={content_type}",
                        fallback_used=True,
                    )
                except Exception:
                    pass
                for obj in objects:
                    obj["cloud_top_height_msl"] = -1.0
                    obj["cloud_height_missing"] = 1.0
                return objects

            with open(tif_path, "wb") as f:
                f.write(r.content)
            write_last_timestamp(timestamp_wms)
            print(f"[OK] TIFF gespeichert: {tif_path}")

        except Exception as e:
            print(f"[FEHLER] TIFF-Download fehlgeschlagen: {e}")
            try:
                from debug_utils import log_api_failure

                log_api_failure(
                    "EUMETView-WMS", tif_url, f"{type(e).__name__}: {e}", fallback_used=True
                )
            except Exception:
                pass
            for obj in objects:
                obj["cloud_top_height_msl"] = -1.0
                obj["cloud_height_missing"] = 1.0
            return objects
    else:
        # BUG 2 FIX: Kein neuer Download, aber TIFF muss trotzdem verarbeitet
        # werden – die Objekte dieses Frames sind neu und haben noch keine Höhe.
        print("[INFO] Kein neues TIFF (Timestamp unverändert) – verarbeite vorhandenes TIFF")

    if not os.path.exists(tif_path):
        print(f"[FEHLER] TIFF nach Download nicht vorhanden: {tif_path}")
        for obj in objects:
            obj["cloud_top_height_msl"] = -1.0
            obj["cloud_height_missing"] = 1.0
        return objects

    # ── Oberflächentemperatur ermitteln ──────────────────────────────────────
    weather_path = find_matching_weather_file(
        timestamp_wms, SAVE_PATHS["weather"].rstrip("/")
    )
    T_surface = 290.15
    altitude_m = 600.0

    if weather_data:
        try:
            stations = weather_data if isinstance(weather_data, list) else [weather_data]
            tl_values = [
                float(s["TL"])
                for s in stations
                if isinstance(s, dict) and s.get("TL") not in (None, 0, "0")
            ]
            if tl_values:
                T_surface = sum(tl_values) / len(tl_values) + 273.15
        except Exception as e:
            print(f"[WARNUNG] Wetterdaten (Parameter) konnten nicht gelesen werden: {e}")
    elif weather_path:
        try:
            with open(weather_path) as f:
                raw = json.load(f)
            stations = raw if isinstance(raw, list) else [raw]
            tl_values = [
                float(s["TL"])
                for s in stations
                if isinstance(s, dict) and s.get("TL") not in (None, 0, "0")
            ]
            if tl_values:
                T_surface = sum(tl_values) / len(tl_values) + 273.15
            altitude_m = 600.0
        except Exception as e:
            print(f"[WARNUNG] Wetterdaten-Parsing fehlgeschlagen: {e}")
    else:
        print("[WARNUNG] Keine passende Wetterdatei – verwende Standardwerte.")

    # ── TIFF einlesen, kalibrieren, Wolkenhöhe berechnen ────────────────────
    try:
        with rasterio.open(tif_path) as src:
            bt_uint8 = src.read(1)  # Band 1 (Rot-Kanal), uint8 0–255
            raster_rows, raster_cols = bt_uint8.shape

            # BUG 1 FIX: uint8-Pixelwerte → Brightness Temperature Kelvin
            bt_k = _uint8_to_bt_kelvin(bt_uint8)

            # Diagnose
            valid = bt_k[~np.isnan(bt_k)]
            if len(valid) > 0:
                print(
                    f"[DEBUG] BT nach Kalibrierung: "
                    f"min={valid.min():.1f}K max={valid.max():.1f}K "
                    f"mean={valid.mean():.1f}K | T_surface={T_surface:.1f}K"
                )
            else:
                print("[WARNUNG] Alle Pixel sind NaN nach Kalibrierung!")

            height_km = (T_surface - bt_k) / LAPSE_RATE
            height_msl = altitude_m + (height_km * 1000.0)
            # Negative Höhen (BT > T_surface = wolkenfrei): als NaN markieren
            height_msl[height_msl < 0] = np.nan

            # Cache-JSON speichern
            with open(json_path, "w") as f:
                json.dump(
                    {
                        "bbox": BBOX,
                        "unit": "m MSL",
                        "surface_temperature_K": round(T_surface, 2),
                        "station_altitude_m": round(altitude_m, 1),
                        "calibration": {
                            "bt_max_k": EUMETVIEW_BT_MAX_K,
                            "bt_min_k": EUMETVIEW_BT_MIN_K,
                            "source": "uint8_linear",
                        },
                        "grid": height_msl.tolist(),
                    },
                    f,
                )
            print(f"[OK] Wolkenhöhen-Raster gespeichert: {json_path}")

            assigned = 0
            for obj in objects:
                lat = obj.get("lat")
                lon = obj.get("lon")
                if lat is None or lon is None:
                    obj["cloud_top_height_msl"] = -1.0
                    obj["cloud_height_missing"] = 1.0
                    continue
                try:
                    row, col = rowcol(src.transform, lon, lat)

                    # BUG 3 FIX: Bounds-Check vor Array-Zugriff
                    if row < 0 or col < 0 or row >= raster_rows or col >= raster_cols:
                        print(
                            f"[WARNUNG] Koordinate lat={lat}, lon={lon} außerhalb Raster "
                            f"(row={row}, col={col}, shape={raster_rows}x{raster_cols})"
                        )
                        obj["cloud_top_height_msl"] = -1.0
                        obj["cloud_height_missing"] = 1.0
                        continue

                    value = height_msl[row, col]
                    if np.isnan(value):
                        # wolkenfrei oder nodata → kein messbarer Wolkendeckel
                        obj["cloud_top_height_msl"] = -1.0
                        obj["cloud_height_missing"] = 0.0  # kein Fehler, nur kein Deckel
                    else:
                        obj["cloud_top_height_msl"] = round(float(value), 1)
                        obj["cloud_height_missing"] = 0.0
                        obj["cloud_top_height_timestamp"] = timestamp_file
                        assigned += 1

                except Exception as ex:
                    print(f"[WARNUNG] rowcol-Fehler lat={lat} lon={lon}: {ex}")
                    obj["cloud_top_height_msl"] = -1.0
                    obj["cloud_height_missing"] = 1.0

            print(f"[INFO] Wolkenhöhe zugewiesen: {assigned}/{len(objects)} Objekte")

    except Exception as e:
        print(f"[FEHLER] TIFF-Verarbeitung fehlgeschlagen: {e}")
        try:
            from debug_utils import log_api_failure

            log_api_failure(
                "EUMETView-WMS-TIFF", tif_path, f"{type(e).__name__}: {e}", fallback_used=True
            )
        except Exception:
            pass
        for obj in objects:
            obj["cloud_top_height_msl"] = -1.0
            obj["cloud_height_missing"] = 1.0

    return objects
