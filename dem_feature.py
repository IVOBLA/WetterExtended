import os
import math

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

try:
    import rasterio
    from rasterio.transform import rowcol
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
DEM_FILE = os.path.join(DEM_DIR, "dem_kaernten.tif")

# Copernicus GLO-30 DEM — öffentlich verfügbar, keine Registrierung nötig.
# Kachel für Österreich/Kärnten: N46 E013
DEM_URL = (
    "https://copernicus-dem-30m.s3.amazonaws.com/"
    "Copernicus_DSM_COG_10_N46_00_E013_00_DEM/"
    "Copernicus_DSM_COG_10_N46_00_E013_00_DEM.tif"
)

_dem_dataset = None


def _ensure_dem() -> bool:
    """Lädt das DEM einmalig herunter. Danach nur noch Cache."""
    global _dem_dataset
    if _dem_dataset is not None:
        return True
    if not HAS_RASTERIO or not HAS_NUMPY:
        return False
    os.makedirs(DEM_DIR, exist_ok=True)
    if not os.path.exists(DEM_FILE):
        try:
            import requests
            debug_log("[DEM] Lade Copernicus DEM (einmalig, ~30 MB)...")
            r = requests.get(DEM_URL, timeout=120, stream=True)
            r.raise_for_status()
            with open(DEM_FILE, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    f.write(chunk)
            debug_log(f"[DEM] Gespeichert: {DEM_FILE}")
        except Exception as exc:
            debug_log(f"[DEM] Download fehlgeschlagen: {exc}")
            return False
    try:
        _dem_dataset = rasterio.open(DEM_FILE)
        return True
    except Exception as exc:
        debug_log(f"[DEM] Öffnen fehlgeschlagen: {exc}")
        return False


def get_dem_features(lat: float, lon: float, vx: float = 0.0, vy: float = 0.0) -> dict:
    """Gibt DEM-Features für eine Zellen-Position zurück.
    Fallback auf 0.0 wenn DEM nicht verfügbar.
    """
    default = {"dem_elevation_m": 0.0, "dem_slope_toward_cell": 0.0}
    if not _ensure_dem():
        return default
    try:
        radius_deg = 0.045  # ~5 km
        offsets = [-radius_deg / 2, 0.0, radius_deg / 2]
        heights = []
        data = _dem_dataset.read(1)
        for dlat in offsets:
            for dlon in offsets:
                row, col = rowcol(_dem_dataset.transform, lon + dlon, lat + dlat)
                row = max(0, min(data.shape[0] - 1, row))
                col = max(0, min(data.shape[1] - 1, col))
                val = float(data[row, col])
                if val > -9000:
                    heights.append(val)
        if not heights:
            return default
        mean_elev = round(sum(heights) / len(heights), 1)
        slope_toward = 0.0
        speed = math.hypot(vx, vy)
        if speed > 0.5 and len(heights) == 9:
            scale = radius_deg * 111_000  # Grad → Meter
            grad_x = (heights[5] - heights[3]) / (2 * scale)
            grad_y = (heights[7] - heights[1]) / (2 * scale)
            nx, ny = vx / speed, vy / speed
            slope_toward = round(grad_x * nx + grad_y * ny, 6)
        return {"dem_elevation_m": mean_elev, "dem_slope_toward_cell": slope_toward}
    except Exception as exc:
        debug_log(f"[DEM] Fehler bei {lat},{lon}: {exc}")
        return default


if __name__ == "__main__":
    result = get_dem_features(46.6228, 14.3050, vx=2.0, vy=-1.0)
    print(f"Klagenfurt: {result}")
