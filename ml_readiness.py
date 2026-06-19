import json
import os
from datetime import datetime, timezone
import importlib
import importlib.util

from config import ML_FORECAST_HORIZONS_MIN, ML_NUM_FEATURES, SAVE_PATHS


def _opt(name):
    try:
        if importlib.util.find_spec(name) is None:
            return None
        return importlib.import_module(name)
    except Exception:
        return None


def _runtime_horizons():
    try:
        import runtime_config
        return [int(h) for h in runtime_config.get("ML_FORECAST_HORIZONS_MIN", ML_FORECAST_HORIZONS_MIN)]
    except Exception:
        return [int(h) for h in ML_FORECAST_HORIZONS_MIN]


def _status(ok=False, exists=False, reason=None, **extra):
    d = {"exists": bool(exists), "loadable": bool(ok), "reason": reason}
    d.update(extra)
    return d


def _dataset_sequences(dataset_path):
    if not os.path.exists(dataset_path):
        return 0
    np = _opt("numpy")
    if np is None:
        return None
    try:
        with np.load(dataset_path, allow_pickle=True) as data:
            return int(data["X"].shape[0])
    except Exception:
        return None


def check_ml_readiness(write_json=True, model_dir=None):
    horizons = _runtime_horizons()
    model_dir = model_dir or os.path.join(SAVE_PATHS.get("models", "train_data/models"), "current")
    evaluation_dir = SAVE_PATHS.get("evaluation", "train_data/evaluation")
    dataset_path = os.path.join(SAVE_PATHS.get("dataset", "train_data/dataset"), "dataset.npz")
    missing_files = []

    model_dir_exists = os.path.isdir(model_dir)
    if not model_dir_exists:
        missing_files.append(model_dir)

    joblib = _opt("joblib")
    scaler_status = {}
    scalers_ok = True
    scaler_objects = {}
    for name in ("scaler_X.joblib", "scaler_y.joblib"):
        path = os.path.join(model_dir, name)
        exists = os.path.exists(path)
        if not exists:
            missing_files.append(path)
            scaler_status[name] = _status(False, False, "missing")
            scalers_ok = False
            continue
        if joblib is None:
            scaler_status[name] = _status(False, True, "joblib_missing")
            scalers_ok = False
            continue
        try:
            obj = joblib.load(path)
            scaler_objects[name] = obj
            n_features = getattr(obj, "n_features_in_", None)
            scaler_status[name] = _status(True, True, None, n_features_in=n_features)
        except Exception as exc:
            scaler_status[name] = _status(False, True, f"load_error: {exc}")
            scalers_ok = False

    feature_layout_ok = True
    sx_n = scaler_status.get("scaler_X.joblib", {}).get("n_features_in")
    if sx_n is not None and int(sx_n) != int(ML_NUM_FEATURES):
        feature_layout_ok = False
        scaler_status["scaler_X.joblib"]["reason"] = f"feature_count_mismatch: scaler={sx_n}, config={ML_NUM_FEATURES}"
        scalers_ok = False
    sy_n = scaler_status.get("scaler_y.joblib", {}).get("n_features_in")
    expected_y = len(horizons) * 2
    horizon_layout_ok = True
    if sy_n is not None and int(sy_n) != int(expected_y):
        horizon_layout_ok = False
        scaler_status["scaler_y.joblib"]["reason"] = f"horizon_layout_mismatch: scaler={sy_n}, expected={expected_y}"
        scalers_ok = False

    keras_path = os.path.join(model_dir, "weather_lstm.keras")
    lstm_exists = os.path.exists(keras_path)
    if not lstm_exists:
        missing_files.append(keras_path)
    load_model = None
    try:
        keras_models = importlib.import_module("tensorflow.keras.models")
        load_model = keras_models.load_model
    except Exception:
        try:
            keras_models = importlib.import_module("keras.models")
            load_model = keras_models.load_model
        except Exception:
            load_model = None
    lstm_ok = False
    if lstm_exists and load_model is not None:
        try:
            m = load_model(keras_path, compile=False)
            out_shape = getattr(m, "output_shape", None)
            lstm_ok = True
            if out_shape is not None and int(out_shape[-1]) != expected_y:
                lstm_ok = False
                lstm_status = _status(False, True, f"horizon_layout_mismatch: model={out_shape[-1]}, expected={expected_y}", output_shape=out_shape)
            else:
                lstm_status = _status(True, True, None, output_shape=out_shape)
        except Exception as exc:
            lstm_status = _status(False, True, f"load_error: {exc}")
    elif lstm_exists:
        lstm_status = _status(False, True, "keras_missing")
    else:
        lstm_status = _status(False, False, "missing")

    lgb = _opt("lightgbm")
    lgbm_status_by_horizon = {}
    active_horizons = []
    for h in horizons:
        axes = {}
        complete = True
        for axis in ("x", "y"):
            fname = f"lgbm_h{h}_{axis}.txt"
            path = os.path.join(model_dir, fname)
            exists = os.path.exists(path)
            if not exists:
                missing_files.append(path)
                axes[axis] = _status(False, False, "missing")
                complete = False
            elif lgb is None:
                axes[axis] = _status(False, True, "lightgbm_missing")
                complete = False
            else:
                try:
                    booster = lgb.Booster(model_file=path)
                    nf = booster.num_feature() if hasattr(booster, "num_feature") else None
                    ok = nf is None or int(nf) == int(ML_NUM_FEATURES)
                    axes[axis] = _status(ok, True, None if ok else f"feature_count_mismatch: model={nf}, config={ML_NUM_FEATURES}", num_feature=nf)
                    complete = complete and ok
                except Exception as exc:
                    axes[axis] = _status(False, True, f"load_error: {exc}")
                    complete = False
        lgbm_status_by_horizon[str(h)] = {"complete": bool(complete), "axes": axes}
        if complete:
            active_horizons.append(int(h))

    ml_available = bool(scalers_ok and (lstm_ok or active_horizons))
    if ml_available and (lstm_ok or len(active_horizons) == len(horizons)):
        status = "active"
    elif ml_available:
        status = "partial"
    else:
        status = "fallback"

    fallback_reason = None
    if not ml_available:
        if not scalers_ok:
            fallback_reason = "missing_or_invalid_scalers"
        elif lstm_exists and not lstm_ok:
            fallback_reason = "invalid_lstm_model"
        else:
            fallback_reason = "missing_ml_artifacts"

    result = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": status,
        "ml_available": ml_available,
        "fallback_reason": fallback_reason,
        "scaler_status": scaler_status,
        "lstm_status": lstm_status,
        "lgbm_status_by_horizon": lgbm_status_by_horizon,
        "active_horizons": active_horizons,
        "missing_files": sorted(set(missing_files)),
        "model_dir": model_dir,
        "dataset_sequences": _dataset_sequences(dataset_path),
        "feature_layout_ok": feature_layout_ok,
        "horizon_layout_ok": horizon_layout_ok,
        "expected_num_features": int(ML_NUM_FEATURES),
        "expected_horizons": horizons,
    }
    if write_json:
        os.makedirs(evaluation_dir, exist_ok=True)
        with open(os.path.join(evaluation_dir, "ml_readiness.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    return result


def load_ml_readiness_json():
    path = os.path.join(SAVE_PATHS.get("evaluation", "train_data/evaluation"), "ml_readiness.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None
