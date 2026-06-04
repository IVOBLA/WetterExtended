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
    IR_MIN_CAPE_J_KG,
    IR_MAX_LI_C,
    LAPSE_RATE,
)
from debug_utils import debug_log, log_api_failure

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


def _uint8_to_bt(pixel_arr: np.ndarray) -> np.ndarray:
    """uint8-Pixel → Brightness Temperature [K]."""
    bt = pixel_arr.astype(np.float32)
    bt[bt <= EUMETVIEW_NODATA_PIXEL] = np.nan
    scale = (EUMETVIEW_BT_MAX_K - EUMETVIEW_BT_MIN_K) / 255.0
    return EUMETVIEW_BT_MAX_K - scale * bt


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


def detect_ir_cells(timestamp: str | None = None) -> list:
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

    if timestamp is None:
        timestamp = datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")

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
            threshold = float(IR_CONVECTION_BT_THRESHOLD_K)
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

                if area_px < IR_MIN_CELL_AREA_PX:
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
                cloud_h = _bt_to_height_m(bt_min)

                # CAPE / LI aus Snapshot
                cape_val, li_val = _lookup_atm(lat_c, lon_c, snapshot)

                # ── CAPE/LI-Filter ─────────────────────────────────────────
                # Nur anwenden wenn Atmosphären-Daten verfügbar sind.
                # cape_val = None → kein ATM-Ort in Reichweite → nicht filtern.
                if cape_val is not None:
                    if IR_MIN_CAPE_J_KG > 0 and cape_val < IR_MIN_CAPE_J_KG:
                        debug_log(
                            f"[IR-DET] Cluster {label_num}/{n_labels} verworfen: "
                            f"CAPE={cape_val:.0f} < {IR_MIN_CAPE_J_KG} J/kg"
                        )
                        continue
                if li_val is not None:
                    if IR_MAX_LI_C < 0 and li_val > IR_MAX_LI_C:
                        debug_log(
                            f"[IR-DET] Cluster {label_num}/{n_labels} verworfen: "
                            f"LI={li_val:.2f} > {IR_MAX_LI_C} °C (zu stabil)"
                        )
                        continue

                cells.append({
                    "ir_id":            f"ir_{cell_idx}",
                    "lat":              round(lat_c, 5),
                    "lon":              round(lon_c, 5),
                    "bt_min_k":         round(bt_min, 2),
                    "bt_mean_k":        round(bt_mean, 2),
                    "area_px":          area_px,
                    "overshooting_top": overshooting,
                    "cloud_height_m":   cloud_h,
                    "cape":             round(cape_val, 1) if cape_val is not None else 0.0,
                    "arome_li":         round(li_val,  2) if li_val  is not None else 0.0,
                    "timestamp":        timestamp,
                    "tiff_file":        tiff_name,
                })
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
