# intensity_regression.py
"""
Trainiert zwei LightGBM-Regressionsmodelle als Ersatz für den binären
Intensification-Classifier:

  lgbm_intensity_delta_core.txt  → Vorhersage von Δcore_ratio (nach 20 Min.)
  lgbm_intensity_delta_area.txt  → Vorhersage von Δarea_pct   (nach 20 Min.)

Ziel-Variablen (continuous):
  delta_core_ratio = core_ratio_future − core_ratio_now        (Einheit: [0..1])
  delta_area_pct   = (area_future − area_now) / area_now       (Einheit: Anteil)

Beide Modelle verwenden dieselben Features wie der Positions-LightGBM
(letzter Frame der Sequenz → 1-D Feature-Vektor).

Fallback: Wenn zu wenige Samples vorliegen, werden keine Modelle gespeichert
und prediction.py gibt 0.0 zurück.
"""

import os
import glob
import json
import importlib.util
from datetime import datetime
from math import cos, pi, sin

from debug_utils import debug_log
from config import (
    ML_CELL_FEATURES,
    ML_STATION_FEATURES,
    ML_SEQUENCE_LENGTH,
    SAVE_PATHS,
)

lgb      = importlib.import_module("lightgbm") if importlib.util.find_spec("lightgbm") else None
np       = importlib.import_module("numpy")    if importlib.util.find_spec("numpy")    else None
joblib   = importlib.import_module("joblib")   if importlib.util.find_spec("joblib")   else None
pd       = importlib.import_module("pandas")   if importlib.util.find_spec("pandas")   else None

_HORIZON_STEP = 4      # 4 Frames × ~5 Min = 20 Min Vorhersagehorizont
_MIN_SAMPLES  = 30     # Mindest-Samples für sinnvolles Training
_MODEL_DIR    = os.path.join(SAVE_PATHS["models"], "current")

try:
    from utils import find_nearest_station
except Exception:
    def find_nearest_station(lat, lon, stations): return None

try:
    from geo_utils import pixel_to_geo
except Exception:
    def pixel_to_geo(x, y): return 0.0, 0.0


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _safe_float(v):
    try: return float(v)
    except: return 0.0


def _merge_contaminated(o_now, o_fut):
    """P-M04: True, wenn Jetzt- ODER Ziel-Frame eine Merge-Diskontinuität trägt.
    An solchen Frames ist der Flächen-/Kern-Sprung ein Tracking-Artefakt, kein
    physikalischer Trend → Sample für Δ-Label-Training ausschließen."""
    try:
        if int(o_now.get("merge_discontinuity", 0)) == 1:
            return True
        if int(o_fut.get("merge_discontinuity", 0)) == 1:
            return True
    except (AttributeError, TypeError, ValueError):
        return False
    return False


def _parse_ts(path):
    name = os.path.splitext(os.path.basename(path))[0]
    return datetime.strptime(name, "%Y-%m-%d_%H-%M-%S")


def _load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _frame_features(obj, stations, ts):
    """Baut den 1-D Feature-Vektor identisch zu dataset_builder._frame_features."""
    cell_feats = [_safe_float(obj.get(k, 0.0)) for k in ML_CELL_FEATURES]
    # Fix P02: lat/lon direkt aus obj — pixel_to_geo() würde pre-upscale
    # x/y fälschlich erneut herunterskalieren.
    _lat_obj = obj.get("lat")
    _lon_obj = obj.get("lon")
    if _lat_obj is not None and _lon_obj is not None:
        lat = float(_lat_obj)
        lon = float(_lon_obj)
    else:
        try:
            from config import UPSCALE_FACTOR as _UF_IR
        except Exception:
            _UF_IR = 3.0
        _ox = _safe_float(obj.get("x", 0.0)) * float(_UF_IR)
        _oy = _safe_float(obj.get("y", 0.0)) * float(_UF_IR)
        lat, lon = pixel_to_geo(_ox, _oy)
    nearest = find_nearest_station(lat, lon, stations) if stations else None
    stat_feats = [
        _safe_float(nearest.get(k, 0.0)) if nearest else 0.0
        for k in ML_STATION_FEATURES
    ]
    hf = (ts.hour * 60 + ts.minute) / (24 * 60)
    ha = 2 * pi * hf
    mf = (ts.month - 1) / 12.0
    ma = 2 * pi * mf
    return cell_feats + stat_feats + [sin(ha), cos(ha), sin(ma), cos(ma)]


# ---------------------------------------------------------------------------
# Dataset aufbauen
# ---------------------------------------------------------------------------

