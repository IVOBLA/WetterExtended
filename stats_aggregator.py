"""
P-S02: Aggregiert train_data/evaluation/track_ends.jsonl zu Jahres-Statistiken
und zum Klimatologie-Raster (ML-Quelle für P-S05).

Output:
  train_data/statistics/stats_<YYYY>.json
  train_data/statistics/climatology_grid.json
  train_data/statistics/_aggregate_state.json  (Watermark, Roh-Akkumulatoren)

Idempotent: verarbeitet jede track_ends-Zeile genau einmal (Watermark = Byte-Offset
PLUS Track-ID-Set des laufenden Jahres als Doppelschutz). Roh-Akkumulatoren werden
persistiert, damit zirkuläre Mittel ohne erneutes Vollscan-Lesen fortschreibbar sind.
"""

import json
import math
import os
from datetime import datetime

from config import (
    CLIM_BBOX,
    CLIM_GRID_DEG,
    CLIM_MIN_SAMPLES,
    SAVE_PATHS,
    STATS_DIR,
    STATS_LIFETIME_BINS_MIN,
    STATS_SPEED_BINS_KMH,
)
from track_statistics import circular_mean_from_sums


def debug_log(message):
    print(message)

_TS_FMT = "%Y-%m-%d_%H-%M-%S"


def _stats_dir():
    return SAVE_PATHS.get("statistics", STATS_DIR)


def _track_ends_file():
    return os.path.join(SAVE_PATHS.get("evaluation", "train_data/evaluation"), "track_ends.jsonl")


def _state_file():
    return os.path.join(_stats_dir(), "_aggregate_state.json")


def _parse_ts(s):
    try:
        return datetime.strptime(s, _TS_FMT)
    except (ValueError, TypeError):
        return None


def _bin_index(value, edges):
    for i in range(len(edges) - 1):
        if edges[i] <= value < edges[i + 1]:
            return i
    return len(edges) - 2


def _grid_key(lat, lon):
    step = float(CLIM_GRID_DEG)
    gl = math.floor(float(lat) / step) * step
    go = math.floor(float(lon) / step) * step
    return f"{gl:.2f}_{go:.2f}"


def _in_bbox(lat, lon):
    if lat is None or lon is None:
        return False
    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return False
    la0, la1, lo0, lo1 = CLIM_BBOX
    return la0 <= lat <= la1 and lo0 <= lon <= lo1


def _empty_year():
    return {
        "cells_total": 0,
        "by_month": [0] * 12,
        "by_day": {},          # "YYYY-MM-DD" -> count
        "by_hour": [0] * 24,
        # Intensität pro Monat: 4 Buckets [schwach, mittel, stark, hagelverdaechtig]
        "intensity_by_month": [[0, 0, 0, 0] for _ in range(12)],
        # Zirkuläre Jahres-Zugrichtung (Akkumulatoren, gewichtet nach track_length_km)
        "dir_sum_sin": 0.0,
        "dir_sum_cos": 0.0,
        "dir_w_sum": 0.0,
        "dir_rose16": [0] * 16,     # 16 Sektoren à 22.5°, ungewichtet (Track-Zahl)
        "lifetime_bins": [0] * (len(STATS_LIFETIME_BINS_MIN) - 1),
        "lifetime_sum": 0.0,
        "lifetime_n": 0,
        "speed_bins": [0] * (len(STATS_SPEED_BINS_KMH) - 1),
        "speed_sum": 0.0,
        "speed_n": 0,
        "merges": 0,
        "splits": 0,
        "stationary_tracks": 0,
        # P-S06: [summe_lebensdauer_min, n] je Intensitätsklasse
        # Index 0=schwach, 1=mittel, 2=stark, 3=hagelverdächtig
        "lifetime_by_intensity": [[0.0, 0] for _ in range(4)],
    }


def _intensity_bucket(rec):
    """0=schwach,1=mittel,2=stark,3=hagelverdaechtig. Hagel hat Vorrang."""
    if rec.get("max_hail_cat") in ("klein", "gross"):
        return 3
    lvl = rec.get("max_severity_level")
    if lvl is None:
        return 0
    try:
        lvl = int(lvl)
    except (TypeError, ValueError):
        return 0
    if lvl >= 3:
        return 2
    if lvl == 2:
        return 1
    return 0


