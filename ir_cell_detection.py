# ir_cell_detection.py
"""
Phase E — Task E1: IR-Sat Pre-Convection Detection.

Erkennt konvektive Wolken-Cluster aus dem EUMETView MSG IR108 TIFF
(bereits von cloud_height_from_eumetview.py gecacht, kein neuer Download).

Schwellwerte:
  BT < IR_CONVECTION_BT_THRESHOLD_K (230 K) → konvektiver Wolkentop
  BT < IR_OVERSHOOTING_TOP_BT_K    (215 K) → Overshooting Top

Filterung:
  - Cluster-Fläche >= IR_MIN_CELL_AREA_PX Pixel
  - atmosphärische Instabilität (CAPE, LI) aus AROME-Snapshot wenn verfügbar

Output: train_data/ir_cells/ir_cells_<timestamp>.json
Format pro IR-Cell:
  {
    "ir_id":             "ir_0",
    "lat":               float,   # Schwerpunkt-Breitengrad
    "lon":               float,   # Schwerpunkt-Längengrad
    "bt_min_k":          float,   # kältestes Pixel der Zelle [K]
    "bt_mean_k":         float,   # mittlere Helligkeit [K]
    "area_px":           int,     # Fläche [Pixel im TIFF]
    "overshooting_top":  float,   # 1.0 wenn bt_min_k < IR_OVERSHOOTING_TOP_BT_K
    "cloud_height_m":    float,   # abgeleitete MSL-Höhe am Minimum-BT-Pixel [m]
    "cape":              float,   # CAPE am Schwerpunkt (0.0 wenn nicht verfügbar)
    "arome_li":          float,   # Lifted Index (0.0 wenn nicht verfügbar)
    "timestamp":         str,     # Zeitstempel des TIFF
    "tiff_file":         str,     # Dateiname des verwendeten TIFFs
  }
"""

import json
import os
from datetime import datetime
from glob import glob
from math import radians, cos, sin, sqrt, atan2

import numpy as np

from config import (
    SAVE_PATHS,
    EUMETVIEW_BT_MAX_K,
    EUMETVIEW_BT_MIN_K,
    EUMETVIEW_NODATA_PIXEL,
    IR_CONVECTION_BT_THRESHOLD_K,
    IR_OVERSHOOTING_TOP_BT_K,
    IR_MIN_CELL_AREA_PX,
    IR_WATCH_BT_THRESHOLD_K, IR_PRE_CB_BT_THRESHOLD_K, IR_CB_BT_THRESHOLD_K,
    IR_WATCH_MIN_CELL_AREA_PX, IR_PRE_CB_MIN_CELL_AREA_PX, IR_CB_MIN_CELL_AREA_PX,
    IR_WATCH_CLOUD_HEIGHT_MIN_M, IR_PRE_CB_CLOUD_HEIGHT_MIN_M, IR_CB_CLOUD_HEIGHT_MIN_M, IR_SEVERE_CB_CLOUD_HEIGHT_MIN_M,
    IR_WATCH_MIN_SCORE, IR_PRE_CB_MIN_SCORE, IR_CB_MIN_SCORE,
    IR_MIN_CAPE_J_KG,
    IR_MAX_LI_C,
    LAPSE_RATE,
)
from debug_utils import debug_log, log_api_failure
try:
    import runtime_config
except Exception:
    runtime_config = None

try:
    import rasterio
    from rasterio.transform import xy as rasterio_xy
    HAS_RASTERIO = True
except ImportError:
    HAS_RASTERIO = False

try:
    from scipy import ndimage as _ndimage
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

_SAVE_DIR = SAVE_PATHS.get("ir_cells", "train_data/ir_cells/")
_CLOUD_DIR = SAVE_PATHS.get("cloud", "train_data/cloud/")
_DEFAULT_SURFACE_K = 290.15
_DEFAULT_ALT_M = 600.0


def _parse_ir108_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d_%H-%M-%S"):
        try:
            return datetime.strptime(value.replace("+00:00", "Z"), fmt)
        except ValueError:
            continue
    return None


def _timestamp_from_tiff_name(tiff_name: str) -> str | None:
    import re
    m = re.search(r"ir108_(\d{14})\.tif$", tiff_name or "")
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y%m%d%H%M%S").strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None


