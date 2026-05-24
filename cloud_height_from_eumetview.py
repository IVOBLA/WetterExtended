# cloud_height_from_eumetview.py
"""
Lädt EUMETView IR108 GeoTIFF via WMS und berechnet Wolkenhöhe MSL je Zelle.

Hardening B11:
  - Alle Konsolen-Ausgaben durch debug_log() ersetzt
  - log_api_failure/log_api_call als Top-Level-Imports
  - EUMETView-Fehler erscheinen in /api/api_health
"""
import json
import os
import requests
import numpy as np
import xml.etree.ElementTree as ET
from datetime import datetime
from glob import glob

from config import (
    BBOX_KAERNTEN_EXTENDED,
    SAVE_PATHS,
    EUMETVIEW_BT_MAX_K,
    EUMETVIEW_BT_MIN_K,
    EUMETVIEW_NODATA_PIXEL,
)
from debug_utils import debug_log, log_api_failure, log_api_call, log_http_response
from api_cache import cache_key, cache_get, cache_set, get_ttl
import runtime_config

try:
    import rasterio
    from rasterio.transform import rowcol
    HAS_RASTERIO = True
except ImportError:
    HAS_RASTERIO = False

try:
    import numpy as _np_check  # noqa: F401 — nur Import-Test
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

# ── Konstanten ───────────────────────────────────────────────────────────────
BBOX = [
    BBOX_KAERNTEN_EXTENDED["west"],
    BBOX_KAERNTEN_EXTENDED["south"],
    BBOX_KAERNTEN_EXTENDED["east"],
    BBOX_KAERNTEN_EXTENDED["north"],
]

WIDTH  = 1600
HEIGHT = 600
LAYER  = "msg_fes:ir108"
FORMAT = "image/geotiff"
# WMS 1.3.0 + EPSG:4326: Achsenreihenfolge Lat,Lon → BBOX-Interpretation falsch.
# Code sendet west,south,east,north (Lon,Lat) → Server interpretiert als Lat,Lon
# → völlig falsches Gebiet → TIFF: nur 0–3 statt 0–255 BT-Grauwerte.
# WMS 1.1.1: BBOX immer Lon,Lat,Lon,Lat unabhängig vom CRS → korrekt.
_WMS_VERSION = "1.1.1"    # 1.3.0 → 1.1.1
_WMS_SRS_KEY = "srs"      # WMS 1.3.0 nutzt "crs=", WMS 1.1.1 nutzt "srs="
CRS = "EPSG:4326"

SAVE_DIR            = SAVE_PATHS.get("cloud", "train_data/cloud/")
LAST_TIMESTAMP_FILE = os.path.join(SAVE_DIR, "last_wms_timestamp.txt")


# ── Hilfsfunktionen ──────────────────────────────────────────────────────────

def get_latest_wms_time() -> str | None:
    """
    Fragt EUMETView WMS GetCapabilities ab und gibt den aktuellen
    Zeitstempel des MSG IR108 Layers zurück.
    Cache 10 Min (MSG Full Earth Scan aktualisiert alle 15 Min).
    """
    url = (
        "https://view.eumetsat.int/geoserver/wms"
        "?service=WMS&request=GetCapabilities&version=1.3.0"
    )
    ck = cache_key("eumetview:capabilities", LAYER)
    cached_ts = cache_get(ck, ttl_seconds=get_ttl("eumetview_capabilities", 600))
    if cached_ts is not None:
        debug_log(f"[CLOUD] WMS-Timestamp aus Cache: {cached_ts}")
        return cached_ts

    try:
        import time as _t_wms_cap
        _t0_wms_cap = _t_wms_cap.monotonic()
        from http_retry import retry_get
        r = retry_get(url, service="EUMETView-WMS-Caps", timeout=10)
        _dur_ms = (_t_wms_cap.monotonic() - _t0_wms_cap) * 1000
        log_http_response(
            service="eumetview_wms_caps",
            method="GET",
            response=r,
            duration_ms=_dur_ms,
        )
        if r.ok:
            root = ET.fromstring(r.content)
            for elem in root.iter():
                if elem.tag.endswith("Dimension") and elem.attrib.get("name") == "time":
                    ts = elem.attrib.get("default")
                    if ts:
                        debug_log(f"[CLOUD] WMS-Timestamp gefunden: {ts}")
                        cache_set(ck, ts)
                        return ts
    except Exception as e:
        debug_log(f"[CLOUD] GetCapabilities fehlgeschlagen: {e}")
        log_api_failure(
            "EUMETView-WMS", url, f"{type(e).__name__}: {e}", fallback_used=True
        )
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
    debug_log(f"[CLOUD] Timestamp gespeichert: {ts}")


