import importlib
import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta, timezone

try:
    from debug_utils import debug_log
except Exception:
    def debug_log(message):
        print(message)


def _optional_import(name):
    """Importiert optionale Abhängigkeiten robust ohne Modulimport-Crash."""
    try:
        if name not in sys.modules and importlib.util.find_spec(name) is None:
            return None
    except Exception as exc:
        debug_log(f"[OPTIONAL_IMPORT] {name}: find_spec fehlgeschlagen: {exc}")
        return None
    try:
        return importlib.import_module(name)
    except Exception as exc:
        debug_log(f"[OPTIONAL_IMPORT] {name}: Import fehlgeschlagen: {exc}")
        return None


np = _optional_import("numpy")
lgb = _optional_import("lightgbm")
joblib = _optional_import("joblib")

sklearn_model_selection = _optional_import("sklearn.model_selection")
sklearn_metrics = _optional_import("sklearn.metrics")
if sklearn_model_selection is not None and sklearn_metrics is not None:
    train_test_split = getattr(sklearn_model_selection, "train_test_split", None)
    roc_auc_score = getattr(sklearn_metrics, "roc_auc_score", None)
    precision_score = getattr(sklearn_metrics, "precision_score", None)
    recall_score = getattr(sklearn_metrics, "recall_score", None)
else:
    train_test_split = None
    roc_auc_score = precision_score = recall_score = None

keras_models = _optional_import("tensorflow.keras.models")
keras_layers = _optional_import("tensorflow.keras.layers")
keras_callbacks = _optional_import("tensorflow.keras.callbacks")
keras_optimizers = _optional_import("tensorflow.keras.optimizers")
if (
    keras_models is not None
    and keras_layers is not None
    and keras_callbacks is not None
    and keras_optimizers is not None
):
    Sequential = getattr(keras_models, "Sequential", None)
    load_model = getattr(keras_models, "load_model", None)
    Input = getattr(keras_layers, "Input", None)
    LSTM = getattr(keras_layers, "LSTM", None)
    Dense = getattr(keras_layers, "Dense", None)
    Dropout = getattr(keras_layers, "Dropout", None)
    EarlyStopping = getattr(keras_callbacks, "EarlyStopping", None)
    ModelCheckpoint = getattr(keras_callbacks, "ModelCheckpoint", None)
    Adam = getattr(keras_optimizers, "Adam", None)
else:
    Sequential = load_model = Input = LSTM = Dense = Dropout = EarlyStopping = ModelCheckpoint = Adam = None

from feature_schema import get_current_feature_schema

from config import (
    DATA_RETENTION_DAYS, MIN_SEQUENCES_LSTM,
    ML_FORECAST_HORIZONS_MIN, ML_NUM_FEATURES, ML_SEQUENCE_LENGTH,
    ML_TARGET_ENCODING, ML_CELL_FEATURES, ML_STATION_FEATURES, SAVE_PATHS,
)

MIN_SAMPLES_FOR_PROMOTION = 50
LARGE_SAMPLE_THRESHOLD = 500
TOLERANCE_LARGE = 1.02


def _clean_json_value(value):
    import math
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _clean_json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean_json_value(v) for v in value]
    return value


def _write_training_meta(path, meta):
    meta = _clean_json_value(meta)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False, allow_nan=False)
    return meta

_MODELS_BASE = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "train_data", "models")
)
try:
    from dataset_builder import build_classification_dataset, build_dataset
except Exception as exc:
    debug_log(f"[OPTIONAL_IMPORT] dataset_builder: Import fehlgeschlagen: {exc}")

    def build_classification_dataset():
        return None

    def build_dataset(*args, **kwargs):
        return None


def _current_models_dir():
    return os.path.join(_MODELS_BASE, "current")


def _version_models_dir(version_id):
    return os.path.join(_MODELS_BASE, version_id)


def _list_versions():
    base = _MODELS_BASE
    if not os.path.isdir(base):
        return []
    return sorted([name for name in os.listdir(base) if name.startswith("v_") and os.path.isdir(os.path.join(base, name))])


def _current_target_version():
    current = _current_models_dir()
    try:
        if os.path.islink(current):
            target = os.path.realpath(current)
            if os.path.isdir(target):
                return os.path.basename(target)
        if os.path.isdir(current) and os.path.basename(os.path.realpath(current)).startswith("v_"):
            return os.path.basename(os.path.realpath(current))
    except Exception:
        return None
    return None


def cleanup_old_versions(keep_n=5):
    versions = _list_versions()
    active = _current_target_version()
    deletable = [v for v in versions if v != active]
    for old in deletable[:-keep_n]:
        old_path = _version_models_dir(old)
        for root, dirs, files in os.walk(old_path, topdown=False):
            for f in files:
                os.remove(os.path.join(root, f))
            for d in dirs:
                os.rmdir(os.path.join(root, d))
        os.rmdir(old_path)


def _atomic_switch_current(version_id):
    base_dir = _MODELS_BASE
    target = _version_models_dir(version_id)
    current_link = _current_models_dir()
    tmp_link = os.path.join(base_dir, ".current_tmp")

    # os.replace() kann atomar nur Symlinks/Dateien auf Dateisystem-Ebene ersetzen.
    # Ein echtes Verzeichnis als Ziel führt auf Linux zu IsADirectoryError.
    if os.path.islink(current_link) and not os.path.exists(current_link):
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        os.rename(current_link, os.path.join(base_dir, f"current_broken_{ts}"))

    if os.path.exists(current_link) and not os.path.islink(current_link):
        debug_log(f"[TRAINING] current ist ein echtes Verzeichnis — konvertiere zu Symlink")
        import shutil
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        tmp_backup = os.path.join(base_dir, f"current_backup_{ts}")
        os.rename(current_link, tmp_backup)
        try:
            if os.path.lexists(tmp_link):
                os.remove(tmp_link)
            os.symlink(os.path.relpath(target, base_dir), tmp_link)
            os.replace(tmp_link, current_link)
            shutil.rmtree(tmp_backup, ignore_errors=True)
        except Exception as exc:
            # Rollback: echtes Verzeichnis wiederherstellen
            if os.path.lexists(tmp_link):
                os.remove(tmp_link)
            if os.path.islink(current_link):
                os.remove(current_link)
            if os.path.exists(tmp_backup):
                os.rename(tmp_backup, current_link)
            raise RuntimeError(f"_atomic_switch_current fehlgeschlagen: {exc}") from exc
        return

    if os.path.lexists(tmp_link):
        os.remove(tmp_link)
    os.symlink(os.path.relpath(target, base_dir), tmp_link)
    os.replace(tmp_link, current_link)