def _load_ir108_metadata(tif_path: str) -> dict:
    meta_path = os.path.splitext(tif_path)[0] + ".json"
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f) or {}
            obs = meta.get("observation_timestamp") or meta.get("wms_timestamp")
            if _parse_ir108_timestamp(obs):
                meta["observation_timestamp"] = _parse_ir108_timestamp(obs).strftime("%Y-%m-%dT%H:%M:%SZ")
                meta.setdefault("timestamp_source", "wms_time_dimension")
                return meta
        except Exception as exc:
            debug_log(f"[IR-DET] Metadaten-Parsing fehlgeschlagen: {exc}")
    obs = _timestamp_from_tiff_name(os.path.basename(tif_path))
    if obs:
        return {"observation_timestamp": obs, "wms_timestamp": obs, "timestamp_source": "tiff_filename"}
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"observation_timestamp": now, "wms_timestamp": now, "timestamp_source": "fallback_processing_time"}


def _uint8_to_bt(pixel_arr: np.ndarray) -> np.ndarray:
    """uint8-Pixel → Brightness Temperature [K]."""
    bt = pixel_arr.astype(np.float32)
    bt[bt <= EUMETVIEW_NODATA_PIXEL] = np.nan
    scale = (EUMETVIEW_BT_MAX_K - EUMETVIEW_BT_MIN_K) / 255.0
    return EUMETVIEW_BT_MAX_K - scale * bt


def _cfg(name, default):
    if runtime_config is not None:
        try:
            return runtime_config.get(name, default)
        except Exception:
            return default
    return default


def _bt_to_height_m(bt_k: float, T_surface_K: float = _DEFAULT_SURFACE_K,
                    alt_m: float = _DEFAULT_ALT_M) -> float:
    """BT [K] → geschätzte Wolkenhöhe MSL [m] via Umgebungstemperaturgradient."""
    lapse = LAPSE_RATE / 1000.0  # K/m
    h = (T_surface_K - bt_k) / lapse + alt_m
    return max(0.0, round(float(h), 0))


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


def _load_arome_snapshot() -> dict:
    """
    Lädt atmosphere_latest.json für CAPE/LI-Lookup.
    Gibt leeres Dict zurück wenn Datei fehlt.
    """
    path = os.path.join(
        SAVE_PATHS.get("evaluation", "train_data/evaluation"),
        "atmosphere_latest.json"
    )
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _lookup_atm(lat: float, lon: float, snapshot: dict,
                max_dist_km: float = 50.0) -> tuple:
    """
    Sucht nächstgelegene AROME-Snapshot-Location für lat/lon.
    Rückgabe: (cape, li) — (None, None) wenn kein Snapshot oder
    kein Ort innerhalb max_dist_km.
    None = keine Daten verfügbar → Filter wird nicht angewendet.
    """
    locs = snapshot.get("locations", [])
    if not locs:
        return None, None
    best_dist = float("inf")
    cape_val = li_val = None
    for loc in locs:
        d = _haversine_km(lat, lon, loc.get("lat", 0), loc.get("lon", 0))
        if d < best_dist:
            best_dist = d
            cape_val = float(loc.get("cape", 0.0) or 0.0)
            li_val   = float(loc.get("li", 0.0) or 0.0)
    if best_dist > max_dist_km:
        return None, None   # zu weit → keine verlässlichen Daten
    return cape_val, li_val


def classify_height_stage(cloud_height_m: float) -> str:
    h = float(cloud_height_m or 0.0)
    if h >= float(_cfg("IR_SEVERE_CB_CLOUD_HEIGHT_MIN_M", IR_SEVERE_CB_CLOUD_HEIGHT_MIN_M)):
        return "severe_cb"
    if h >= float(_cfg("IR_CB_CLOUD_HEIGHT_MIN_M", IR_CB_CLOUD_HEIGHT_MIN_M)):
        return "cb"
    if h >= float(_cfg("IR_PRE_CB_CLOUD_HEIGHT_MIN_M", IR_PRE_CB_CLOUD_HEIGHT_MIN_M)):
        return "pre_cb"
    if h >= float(_cfg("IR_WATCH_CLOUD_HEIGHT_MIN_M", IR_WATCH_CLOUD_HEIGHT_MIN_M)):
        return "watch"
    return "low"