def _load_state():
    path = _state_file()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            debug_log(f"[P-S02] State-Lesefehler, beginne neu: {exc}")
    return {"offset": 0, "seen_ids": [], "years": {}, "grid": {}}


def _save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def _accumulate_record(rec, years, grid):
    first = _parse_ts(rec.get("first_seen"))
    if first is None:
        return False
    yr = str(first.year)
    y = years.setdefault(yr, _empty_year())
    # P-S06: bestehende State-Jahre (vor P-S06) haben den Key noch nicht.
    y.setdefault("lifetime_by_intensity", [[0.0, 0] for _ in range(4)])

    y["cells_total"] += 1
    y["by_month"][first.month - 1] += 1
    y["by_hour"][first.hour] += 1
    day = first.strftime("%Y-%m-%d")
    y["by_day"][day] = y["by_day"].get(day, 0) + 1
    _intensity_b = _intensity_bucket(rec)
    y["intensity_by_month"][first.month - 1][_intensity_b] += 1

    md = rec.get("mean_dir_deg")
    w = float(rec.get("track_length_km") or 0.0)
    if md is not None and w > 0.0:
        md = float(md)
        y["dir_sum_sin"] += w * math.sin(math.radians(md))
        y["dir_sum_cos"] += w * math.cos(math.radians(md))
        y["dir_w_sum"] += w
        y["dir_rose16"][int(((md % 360.0) / 22.5)) % 16] += 1

    lt = rec.get("lifetime_min")
    if lt is not None:
        y["lifetime_bins"][_bin_index(float(lt), STATS_LIFETIME_BINS_MIN)] += 1
        y["lifetime_sum"] += float(lt)
        y["lifetime_n"] += 1
        # P-S06: Lebensdauer je Intensitätsklasse (Stärke <-> Lebensdauer-Korrelation)
        y["lifetime_by_intensity"][_intensity_b][0] += float(lt)
        y["lifetime_by_intensity"][_intensity_b][1] += 1

    sp = rec.get("mean_speed_kmh")
    if sp is not None:
        y["speed_bins"][_bin_index(float(sp), STATS_SPEED_BINS_KMH)] += 1
        y["speed_sum"] += float(sp)
        y["speed_n"] += 1

    if str(rec.get("end_reason", "")).startswith("merged_into"):
        y["merges"] += 1
    if len(rec.get("children") or []) > 1:
        y["splits"] += 1
    if int(rec.get("stationary_frames") or 0) >= 3:
        y["stationary_tracks"] += 1

    # Klimatologie-Raster (Entstehungsposition, pro Monat)
    slat, slon = rec.get("start_lat"), rec.get("start_lon")
    if _in_bbox(slat, slon):
        slat = float(slat)
        slon = float(slon)
        gk = _grid_key(slat, slon)
        cellmon = grid.setdefault(gk, {})
        m = str(first.month)
        c = cellmon.setdefault(m, {"n": 0, "sin": 0.0, "cos": 0.0, "lt_sum": 0.0, "lt_n": 0})
        c["n"] += 1
        if md is not None:
            c["sin"] += math.sin(math.radians(float(md)))
            c["cos"] += math.cos(math.radians(float(md)))
        if lt is not None:
            c["lt_sum"] += float(lt)
            c["lt_n"] += 1
    return True


def _finalize_year(yr, y):
    dir_mean, dir_cons = circular_mean_from_sums(
        y["dir_sum_sin"], y["dir_sum_cos"], y["dir_w_sum"]
    )
    return {
        "year": int(yr),
        "cells_total": y["cells_total"],
        "by_month": y["by_month"],
        "by_day": dict(sorted(y["by_day"].items())),
        "by_hour": y["by_hour"],
        "intensity_by_month": y["intensity_by_month"],
        "dominant_dir_deg": dir_mean,
        "dir_consistency": dir_cons,
        "dir_rose16": y["dir_rose16"],
        "lifetime_bins": y["lifetime_bins"],
        "lifetime_bin_edges": STATS_LIFETIME_BINS_MIN,
        "mean_lifetime_min": round(y["lifetime_sum"] / y["lifetime_n"], 1) if y["lifetime_n"] else None,
        "speed_bins": y["speed_bins"],
        "speed_bin_edges": STATS_SPEED_BINS_KMH,
        "mean_speed_kmh": round(y["speed_sum"] / y["speed_n"], 1) if y["speed_n"] else None,
        "merges": y["merges"],
        "splits": y["splits"],
        "stationary_tracks": y["stationary_tracks"],
        "mean_lifetime_by_intensity": [
            (round(s / n, 1) if n else None)
            for s, n in y.get("lifetime_by_intensity", [[0.0, 0] for _ in range(4)])
        ],
        "generated_utc": datetime.utcnow().isoformat(timespec="seconds"),
    }