def _kinematic_baseline_mae(X_recent, y_recent, model_dir, eval_horizons, avail_cols):
    """B243: MAE der rein kinematischen Vorhersage (Position + v*Horizont) auf denselben
    Samples wie evaluate_on_recent. Encoding-robust (delta|absolute). Feature-Indizes
    x,y,vx,vy = 0,1,2,3 (ML_CELL_FEATURES). Liefert (mae_by_horizon, mae_total)."""
    result_by_h, valid = {}, []
    if np is None or joblib is None:
        return result_by_h, float("inf")
    _enc = ML_TARGET_ENCODING
    scaler_x_path = os.path.join(model_dir, "scaler_X.joblib")
    if not os.path.exists(scaler_x_path):
        return result_by_h, float("inf")
    try:
        scaler_X = joblib.load(scaler_x_path)
        raw = scaler_X.inverse_transform(X_recent)
    except Exception:
        return result_by_h, float("inf")
    x0, y0, vx, vy = raw[:, 0], raw[:, 1], raw[:, 2], raw[:, 3]
    for h_idx, horizon in enumerate(eval_horizons):
        c0, c1 = h_idx * 2, h_idx * 2 + 1
        if c0 not in avail_cols or c1 not in avail_cols:
            continue
        if _enc == "delta":
            pred_x = vx * float(horizon)
            pred_y = vy * float(horizon)
        else:
            pred_x = x0 + vx * float(horizon)
            pred_y = y0 + vy * float(horizon)
        diff = np.abs(np.stack([pred_x, pred_y], axis=1) - y_recent[:, c0:c1 + 1])
        if np.all(np.isnan(diff)):
            continue
        h_mae = float(np.nanmean(diff))
        result_by_h[str(horizon)] = h_mae
        valid.append(h_mae)
    return result_by_h, (float(np.mean(valid)) if valid else float("inf"))


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

    _avail_cols = set()
    for h_idx, horizon in enumerate(ML_FORECAST_HORIZONS_MIN):
        for axis_idx, axis in enumerate(["x", "y"]):
            col = h_idx * 2 + axis_idx
            model_path = os.path.join(model_dir, f"lgbm_h{horizon}_{axis}.txt")
            if not os.path.exists(model_path):
                continue  # P-T08: fehlende Horizonte überspringen (partielle Abdeckung)
            booster = lgb.Booster(model_file=model_path)
            y_pred_scaled[:, col] = booster.predict(X_recent)
            _avail_cols.add(col)

    if not _avail_cols:
        return {"mae_total": float("inf"), "mae_by_horizon": {}, "samples": len(idx)}

    y_pred = scaler_y.inverse_transform(y_pred_scaled)
    mae_by_horizon = {}
    _eval_horizons = _get_training_horizons()  # P29: runtime-fähig
    _valid_h_maes = []
    for h_idx, horizon in enumerate(_eval_horizons):
        c0, c1 = h_idx * 2, h_idx * 2 + 1
        if c0 not in _avail_cols or c1 not in _avail_cols:
            continue
        _diff = np.abs(y_pred[:, c0:c1 + 1] - y_recent[:, c0:c1 + 1])
        if np.all(np.isnan(_diff)):
            continue
        _h_mae = float(np.nanmean(_diff))
        mae_by_horizon[str(horizon)] = _h_mae
        _valid_h_maes.append(_h_mae)
    mae_total = float(np.mean(_valid_h_maes)) if _valid_h_maes else float("inf")

    # B243: kinematische Baseline-MAE auf denselben recent-Samples.
    kin_mae_by_horizon, kin_mae_total = _kinematic_baseline_mae(
        X_recent, y_recent, model_dir, _eval_horizons, _avail_cols
    )
    return {
        "mae_total": mae_total, "mae_by_horizon": mae_by_horizon,
        "kin_mae_total": kin_mae_total, "kin_mae_by_horizon": kin_mae_by_horizon,
        "samples": len(idx),
    }

def _masked_mse(y_true, y_pred):
    """P-T08: MSE-Loss der maskierte Ziele (NaN) ignoriert.
    Maskierte Horizonte tragen 0 zu Loss/Gradient bei."""
    import tensorflow as _tf
    mask = _tf.cast(~_tf.math.is_nan(y_true), _tf.float32)
    y_true_safe = _tf.where(_tf.math.is_nan(y_true), _tf.zeros_like(y_true), y_true)
    sq = _tf.square(y_pred - y_true_safe) * mask
    return _tf.reduce_sum(sq) / (_tf.reduce_sum(mask) + 1e-6)


