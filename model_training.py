import importlib
import importlib.util
import json
import os
from datetime import datetime, timedelta, timezone

np = importlib.import_module("numpy") if importlib.util.find_spec("numpy") else None
lgb = importlib.import_module("lightgbm") if importlib.util.find_spec("lightgbm") else None
joblib = importlib.import_module("joblib") if importlib.util.find_spec("joblib") else None

if importlib.util.find_spec("sklearn"):
    train_test_split = importlib.import_module("sklearn.model_selection").train_test_split
    sklearn_metrics = importlib.import_module("sklearn.metrics")
    roc_auc_score = sklearn_metrics.roc_auc_score
    precision_score = sklearn_metrics.precision_score
    recall_score = sklearn_metrics.recall_score
else:
    train_test_split = None
    roc_auc_score = precision_score = recall_score = None

if importlib.util.find_spec("tensorflow"):
    keras_models = importlib.import_module("tensorflow.keras.models")
    keras_layers = importlib.import_module("tensorflow.keras.layers")
    keras_callbacks = importlib.import_module("tensorflow.keras.callbacks")
    keras_optimizers = importlib.import_module("tensorflow.keras.optimizers")
    Sequential = keras_models.Sequential
    load_model = keras_models.load_model
    LSTM = keras_layers.LSTM
    Dense = keras_layers.Dense
    Dropout = keras_layers.Dropout
    EarlyStopping = keras_callbacks.EarlyStopping
    ModelCheckpoint = keras_callbacks.ModelCheckpoint
    Adam = keras_optimizers.Adam
else:
    Sequential = load_model = LSTM = Dense = Dropout = EarlyStopping = ModelCheckpoint = Adam = None

from config import ML_FORECAST_HORIZONS_MIN, ML_NUM_FEATURES, ML_SEQUENCE_LENGTH, SAVE_PATHS

MODELS_ROOT = SAVE_PATHS["models"]
from dataset_builder import build_classification_dataset, build_dataset
try:
    from debug_utils import debug_log
except Exception:
    def debug_log(message):
        print(message)




def _current_models_dir():
    return os.path.join(MODELS_ROOT, "current")


def _version_models_dir(version_id):
    return os.path.join(MODELS_ROOT, version_id)


def _list_versions():
    base = MODELS_ROOT
    if not os.path.isdir(base):
        return []
    return sorted([name for name in os.listdir(base) if name.startswith("v_") and os.path.isdir(os.path.join(base, name))])


def cleanup_old_versions(keep_n=5):
    versions = _list_versions()
    for old in versions[:-keep_n]:
        old_path = _version_models_dir(old)
        for root, dirs, files in os.walk(old_path, topdown=False):
            for f in files:
                os.remove(os.path.join(root, f))
            for d in dirs:
                os.rmdir(os.path.join(root, d))
        os.rmdir(old_path)


def _atomic_switch_current(version_id):
    base_dir = MODELS_ROOT
    target = _version_models_dir(version_id)
    current_link = _current_models_dir()
    tmp_link = os.path.join(base_dir, ".current_tmp")
    if os.path.lexists(tmp_link):
        os.remove(tmp_link)
    os.symlink(os.path.relpath(target, base_dir), tmp_link)
    os.replace(tmp_link, current_link)


