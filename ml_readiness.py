import json
import os
from datetime import datetime, timezone
import importlib
import importlib.util

from config import ML_FORECAST_HORIZONS_MIN, ML_NUM_FEATURES, SAVE_PATHS

ACTIVE_MODEL_STATUSES = {"promoted", "cold_start_promoted_low_confidence"}
NON_ACTIVE_MODEL_STATUSES = {
    "cold_start_insufficient_samples",
    "rejected_low_samples",
    "rejected",
    "rejected_incompatible",
    "rejected_invalid_holdout",
    "no_data",
    "cold_start_rejected_invalid_model",
}
DEFAULT_PROMOTION_SAMPLES_REQUIRED = 50


def _clean_json_value(value):
    import math
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _clean_json_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean_json_value(v) for v in value]
    return value


def _read_training_meta(model_dir):
    path = os.path.join(model_dir, "training_meta.json")
    if not os.path.exists(path):
        return None, path, "missing_training_meta"
    try:
        with open(path, encoding="utf-8") as f:
            return _clean_json_value(json.load(f)), path, None
    except Exception as exc:
        return None, path, f"invalid_training_meta:{exc}"



def _active_model_schema(meta):
    if not isinstance(meta, dict):
        return {}, None
    schema = meta.get("feature_schema") or {
        "feature_schema_hash": meta.get("feature_schema_hash"),
        "schema_version": meta.get("feature_schema_version"),
        "feature_names": meta.get("feature_names"),
        "num_features": meta.get("feature_count"),
    }
    return schema, schema.get("feature_schema_hash")


def _model_schema_status(meta):
    try:
        from feature_schema import get_current_feature_schema
        current_schema = get_current_feature_schema()
    except Exception as exc:
        current_schema = {}
        return {
            "current_schema": current_schema,
            "active_model_schema": {},
            "active_model_schema_hash": None,
            "model_schema_compatible": False,
            "schema_incompatibility_reason": f"current_schema_unavailable:{exc}",
        }
    active_schema, active_hash = _active_model_schema(meta)
    current_hash = current_schema.get("feature_schema_hash")
    if not active_hash:
        reason = "model_missing_feature_schema_hash"
    elif active_hash != current_hash:
        reason = "feature_schema_hash_mismatch"
    else:
        reason = None
    return {
        "current_schema": current_schema,
        "active_model_schema": active_schema,
        "active_model_schema_hash": active_hash,
        "model_schema_compatible": bool(active_hash and active_hash == current_hash),
        "schema_incompatibility_reason": reason,
    }


def _active_version_from_current(model_path, valid):
    if not valid or not (os.path.exists(model_path) or os.path.islink(model_path)):
        return None
    name = _model_version_from_path(model_path)
    return name if name and name.startswith("v_") else None

def _promotion_status_from_meta(meta):
    if not isinstance(meta, dict):
        return None
    val = meta.get("validation") or {}
    return val.get("status") or meta.get("status") or val.get("promotion_status")