def _build_lstm(n_horizons: int = 0):
    """P0-2: n_horizons aus _get_training_horizons() — NICHT aus compile-time Import.
    Sicherstellt dass LSTM-Output-Dim mit LightGBM-Zielspalten übereinstimmt.

    B101: Lazy-Re-Import der Keras-Klassen falls beim Modul-Import noch None
    (z. B. wenn TF erst nach Collection verfügbar ist). RuntimeError statt
    kryptischem TypeError wenn TF wirklich fehlt.
    """
    # B101/B110: Lazy-Re-Import — damit pytest.importorskip("tensorflow") greift
    global Sequential, Input, LSTM, Dense, Dropout, Adam, EarlyStopping, ModelCheckpoint  # noqa: PLW0603
    if (
        Sequential is None
        or Input is None
        or LSTM is None
        or Dense is None
        or Dropout is None
        or Adam is None
        or EarlyStopping is None
        or ModelCheckpoint is None
    ):
        _km = _optional_import("tensorflow.keras.models")
        _kl = _optional_import("tensorflow.keras.layers")
        _ko = _optional_import("tensorflow.keras.optimizers")
        _kc = _optional_import("tensorflow.keras.callbacks")
        if _km is not None and _kl is not None and _ko is not None:
            Sequential = getattr(_km, "Sequential", None)
            Input = getattr(_kl, "Input", None)
            LSTM = getattr(_kl, "LSTM", None)
            Dense = getattr(_kl, "Dense", None)
            Dropout = getattr(_kl, "Dropout", None)
            Adam = getattr(_ko, "Adam", None)
        if _kc is not None:
            EarlyStopping = getattr(_kc, "EarlyStopping", None)
            ModelCheckpoint = getattr(_kc, "ModelCheckpoint", None)

    if Sequential is None or Input is None or LSTM is None or Dense is None or Dropout is None or Adam is None:
        raise RuntimeError(
            "[_build_lstm] TensorFlow/Keras nicht verfügbar — "
            "Sequential/Input/LSTM/Dense/Dropout/Adam sind None. "
            "Bitte tensorflow installieren: pip install tensorflow"
        )

    _n = n_horizons if n_horizons > 0 else len(_get_training_horizons())
    model = Sequential([
        Input(shape=(ML_SEQUENCE_LENGTH, ML_NUM_FEATURES)),
        LSTM(64, return_sequences=True),
        Dropout(0.2),
        LSTM(32),
        Dropout(0.2),
        Dense(32, activation="relu"),
        Dense(_n * 2),
    ])
    model.compile(optimizer=Adam(1e-3), loss=_masked_mse)  # P-T08: maskierter Loss
    return model


def train_lstm(X, y, model_dir):
    model_path = os.path.join(model_dir, "weather_lstm.keras")
    os.makedirs(SAVE_PATHS["models"], exist_ok=True)
    if Sequential is None or train_test_split is None:
        debug_log("[LSTM] Skip: tensorflow oder sklearn nicht installiert")
        return {"trained": False, "model_path": model_path, "val_loss": None, "samples": len(X)}
    try:
        from config import MIN_SEQUENCES_LSTM as _LSTM_MIN
    except ImportError:
        _LSTM_MIN = 50
    if len(X) < _LSTM_MIN:
        debug_log(f"[LSTM] Skip: zu wenig Samples ({len(X)} < {_LSTM_MIN})")
        return {"trained": False, "model_path": model_path, "val_loss": None, "samples": len(X)}
    # Fix P07: zeitbasierter Split — Samples sind in build_dataset chronologisch
    # angeordnet. Zufälliger Split würde sehr ähnliche Frames in Train+Val mischen
    # (Data Leakage bei Radarbild-Sequenzen alle 2-5 min).
    split_idx = int(len(X) * 0.8)
    X_train, X_val = X[:split_idx], X[split_idx:]
    y_train, y_val = y[:split_idx], y[split_idx:]
    debug_log(f"[LSTM] Zeitbasierter Split: train={len(X_train)}, val={len(X_val)}")
    model = _build_lstm(n_horizons=len(_get_training_horizons()))  # P0-2
    # B110: Guards für den Fall, dass Keras-Callbacks nicht importiert werden konnten.
    callbacks = []
    if EarlyStopping is not None:
        callbacks.append(EarlyStopping(monitor="val_loss", patience=10, restore_best_weights=True))
    if ModelCheckpoint is not None:
        callbacks.append(ModelCheckpoint(filepath=model_path, monitor="val_loss", save_best_only=True))
    history = model.fit(
        X_train,
        y_train,
        validation_data=(X_val, y_val),
        epochs=200,
        batch_size=32,
        callbacks=callbacks or None,
        verbose=1,
    )
    val_loss = float(min(history.history.get("val_loss", [float("nan")])))
    return {"trained": True, "model_path": model_path, "val_loss": val_loss, "samples": len(X)}


