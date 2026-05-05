import importlib
import importlib.util
import json
import os
from datetime import datetime, timezone

np = importlib.import_module("numpy") if importlib.util.find_spec("numpy") else None
lgb = importlib.import_module("lightgbm") if importlib.util.find_spec("lightgbm") else None

if importlib.util.find_spec("sklearn"):
    train_test_split = importlib.import_module("sklearn.model_selection").train_test_split
else:
    train_test_split = None

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
from dataset_builder import build_dataset
try:
    from debug_utils import debug_log
except Exception:
    def debug_log(message):
        print(message)


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
    model_path = os.path.join(SAVE_PATHS["models"], "weather_lstm.keras")
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
            path = os.path.join(SAVE_PATHS["models"], f"{name}.txt")
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
                q_path = os.path.join(SAVE_PATHS["models"], f"{q_model_name}.txt")
                q_booster.save_model(q_path)
                models[q_model_name] = q_path
                quantile_scores[q_model_name] = float(q_booster.best_score.get("valid_0", {}).get("quantile", float("nan")))
    return {"trained": True, "models": models, "best_scores": best_scores, "quantile_scores": quantile_scores, "samples": len(X)}


def load_lstm():
    model_path = os.path.join(SAVE_PATHS["models"], "weather_lstm.keras")
    return load_model(model_path) if load_model is not None and os.path.exists(model_path) else None


def load_lgbm_models():
    models = {}
    if lgb is None:
        return models
    for h in ML_FORECAST_HORIZONS_MIN:
        for axis in ["x", "y"]:
            name = f"lgbm_h{h}_{axis}"
            path = os.path.join(SAVE_PATHS["models"], f"{name}.txt")
            if os.path.exists(path):
                models[name] = lgb.Booster(model_file=path)
            for q in ["q10", "q50", "q90"]:
                q_name = f"{name}_{q}"
                q_path = os.path.join(SAVE_PATHS["models"], f"{q_name}.txt")
                if os.path.exists(q_path):
                    models[q_name] = lgb.Booster(model_file=q_path)
    return models


def retrain_all():
    dataset = build_dataset()
    X = np.asarray(dataset.get("X", [])) if np is not None else []
    y = np.asarray(dataset.get("y", [])) if np is not None else []
    has_data = np is not None and getattr(X, "size", 0) and getattr(y, "size", 0)
    lstm_result = train_lstm(X, y) if has_data else {"trained": False, "val_loss": None}
    lgbm_result = train_lgbm(X, y) if has_data else {"trained": False, "best_scores": {}, "quantile_scores": {}}
    meta = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "num_samples": int(len(X)) if has_data else 0,
        "lstm": {"trained": lstm_result.get("trained", False), "val_loss": lstm_result.get("val_loss")},
        "lgbm": {
            "trained": lgbm_result.get("trained", False),
            "best_scores": lgbm_result.get("best_scores", {}),
            "quantile_scores": lgbm_result.get("quantile_scores", {}),
        },
    }
    os.makedirs(SAVE_PATHS["models"], exist_ok=True)
    with open(os.path.join(SAVE_PATHS["models"], "training_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    return meta


if __name__ == "__main__":
    retrain_all()