def build_tiff_url(timestamp: str) -> str:
    bbox_str = f"{BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]}"
    return (
        f"https://view.eumetsat.int/geoserver/wms?"
        f"service=WMS&version={_WMS_VERSION}&request=GetMap"
        f"&layers={LAYER}&styles=&format={FORMAT}&transparent=false"
        f"&{_WMS_SRS_KEY}={CRS}&bbox={bbox_str}&width={WIDTH}&height={HEIGHT}"
        f"&time={timestamp}"
    )


def get_adaptive_nan_threshold(utc_hour: int) -> float:
    """
    BT-Schwelle (Kelvin) ÜBER der kein Konvektionswolkentop angenommen wird.
    Nach _uint8_to_bt_kelvin liegt bt_k zwischen 180 K (Pixelwert 255, hohe
    Wolke) und 330 K (Pixelwert 0, warme Erdoberfläche).

    Physikalische Referenz MSG IR108:
      < 220 K  = sehr hohe Wolke (Cb-Amboss)
      220–250 K = hohe Wolke (Ci, hoher Cu)
      250–265 K = mittelhohe Konvektionswolke
      > 265 K  = warme Erdoberfläche oder tiefe Wolke → kein Wolkentop

    Tagsüber (6–18 UTC): 265 K
    Dämmerung (3–6 / 18–21 UTC): 260 K
    Nachts: 255 K (IR-Kontrast besser, strengerer Threshold sinnvoll)
    """
    if 6 <= utc_hour <= 18:
        return 265.0
    elif 3 <= utc_hour < 6 or 18 < utc_hour <= 21:
        return 260.0
    else:
        return 255.0


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
    Pixelwert 0   → EUMETVIEW_BT_MAX_K (warme Oberfläche)
    Pixelwert 255 → EUMETVIEW_BT_MIN_K (hohe, kalte Wolke)
    Nodata-Pixel (<= EUMETVIEW_NODATA_PIXEL) werden auf NaN gesetzt.
    """
    bt = bt_uint8.copy().astype(np.float32)
    bt[bt <= EUMETVIEW_NODATA_PIXEL] = np.nan
    scale = (EUMETVIEW_BT_MAX_K - EUMETVIEW_BT_MIN_K) / 255.0
    bt_k = EUMETVIEW_BT_MAX_K - scale * bt
    return bt_k


# ── Haupt-API ─────────────────────────────────────────────────────────────────

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
    os.makedirs(SAVE_DIR, exist_ok=True)

    timestamp_wms = get_latest_wms_time()
    if not timestamp_wms:
        debug_log("[CLOUD] Kein gültiger WMS-Timestamp — cloud_top_height_msl=-1")
        log_api_failure("EUMETView-WMS", "GetCapabilities", "no-timestamp", fallback_used=True)
        for obj in objects:
            obj["cloud_top_height_msl"] = -1.0
            obj["cloud_height_missing"] = 1.0
        return objects

    timestamp_file = wms_to_filename_timestamp(timestamp_wms)
    pipeline_ts    = timestamp if timestamp else timestamp_file
    tif_path = os.path.join(
        SAVE_DIR,
        f"ir108_{timestamp_file.replace('-', '').replace('_', '')}.tif",
    )
    json_path = os.path.join(SAVE_DIR, f"cloud_height_{pipeline_ts}.json")

    # ── Download: nur wenn neuer Timestamp ODER TIFF fehlt lokal ─────────────
    need_download = (read_last_timestamp() != timestamp_wms) or (
        not os.path.exists(tif_path)
    )

    if need_download:
        tif_url = build_tiff_url(timestamp_wms)
        debug_log(f"[CLOUD] Lade neues TIFF: {tif_url}")
        try:
            import time as _t_wms_tiff
            _t0_wms_tiff = _t_wms_tiff.monotonic()
            from http_retry import retry_get
            r = retry_get(tif_url, service="EUMETView-WMS-TIFF", timeout=20)
            _dur_ms = (_t_wms_tiff.monotonic() - _t0_wms_tiff) * 1000
            _ts_str = timestamp_file.replace("-", "").replace("_", "")
            _tif_save = os.path.join(SAVE_DIR, f"ir108_{_ts_str}.tif") if "r" in dir() else None
            log_http_response(
                service="eumetview_wms",
                method="GET",
                response=r,
                duration_ms=_dur_ms,
                saved_to=_tif_save,
            )
            r.raise_for_status()

            # WMS ServiceException kommt als "200 OK + XML"
            content_type = r.headers.get("Content-Type", "")
            if "tiff" not in content_type.lower() and "image" not in content_type.lower():
                debug_log(f"[CLOUD] WMS lieferte kein Bild (Content-Type={content_type})")
                debug_log(f"[CLOUD] Server-Antwort: {r.text[:300]}")
                log_api_failure(
                    "EUMETView-WMS",
                    tif_url,
                    f"Content-Type={content_type}",
                    fallback_used=True,
                )
                for obj in objects:
                    obj["cloud_top_height_msl"] = -1.0
                    obj["cloud_height_missing"] = 1.0
                return objects

            with open(tif_path, "wb") as f:
                f.write(r.content)
            write_last_timestamp(timestamp_wms)
            debug_log(f"[CLOUD] TIFF gespeichert: {tif_path}")

        except Exception as e:
            debug_log(f"[CLOUD] TIFF-Download fehlgeschlagen: {e}")
            log_api_failure(
                "EUMETView-WMS", tif_url, f"{type(e).__name__}: {e}", fallback_used=True
            )
            for obj in objects:
                obj["cloud_top_height_msl"] = -1.0
                obj["cloud_height_missing"] = 1.0
            return objects
    else:
        # Kein neuer Download, aber TIFF muss trotzdem verarbeitet werden —
        # die Objekte dieses Frames sind neu und haben noch keine Höhe.
        debug_log("[CLOUD] Kein neues TIFF (Timestamp unverändert) – verarbeite vorhandenes TIFF")

    if not os.path.exists(tif_path):
        debug_log(f"[CLOUD] TIFF nach Download nicht vorhanden: {tif_path}")
        log_api_failure(
            "EUMETView-WMS", tif_path, "tiff-missing-after-download", fallback_used=True
        )
        for obj in objects:
            obj["cloud_top_height_msl"] = -1.0
            obj["cloud_height_missing"] = 1.0
        return objects

    # ── Oberflächentemperatur ermitteln ───────────────────────────────────────
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
            debug_log(f"[CLOUD] Wetterdaten (Parameter) konnten nicht gelesen werden: {e}")
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
            debug_log(f"[CLOUD] Wetterdaten-Parsing fehlgeschlagen: {e}")
    else:
        debug_log("[CLOUD] Keine passende Wetterdatei gefunden — Standardwerte.")

    # ── TIFF verarbeiten ──────────────────────────────────────────────────────
    if not HAS_RASTERIO:
        debug_log("[CLOUD] rasterio nicht verfügbar – cloud_top_height_msl=-1")
        for obj in objects:
            obj["cloud_top_height_msl"] = -1.0
            obj["cloud_height_missing"] = 1.0
        return objects

    try:
        with rasterio.open(tif_path) as src:
            raster_rows, raster_cols = src.height, src.width
            band = src.read(1)
            utc_hour = datetime.utcnow().hour
            nan_threshold = get_adaptive_nan_threshold(utc_hour)

            # dtype-adaptiver Pfad: EUMETView liefert je nach Konfiguration
            # entweder uint8-Visualisierungsbild (Pixelwert 0–255) oder
            # float32-Physikwerte direkt in Kelvin (~180–330 K).
            debug_log(
                f"[CLOUD] TIFF: dtype={band.dtype}, shape={band.shape}, "
                f"min={float(band.min()):.2f}, max={float(band.max()):.2f}, "
                f"zeros={int((band == 0).sum())}, nan_threshold={nan_threshold}"
            )

            if np.issubdtype(band.dtype, np.floating):
                # Float32-Physikwerte direkt in Kelvin
                bt_k = band.astype(np.float32)
                # Ungültige Werte (0 oder extrem) maskieren
                bt_k[bt_k <= 0] = np.nan
                bt_k[bt_k > 400] = np.nan
                debug_log(f"[CLOUD] Float32-Modus: {np.nanmean(bt_k):.1f} K Mittel")
            else:
                # uint8-Visualisierungsbild → Kalibrierung via config
                bt_k = _uint8_to_bt_kelvin(band)
                debug_log(
                    f"[CLOUD] uint8-Modus: bt_k min={float(np.nanmin(bt_k)):.1f} K, "
                    f"max={float(np.nanmax(bt_k)):.1f} K, "
                    f"nan_threshold={nan_threshold} K"
                )
            lapse_rate = runtime_config.get("LAPSE_RATE", 6.5) / 1000.0  # K/m
            height_msl = (T_surface - bt_k) / lapse_rate + altitude_m

            # Werte unter NaN-Threshold → NaN (wolkenfrei oder Nodata)
            height_msl[bt_k > nan_threshold] = float("nan")

            # JSON-Snapshot speichern
            try:
                import json as _json
                snap = {
                    "timestamp_wms": timestamp_wms,
                    "pipeline_ts":   pipeline_ts,
                    "T_surface_K":   round(T_surface, 2),
                    "altitude_m":    altitude_m,
                    "nan_threshold": nan_threshold,
                }
                with open(json_path, "w") as jf:
                    _json.dump(snap, jf)
                debug_log(f"[CLOUD] JSON-Snapshot gespeichert: {json_path}")
            except Exception:
                pass

            assigned = 0
            for obj in objects:
                lat, lon = obj.get("lat"), obj.get("lon")
                if lat is None or lon is None:
                    obj["cloud_top_height_msl"] = -1.0
                    obj["cloud_height_missing"] = 1.0
                    continue
                try:
                    row, col = rowcol(src.transform, lon, lat)
                    if row < 0 or col < 0 or row >= raster_rows or col >= raster_cols:
                        debug_log(
                            f"[CLOUD] Koordinate lat={lat},lon={lon} außerhalb Raster "
                            f"(row={row},col={col},shape={raster_rows}x{raster_cols})"
                        )
                        obj["cloud_top_height_msl"] = -1.0
                        obj["cloud_height_missing"] = 1.0
                        continue

                    value   = height_msl[row, col]
                    bt_val  = bt_k[row, col]

                    if np.isnan(value):
                        if np.isnan(bt_val):
                            # bt_k war Nodata/korrupt → fehlende Satellitendaten
                            obj["cloud_top_height_msl"] = -1.0
                            obj["cloud_height_missing"] = 1.0
                        else:
                            # bt_k > nan_threshold → Satellit sieht keine kalte Wolke.
                            # Bei erkannter Gewitterzelle (core_ratio > 0) ist das
                            # ein Widerspruch (MSG-Scan zu alt, Koordinatenversatz,
                            # frisch entstehende Konvektion) → Datenfehler, nicht wolkenfrei.
                            is_convective = float(obj.get("core_ratio", 0.0)) > 0.0
                            obj["cloud_top_height_msl"] = -1.0
                            obj["cloud_height_missing"] = 1.0 if is_convective else 0.0
                            if is_convective:
                                debug_log(
                                    f"[CLOUD] Widerspruch: Zelle {obj.get('id','?')} "
                                    f"core_ratio={obj.get('core_ratio',0):.2f} aber "
                                    f"bt_k={float(bt_val):.1f} K > threshold={nan_threshold} K"
                                    f" → cloud_height_missing=1"
                                )
                    else:
                        obj["cloud_top_height_msl"]       = round(float(value), 1)
                        obj["cloud_height_missing"]        = 0.0
                        obj["cloud_top_height_timestamp"] = timestamp_file
                        assigned += 1

                except Exception as ex:
                    debug_log(f"[CLOUD] rowcol-Fehler lat={lat} lon={lon}: {ex}")
                    obj["cloud_top_height_msl"] = -1.0
                    obj["cloud_height_missing"] = 1.0

            debug_log(f"[CLOUD] Wolkenhöhe zugewiesen: {assigned}/{len(objects)} Objekte")

    except Exception as e:
        debug_log(f"[CLOUD] TIFF-Verarbeitung fehlgeschlagen: {e}")
        log_api_failure(
            "EUMETView-WMS-TIFF", tif_path, f"{type(e).__name__}: {e}", fallback_used=True
        )
        for obj in objects:
            obj["cloud_top_height_msl"] = -1.0
            obj["cloud_height_missing"] = 1.0

    write_last_timestamp(timestamp_wms)
    return objects