def train_lgbm(X, y, model_dir):
    os.makedirs(SAVE_PATHS["models"], exist_ok=True)
    if lgb is None or train_test_split is None:
        debug_log("[LGBM] Skip: lightgbm oder sklearn nicht installiert")
        return {"trained": False, "models": {}, "best_scores": {}, "samples": len(X)}
    try:
        from config import MIN_SEQUENCES_LGBM as _LGBM_MIN
    except ImportError:
        _LGBM_MIN = 30
    if len(X) < _LGBM_MIN:
        debug_log(f"[LGBM] Skip: zu wenig Samples ({len(X)} < {_LGBM_MIN})")
        return {"trained": False, "models": {}, "best_scores": {}, "samples": len(X)}
    X_flat = X[:, -1, :]
    # Fix P07: zeitbasierter Split (siehe train_lstm).
    split_idx = int(len(X_flat) * 0.8)
    X_train, X_val = X_flat[:split_idx], X_flat[split_idx:]
    y_train, y_val = y[:split_idx], y[split_idx:]
    debug_log(f"[LGBM] Zeitbasierter Split: train={len(X_train)}, val={len(X_val)}")
    base_params = {"num_leaves": 31, "learning_rate": 0.05, "feature_fraction": 0.9, "bagging_fraction": 0.8, "bagging_freq": 5, "verbose": -1}
    point_params = {**base_params, "objective": "regression", "metric": "rmse"}
    quantiles = [0.1, 0.5, 0.9]
    quantiles_to_train = quantiles if len(X) >= 100 else [0.5]
    if len(X) < 100:
        debug_log(f"[LGBM] Wenig Samples ({len(X)} < 100): trainiere nur Median-Quantil (q50)")
    _train_horizons = _get_training_horizons()  # P29: runtime-fähig
    # P-T08: Per-Horizont-Mindestanzahl gültiger (nicht-NaN) Ziele.
    try:
        from config import MIN_SEQUENCES_LGBM_PER_HORIZON as _LGBM_MIN_H
    except ImportError:
        _LGBM_MIN_H = 15
    models, best_scores, quantile_scores = {}, {}, {}
    skipped_horizons = []
    for h_idx, h in enumerate(_train_horizons):
        for axis_idx, axis in enumerate(["x", "y"]):
            target_idx = h_idx * 2 + axis_idx
            # P-T08: nur Zeilen mit gültigem Ziel für DIESE Spalte verwenden
            _tr_mask = ~np.isnan(y_train[:, target_idx])
            _va_mask = ~np.isnan(y_val[:, target_idx])
            _n_valid = int(_tr_mask.sum())
            if _n_valid < _LGBM_MIN_H:
                skipped_horizons.append(f"h{h}_{axis}({_n_valid})")
                continue
            _Xtr = X_train[_tr_mask]
            _ytr = y_train[_tr_mask, target_idx]
            if int(_va_mask.sum()) > 0:
                _Xva = X_val[_va_mask]
                _yva = y_val[_va_mask, target_idx]
            else:
                _Xva, _yva = _Xtr, _ytr  # leeres Val nach Maskierung → Train als Val
            booster = lgb.train(
                point_params,
                lgb.Dataset(_Xtr, label=_ytr),
                num_boost_round=500,
                valid_sets=[lgb.Dataset(_Xva, label=_yva)],
                callbacks=[lgb.early_stopping(20, verbose=False)],
            )
            name = f"lgbm_h{h}_{axis}"
            path = os.path.join(model_dir, f"{name}.txt")
            booster.save_model(path)
            models[name] = path
            best_scores[name] = float(booster.best_score.get("valid_0", {}).get("rmse", float("nan")))

            for quantile in quantiles_to_train:
                q_name = f"q{int(quantile * 100):02d}"
                quantile_params = {**base_params, "objective": "quantile", "alpha": quantile, "metric": "quantile"}
                q_booster = lgb.train(
                    quantile_params,
                    lgb.Dataset(_Xtr, label=_ytr),
                    num_boost_round=500,
                    valid_sets=[lgb.Dataset(_Xva, label=_yva)],
                    callbacks=[lgb.early_stopping(20, verbose=False)],
                )
                q_model_name = f"lgbm_h{h}_{axis}_{q_name}"
                q_path = os.path.join(model_dir, f"{q_model_name}.txt")
                q_booster.save_model(q_path)
                models[q_model_name] = q_path
                quantile_scores[q_model_name] = float(q_booster.best_score.get("valid_0", {}).get("quantile", float("nan")))
    if skipped_horizons:
        debug_log(f"[LGBM] Übersprungene Horizonte (zu wenig Daten): {skipped_horizons}")
    return {"trained": True, "models": models, "best_scores": best_scores, "quantile_scores": quantile_scores, "samples": len(X)}


def _get_training_horizons() -> list:
    """
    P29: Runtime-Horizonte für Training/Evaluation/Laden.
    Priorisiert runtime_config (Admin-Panel), Fallback: config.py.
    """
    try:
        import runtime_config as _rc_tr
        return list(_rc_tr.get("ML_FORECAST_HORIZONS_MIN", ML_FORECAST_HORIZONS_MIN))
    except Exception:
        return list(ML_FORECAST_HORIZONS_MIN)


def _check_model_compatibility(model_dir: str) -> dict:
    """
    P23: Prüft ob das Modell in model_dir mit der aktuellen Runtime-Konfiguration
    kompatibel ist (Horizonte + Feature-Anzahl).
    Gibt {"compatible": bool, "reason": str} zurück.
    """
    meta_path = os.path.join(model_dir, "training_meta.json")
    if not os.path.exists(meta_path):
        return {"compatible": True, "reason": "kein meta — assume compatible"}
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    except Exception:
        return {"compatible": True, "reason": "meta nicht lesbar"}

    trained_horizons = meta.get("horizons_trained") or meta.get("horizons") or meta.get("ML_FORECAST_HORIZONS_MIN")
    trained_features = meta.get("feature_count")
    trained_schema_hash = meta.get("feature_schema_hash")
    current_schema = get_current_feature_schema()

    try:
        import runtime_config as _rc_mt
        runtime_horizons = list(_rc_mt.get("ML_FORECAST_HORIZONS_MIN", ML_FORECAST_HORIZONS_MIN))
    except Exception:
        runtime_horizons = list(ML_FORECAST_HORIZONS_MIN)

    if trained_schema_hash and trained_schema_hash != current_schema.get("feature_schema_hash"):
        return {
            "compatible": False,
            "reason": f"Feature-Schema-Hash: trainiert={trained_schema_hash}, aktuell={current_schema.get('feature_schema_hash')}",
        }
    if trained_horizons is not None and sorted(trained_horizons) != sorted(runtime_horizons):
        return {
            "compatible": False,
            "reason": f"Horizonte: trainiert={trained_horizons}, runtime={runtime_horizons}",
        }
    if trained_features is not None and trained_features != ML_NUM_FEATURES:
        return {
            "compatible": False,
            "reason": f"Feature-Anzahl: trainiert={trained_features}, aktuell={ML_NUM_FEATURES}",
        }
    return {"compatible": True, "reason": "OK"}


def _quarantine_incompatible_current(reason: str) -> None:
    """
    B116: Benennt einen dauerhaft inkompatiblen `current`-Modellstand um
    (current -> current_incompatible_<ts>), damit load_* sauber 'kein Modell'
    liefert statt einen veralteten Feature-Stand zu behalten. Kein Löschen
    (Modelle sind user-generierte Lerndaten). Idempotent: läuft nur, wenn ein
    realer current-Pfad existiert.
    """
    try:
        cur = _current_models_dir()
        if not cur or not os.path.isdir(cur):
            return
        _stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        _dest = f"{cur.rstrip('/')}_incompatible_{_stamp}"
        os.rename(cur, _dest)
        debug_log(
            f"[MODEL] B116: inkompatibler current-Stand quarantänisiert "
            f"({reason}) → {_dest}. System läuft kinematisch bis Retrain."
        )
    except Exception as exc:
        debug_log(f"[MODEL] B116: Quarantäne fehlgeschlagen: {exc}")