def _meta_summary(meta):
    val = (meta or {}).get("validation") or {}
    status = _promotion_status_from_meta(meta)
    recent = val.get("samples_recent", 0)
    required = val.get("samples_required", DEFAULT_PROMOTION_SAMPLES_REQUIRED)
    try:
        missing = max(0, int(required) - int(recent or 0))
    except Exception:
        missing = val.get("samples_missing")
    return {
        "training_status": status,
        "training_status_reason": val.get("status_reason") or (meta or {}).get("status_reason"),
        "promotion_samples_recent": recent,
        "promotion_samples_required": required,
        "promotion_samples_missing": missing,
        "ml_low_confidence": bool(val.get("low_confidence") or status == "cold_start_promoted_low_confidence"),
    }


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
    for name in ("scaler_X.joblib", "scaler_y.joblib"):
        path = os.path.join(model_dir, name)
        exists = os.path.exists(path)
        if not exists:
            missing_files.append(path); scaler_status[name] = _status(False, False, "missing"); scalers_ok = False; continue
        if joblib is None:
            scaler_status[name] = _status(False, True, "joblib_missing"); scalers_ok = False; continue
        try:
            obj = joblib.load(path)
            n_features = getattr(obj, "n_features_in_", None)
            scaler_status[name] = _status(True, True, None, n_features_in=n_features)
        except Exception as exc:
            scaler_status[name] = _status(False, True, f"load_error: {exc}"); scalers_ok = False

    feature_layout_ok = True
    sx_n = scaler_status.get("scaler_X.joblib", {}).get("n_features_in")
    if sx_n is not None and int(sx_n) != int(ML_NUM_FEATURES):
        feature_layout_ok = False; scaler_status["scaler_X.joblib"]["reason"] = f"feature_count_mismatch: scaler={sx_n}, config={ML_NUM_FEATURES}"; scalers_ok = False
    sy_n = scaler_status.get("scaler_y.joblib", {}).get("n_features_in")
    expected_y = len(horizons) * 2
    horizon_layout_ok = True
    if sy_n is not None and int(sy_n) != int(expected_y):
        horizon_layout_ok = False; scaler_status["scaler_y.joblib"]["reason"] = f"horizon_layout_mismatch: scaler={sy_n}, expected={expected_y}"; scalers_ok = False

    keras_path = os.path.join(model_dir, "weather_lstm.keras")
    lstm_exists = os.path.exists(keras_path)
    if not lstm_exists: missing_files.append(keras_path)
    load_model = None
    try: load_model = importlib.import_module("tensorflow.keras.models").load_model
    except Exception:
        try: load_model = importlib.import_module("keras.models").load_model
        except Exception: load_model = None
    lstm_ok = False
    if lstm_exists and load_model is not None:
        try:
            m = load_model(keras_path, compile=False); out_shape = getattr(m, "output_shape", None); lstm_ok = True
            if out_shape is not None and int(out_shape[-1]) != expected_y:
                lstm_ok = False; lstm_status = _status(False, True, f"horizon_layout_mismatch: model={out_shape[-1]}, expected={expected_y}", output_shape=out_shape)
            else: lstm_status = _status(True, True, None, output_shape=out_shape)
        except Exception as exc: lstm_status = _status(False, True, f"load_error: {exc}")
    elif lstm_exists: lstm_status = _status(False, True, "keras_missing")
    else: lstm_status = _status(False, False, "missing")

    lgb = _opt("lightgbm")
    lgbm_status_by_horizon = {}; active_horizons = []
    for h in horizons:
        axes = {}; complete = True
        for axis in ("x", "y"):
            path = os.path.join(model_dir, f"lgbm_h{h}_{axis}.txt")
            exists = os.path.exists(path)
            if not exists:
                missing_files.append(path); axes[axis] = _status(False, False, "missing"); complete = False
            elif lgb is None:
                axes[axis] = _status(False, True, "lightgbm_missing"); complete = False
            else:
                try:
                    booster = lgb.Booster(model_file=path); nf = booster.num_feature() if hasattr(booster, "num_feature") else None
                    ok = nf is None or int(nf) == int(ML_NUM_FEATURES)
                    axes[axis] = _status(ok, True, None if ok else f"feature_count_mismatch: model={nf}, config={ML_NUM_FEATURES}", num_feature=nf)
                    complete = complete and ok
                except Exception as exc:
                    axes[axis] = _status(False, True, f"load_error: {exc}"); complete = False
        lgbm_status_by_horizon[str(h)] = {"complete": bool(complete), "axes": axes}
        if complete: active_horizons.append(int(h))

    ml_artifacts_available = bool(scalers_ok and (lstm_ok or active_horizons))
    artifact_status = "active" if ml_artifacts_available and (lstm_ok or len(active_horizons) == len(horizons)) else ("partial" if ml_artifacts_available else "fallback")
    meta, meta_path, meta_error = _read_training_meta(model_dir)
    promotion_status = _promotion_status_from_meta(meta)
    promoted = bool(promotion_status in ACTIVE_MODEL_STATUSES)
    ml_available = bool(ml_artifacts_available and promoted)
    status = "active" if ml_available else "fallback"
    fallback_reason = None
    if not ml_artifacts_available:
        fallback_reason = "missing_or_invalid_scalers" if not scalers_ok else ("invalid_lstm_model" if lstm_exists and not lstm_ok else "missing_ml_artifacts")
    elif meta_error:
        fallback_reason = meta_error
    elif not promotion_status:
        fallback_reason = "missing_promotion_status"
    elif not promoted:
        fallback_reason = f"current_model_not_promoted:{promotion_status}"

    # B343: Regressions-Erkennung — vergleicht den NEU ermittelten Stand
    # gegen die zuletzt persistierte evaluation/ml_readiness.json (dieselbe
    # Datei, die diese Funktion selbst schreibt), BEVOR sie ueberschrieben
    # wird. Unterscheidet einen echten Cold-Start (noch nie Artefakte
    # vorhanden) von einer Regression (Artefakte waren da, sind jetzt weg).
    _readiness_json_path = os.path.join(evaluation_dir, "ml_readiness.json")
    regression_alert = False
    regression_reason = None
    try:
        if os.path.exists(_readiness_json_path):
            with open(_readiness_json_path, encoding="utf-8") as _f_prev:
                _prev_readiness = json.load(_f_prev)
            if bool(_prev_readiness.get("ml_artifacts_available")) and not ml_artifacts_available:
                regression_alert = True
                regression_reason = (
                    f"ml_artifacts_available wechselte von true (zuletzt geprueft "
                    f"{_prev_readiness.get('checked_at_utc', 'unbekannt')}) auf false "
                    f"— fallback_reason={fallback_reason}"
                )
    except Exception as _reg_exc:
        from debug_utils import debug_log as _debug_log_reg
        _debug_log_reg(f"[ML-READINESS] Regressions-Vergleich fehlgeschlagen: {_reg_exc}")

    result = _clean_json_value({
        "checked_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": status,
        "artifact_status": artifact_status,
        "promotion_status": promotion_status,
        "promoted": promoted,
        "runtime_status": "active" if ml_available else "fallback",
        "ml_available": ml_available,
        "ml_artifacts_available": ml_artifacts_available,
        "fallback_reason": fallback_reason,
        "regression_alert": regression_alert,
        "regression_reason": regression_reason,
        "scaler_status": scaler_status, "lstm_status": lstm_status, "lgbm_status_by_horizon": lgbm_status_by_horizon,
        "active_horizons": active_horizons, "missing_files": sorted(set(missing_files)), "model_dir": model_dir,
        "training_meta_path": meta_path, "training_meta": meta,
        "dataset_sequences": _dataset_sequences(dataset_path), "feature_layout_ok": feature_layout_ok, "horizon_layout_ok": horizon_layout_ok,
        "expected_num_features": int(ML_NUM_FEATURES), "expected_horizons": horizons,
    })
    if regression_alert:
        from debug_utils import debug_log as _debug_log_alarm
        _debug_log_alarm(f"[ML-ALARM] {regression_reason}")
    if write_json:
        os.makedirs(evaluation_dir, exist_ok=True)
        with open(os.path.join(evaluation_dir, "ml_readiness.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, allow_nan=False)
    return result


def _latest_training_meta_from_disk(models_root=None):
    import glob
    models_root = models_root or SAVE_PATHS.get("models", "train_data/models")
    metas = sorted(glob.glob(os.path.join(models_root, "v_*", "training_meta.json")))
    if not metas:
        return None
    try:
        with open(metas[-1], encoding="utf-8") as f:
            meta = json.load(f)
    except Exception:
        return None
    val = meta.get("validation", {}) or {}
    return {
        "timestamp_utc": meta.get("timestamp_utc"),
        "status": val.get("status"),
        "status_reason": val.get("status_reason"),
        "promotion_status": val.get("promotion_status", val.get("status")),
        "promotion_samples_recent": val.get("samples_recent", 0),
        "promotion_samples_required": val.get("samples_required", 50),
        "promotion_samples_missing": val.get("samples_missing"),
        "low_confidence": bool(val.get("low_confidence", False)),
    }


def _model_version_from_path(path):
    try:
        resolved = os.path.realpath(path)
        name = os.path.basename(resolved.rstrip(os.sep))
        return name or None
    except Exception:
        return None


def get_forecast_runtime_status(write_json=True, model_dir=None):
    """Zentrale Quelle für die produktive Forecast-Entscheidung."""
    readiness = check_ml_readiness(write_json=write_json, model_dir=model_dir)
    expected = [int(h) for h in readiness.get("expected_horizons") or _runtime_horizons()]
    active = [int(h) for h in readiness.get("active_horizons") or []]
    missing = [h for h in expected if h not in set(active)]
    model_path = readiness.get("model_dir") or model_dir or os.path.join(SAVE_PATHS.get("models", "train_data/models"), "current")
    current_exists = os.path.exists(model_path)
    current_is_link = os.path.islink(model_path)
    resolved = os.path.realpath(model_path) if current_exists or current_is_link else None
    meta = readiness.get("training_meta") or {}
    summary = _meta_summary(meta)
    artifacts_valid = bool(readiness.get("ml_artifacts_available"))
    promoted = bool(readiness.get("promoted"))
    schema_status = _model_schema_status(meta)
    schema_compatible = bool(schema_status.get("model_schema_compatible"))
    valid = bool(artifacts_valid and promoted and schema_compatible)
    runtime_mode = "ml" if valid else "kinematic_fallback"
    mode_by_horizon = {str(h): ("ml" if valid and h in set(active) else "kinematic_fallback") for h in expected}
    result = _clean_json_value({
        "checked_at_utc": readiness.get("checked_at_utc"),
        "runtime_mode": runtime_mode,
        "ml_model_available": valid,
        "ml_model_artifacts_valid": artifacts_valid,
        "ml_model_promoted": promoted,
        "model_schema_compatible": schema_compatible,
        "active_model_schema_hash": schema_status.get("active_model_schema_hash") if valid else None,
        "active_model_version": _active_version_from_current(model_path, valid),
        "display_status": "ml_active" if valid else ("missing_model" if not artifacts_valid else ("incompatible" if not schema_compatible else "fallback")),
        "ml_low_confidence": summary.get("ml_low_confidence"),
        "low_confidence": summary.get("ml_low_confidence"),
        "model_dir": model_path,
        "model_version": _active_version_from_current(model_path, valid),
        "current_resolved_path": resolved,
        "ml_model_path": model_path,
        "ml_model_resolved_path": resolved,
        "ml_model_version": _active_version_from_current(model_path, valid),
        "current_symlink": os.readlink(model_path) if current_is_link else None,
        "current_exists": bool(current_exists),
        "active_horizons": active if valid else [],
        "missing_horizons": missing if valid else expected,
        **summary,
        **schema_status,
        "fallback_reason": None if valid else (readiness.get("fallback_reason") if readiness.get("fallback_reason") == "missing_training_meta" else (schema_status.get("schema_incompatibility_reason") or readiness.get("fallback_reason") or "missing_or_invalid_current_model")),
        "forecast_mode_by_horizon": mode_by_horizon,
        "readiness": readiness,
    })
    return result


def load_ml_readiness_json():
    path = os.path.join(SAVE_PATHS.get("evaluation", "train_data/evaluation"), "ml_readiness.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None