def evaluate_on_recent(model_dir, hours=24):
    if np is None or lgb is None or joblib is None:
        return {"mae_total": float("inf"), "mae_by_horizon": {}, "samples": 0}
    dataset_path = os.path.join(SAVE_PATHS["dataset"], "dataset.npz")
    if not os.path.exists(dataset_path):
        return {"mae_total": float("inf"), "mae_by_horizon": {}, "samples": 0}
    ds = np.load(dataset_path, allow_pickle=True)
    X = ds.get("X")
    y_raw = ds.get("y_raw")
    ids = ds.get("ids")
    if X is None or y_raw is None or ids is None or len(X) == 0:
        return {"mae_total": float("inf"), "mae_by_horizon": {}, "samples": 0}

    timestamps = []
    for item in ids.tolist():
        ts_text = item.get("timestamp") if isinstance(item, dict) else None
        ts = datetime.strptime(ts_text, "%Y-%m-%d_%H-%M-%S").replace(tzinfo=timezone.utc) if ts_text else None
        timestamps.append(ts)
    valid_ts = [ts for ts in timestamps if ts is not None]
    if not valid_ts:
        return {"mae_total": float("inf"), "mae_by_horizon": {}, "samples": 0}
    cutoff = max(valid_ts) - timedelta(hours=hours)
    idx = [i for i, ts in enumerate(timestamps) if ts is not None and ts >= cutoff]
    if not idx:
        return {"mae_total": float("inf"), "mae_by_horizon": {}, "samples": 0}

    X_recent = X[idx][:, -1, :]
    y_recent = y_raw[idx]
    scaler_y_path = os.path.join(model_dir, "scaler_y.joblib")
    if not os.path.exists(scaler_y_path):
        return {"mae_total": float("inf"), "mae_by_horizon": {}, "samples": len(idx)}
    scaler_y = joblib.load(scaler_y_path)
    y_pred_scaled = np.zeros_like(y_recent, dtype=float)

    for h_idx, horizon in enumerate(ML_FORECAST_HORIZONS_MIN):
        for axis_idx, axis in enumerate(["x", "y"]):
            col = h_idx * 2 + axis_idx
            model_path = os.path.join(model_dir, f"lgbm_h{horizon}_{axis}.txt")
            if not os.path.exists(model_path):
                return {"mae_total": float("inf"), "mae_by_horizon": {}, "samples": len(idx)}
            booster = lgb.Booster(model_file=model_path)
            y_pred_scaled[:, col] = booster.predict(X_recent)

    y_pred = scaler_y.inverse_transform(y_pred_scaled)
    mae_by_horizon = {}
    for h_idx, horizon in enumerate(ML_FORECAST_HORIZONS_MIN):
        sl = slice(h_idx * 2, h_idx * 2 + 2)
        mae_by_horizon[str(horizon)] = float(np.mean(np.abs(y_pred[:, sl] - y_recent[:, sl])))
    mae_total = float(np.mean([mae_by_horizon[str(h)] for h in ML_FORECAST_HORIZONS_MIN]))
    return {"mae_total": mae_total, "mae_by_horizon": mae_by_horizon, "samples": len(idx)}

def _build_lstm():
    model = Sequential([
        LSTM(64, return_sequences=True, input_shape=(ML_SEQUENCE_LENGTH, ML_NUM_FEATURES)),
        Dropout(0.2),
        LSTM(32),
        Dropout(0.2),
        Dense(32, activation="relu"),
        Dense(len(ML_FORECAST_HORIZONS_MIN) * 2),
    ])
    model.compile(optimizer=Adam(1e-3), loss="mse")
    return model


def train_lstm(X, y):
    model_path = os.path.join(_current_models_dir(), "weather_lstm.keras")
    os.makedirs(SAVE_PATHS["models"], exist_ok=True)
    if Sequential is None or train_test_split is None:
        debug_log("[LSTM] Skip: tensorflow oder sklearn nicht installiert")
        return {"trained": False, "model_path": model_path, "val_loss": None, "samples": len(X)}
    if len(X) < 50:
        debug_log(f"[LSTM] Skip: zu wenig Samples ({len(X)} < 50)")
        return {"trained": False, "model_path": model_path, "val_loss": None, "samples": len(X)}
    X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, random_state=42)
    model = _build_lstm()
    history = model.fit(
        X_train,
        y_train,
        validation_data=(X_val, y_val),
        epochs=200,
        batch_size=32,
        callbacks=[
            EarlyStopping(monitor="val_loss", patience=10, restore_best_weights=True),
            ModelCheckpoint(filepath=model_path, monitor="val_loss", save_best_only=True),
        ],
        verbose=1,
    )
    val_loss = float(min(history.history.get("val_loss", [float("nan")])))
    return {"trained": True, "model_path": model_path, "val_loss": val_loss, "samples": len(X)}