def _has_required_model_artifacts(model_dir: str) -> bool:
    if not os.path.isdir(model_dir):
        return False
    if not (os.path.exists(os.path.join(model_dir, "scaler_X.joblib")) and os.path.exists(os.path.join(model_dir, "scaler_y.joblib"))):
        return False
    has_lstm = os.path.exists(os.path.join(model_dir, "weather_lstm.keras"))
    has_lgbm = any(
        os.path.exists(os.path.join(model_dir, f"lgbm_h{h}_{axis}.txt"))
        for h in _get_training_horizons()
        for axis in ("x", "y")
    )
    return has_lstm or has_lgbm


def _is_valid_current_model(model_dir: str | None = None) -> bool:
    cur = model_dir or _current_models_dir()
    if not os.path.lexists(cur):
        return False
    if os.path.islink(cur) and not os.path.exists(cur):
        return False
    if not os.path.isdir(cur):
        return False
    compat = _check_model_compatibility(cur)
    if not bool(compat.get("compatible") and _has_required_model_artifacts(cur)):
        return False
    try:
        from ml_readiness import get_forecast_runtime_status
        runtime = get_forecast_runtime_status(write_json=False, model_dir=cur)
        if runtime.get("runtime_mode") != "ml":
            debug_log(f"[MODEL] current technisch vorhanden, aber nicht promoted: {runtime.get('fallback_reason')}")
            return False
    except Exception as exc:
        debug_log(f"[MODEL] Promotion-Prüfung für current fehlgeschlagen: {exc}")
        return False
    return True


def _status_reason(status: str, promotion_samples: int) -> str:
    missing = max(0, MIN_SAMPLES_FOR_PROMOTION - int(promotion_samples or 0))
    mapping = {
        "cold_start_promoted_low_confidence": f"Erstes ML-Modell wurde aktiviert, obwohl erst {promotion_samples} von {MIN_SAMPLES_FOR_PROMOTION} aktuellen Promotion-/Validierungs-Samples vorhanden sind. Das Modell ist nutzbar, aber mit niedriger Vertrauensstufe markiert.",
        "cold_start_insufficient_samples": "Erstaktivierung blockiert: kein brauchbarer Modellkandidat vorhanden oder Training nicht erfolgreich abgeschlossen.",
        "cold_start_rejected_invalid_model": "Erstes Modell wurde nicht aktiviert, weil Modellartefakte fehlen, inkompatibel sind oder das Training ungültig war.",
        "rejected_low_samples": f"Neuer Trainingslauf wurde nicht promoted: nur {promotion_samples} von {MIN_SAMPLES_FOR_PROMOTION} aktuellen Promotion-/Validierungs-Samples vorhanden. Das aktive Modell bleibt unverändert.",
        "promoted": "Modell wurde aktiviert.",
        "rejected": "Neues Modell war nicht besser als das aktive Modell.",
        "rejected_incompatible": "Modell ist inkompatibel zu aktuellen Horizonten oder Features.",
        "rejected_invalid_holdout": "Holdout-Prüfung ungültig. Modell wurde nicht aktiviert.",
        "rejected_below_kinematic_baseline": "Modell wurde nicht aktiviert, weil sein MAE schlechter als die kinematische Baseline war. Kinematik bleibt in diesem Vergleich überlegen.",
        "fallback_kinematic": "Kinematischer Fallback ist aktiv, weil kein nutzbares ML-Modell verwendet werden kann.",
        "insufficient_samples": f"Zu wenige Samples für eine belastbare Aktivierung oder Bewertung. Es fehlen {missing} Promotion-/Validierungs-Samples.",
        "no_data": "Kein nutzbarer Datensatz für diesen Trainingslauf vorhanden.",
    }
    text = mapping.get(status, status)
    if missing and status not in {"cold_start_promoted_low_confidence", "rejected_low_samples"}:
        text += f" Es fehlen {missing} Promotion-/Validierungs-Samples."
    return text

def load_lstm(model_dir=None):
    if load_model is None:
        return None
    _dir = model_dir or _current_models_dir()
    model_path = os.path.join(_dir, "weather_lstm.keras")
    if not os.path.exists(model_path):
        return None
    # P24: Kompatibilitätsprüfung (Horizonte + Feature-Anzahl)
    compat = _check_model_compatibility(_dir)
    if not compat["compatible"]:
        debug_log(
            f"[MODEL] load_lstm: Modell inkompatibel — {compat['reason']}. "
            f"Kinematischer Fallback aktiv."
        )
        # B116: dauerhaft inkompatiblen current beiseiteräumen, damit der nächste
        # erfolgreiche Retrain einen sauberen Cold-Start machen kann.
        _quarantine_incompatible_current(compat["reason"])
        return None
    try:
        # P-T08: compile=False — der maskierte Trainings-Loss wird zur Inferenz
        # nicht gebraucht und wäre sonst nicht deserialisierbar.
        return load_model(model_path, compile=False)
    except Exception as exc:
        debug_log(f"[MODEL] load_lstm Fehler: {exc}")
        return None


