# dem_feature.py
"""
Topographie-Features aus Copernicus GLO-30 DEM — ganz Kärnten.

Kacheln N46/N47 + E013/E014/E015 werden als Mosaic zusammengefügt.
Download einmalig (~180 MB). Danach nur In-Memory-Zugriff.

Features:
  dem_elevation_m       – mittlere Höhe im 5-km-Umkreis (m)
  dem_slope_toward_cell – Gradient in Bewegungsrichtung (m/m, pos=Stau, neg=Lee)
  dem_barrier_ahead     – Höhendiff. 10-20 km voraus minus aktuell (m, pos=Barriere)
"""
from __future__ import annotations
import math
import os
from typing import Any

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

try:
    import rasterio
    from rasterio.transform import rowcol
    from rasterio.merge import merge as _rasterio_merge
    HAS_RASTERIO = True
except ImportError:
    HAS_RASTERIO = False

try:
    from debug_utils import debug_log
except Exception:
    def debug_log(msg):
        print(msg)

from config import SAVE_PATHS

DEM_DIR = SAVE_PATHS.get("dem", "train_data/dem/")

_DEM_TILES = [
    # N46 – südlicher Bereich Kärnten
    ("dem_kaernten_N46_E013.tif",
     "https://copernicus-dem-30m.s3.amazonaws.com/"
     "Copernicus_DSM_COG_10_N46_00_E013_00_DEM/"
     "Copernicus_DSM_COG_10_N46_00_E013_00_DEM.tif"),
    ("dem_kaernten_N46_E014.tif",
     "https://copernicus-dem-30m.s3.amazonaws.com/"
     "Copernicus_DSM_COG_10_N46_00_E014_00_DEM/"
     "Copernicus_DSM_COG_10_N46_00_E014_00_DEM.tif"),
    ("dem_kaernten_N46_E015.tif",
     "https://copernicus-dem-30m.s3.amazonaws.com/"
     "Copernicus_DSM_COG_10_N46_00_E015_00_DEM/"
     "Copernicus_DSM_COG_10_N46_00_E015_00_DEM.tif"),

    # N47 – nördlicher Bereich der Extended-BBOX bis north=47.18
    ("dem_kaernten_N47_E013.tif",
     "https://copernicus-dem-30m.s3.amazonaws.com/"
     "Copernicus_DSM_COG_10_N47_00_E013_00_DEM/"
     "Copernicus_DSM_COG_10_N47_00_E013_00_DEM.tif"),
    ("dem_kaernten_N47_E014.tif",
     "https://copernicus-dem-30m.s3.amazonaws.com/"
     "Copernicus_DSM_COG_10_N47_00_E014_00_DEM/"
     "Copernicus_DSM_COG_10_N47_00_E014_00_DEM.tif"),
    ("dem_kaernten_N47_E015.tif",
     "https://copernicus-dem-30m.s3.amazonaws.com/"
     "Copernicus_DSM_COG_10_N47_00_E015_00_DEM/"
     "Copernicus_DSM_COG_10_N47_00_E015_00_DEM.tif"),
]

_mosaic_data: "np.ndarray | None" = None
_mosaic_transform: Any = None


def _download_tile(filename, url):
    path = os.path.join(DEM_DIR, filename)
    if os.path.exists(path):
        return True
    try:
        import requests
        debug_log(f"[DEM] Lade {filename} (~30 MB)...")
        r = requests.get(url, timeout=300, stream=True)
        r.raise_for_status()
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1024*1024):
                f.write(chunk)
        os.replace(tmp, path)
        debug_log(f"[DEM] {filename} gespeichert.")
        return True
    except Exception as exc:
        debug_log(f"[DEM] Download {filename} fehlgeschlagen: {exc}")
        return False