def _finalize_grid(grid):
    out = {"grid_deg": CLIM_GRID_DEG, "min_samples": CLIM_MIN_SAMPLES, "cells": {}}
    for gk, months in grid.items():
        out["cells"][gk] = {}
        for m, c in months.items():
            n = int(c["n"])
            dir_mean, dir_cons = circular_mean_from_sums(c["sin"], c["cos"], float(n))
            out["cells"][gk][m] = {
                "n": n,
                "reliable": bool(n >= CLIM_MIN_SAMPLES),
                "pref_dir_deg": dir_mean,
                "dir_consistency": dir_cons,
                "dir_cos": round(math.cos(math.radians(dir_mean)), 4) if dir_mean is not None else 0.0,
                "dir_sin": round(math.sin(math.radians(dir_mean)), 4) if dir_mean is not None else 0.0,
                "mean_lifetime_min": round(c["lt_sum"] / c["lt_n"], 1) if c["lt_n"] else None,
            }
    out["generated_utc"] = datetime.utcnow().isoformat(timespec="seconds")
    return out


def aggregate(reset: bool = False) -> dict:
    """
    Liest neue track_ends-Zeilen ab Watermark und schreibt Jahres-Aggregate +
    Klimatologie-Raster. reset=True verwirft den State und liest komplett neu
    (z.B. nach Backfill).

    Rückgabe: {"processed": int, "years": [..], "grid_cells": int}
    """
    os.makedirs(_stats_dir(), exist_ok=True)
    state = {"offset": 0, "seen_ids": [], "years": {}, "grid": {}} if reset else _load_state()
    seen = set(state.get("seen_ids", []))
    years = state.get("years", {})
    grid = state.get("grid", {})

    ends = _track_ends_file()
    processed = 0
    if os.path.exists(ends):
        with open(ends, "r", encoding="utf-8") as f:
            f.seek(int(state.get("offset", 0)))
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                key = f"{rec.get('id')}|{rec.get('first_seen')}"
                if key in seen:
                    continue
                if _accumulate_record(rec, years, grid):
                    seen.add(key)
                    processed += 1
            state["offset"] = f.tell()

    # Backfill einmalig mitverarbeiten (eigener seen-Schutz via key, kein Offset).
    backfill_path = os.path.join(_stats_dir(), "track_ends_backfill.jsonl")
    if os.path.exists(backfill_path) and not state.get("backfill_done"):
        with open(backfill_path, "r", encoding="utf-8") as bf:
            for line in bf:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                key = f"{rec.get('id')}|{rec.get('first_seen')}"
                if key in seen:
                    continue
                if _accumulate_record(rec, years, grid):
                    seen.add(key)
                    processed += 1
        state["backfill_done"] = True

    # Begrenze seen_ids (Speicher): nur IDs des aktuellen + Vorjahres behalten.
    cur_year = datetime.utcnow().year
    seen = {
        k for k in seen
        if (_parse_ts(k.split("|", 1)[-1]) or datetime(1900, 1, 1)).year >= cur_year - 1
    }

    for yr, y in years.items():
        _save_json(os.path.join(_stats_dir(), f"stats_{yr}.json"), _finalize_year(yr, y))
    _save_json(os.path.join(_stats_dir(), "climatology_grid.json"), _finalize_grid(grid))

    state["seen_ids"] = sorted(seen)
    state["years"] = years
    state["grid"] = grid
    _save_json(_state_file(), state)

    debug_log(f"[P-S02] aggregate: {processed} neue Tracks, {len(years)} Jahre, {len(grid)} Rasterzellen")
    return {"processed": processed, "years": sorted(years.keys()), "grid_cells": len(grid)}