def calculate_ir_convective_score(cell: dict, track: dict | None = None, met: dict | None = None) -> float:
    height_stage = cell.get("height_stage") or classify_height_stage(cell.get("cloud_height_m", 0.0))
    score = {"low": 0.0, "watch": 0.28, "pre_cb": 0.42, "cb": 0.58, "severe_cb": 0.68}.get(height_stage, 0.0)
    bt_min = float(cell.get("bt_min_k", 999.0) or 999.0)
    if bt_min <= float(_cfg("IR_CB_BT_THRESHOLD_K", IR_CB_BT_THRESHOLD_K)):
        score += 0.18
    elif bt_min <= float(_cfg("IR_PRE_CB_BT_THRESHOLD_K", IR_PRE_CB_BT_THRESHOLD_K)):
        score += 0.12
    elif bt_min <= float(_cfg("IR_WATCH_BT_THRESHOLD_K", IR_WATCH_BT_THRESHOLD_K)):
        score += 0.08
    if float(cell.get("overshooting_top", 0.0) or 0.0) >= 1.0:
        score += 0.14
    if float(cell.get("bt_trend_k_per_min", 0.0) or 0.0) <= -0.15:
        score += 0.10
    if float(cell.get("cloud_height_trend_m_per_min", 0.0) or 0.0) >= 60.0:
        score += 0.10
    if float(cell.get("area_growth_px_per_min", 0.0) or 0.0) >= 2.0:
        score += 0.08
    cape = cell.get("cape")
    li = cell.get("arome_li")
    if cape not in (None, "") and float(cape or 0.0) >= 200.0:
        score += 0.06
    if li not in (None, "") and float(li or 0.0) <= -0.5:
        score += 0.06
    if cape not in (None, "") and li not in (None, "") and float(cape or 0.0) < 50.0 and float(li or 0.0) > 3.0:
        score -= 0.20
    return round(max(0.0, min(1.0, score)), 3)


def classify_ir_stage(cell: dict) -> str:
    score = float(cell.get("ir_score", 0.0) or 0.0)
    hstage = cell.get("height_stage") or classify_height_stage(cell.get("cloud_height_m", 0.0))
    area = int(cell.get("area_px", 0) or 0)
    conv = bool(float(cell.get("overshooting_top", 0.0) or 0.0) >= 1.0 or float(cell.get("bt_trend_k_per_min", 0.0) or 0.0) <= -0.15 or float(cell.get("cloud_height_trend_m_per_min", 0.0) or 0.0) >= 60.0 or float(cell.get("area_growth_px_per_min", 0.0) or 0.0) >= 2.0 or float(cell.get("cape", 0.0) or 0.0) >= 200.0 or float(cell.get("arome_li", 0.0) or 0.0) <= -0.5)
    if hstage in {"cb", "severe_cb"} and area >= int(_cfg("IR_CB_MIN_CELL_AREA_PX", IR_CB_MIN_CELL_AREA_PX)) and score >= float(_cfg("IR_CB_MIN_SCORE", IR_CB_MIN_SCORE)) and conv:
        return "ir_cb_precursor"
    if hstage in {"pre_cb", "cb", "severe_cb"} and area >= int(_cfg("IR_PRE_CB_MIN_CELL_AREA_PX", IR_PRE_CB_MIN_CELL_AREA_PX)) and score >= float(_cfg("IR_PRE_CB_MIN_SCORE", IR_PRE_CB_MIN_SCORE)) and conv:
        return "ir_pre_cb"
    if hstage in {"watch", "pre_cb", "cb", "severe_cb"} and area >= int(_cfg("IR_WATCH_MIN_CELL_AREA_PX", IR_WATCH_MIN_CELL_AREA_PX)) and score >= float(_cfg("IR_WATCH_MIN_SCORE", IR_WATCH_MIN_SCORE)) and conv:
        return "ir_watch_candidate"
    return "inactive"


def _height_context(weather_data=None, lat=None, lon=None):
    temp = None
    if isinstance(weather_data, dict):
        for key in ("temperature_2m", "temp_c", "temperature", "T2m"):
            if key in weather_data:
                temp = float(weather_data[key]) + 273.15 if float(weather_data[key]) < 200 else float(weather_data[key]); break
    source_temp = temp is not None
    alt = _DEFAULT_ALT_M
    return (temp or _DEFAULT_SURFACE_K), alt, ("local_weather_default_alt" if source_temp else "default_fallback"), (0.65 if source_temp else 0.35)