def train_lgbm(X, y):
    os.makedirs(SAVE_PATHS["models"], exist_ok=True)
    if lgb is None or train_test_split is None:
        debug_log("[LGBM] Skip: lightgbm oder sklearn nicht installiert")
        return {"trained": False, "models": {}, "best_scores": {}, "samples": len(X)}
    if len(X) < 30:
        debug_log(f"[LGBM] Skip: zu wenig Samples ({len(X)} < 30)")
        return {"trained": False, "models": {}, "best_scores": {}, "samples": len(X)}
    X_flat = X[:, -1, :]
    X_train, X_val, y_train, y_val = train_test_split(X_flat, y, test_size=0.2, random_state=42)
    base_params = {"num_leaves": 31, "learning_rate": 0.05, "feature_fraction": 0.9, "bagging_fraction": 0.8, "bagging_freq": 5, "verbose": -1}
    point_params = {**base_params, "objective": "regression", "metric": "rmse"}
    quantiles = [0.1, 0.5, 0.9]
    quantiles_to_train = quantiles if len(X) >= 100 else [0.5]
    if len(X) < 100:
        debug_log(f"[LGBM] Wenig Samples ({len(X)} < 100): trainiere nur Median-Quantil (q50)")
    models, best_scores, quantile_scores = {}, {}, {}
    for h_idx, h in enumerate(ML_FORECAST_HORIZONS_MIN):
        for axis_idx, axis in enumerate(["x", "y"]):
            target_idx = h_idx * 2 + axis_idx
            booster = lgb.train(
                point_params,
                lgb.Dataset(X_train, label=y_train[:, target_idx]),
                num_boost_round=500,
                valid_sets=[lgb.Dataset(X_val, label=y_val[:, target_idx])],
                callbacks=[lgb.early_stopping(20, verbose=False)],
            )
            name = f"lgbm_h{h}_{axis}"
            path = os.path.join(_current_models_dir(), f"{name}.txt")
            booster.save_model(path)
            models[name] = path
            best_scores[name] = float(booster.best_score.get("valid_0", {}).get("rmse", float("nan")))

            for quantile in quantiles_to_train:
                q_name = f"q{int(quantile * 100):02d}"
                quantile_params = {**base_params, "objective": "quantile", "alpha": quantile, "metric": "quantile"}
                q_booster = lgb.train(
                    quantile_params,
                    lgb.Dataset(X_train, label=y_train[:, target_idx]),
                    num_boost_round=500,
                    valid_sets=[lgb.Dataset(X_val, label=y_val[:, target_idx])],
                    callbacks=[lgb.early_stopping(20, verbose=False)],
                )
                q_model_name = f"lgbm_h{h}_{axis}_{q_name}"
                q_path = os.path.join(_current_models_dir(), f"{q_model_name}.txt")
                q_booster.save_model(q_path)
                models[q_model_name] = q_path
                quantile_scores[q_model_name] = float(q_booster.best_score.get("valid_0", {}).get("quantile", float("nan")))
    return {"trained": True, "models": models, "best_scores": best_scores, "quantile_scores": quantile_scores, "samples": len(X)}


def load_lstm():
    model_path = os.path.join(_current_models_dir(), "weather_lstm.keras")
    return load_model(model_path) if load_model is not None and os.path.exists(model_path) else None


def load_lgbm_models():
    models = {}
    if lgb is None:
        return models
    for h in ML_FORECAST_HORIZONS_MIN:
        for axis in ["x", "y"]:
            name = f"lgbm_h{h}_{axis}"
            path = os.path.join(_current_models_dir(), f"{name}.txt")
            if os.path.exists(path):
                models[name] = lgb.Booster(model_file=path)
            for q in ["q10", "q50", "q90"]:
                q_name = f"{name}_{q}"
                q_path = os.path.join(_current_models_dir(), f"{q_name}.txt")
                if os.path.exists(q_path):
                    models[q_name] = lgb.Booster(model_file=q_path)
    return models


def train_intensification_classifier():
    model_path = os.path.join(_current_models_dir(), "lgbm_intensification.txt")
    if lgb is None or train_test_split is None or roc_auc_score is None:
        debug_log("[LGBM-CLS] Skip: lightgbm oder sklearn nicht installiert")
        return {"trained": False, "auc": None, "precision": None, "recall": None, "samples": 0, "positive_samples": 0}

    cls_data = build_classification_dataset()
    X_df = cls_data.get("X")
    y_series = cls_data.get("y")
    samples = int(cls_data.get("samples", 0))
    positives = int(cls_data.get("positive_samples", 0))
    if samples == 0:
        return {"trained": False, "auc": None, "precision": None, "recall": None, "samples": 0, "positive_samples": 0}
    if positives < 50:
        debug_log(f"[LGBM-CLS] Skip: zu wenig positive Samples ({positives} < 50)")
        return {"trained": False, "auc": None, "precision": None, "recall": None, "samples": samples, "positive_samples": positives}

    X = X_df.to_numpy(dtype=float)
    y = y_series.to_numpy(dtype=int)
    X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
    pos_train = max(int((y_train == 1).sum()), 1)
    neg_train = max(int((y_train == 0).sum()), 1)
    scale_pos_weight = neg_train / pos_train

    params = {
        "objective": "binary",
        "metric": "auc",
        "learning_rate": 0.05,
        "num_leaves": 31,
        "feature_fraction": 0.9,
        "bagging_fraction": 0.8,
        "bagging_freq": 5,
        "verbose": -1,
        "scale_pos_weight": scale_pos_weight,
    }
    booster = lgb.train(
        params,
        lgb.Dataset(X_train, label=y_train),
        num_boost_round=500,
        valid_sets=[lgb.Dataset(X_val, label=y_val)],
        callbacks=[lgb.early_stopping(20, verbose=False)],
    )
    os.makedirs(SAVE_PATHS["models"], exist_ok=True)
    booster.save_model(model_path)

    y_prob = booster.predict(X_val)
    y_pred = (y_prob >= 0.5).astype(int)
    auc = float(roc_auc_score(y_val, y_prob))
    precision = float(precision_score(y_val, y_pred, zero_division=0))
    recall = float(recall_score(y_val, y_pred, zero_division=0))
    return {
        "trained": True,
        "model_path": model_path,
        "auc": auc,
        "precision": precision,
        "recall": recall,
        "samples": samples,
        "positive_samples": positives,
    }