def load_lgbm_models():
    models = {}
    if lgb is None:
        return models
    _dir = _current_models_dir()
    # P29/P24: Kompatibilitätsprüfung vor dem Laden
    compat = _check_model_compatibility(_dir)
    if not compat["compatible"]:
        debug_log(
            f"[MODEL] load_lgbm_models: Modell inkompatibel — {compat['reason']}. "
            f"Kinematischer Fallback aktiv."
        )
        # B116: auch ein reiner LGBM-Ladepfad darf keinen stale current behalten.
        _quarantine_incompatible_current(compat["reason"])
        return models  # leer → kinematischer Fallback in prediction.py
    _load_horizons = _get_training_horizons()  # P29: runtime-fähig
    for h in _load_horizons:
        for axis in ["x", "y"]:
            name = f"lgbm_h{h}_{axis}"
            path = os.path.join(_dir, f"{name}.txt")
            if os.path.exists(path):
                models[name] = lgb.Booster(model_file=path)
            for q in ["q10", "q50", "q90"]:
                q_name = f"{name}_{q}"
                q_path = os.path.join(_dir, f"{q_name}.txt")
                if os.path.exists(q_path):
                    models[q_name] = lgb.Booster(model_file=q_path)
    return models


def train_intensification_classifier(model_dir):
    model_path = os.path.join(model_dir, "lgbm_intensification.txt")
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
    X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, stratify=y)
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


def _compute_holdout_metrics(X_h, y_h, model_dir: str) -> dict:
    """
    Berechnet MAE auf dem Holdout-Set (letzter Tag) mit den gerade
    trainierten Modellen. Gibt ehrliche Test-Metriken ohne Data-Leakage.
    """
    result = {"samples": int(len(X_h)), "mae_px": None, "mae_by_horizon": {}}
    if np is None or len(X_h) == 0:
        return result
    try:
        lstm_path = os.path.join(model_dir, "weather_lstm.keras")
        scaler_y_path = os.path.join(model_dir, "scaler_y.joblib")
        if load_model is None or joblib is None or not (os.path.exists(lstm_path) and os.path.exists(scaler_y_path)):
            result["note"] = "Modelle nicht geladen"
            return result

        _lstm = load_model(lstm_path, compile=False)  # P-T08: maskierter Loss nicht nötig
        _scaler_y = joblib.load(scaler_y_path)
        preds_scaled = _lstm.predict(X_h, verbose=0)
        preds = _scaler_y.inverse_transform(preds_scaled)
        # B242: y_h stammt aus dataset["y"] (= y_scaled, StandardScaler). preds sind nach
        # inverse_transform roh — daher muss y_h ebenfalls in den Rohraum, sonst vergleicht
        # errs roh gegen skaliert und misst ~den mittleren Positionsbetrag statt des
        # Modellfehlers (Beleg Export 2026-06-23: mae_px≈217 fast konstant über alle
        # Horizonte). Danach ist holdout.mae_px im selben Rohraum wie evaluate_on_recent.
        y_h_raw = _scaler_y.inverse_transform(y_h)  # NaN bleibt NaN (maskierte Horizonte)
        errs = np.abs(preds - y_h_raw)  # beide roh; y_h_raw kann NaN enthalten
        mae_total = float(np.nanmean(errs))
        result["mae_px"] = round(mae_total, 3)
        for i, h in enumerate(ML_FORECAST_HORIZONS_MIN):
            h_errs = errs[:, i * 2:(i + 1) * 2]
            if np.all(np.isnan(h_errs)):
                result["mae_by_horizon"][str(h)] = None
            else:
                result["mae_by_horizon"][str(h)] = round(float(np.nanmean(h_errs)), 3)
        result["note"] = "OK"
    except Exception as exc:
        result["note"] = f"Fehler: {exc}"
        debug_log(f"[HOLDOUT] Metric-Fehler: {exc}")
    return result


