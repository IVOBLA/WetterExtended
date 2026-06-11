"""
P-S02: Rekonstruiert historische Track-Enden aus train_data/evaluation/cells_log.jsonl
und schreibt sie nach train_data/statistics/track_ends_backfill.jsonl.

cells_log.jsonl-Schema pro Zeile:
  {"ts": "YYYY-MM-DD_HH-MM-SS", "count": N,
   "cells": [{"id","lat","lon","size","core_ratio","missing","lineage","vx","vy"}, ...]}

Rekonstruiert pro Zell-ID: first/last ts, Pfad (lat/lon-Folge), zirkuläre Richtung,
Lebensdauer, mittlere Geschwindigkeit. Severity/Hagel sind in cells_log NICHT
enthalten -> max_severity_level/max_hail_cat = null (keine erfundenen Werte).

Wird einmalig vor dem ersten aggregate(reset=True) ausgeführt. Idempotent: erzeugt
die Backfill-Datei jedes Mal neu (deterministisch aus cells_log).
"""

import json
import math
import os
from collections import OrderedDict
from datetime import datetime

from config import SAVE_PATHS, STATS_DIR, TRACK_SEG_MIN_KM
from track_statistics import bearing_deg, circular_mean_from_sums, haversine_km


def debug_log(message):
    print(message)

_TS_FMT = "%Y-%m-%d_%H-%M-%S"


def _cells_log():
    return os.path.join(SAVE_PATHS.get("evaluation", "train_data/evaluation"), "cells_log.jsonl")


def _out_file():
    d = SAVE_PATHS.get("statistics", STATS_DIR)
    return os.path.join(d, "track_ends_backfill.jsonl")


def backfill() -> dict:
    src = _cells_log()
    if not os.path.exists(src):
        debug_log("[P-S02] backfill: keine cells_log.jsonl — übersprungen")
        return {"tracks": 0, "frames": 0}

    # Pro Track: geordnete (ts, lat, lon, vx, vy, core_ratio, lineage)
    tracks = OrderedDict()
    frames = 0
    with open(src, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = entry.get("ts")
            if not ts:
                continue
            frames += 1
            for c in entry.get("cells", []) or []:
                cid = c.get("id")
                if cid is None or c.get("lat") is None or c.get("lon") is None:
                    continue
                tracks.setdefault(cid, []).append({
                    "ts": ts,
                    "lat": float(c["lat"]),
                    "lon": float(c["lon"]),
                    "core_ratio": float(c.get("core_ratio") or 0.0),
                    "lineage": c.get("lineage"),
                })

    out = _out_file()
    os.makedirs(os.path.dirname(out), exist_ok=True)
    n = 0
    with open(out, "w", encoding="utf-8") as fo:
        for cid, pts in tracks.items():
            pts.sort(key=lambda p: p["ts"])
            if len(pts) < 2:
                # Einzelframe: keine Richtung/Lebensdauer ableitbar, dennoch zählen
                first = pts[0]
                rec = _single(cid, first)
                json.dump(rec, fo, ensure_ascii=False)
                fo.write("\n")
                n += 1
                continue
            rec = _reconstruct(cid, pts)
            json.dump(rec, fo, ensure_ascii=False)
            fo.write("\n")
            n += 1

    debug_log(f"[P-S02] backfill: {n} Tracks aus {frames} Frames -> {out}")
    return {"tracks": n, "frames": frames}


def _single(cid, p):
    return {
        "id": cid,
        "first_seen": p["ts"],
        "last_seen": p["ts"],
        "end_detected_ts": p["ts"],
        "lifetime_min": 0.0,
        "total_active_frames": 1,
        "end_reason": "backfill",
        "start_lat": round(p["lat"], 4),
        "start_lon": round(p["lon"], 4),
        "end_lat": round(p["lat"], 4),
        "end_lon": round(p["lon"], 4),
        "track_length_km": 0.0,
        "mean_dir_deg": None,
        "dir_consistency": 0.0,
        "segment_dirs_deg": [],
        "path_points": [[round(p["lat"], 4), round(p["lon"], 4)]],
        "mean_speed_kmh": None,
        "stationary_frames": 0,
        "max_core_ratio": round(p["core_ratio"], 3),
        "max_severity_level": None,
        "max_hail_cat": None,
        "max_hail_prob": None,
        "max_lightning_10km": None,
        "lineage": p.get("lineage"),
        "parents": [],
        "children": [],
        "source": "backfill",
    }


def _reconstruct(cid, pts):
    s_sin = s_cos = w = 0.0
    seg_dirs = []
    path_len = 0.0
    max_core = 0.0
    path_points = []
    speed_sum = 0.0
    speed_n = 0
    for i, p in enumerate(pts):
        max_core = max(max_core, p["core_ratio"])
        path_points.append([round(p["lat"], 4), round(p["lon"], 4)])
        if i == 0:
            continue
        prev = pts[i - 1]
        seg = haversine_km(prev["lat"], prev["lon"], p["lat"], p["lon"])
        path_len += seg
        dt = _dt_min(prev["ts"], p["ts"])
        if dt and dt > 0:
            speed_sum += (seg / dt) * 60.0
            speed_n += 1
        if seg >= float(TRACK_SEG_MIN_KM):
            b = bearing_deg(prev["lat"], prev["lon"], p["lat"], p["lon"])
            s_sin += seg * math.sin(math.radians(b))
            s_cos += seg * math.cos(math.radians(b))
            w += seg
            seg_dirs.append(round(b, 1))
    dir_mean, dir_cons = circular_mean_from_sums(s_sin, s_cos, w)
    lifetime = _dt_min(pts[0]["ts"], pts[-1]["ts"])
    return {
        "id": cid,
        "first_seen": pts[0]["ts"],
        "last_seen": pts[-1]["ts"],
        "end_detected_ts": pts[-1]["ts"],
        "lifetime_min": round(lifetime, 1) if lifetime is not None else None,
        "total_active_frames": len(pts),
        "end_reason": "backfill",
        "start_lat": round(pts[0]["lat"], 4),
        "start_lon": round(pts[0]["lon"], 4),
        "end_lat": round(pts[-1]["lat"], 4),
        "end_lon": round(pts[-1]["lon"], 4),
        "track_length_km": round(path_len, 2),
        "mean_dir_deg": dir_mean,
        "dir_consistency": dir_cons,
        "segment_dirs_deg": seg_dirs[-500:],
        "path_points": path_points[-500:],
        "mean_speed_kmh": round(speed_sum / speed_n, 1) if speed_n else None,
        "stationary_frames": 0,
        "max_core_ratio": round(max_core, 3),
        "max_severity_level": None,
        "max_hail_cat": None,
        "max_hail_prob": None,
        "max_lightning_10km": None,
        "lineage": pts[0].get("lineage"),
        "parents": [],
        "children": [],
        "source": "backfill",
    }


def _dt_min(ts1, ts2):
    try:
        d1 = datetime.strptime(ts1, _TS_FMT)
        d2 = datetime.strptime(ts2, _TS_FMT)
        return (d2 - d1).total_seconds() / 60.0
    except (ValueError, TypeError):
        return None


if __name__ == "__main__":
    print(backfill())