def retrain_all():
    timestamp = datetime.now(timezone.utc).strftime("v_%Y-%m-%dT%H-%M-%SZ")
    version_dir = _version_models_dir(timestamp)
    os.makedirs(version_dir, exist_ok=True)

    old_models_dir = SAVE_PATHS["models"]
    SAVE_PATHS["models"] = version_dir
    try:
        dataset = build_dataset()
        X = np.asarray(dataset.get("X", [])) if np is not None else []
        y = np.asarray(dataset.get("y", [])) if np is not None else []
        has_data = np is not None and getattr(X, "size", 0) and getattr(y, "size", 0)
        lstm_result = train_lstm(X, y) if has_data else {"trained": False, "val_loss": None}
        lgbm_result = train_lgbm(X, y) if has_data else {"trained": False, "best_scores": {}, "quantile_scores": {}}
        intensification_result = train_intensification_classifier()
        meta = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "version": timestamp,
            "num_samples": int(len(X)) if has_data else 0,
            "rejected_samples": int(dataset.get("rejected_samples", 0)),
            "rejection_reasons": dataset.get("rejection_reasons", {}),
            "lstm": {"trained": lstm_result.get("trained", False), "val_loss": lstm_result.get("val_loss")},
            "lgbm": {
                "trained": lgbm_result.get("trained", False),
                "best_scores": lgbm_result.get("best_scores", {}),
                "quantile_scores": lgbm_result.get("quantile_scores", {}),
            },
            "intensification": {
                "trained": intensification_result.get("trained", False),
                "auc": intensification_result.get("auc"),
                "precision_at_0_5": intensification_result.get("precision"),
                "recall_at_0_5": intensification_result.get("recall"),
                "samples": intensification_result.get("samples", 0),
                "positive_samples": intensification_result.get("positive_samples", 0),
            },
        }
        with open(os.path.join(version_dir, "training_meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)
    finally:
        SAVE_PATHS["models"] = old_models_dir

    new_eval = evaluate_on_recent(version_dir)
    current_dir = _current_models_dir()
    has_current = os.path.isdir(current_dir)
    old_eval = evaluate_on_recent(current_dir) if has_current else {"mae_total": float("inf"), "mae_by_horizon": {}, "samples": 0}

    if not has_current:
        status = "promoted"
        _atomic_switch_current(timestamp)
        debug_log(f"[TRAINING] PROMOTED {timestamp} (cold-start)")
    elif new_eval.get("samples", 0) < 20:
        status = "no_baseline"
        _atomic_switch_current(timestamp)
        debug_log(f"[TRAINING] PROMOTED {timestamp} (no_baseline: <20 recent samples)")
    elif new_eval["mae_total"] < old_eval["mae_total"] * 1.02:
        status = "promoted"
        _atomic_switch_current(timestamp)
        debug_log(f"[TRAINING] PROMOTED {timestamp} (mae_new={new_eval['mae_total']:.4f} vs mae_old={old_eval['mae_total']:.4f})")
    else:
        status = "rejected"
        debug_log(f"[TRAINING] REJECTED {timestamp} (mae_new={new_eval['mae_total']:.4f} vs mae_old={old_eval['mae_total']:.4f})")

    meta["validation"] = {
        "mae_old": old_eval.get("mae_total"),
        "mae_new": new_eval.get("mae_total"),
        "mae_by_horizon_old": old_eval.get("mae_by_horizon", {}),
        "mae_by_horizon_new": new_eval.get("mae_by_horizon", {}),
        "samples_recent": new_eval.get("samples", 0),
        "status": status,
    }
    with open(os.path.join(version_dir, "training_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    cleanup_old_versions(keep_n=5)
    return meta


if __name__ == "__main__":
    retrain_all()