def detect_ir_cells(timestamp: str | None = None, weather_data: dict | None = None) -> list:
    """
    Hauptfunktion: Liest das neueste IR108-TIFF, extrahiert konvektive Cluster
    und gibt die IR-Cell-Liste zurück (leer wenn kein TIFF).

    Parameter
    ---------
    timestamp : Zeitstempel YYYY-MM-DD_HH-MM-SS — wird als Dateiname verwendet.
                Wenn None → aktueller UTC-Zeitstempel.

    Rückgabe: Liste von IR-Cell-Dicts (siehe Modul-Docstring).
    """
    if not HAS_RASTERIO:
        debug_log("[IR-DET] rasterio nicht verfügbar — IR-Detection übersprungen.")
        return []
    if not HAS_SCIPY:
        debug_log("[IR-DET] scipy nicht verfügbar — IR-Detection übersprungen.")
        return []

    os.makedirs(_SAVE_DIR, exist_ok=True)

    # ── Neuestes TIFF suchen ──────────────────────────────────────────────────
    tif_files = sorted(glob(os.path.join(_CLOUD_DIR, "ir108_*.tif")))
    if not tif_files:
        debug_log("[IR-DET] Kein IR108-TIFF vorhanden — Detection übersprungen.")
        return []

    tif_path = tif_files[-1]
    tiff_name = os.path.basename(tif_path)

    meta = _load_ir108_metadata(tif_path)
    observation_timestamp = meta.get("observation_timestamp") or meta.get("wms_timestamp")
    obs_dt = _parse_ir108_timestamp(observation_timestamp)
    if timestamp is None:
        timestamp = obs_dt.strftime("%Y-%m-%d_%H-%M-%S") if obs_dt else datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")

    # ── TIFF einlesen ─────────────────────────────────────────────────────────
    try:
        with rasterio.open(tif_path) as src:
            band = src.read(1)
            transform = src.transform
            crs_height = src.height
            crs_width = src.width

            # BT-Array erzeugen
            if np.issubdtype(band.dtype, np.floating):
                bt = band.astype(np.float32)
                bt[bt <= 0] = np.nan
                bt[bt > 400] = np.nan
            else:
                bt = _uint8_to_bt(band)

            # ── Konvektive Maske (BT < Schwellwert) ──────────────────────────
            threshold = float(_cfg("IR_WATCH_BT_THRESHOLD_K", IR_WATCH_BT_THRESHOLD_K))
            mask = (bt < threshold) & np.isfinite(bt)

            if not mask.any():
                debug_log(f"[IR-DET] Keine Pixel unter {threshold} K — keine IR-Cells.")
                _save_ir_cells([], timestamp)
                return []

            # ── Connected Components ──────────────────────────────────────────
            labeled, n_labels = _ndimage.label(mask)
            debug_log(f"[IR-DET] {n_labels} Cluster gefunden (vor Größenfilter).")

            # ── AROME-Snapshot für CAPE/LI ────────────────────────────────────
            snapshot = _load_arome_snapshot()

            cells = []
            cell_idx = 0

            for label_num in range(1, n_labels + 1):
                cluster_mask = labeled == label_num
                area_px = int(cluster_mask.sum())

                if area_px < int(_cfg("IR_WATCH_MIN_CELL_AREA_PX", IR_WATCH_MIN_CELL_AREA_PX)):
                    continue  # zu klein → verwerfen

                # Schwerpunkt (Pixel) → Geo-Koordinaten
                rows_idx, cols_idx = np.where(cluster_mask)
                center_row = float(rows_idx.mean())
                center_col = float(cols_idx.mean())

                # rasterio.transform.xy: row, col → (lon, lat) in EPSG:4326
                lon_c, lat_c = rasterio_xy(transform, center_row, center_col)
                lat_c = float(lat_c)
                lon_c = float(lon_c)

                # BT-Werte des Clusters
                bt_vals = bt[cluster_mask]
                bt_min = float(np.nanmin(bt_vals))
                bt_mean = float(np.nanmean(bt_vals))

                # Overshooting Top
                overshooting = 1.0 if bt_min < float(IR_OVERSHOOTING_TOP_BT_K) else 0.0

                # Geschätzte Wolkenhöhe am kältesten Pixel
                surf_k, alt_m, h_source, h_conf = _height_context(weather_data, lat_c, lon_c)
                cloud_h = _bt_to_height_m(bt_min, surf_k, alt_m)
                height_stage = classify_height_stage(cloud_h)

                # CAPE / LI aus Snapshot
                cape_val, li_val = _lookup_atm(lat_c, lon_c, snapshot)

                # ── CAPE/LI-Filter ─────────────────────────────────────────
                # Nur anwenden wenn Atmosphären-Daten verfügbar sind.
                # cape_val = None → kein ATM-Ort in Reichweite → nicht filtern.
                # Frühe IR-Watch-Kandidaten werden nicht mehr allein wegen fehlender
                # oder schwacher CAPE/LI-Daten verworfen. Nur eine eindeutig stabile
                # Kombination reduziert/unterbindet die öffentliche Stage über den Score.
                if cape_val is not None and li_val is not None:
                    if cape_val < 50.0 and li_val > 3.0:
                        debug_log(
                            f"[IR-DET] Cluster {label_num}/{n_labels}: stabile Umgebung "
                            f"CAPE={cape_val:.0f}, LI={li_val:.2f} → Score-Abzug"
                        )

                cells.append({
                    "ir_id":            f"ir_{cell_idx}",
                    "lat":              round(lat_c, 5),
                    "lon":              round(lon_c, 5),
                    "bt_min_k":         round(bt_min, 2),
                    "bt_mean_k":        round(bt_mean, 2),
                    "area_px":          area_px,
                    "overshooting_top": overshooting,
                    "cloud_height_m":   cloud_h,
                    "cloud_height_confidence": h_conf,
                    "cloud_height_source": h_source,
                    "cloud_height_trend_m_per_min": 0.0,
                    "max_cloud_height_m": cloud_h,
                    "height_stage": height_stage,
                    "first_height_alert_timestamp": timestamp if height_stage != "low" else None,
                    "cape":             round(cape_val, 1) if cape_val is not None else 0.0,
                    "arome_li":         round(li_val,  2) if li_val  is not None else 0.0,
                    "timestamp":        observation_timestamp,
                    "source_timestamp": observation_timestamp,
                    "observation_timestamp": observation_timestamp,
                    "timestamp_source": meta.get("timestamp_source"),
                    "source_layer":     meta.get("layer", "msg_fes:ir108"),
                    "scan_mode":        meta.get("scan_mode", "FES"),
                    "availability_latency_min": meta.get("availability_latency_min"),
                    "tiff_file":        tiff_name,
                })
                cells[-1]["ir_score"] = calculate_ir_convective_score(cells[-1])
                cells[-1]["ir_stage"] = classify_ir_stage(cells[-1])
                cells[-1]["status"] = cells[-1]["ir_stage"]
                cell_idx += 1

            debug_log(f"[IR-DET] {len(cells)} IR-Cells nach Größenfilter (>= {IR_MIN_CELL_AREA_PX} px).")
            _save_ir_cells(cells, timestamp)
            return cells

    except Exception as exc:
        log_api_failure("EUMETView-IR-Detection", tif_path,
                        f"{type(exc).__name__}: {exc}", fallback_used=True)
        debug_log(f"[IR-DET] Fehler: {exc}")
        return []


def _save_ir_cells(cells: list, timestamp: str) -> None:
    path = os.path.join(_SAVE_DIR, f"ir_cells_{timestamp}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cells, f, indent=2, ensure_ascii=False)
        debug_log(f"[IR-DET] Gespeichert: {path} ({len(cells)} IR-Cells)")
    except Exception as exc:
        debug_log(f"[IR-DET] Speicherfehler: {exc}")


def load_latest_ir_cells() -> list:
    """
    Hilfsfunktion: Lädt die neueste ir_cells_*.json.
    Gibt leere Liste zurück wenn keine Datei vorhanden.
    """
    files = sorted(glob(os.path.join(_SAVE_DIR, "ir_cells_*.json")))
    if not files:
        return []
    try:
        with open(files[-1], "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


if __name__ == "__main__":
    cells = detect_ir_cells()
    print(f"[IR-DET] {len(cells)} IR-Cells erkannt:")
    for c in cells:
        print(f"  {c['ir_id']}: lat={c['lat']} lon={c['lon']} "
              f"bt_min={c['bt_min_k']} K area={c['area_px']} px "
              f"overshooting={c['overshooting_top']}")