def build_regression_intensity_dataset():
    """
    Liest Objekt- und Wetterdateien und baut ein DataFrame mit:
      Features: letzter Frame-Vektor (alle ML_CELL + ML_STATION + Zeit-Features)
      Targets:  delta_core_ratio, delta_area_pct  (nach _HORIZON_STEP Frames)

    Gibt DataFrame zurück oder None bei zu wenigen Samples.
    """
    if None in (np, pd, lgb):
        debug_log("[INTREG] Abbruch: fehlende Abhängigkeiten (numpy/pandas/lightgbm)")
        return None

    obj_files  = sorted(glob.glob(os.path.join(SAVE_PATHS["objects"], "*.json")))
    wthr_files = sorted(glob.glob(os.path.join(SAVE_PATHS["weather"], "*.json")))
    weather_by = {os.path.basename(p): p for p in wthr_files}

    paired = [
        (op, weather_by[os.path.basename(op)])
        for op in obj_files if os.path.basename(op) in weather_by
    ]
    min_needed = ML_SEQUENCE_LENGTH + _HORIZON_STEP + 1
    if len(paired) < min_needed:
        debug_log(f"[INTREG] Zu wenige Frames ({len(paired)} < {min_needed})")
        return None

    # Alle Frames vorladen
    frames = []
    for op, wp in paired:
        try:
            frames.append((_parse_ts(op), _load_json(op), _load_json(wp)))
        except Exception as exc:
            debug_log(f"[INTREG] Ladefehler {op}: {exc}")

    rows = []
    _n_merge_skipped = 0
    for i in range(ML_SEQUENCE_LENGTH - 1, len(frames) - _HORIZON_STEP):
        ts_now, objs_now, stations_now = frames[i]
        _, objs_fut, _               = frames[i + _HORIZON_STEP]

        now_map = {str(o.get("id")): o for o in objs_now if isinstance(o, dict) and "id" in o}
        fut_map = {str(o.get("id")): o for o in objs_fut if isinstance(o, dict) and "id" in o}
        common  = set(now_map.keys()) & set(fut_map.keys())

        for oid in common:
            o_now = now_map[oid]
            o_fut = fut_map[oid]

            # P-M04: Merge-kontaminierte Frames ausschließen (künstlicher Sprung).
            if _merge_contaminated(o_now, o_fut):
                _n_merge_skipped += 1
                continue

            feats = _frame_features(o_now, stations_now, ts_now)
            if len(feats) == 0:
                continue

            core_now  = _safe_float(o_now.get("core_ratio", 0.0))
            core_fut  = _safe_float(o_fut.get("core_ratio", 0.0))
            area_now  = max(_safe_float(o_now.get("area", 1.0)), 1.0)
            area_fut  = _safe_float(o_fut.get("area", 0.0))

            delta_core = core_fut - core_now
            delta_area = (area_fut - area_now) / area_now   # relativer Anteil

            feat_names = (
                ML_CELL_FEATURES + ML_STATION_FEATURES
                + ["hour_sin", "hour_cos", "month_sin", "month_cos"]
            )
            row = dict(zip(feat_names, feats))
            row["delta_core_ratio"] = float(delta_core)
            row["delta_area_pct"]   = float(delta_area)
            row["id"]        = oid
            row["timestamp"] = ts_now.strftime("%Y-%m-%d_%H-%M-%S")
            rows.append(row)

    if len(rows) < _MIN_SAMPLES:
        debug_log(f"[INTREG] Nur {len(rows)} Samples — zu wenig für Training")
        return None

    df = pd.DataFrame(rows)
    debug_log(f"[INTREG] Dataset: {len(df)} Samples gebaut "
              f"({_n_merge_skipped} Merge-kontaminierte Samples übersprungen, P-M04)")
    return df


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train_intensity_regressors():
    """
    Trainiert delta_core und delta_area LightGBM-Regressoren und speichert sie.
    Gibt dict mit Trainings-Meta zurück.
    """
    if lgb is None:
        debug_log("[INTREG] LightGBM nicht verfügbar — Training übersprungen")
        return {"trained": False, "reason": "lightgbm missing"}

    df = build_regression_intensity_dataset()
    if df is None:
        return {"trained": False, "reason": "insufficient data"}

    os.makedirs(_MODEL_DIR, exist_ok=True)
    feat_cols = [
        c for c in df.columns
        if c not in ("delta_core_ratio", "delta_area_pct", "id", "timestamp")
    ]
    X = df[feat_cols].values.astype(float)

    meta = {}
    for target_col, model_name in [
        ("delta_core_ratio", "lgbm_intensity_delta_core"),
        ("delta_area_pct",   "lgbm_intensity_delta_area"),
    ]:
        y = df[target_col].values.astype(float)
        train_data = lgb.Dataset(X, label=y)
        params = {
            "objective":   "regression",
            "metric":      "rmse",
            "n_estimators": 300,
            "learning_rate": 0.05,
            "num_leaves":  31,
            "min_child_samples": 10,
            "verbose": -1,
        }
        try:
            booster = lgb.train(
                params,
                train_data,
                num_boost_round=params.pop("n_estimators"),
                valid_sets=[train_data],
                callbacks=[lgb.log_evaluation(period=-1)],
            )
            out_path = os.path.join(_MODEL_DIR, f"{model_name}.txt")
            booster.save_model(out_path)
            debug_log(f"[INTREG] Modell gespeichert: {out_path}")
            meta[target_col] = {"trained": True, "samples": len(df)}
        except Exception as exc:
            debug_log(f"[INTREG] Training fehlgeschlagen ({target_col}): {exc}")
            meta[target_col] = {"trained": False, "error": str(exc)}

    return {"trained": True, "meta": meta}


# ---------------------------------------------------------------------------
# Inference-Helper (wird von prediction.py genutzt)
# ---------------------------------------------------------------------------

def load_intensity_regressors():
    """
    Lädt die beiden Regressionsmodelle.
    Gibt (model_core, model_area) zurück — beide können None sein.
    """
    if lgb is None:
        return None, None

    def _load(name):
        path = os.path.join(_MODEL_DIR, f"{name}.txt")
        if not os.path.exists(path):
            return None
        try:
            return lgb.Booster(model_file=path)
        except Exception as e:
            debug_log(f"[INTREG] Laden fehlgeschlagen ({name}): {e}")
            return None

    return _load("lgbm_intensity_delta_core"), _load("lgbm_intensity_delta_area")


if __name__ == "__main__":
    result = train_intensity_regressors()
    print(result)