def _ensure_dem():
    global _mosaic_data, _mosaic_transform
    if _mosaic_data is not None:
        return True
    if not HAS_RASTERIO or not HAS_NUMPY:
        debug_log("[DEM] rasterio/numpy nicht verfügbar.")
        return False
    os.makedirs(DEM_DIR, exist_ok=True)
    tile_paths = [os.path.join(DEM_DIR, fn)
                  for fn, url in _DEM_TILES if _download_tile(fn, url)]
    if not tile_paths:
        debug_log("[DEM] Keine Kachel verfügbar.")
        return False
    try:
        datasets = [rasterio.open(p) for p in tile_paths]
        mosaic, mosaic_transform = _rasterio_merge(datasets)
        for ds in datasets:
            ds.close()
        arr = mosaic[0].astype(np.float32)
        arr[arr < -9000] = float("nan")
        _mosaic_data = arr
        _mosaic_transform = mosaic_transform
        debug_log(f"[DEM] Mosaic: {arr.shape[1]}x{arr.shape[0]} px, {len(tile_paths)} Kacheln.")
        return True
    except Exception as exc:
        debug_log(f"[DEM] Mosaic fehlgeschlagen: {exc}")
        return False


def _height(lat, lon):
    if _mosaic_data is None:
        return None
    try:
        row, col = rowcol(_mosaic_transform, lon, lat)
        r = max(0, min(_mosaic_data.shape[0]-1, int(row)))
        c = max(0, min(_mosaic_data.shape[1]-1, int(col)))
        v = float(_mosaic_data[r, c])
        return None if v != v else v
    except Exception:
        return None


def get_dem_features(lat, lon, vx=0.0, vy=0.0):
    default = {"dem_elevation_m": 0.0, "dem_slope_toward_cell": 0.0,
               "dem_barrier_ahead": 0.0}
    if not _ensure_dem():
        return default
    try:
        r = 0.045
        offsets = [-r/2, 0.0, r/2]
        heights = []
        for dlat in offsets:
            for dlon in offsets:
                h = _height(lat+dlat, lon+dlon)
                if h is not None:
                    heights.append(h)
        if not heights:
            return default
        mean_elev = round(sum(heights)/len(heights), 1)

        slope_toward = 0.0
        speed = math.hypot(vx, vy)
        if speed > 0.5 and len(heights) == 9:
            scale = r * 111_000
            gx = (heights[5]-heights[3])/(2*scale)
            gy = (heights[7]-heights[1])/(2*scale)
            nx, ny = vx/speed, vy/speed
            slope_toward = round(gx*nx + gy*ny, 6)

        barrier_ahead = 0.0
        if speed > 0.5:
            nx, ny = vx/speed, vy/speed
            ahead = []
            for km in (10.0, 13.0, 16.0, 20.0):
                dlat = (km/111.0)*(-ny)
                dlon = (km/(111.0*max(math.cos(math.radians(lat)), 0.01)))*nx
                h = _height(lat+dlat, lon+dlon)
                if h is not None:
                    ahead.append(h)
            if ahead:
                barrier_ahead = round(sum(ahead)/len(ahead) - mean_elev, 1)

        return {"dem_elevation_m": mean_elev,
                "dem_slope_toward_cell": slope_toward,
                "dem_barrier_ahead": barrier_ahead}
    except Exception as exc:
        debug_log(f"[DEM] Fehler ({lat:.3f},{lon:.3f}): {exc}")
        return default


if __name__ == "__main__":
    tests = [("Klagenfurt",46.6228,14.3050),("Villach",46.6111,13.8558),
             ("Wolfsberg",46.8403,14.8408),("Spittal",46.7956,13.4978),
             ("St.Veit",46.7700,14.3614)]
    for name, lat, lon in tests:
        r = get_dem_features(lat, lon, vx=2.0, vy=-1.0)
        ok = "OK" if r["dem_elevation_m"] > 0 else "FEHLER"
        print(f"  {name}: {r['dem_elevation_m']:.0f}m [{ok}]")
