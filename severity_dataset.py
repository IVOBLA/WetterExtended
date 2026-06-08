# severity_dataset.py
"""
Baut den Schwere-Trainingsdatensatz fuer Regen- und Boeen-Regression.

Targets sind ZUKUENFTIG BEOBACHTETE Werte (+SEVERITY_HORIZON_MIN) an der Zellposition,
gewonnen per Timestamp-Suche (analog dataset_builder.build_classification_dataset):

  rain_mm_h : max(nowcast_rain_rate_1h, nowcast_rr_mm15*4, station RR-Rate)  [mm/h]
  gust_kmh  : max(nowcast_ffx_kmh, station FFX, wind_gust_10m_kmh)           [km/h]

Features = letzter Frame-Vektor (identisch zu dataset_builder._frame_features):
  ML_CELL_FEATURES + ML_STATION_FEATURES + [hour_sin, hour_cos, month_sin, month_cos]

Ausgabe: train_data/dataset/tabular_severity.parquet
Fallback: zu wenige Samples -> Datei wird nicht geschrieben, dict mit samples=0.
"""

import os
import glob
import importlib.util
from datetime import datetime, timedelta

from debug_utils import debug_log
from config import (
    ML_CELL_FEATURES,
    ML_STATION_FEATURES,
    ML_SEQUENCE_LENGTH,
    SAVE_PATHS,
)

pd = importlib.import_module("pandas") if importlib.util.find_spec("pandas") else None

# dieselben Helfer wie im Haupt-Datasetbuilder verwenden (eine Quelle der Wahrheit)
from dataset_builder import _frame_features, _load_json, _parse_ts, _safe_float

SEVERITY_HORIZON_MIN = 20
_TOL_FACTOR  = 0.5
_MIN_TOL_MIN = 3.0
_MIN_SAMPLES = 30


def _rain_mm_h(obj):
    """Robuste Regenrate in mm/h aus den verfuegbaren Nowcast-/Stationsfeldern."""
    cands = [
        _safe_float(obj.get("nowcast_rain_rate_1h")),
        _safe_float(obj.get("nowcast_rr_mm15")) * 4.0,   # 15-min-Summe -> mm/h
        _safe_float(obj.get("RR")) * 6.0,                # TAWES 10-min-Summe -> mm/h
    ]
    return round(max(cands), 2)


def _gust_kmh(obj):
    # B89: arome_ff10m ist mittlerer Hintergrundwind, kein Böenwert — entfernt.
    # Böenquellen in Priorität: Nowcast-Böe → TAWES-FFX → Open-Meteo-Böe
    cands = [
        _safe_float(obj.get("nowcast_ffx_kmh")),
        _safe_float(obj.get("FFX")),
        _safe_float(obj.get("wind_gust_10m_kmh")),
    ]
    return round(max(cands), 1)


def build_severity_dataset():
    if pd is None:
        debug_log("[SEVERITY-DS] Abbruch: pandas fehlt")
        return {"samples": 0}

    obj_files  = sorted(glob.glob(os.path.join(SAVE_PATHS["objects"], "*.json")))
    wthr_files = sorted(glob.glob(os.path.join(SAVE_PATHS["weather"], "*.json")))
    weather_by_name = {os.path.basename(p): p for p in wthr_files}
    paired = [(op, weather_by_name[os.path.basename(op)])
              for op in obj_files if os.path.basename(op) in weather_by_name]

    min_required = ML_SEQUENCE_LENGTH + 1
    if len(paired) < min_required:
        debug_log(f"[SEVERITY-DS] Zu wenige Frames: {len(paired)} < {min_required}")
        return {"samples": 0}

    frames = []
    for op, wp in paired:
        try:
            frames.append((_parse_ts(op), _load_json(op), _load_json(wp)))
        except Exception as exc:
            debug_log(f"[SEVERITY-DS] Ladefehler {op}: {exc}")
    frames.sort(key=lambda e: e[0])

    rows = []
    feat_cols = ML_CELL_FEATURES + ML_STATION_FEATURES + ["hour_sin", "hour_cos", "month_sin", "month_cos"]

    for i in range(ML_SEQUENCE_LENGTH - 1, len(frames)):
        seq_slice = frames[i - ML_SEQUENCE_LENGTH + 1: i + 1]
        now_ts   = seq_slice[-1][0]
        now_objs = seq_slice[-1][1]
        now_map  = {str(o.get("id")): o for o in now_objs if isinstance(o, dict) and "id" in o}

        target_ts = now_ts + timedelta(minutes=SEVERITY_HORIZON_MIN)
        tol = timedelta(minutes=max(SEVERITY_HORIZON_MIN * _TOL_FACTOR, _MIN_TOL_MIN))
        best_idx, best_diff = None, timedelta(days=999)
        for j in range(i + 1, len(frames)):
            diff = abs(frames[j][0] - target_ts)
            if diff < best_diff:
                best_diff, best_idx = diff, j
            if frames[j][0] > target_ts + tol:
                break
        if best_idx is None or best_diff > tol:
            continue
        fut_map = {str(o.get("id")): o for o in frames[best_idx][1] if isinstance(o, dict) and "id" in o}

        for oid in set(now_map.keys()) & set(fut_map.keys()):
            seq_features, valid = [], True
            for ts, objs, stations in seq_slice:
                obj = next((o for o in objs if str(o.get("id")) == oid), None)
                if obj is None:
                    valid = False
                    break
                seq_features.append(_frame_features(obj, stations, ts))
            if not valid:
                continue
            obj_fut = fut_map[oid]
            row = {k: v for k, v in zip(feat_cols, seq_features[-1])}
            row["rain_mm_h"] = _rain_mm_h(obj_fut)
            row["gust_kmh"]  = _gust_kmh(obj_fut)
            row["id"] = oid
            row["timestamp"] = now_ts.strftime("%Y-%m-%d_%H-%M-%S")
            rows.append(row)

    if len(rows) < _MIN_SAMPLES:
        debug_log(f"[SEVERITY-DS] Zu wenige Samples: {len(rows)} < {_MIN_SAMPLES} — Datei nicht geschrieben")
        return {"samples": len(rows)}

    os.makedirs(SAVE_PATHS["dataset"], exist_ok=True)
    out_path = os.path.join(SAVE_PATHS["dataset"], "tabular_severity.parquet")
    pd.DataFrame(rows).to_parquet(out_path, index=False)
    debug_log(f"[SEVERITY-DS] {len(rows)} Samples -> {out_path}")
    return {"samples": len(rows), "path": out_path}


if __name__ == "__main__":
    print(build_severity_dataset())
