# severity_training.py
"""
Trainiert zwei LightGBM-Regressoren fuer die Schwere-Vorhersage:

  lgbm_severity_rain.txt  -> rain_mm_h  (mm/h)
  lgbm_severity_gust.txt  -> gust_kmh   (km/h)

Datenquelle: train_data/dataset/tabular_severity.parquet (severity_dataset.py)
Validierung: zeitbasierter Holdout (letzte 20 % als Test).
Metriken:    train_data/models/current/severity_metrics.json (MAE je Ziel).

Fallback: zu wenige Samples oder fehlende Libs -> kein Modell gespeichert, status='skipped'.
"""

import os
import json
import importlib.util
from datetime import datetime

from debug_utils import debug_log
from config import ML_CELL_FEATURES, ML_STATION_FEATURES, SAVE_PATHS

lgb = importlib.import_module("lightgbm") if importlib.util.find_spec("lightgbm") else None
np  = importlib.import_module("numpy")    if importlib.util.find_spec("numpy")    else None
pd  = importlib.import_module("pandas")   if importlib.util.find_spec("pandas")   else None

_MIN_SAMPLES = 50
_MODEL_DIR   = os.path.join(SAVE_PATHS["models"], "current")
_FEAT_COLS   = ML_CELL_FEATURES + ML_STATION_FEATURES + ["hour_sin", "hour_cos", "month_sin", "month_cos"]

_LGB_PARAMS = {
    "objective": "regression_l1",   # MAE-robust gegen Ausreisser (Starkregen/Boeen)
    "num_leaves": 31,
    "learning_rate": 0.05,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "min_data_in_leaf": 20,
    "verbose": -1,
}


def _train_one(df, target, model_name):
    X = df[_FEAT_COLS].astype(float).values
    y = df[target].astype(float).values
    n = len(df)
    split = int(n * 0.8)
    Xtr, Xte = X[:split], X[split:]
    ytr, yte = y[:split], y[split:]

    dtrain = lgb.Dataset(Xtr, label=ytr, feature_name=_FEAT_COLS)
    dvalid = lgb.Dataset(Xte, label=yte, reference=dtrain) if len(Xte) > 0 else None

    booster = lgb.train(
        _LGB_PARAMS, dtrain,
        num_boost_round=300,
        valid_sets=[dvalid] if dvalid else None,
        callbacks=[lgb.early_stopping(30, verbose=False)] if dvalid else None,
    )
    mae = None
    if len(Xte) > 0:
        pred = booster.predict(Xte)
        mae = float(np.mean(np.abs(pred - yte)))
    out_path = os.path.join(_MODEL_DIR, model_name)
    booster.save_model(out_path)
    debug_log(f"[SEVERITY-TRAIN] {model_name} gespeichert (holdout MAE={mae})")
    return mae


def train_severity_models():
    if lgb is None or np is None or pd is None:
        debug_log("[SEVERITY-TRAIN] Skip: lightgbm/numpy/pandas fehlt")
        return {"status": "skipped", "reason": "deps"}

    path = os.path.join(SAVE_PATHS["dataset"], "tabular_severity.parquet")
    if not os.path.exists(path):
        debug_log("[SEVERITY-TRAIN] Skip: tabular_severity.parquet fehlt (Prompt 2 ausfuehren)")
        return {"status": "skipped", "reason": "no_dataset"}

    df = pd.read_parquet(path)
    if "timestamp" in df.columns:
        df = df.sort_values("timestamp").reset_index(drop=True)
    if len(df) < _MIN_SAMPLES:
        debug_log(f"[SEVERITY-TRAIN] Skip: {len(df)} < {_MIN_SAMPLES} Samples")
        return {"status": "skipped", "reason": "too_few", "samples": len(df)}

    missing = [c for c in _FEAT_COLS if c not in df.columns]
    if missing:
        debug_log(f"[SEVERITY-TRAIN] Skip: Feature-Spalten fehlen: {missing[:5]}...")
        return {"status": "skipped", "reason": "feature_mismatch"}

    os.makedirs(_MODEL_DIR, exist_ok=True)
    mae_rain = _train_one(df, "rain_mm_h", "lgbm_severity_rain.txt")
    mae_gust = _train_one(df, "gust_kmh",  "lgbm_severity_gust.txt")

    metrics = {
        "trained_at": datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S"),
        "samples": int(len(df)),
        "mae_rain_mm_h": mae_rain,
        "mae_gust_kmh": mae_gust,
    }
    with open(os.path.join(_MODEL_DIR, "severity_metrics.json"), "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)
    debug_log(f"[SEVERITY-TRAIN] fertig: {metrics}")
    return {"status": "ok", **metrics}


if __name__ == "__main__":
    print(train_severity_models())