def retrain_all():
    status = "failed"
    timestamp = datetime.now(timezone.utc).strftime("v_%Y-%m-%dT%H-%M-%SZ")
    version_dir = _version_models_dir(timestamp)
    os.makedirs(version_dir, exist_ok=True)

    dataset = build_dataset(model_save_dir=version_dir)
    X = np.asarray([])   # Sicherer Default vor try
    y = np.asarray([])
    try:
        X = np.asarray(dataset.get("X", [])) if np is not None else np.asarray([])
        y = np.asarray(dataset.get("y", [])) if np is not None else np.asarray([])
        has_data = np is not None and getattr(X, "size", 0) and getattr(y, "size", 0)

        # P20: Letzter Tag als echter Holdout — nicht zum Training verwendet.
        # Samples mit timestamp >= (jetzt - 24h) → X_holdout/y_holdout
        # Rest → X_train_full/y_train_full (weiterhin intern 80/20 gesplittet)
        X_train_full, y_train_full = X, y
        X_holdout, y_holdout = np.asarray([]), np.asarray([])
        if has_data:
            _ts_list = dataset.get("timestamps", [])
            if len(_ts_list) == len(X):
                _cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
                _cutoff_str = _cutoff.strftime("%Y-%m-%d_%H-%M-%S")
                _holdout_mask = np.array([ts >= _cutoff_str for ts in _ts_list], dtype=bool)
                _train_mask = ~_holdout_mask
                if _holdout_mask.any() and _train_mask.any():
                    X_holdout = X[_holdout_mask]
                    y_holdout = y[_holdout_mask]
                    X_train_full = X[_train_mask]
                    y_train_full = y[_train_mask]
                    debug_log(
                        f"[TRAINING] P20 Holdout: {_holdout_mask.sum()} Samples (letzter Tag), "
                        f"Training: {_train_mask.sum()} Samples"
                    )
                else:
                    debug_log("[TRAINING] P20 Holdout: zu wenige Samples für Split — kein Holdout")
            else:
                debug_log("[TRAINING] P20 Holdout: kein timestamp-Array in Dataset — kein Holdout")

        has_train_data = has_data and getattr(X_train_full, "size", 0) and getattr(y_train_full, "size", 0)
        lstm_result = train_lstm(X_train_full, y_train_full, model_dir=version_dir) if has_train_data else {"trained": False, "val_loss": None}
        lgbm_result = train_lgbm(X_train_full, y_train_full, model_dir=version_dir) if has_train_data else {"trained": False, "best_scores": {}, "quantile_scores": {}}
        intensification_result = train_intensification_classifier(model_dir=version_dir)
        try:
            from intensity_regression import train_intensity_regressors
            reg_meta = train_intensity_regressors()
            debug_log(f"[TRAINING] Intensity-Regressoren: {reg_meta}")
        except Exception as _exc:
            debug_log(f"[TRAINING] Intensity-Regressoren übersprungen: {_exc}")
        _feature_schema = get_current_feature_schema()
        meta = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "feature_schema_hash": _feature_schema["feature_schema_hash"],
            "feature_schema_version": _feature_schema["schema_version"],
            "feature_schema": _feature_schema,
            "version": timestamp,
            "ML_FORECAST_HORIZONS_MIN": list(_get_training_horizons()),   # P0-2
            "horizons": list(_get_training_horizons()),                    # P0-2
            "num_samples": int(len(X)) if has_data else 0,
            "rejected_samples": int(dataset.get("rejected_samples", 0)),
            "rejection_reasons": dataset.get("rejection_reasons", {}),
            "schema_compatible_samples": int(dataset.get("schema_compatible_samples", 0)),
            "schema_legacy_samples": int(dataset.get("schema_legacy_samples", 0)),
            "schema_mismatch_samples": int(dataset.get("schema_mismatch_samples", 0)),
            "lstm": {"trained": lstm_result.get("trained", False), "val_loss": lstm_result.get("val_loss")},
            "horizons_trained": list(_get_training_horizons()),   # P0-2 + P23: Runtime-Horizonte
            "feature_count": int(ML_NUM_FEATURES),               # P23: Feature-Dimension bei Training
            # B250: Feature-Namen in Trainings-Reihenfolge persistieren.
            # Ermöglicht Konsistenz-Check bei Inferenz: stimmt die aktuelle ML_CELL_FEATURES-Liste
            # mit der beim Training verwendeten überein? Mismatch → Kinematik-Fallback.
            "feature_names": list(ML_CELL_FEATURES) + list(ML_STATION_FEATURES) + [
                "hour_sin", "hour_cos", "month_sin", "month_cos"
            ],
            "target_encoding": ML_TARGET_ENCODING,               # P58: delta|absolute
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
            "dataset": {
                "scope": "cumulative_rolling",
                "retention_days": DATA_RETENTION_DAYS,
                "total_samples": int(len(X)) if has_data else 0,
                "train_samples": int(len(X_train_full)) if has_data else 0,
                "holdout_samples": int(len(X_holdout)) if has_data else 0,
                "sequence_length": ML_SEQUENCE_LENGTH,
                "feature_schema_hash": _feature_schema["feature_schema_hash"],
                "schema_compatible_samples": int(dataset.get("schema_compatible_samples", 0)),
                "schema_legacy_samples": int(dataset.get("schema_legacy_samples", 0)),
                "schema_mismatch_samples": int(dataset.get("schema_mismatch_samples", 0)),
            },
            "holdout": _compute_holdout_metrics(
                X_holdout, y_holdout,
                version_dir,
            ) if has_data and getattr(X_holdout, "size", 0) else {
                "samples": 0,
                "mae_px": None,
                "note": "Kein Holdout-Set verfügbar (zu wenige Samples oder erster Tag)",
            },
        }
        meta = _write_training_meta(os.path.join(version_dir, "training_meta.json"), meta)
    except Exception:
        _feature_schema = get_current_feature_schema()
        meta = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "feature_schema_hash": _feature_schema["feature_schema_hash"],
            "feature_schema_version": _feature_schema["schema_version"],
            "feature_schema": _feature_schema,
            "version": timestamp,
            "ML_FORECAST_HORIZONS_MIN": list(_get_training_horizons()),   # P0-2
            "horizons": list(_get_training_horizons()),                    # P0-2
            "num_samples": 0,
            "rejected_samples": 0,
            "rejection_reasons": {},
            "target_encoding": ML_TARGET_ENCODING,               # P58: delta|absolute
        }

    new_eval = evaluate_on_recent(version_dir)
    current_dir = _current_models_dir()
    has_current = _is_valid_current_model(current_dir)
    old_eval = evaluate_on_recent(current_dir) if has_current else {"mae_total": float("inf"), "mae_by_horizon": {}, "samples": 0}

    # Fix P07: harte Promotion-Regeln
    #
    # Mindestsamples für Promotion (außer Cold-Start):
    #   - new_eval muss >= 50 verifizierbare Samples haben.
    #   - Eine Verbesserungstoleranz von 2 % wird nur akzeptiert, wenn
    #     mindestens 500 Samples vorliegen — ansonsten muss new < old strikt sein.
    promotion_samples = int(new_eval.get("samples", 0) or 0)
    _mae_new     = float(new_eval.get("mae_total", float("inf")))
    _mae_old     = float(old_eval.get("mae_total", float("inf")))
    _kin_baseline_mae = float(new_eval.get("kin_mae_total", float("inf")))  # B243

    # P30: Zentrale Compat-Prüfung vor jeder Promotion (Cold-Start + regulär).
    # Prüft: Horizonte, Feature-Anzahl (aus training_meta.json).
    _compat = _check_model_compatibility(version_dir)
    if not _compat["compatible"]:
        status = "rejected_incompatible"
        debug_log(
            f"[TRAINING] REJECTED {timestamp} (inkompatibel): {_compat['reason']}. "
            f"Retraining mit passenden Horizonten/Features erforderlich."
        )
    elif not has_current:
        trained_ok = bool(meta.get("lstm", {}).get("trained") or meta.get("lgbm", {}).get("trained"))
        dataset_ok = int(meta.get("dataset", {}).get("total_samples", meta.get("num_samples", 0)) or 0) >= int(MIN_SEQUENCES_LSTM)
        holdout = meta.get("holdout", {})
        holdout_mae = holdout.get("mae_px")
        holdout_ok = holdout.get("samples", 0) == 0 or (isinstance(holdout_mae, (int, float)) and holdout_mae < float("inf"))
        artifacts_ok = _has_required_model_artifacts(version_dir)
        if trained_ok and dataset_ok and artifacts_ok and holdout_ok:
            status = "cold_start_promoted_low_confidence" if promotion_samples < MIN_SAMPLES_FOR_PROMOTION else "promoted"
            _atomic_switch_current(timestamp)
            debug_log(f"[TRAINING] Cold-Start aktiviert {timestamp} (promotion_samples={promotion_samples}, low_confidence={promotion_samples < MIN_SAMPLES_FOR_PROMOTION})")
        else:
            status = "cold_start_rejected_invalid_model" if trained_ok else "cold_start_insufficient_samples"
            debug_log(f"[TRAINING] Cold-Start ABGELEHNT: trained={trained_ok}, dataset_ok={dataset_ok}, artifacts={artifacts_ok}, holdout_ok={holdout_ok}")
    elif getattr(X, "size", 0) == 0:
        status = "no_data"
        debug_log(
            f"[TRAINING] SKIPPED promotion {timestamp} "
            f"(no_data — current bleibt erhalten)"
        )
    elif promotion_samples < MIN_SAMPLES_FOR_PROMOTION:
        status = "rejected_low_samples"
        debug_log(
            f"[TRAINING] REJECTED {timestamp} "
            f"(samples={promotion_samples} < {MIN_SAMPLES_FOR_PROMOTION} — "
            f"keine Promotion ohne ausreichende Validierung)"
        )
    elif (
        isinstance(_kin_baseline_mae, (int, float))
        and _kin_baseline_mae < float("inf")
        and _mae_new > _kin_baseline_mae
    ):
        # B243: ML schlägt den kinematischen Fallback nicht -> keine Promotion.
        status = "rejected_below_kinematic_baseline"
        debug_log(
            f"[TRAINING] REJECTED {timestamp}: ML mae_new={_mae_new:.4f} > "
            f"kinematische Baseline={_kin_baseline_mae:.4f} — kein ML-Vorteil, "
            f"kinematischer Fallback bleibt aktiv."
        )
    elif promotion_samples >= LARGE_SAMPLE_THRESHOLD and _mae_new < _mae_old * TOLERANCE_LARGE:
        status = "promoted"
        _atomic_switch_current(timestamp)
        debug_log(
            f"[TRAINING] PROMOTED {timestamp} (large-sample tolerance: "
            f"mae_new={_mae_new:.4f} vs mae_old={_mae_old:.4f}, "
            f"samples={promotion_samples})"
        )
    elif _mae_new < _mae_old:
        # P30: Holdout-MAE prüfen — muss endlich sein (Training ohne Fehler abgeschlossen)
        _holdout = meta.get("holdout", {})
        _holdout_mae = _holdout.get("mae_px")
        _holdout_ok = (
            _holdout_mae is not None
            and isinstance(_holdout_mae, (int, float))
            and _holdout_mae < float("inf")
        ) or _holdout.get("samples", 0) == 0  # kein Holdout-Set → trotzdem erlaubt
        if not _holdout_ok:
            status = "rejected_invalid_holdout"
            debug_log(
                f"[TRAINING] REJECTED {timestamp}: Holdout-MAE ungültig "
                f"({_holdout_mae}) — Promotion abgebrochen."
            )
        else:
            status = "promoted"
            _atomic_switch_current(timestamp)
            debug_log(
                f"[TRAINING] PROMOTED {timestamp} "
                f"(mae_new={_mae_new:.4f} < mae_old={_mae_old:.4f}, "
                f"samples={promotion_samples}, holdout_mae_px={_holdout_mae})"
            )
    else:
        status = "rejected"
        debug_log(
            f"[TRAINING] REJECTED {timestamp} "
            f"(mae_new={_mae_new:.4f} vs mae_old={_mae_old:.4f}, "
            f"samples={promotion_samples})"
        )

    low_confidence = bool(status == "cold_start_promoted_low_confidence")
    meta["status"] = status
    if not isinstance(meta.get("dataset"), dict):
        meta["dataset"] = {
            "scope": "cumulative_rolling",
            "retention_days": DATA_RETENTION_DAYS,
            "total_samples": int(len(X)) if getattr(X, "size", 0) else int(meta.get("num_samples", 0) or 0),
            "train_samples": int(len(X_train_full)) if 'X_train_full' in locals() and getattr(X_train_full, "size", 0) else 0,
            "holdout_samples": int(len(X_holdout)) if 'X_holdout' in locals() and getattr(X_holdout, "size", 0) else 0,
            "sequence_length": ML_SEQUENCE_LENGTH,
        }
    meta.setdefault("dataset", {
        "scope": "cumulative_rolling",
        "retention_days": DATA_RETENTION_DAYS,
        "total_samples": int(len(X)) if getattr(X, "size", 0) else 0,
        "train_samples": 0,
        "holdout_samples": 0,
        "sequence_length": ML_SEQUENCE_LENGTH,
    })
    meta["validation"] = {
        "mae_old": old_eval.get("mae_total"),
        "mae_new": new_eval.get("mae_total"),
        "mae_by_horizon_old": old_eval.get("mae_by_horizon", {}),
        "mae_by_horizon_new": new_eval.get("mae_by_horizon", {}),
        "kin_baseline_mae": new_eval.get("kin_mae_total"),                 # B243
        "kin_baseline_by_horizon": new_eval.get("kin_mae_by_horizon", {}),  # B243
        "samples_recent": promotion_samples,
        "samples_required": MIN_SAMPLES_FOR_PROMOTION,
        "samples_missing": max(0, MIN_SAMPLES_FOR_PROMOTION - promotion_samples),
        "low_confidence": low_confidence,
        "status": status,
        "status_reason": _status_reason(status, promotion_samples),
    }
    meta = _write_training_meta(os.path.join(version_dir, "training_meta.json"), meta)

    cleanup_old_versions(keep_n=5)
    return meta


if __name__ == "__main__":
    retrain_all()
