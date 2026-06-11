# climatology_features.py
"""
P-S05: Reichert Zellobjekte mit Zellalter und Klimatologie-Prior-Features an.

Quelle: train_data/statistics/climatology_grid.json (von stats_aggregator erzeugt).
KEIN externer API-Call. Wird in main.py VOR predict_positions() und VOR dem JSON-Save
aufgerufen → Train/Inference-Konsistenz (B108-Prinzip).

Unzuverlässige Gitterzellen (n < CLIM_MIN_SAMPLES) → clim_*-Werte 0.0 (Modell lernt
"fehlend", B95-Pattern). cell_age_min ist immer gesetzt.
"""

import json
import math
import os
from datetime import datetime

from config import CLIM_GRID_DEG, CLIM_FEATURES_ENABLED, SAVE_PATHS


def debug_log(message):
    print(message)

_TS_FMT = "%Y-%m-%d_%H-%M-%S"
_CACHE = {"mtime": None, "cells": {}, "grid_deg": float(CLIM_GRID_DEG), "max_n": 0}

_CLIM_KEYS = ("clim_cell_freq", "clim_dir_cos", "clim_dir_sin", "clim_mean_lifetime_min")


def _grid_path():
    d = SAVE_PATHS.get("statistics", "train_data/statistics/")
    return os.path.join(d.rstrip("/"), "climatology_grid.json")


def _load_grid():
    """Lädt das Raster gecacht; reloaded nur bei geänderter mtime."""
    path = _grid_path()
    if not os.path.exists(path):
        _CACHE.update(mtime=None, cells={}, max_n=0)
        return _CACHE
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return _CACHE
    if _CACHE["mtime"] == mtime:
        return _CACHE
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        debug_log(f"[P-S05] climatology_grid Lesefehler: {exc}")
        return _CACHE
    cells = data.get("cells", {}) or {}
    # Normierungsbasis: größtes n über alle ZUVERLÄSSIGEN Zell-Monate.
    max_n = 0
    for months in cells.values():
        for c in months.values():
            if c.get("reliable") and int(c.get("n", 0)) > max_n:
                max_n = int(c.get("n", 0))
    _CACHE.update(
        mtime=mtime,
        cells=cells,
        grid_deg=float(data.get("grid_deg", CLIM_GRID_DEG)),
        max_n=max_n,
    )
    debug_log(f"[P-S05] climatology_grid geladen: {len(cells)} Zellen, max_n={max_n}")
    return _CACHE


def _grid_key(lat, lon, step):
    gl = math.floor(lat / step) * step
    go = math.floor(lon / step) * step
    return f"{gl:.2f}_{go:.2f}"


def _cell_age_min(obj, ts_dt):
    fs = obj.get("first_seen")
    if not fs or ts_dt is None:
        return 0.0
    try:
        d0 = datetime.strptime(fs, _TS_FMT)
    except (ValueError, TypeError):
        return 0.0
    age = (ts_dt - d0).total_seconds() / 60.0
    return round(age, 1) if age >= 0 else 0.0


def enrich_objects(objects, timestamp):
    """
    Setzt cell_age_min + clim_*-Features auf jedem Objekt (in-place).
    Muss VOR predict_positions() und VOR dem JSON-Save laufen.
    """
    try:
        ts_dt = datetime.strptime(timestamp, _TS_FMT)
    except (ValueError, TypeError):
        ts_dt = None

    cache = _load_grid()
    cells = cache["cells"]
    step = cache["grid_deg"] or float(CLIM_GRID_DEG)
    max_n = cache["max_n"]
    month = str(ts_dt.month) if ts_dt else None

    for obj in objects or []:
        # cell_age_min — immer
        obj["cell_age_min"] = _cell_age_min(obj, ts_dt)

        # clim_* — Default 0.0
        for k in _CLIM_KEYS:
            obj[k] = 0.0

        if not CLIM_FEATURES_ENABLED or month is None or not cells:
            continue
        lat, lon = obj.get("lat"), obj.get("lon")
        if lat is None or lon is None:
            continue
        try:
            cell = cells.get(_grid_key(float(lat), float(lon), step), {}).get(month)
        except (TypeError, ValueError):
            cell = None
        if not cell or not cell.get("reliable"):
            continue  # unzuverlässig → 0.0 (Modell lernt "fehlend")

        n = int(cell.get("n", 0))
        obj["clim_cell_freq"] = round(min(n / max_n, 1.0), 4) if max_n > 0 else 0.0
        obj["clim_dir_cos"] = float(cell.get("dir_cos", 0.0) or 0.0)
        obj["clim_dir_sin"] = float(cell.get("dir_sin", 0.0) or 0.0)
        lt = cell.get("mean_lifetime_min")
        obj["clim_mean_lifetime_min"] = float(lt) if lt is not None else 0.0

    return objects
