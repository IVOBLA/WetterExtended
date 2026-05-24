import glob
import json
import os
from datetime import datetime
from math import cos, pi, sin

import importlib
import importlib.util
np = importlib.import_module("numpy") if importlib.util.find_spec("numpy") else None

joblib = importlib.import_module("joblib") if importlib.util.find_spec("joblib") else None
pd = importlib.import_module("pandas") if importlib.util.find_spec("pandas") else None
StandardScaler = None
if importlib.util.find_spec("sklearn"):
    StandardScaler = importlib.import_module("sklearn.preprocessing").StandardScaler


try:
    from debug_utils import debug_log
except Exception:
    def debug_log(message):
        print(message)

try:
    from geo_utils import pixel_to_geo
except Exception:
    def pixel_to_geo(x, y):
        return 0.0, 0.0

try:
    from utils import find_nearest_station
except Exception:
    def find_nearest_station(lat, lon, stations):
        return None

from config import (
    ML_CELL_FEATURES,
    ML_FORECAST_HORIZONS_MIN,
    ML_SEQUENCE_LENGTH,
    ML_STATION_FEATURES,
    SAVE_PATHS,
)
from data_quality import validate_sample


def _safe_float(value):
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _parse_ts(path):
    name = os.path.splitext(os.path.basename(path))[0]
    return datetime.strptime(name, "%Y-%m-%d_%H-%M-%S")


def _frame_features(obj, stations, ts):
    cell_features = [_safe_float(obj.get(key, 0.0)) for key in ML_CELL_FEATURES]

    # Fix P02: Lat/Lon direkt aus dem Objekt nehmen (object_tracking.py speichert
    # die geografische Position bereits korrekt mit SKALIERTEN Koordinaten).
    # Fallback nur wenn lat/lon fehlen: pixel_to_geo mit UPSCALE-korrigierten
    # Koordinaten (obj["x"]/y sind pre-upscale, pixel_to_geo erwartet skaliert).
    _lat_obj = obj.get("lat")
    _lon_obj = obj.get("lon")
    if _lat_obj is not None and _lon_obj is not None:
        lat = float(_lat_obj)
        lon = float(_lon_obj)
    else:
        try:
            from config import UPSCALE_FACTOR as _UF_DS
        except Exception:
            _UF_DS = 3.0
        _ox = _safe_float(obj.get("x", 0.0)) * float(_UF_DS)
        _oy = _safe_float(obj.get("y", 0.0)) * float(_UF_DS)
        lat, lon = pixel_to_geo(_ox, _oy)

    nearest_station = find_nearest_station(lat, lon, stations) if stations else None
    station_features = [
        _safe_float(nearest_station.get(key, 0.0)) if nearest_station else 0.0
        for key in ML_STATION_FEATURES
    ]

    hour_fraction = (ts.hour * 60 + ts.minute) / (24 * 60)
    hour_angle = 2 * pi * hour_fraction
    month_fraction = (ts.month - 1) / 12.0
    month_angle = 2 * pi * month_fraction
    time_features = [sin(hour_angle), cos(hour_angle), sin(month_angle), cos(month_angle)]

    return cell_features + station_features + time_features



def _empty_result():
    return {"X": [], "y": [], "y_raw": [], "ids": [], "rejected_samples": 0, "rejection_reasons": {}}


def _dependencies_available():
    missing = []
    if np is None:
        missing.append("numpy")
    if joblib is None:
        missing.append("joblib")
    if pd is None:
        missing.append("pandas")
    if StandardScaler is None:
        missing.append("scikit-learn")
    return missing

def _current_models_dir():
    return os.path.join(SAVE_PATHS["models"], "current")


def load_scalers():
    if joblib is None:
        return None, None

    base_dir = _current_models_dir()
    scaler_x_path = os.path.join(base_dir, "scaler_X.joblib")
    scaler_y_path = os.path.join(base_dir, "scaler_y.joblib")
    if not (os.path.exists(scaler_x_path) and os.path.exists(scaler_y_path)):
        return None, None
    return joblib.load(scaler_x_path), joblib.load(scaler_y_path)


def build_dataset(model_save_dir=None):
    missing_deps = _dependencies_available()
    if missing_deps:
        debug_log(f"[DATASET] Abbruch: fehlende Abhängigkeiten: {', '.join(missing_deps)}")
        return _empty_result()

    obj_files = sorted(glob.glob(os.path.join(SAVE_PATHS["objects"], "*.json")))
    wthr_files = sorted(glob.glob(os.path.join(SAVE_PATHS["weather"], "*.json")))

    paired = []
    weather_by_name = {os.path.basename(p): p for p in wthr_files}
    for op in obj_files:
        base = os.path.basename(op)
        wp = weather_by_name.get(base)
        if wp:
            paired.append((op, wp))

    if not paired:
        debug_log("[DATASET] Keine passenden Objekt/Wetter-Dateipaare gefunden.")
        return _empty_result()

    # Fix #5: Timestamp-basierte Horizont-Suche (statt fester h//5 Frame-Index-Annahme)
    # Hintergrund: Live-Loop kann 2-Min-Intervalle haben → h//5 wäre falsch
    from datetime import timedelta as _td_ds
    _DS_TOL_FACTOR  = 0.5   # 50 % des Horizonts als Toleranz
    _DS_MIN_TOL_MIN = 3.0   # mindestens 3 Minuten Toleranz
    # min_required: Sequenz + mind. 1 zukünftiger Frame
    min_required = ML_SEQUENCE_LENGTH + 1
    if len(paired) < min_required:
        debug_log(f"[DATASET] Zu wenige Frames: {len(paired)} < {min_required}.")
        return _empty_result()

    frames = []
    for op, wp in paired:
        try:
            frames.append((op, wp, _parse_ts(op), _load_json(op), _load_json(wp)))
        except Exception as exc:
            debug_log(f"[DATASET] Fehler beim Laden von {op}: {exc}")

    X_rows, y_rows, ids = [], [], []
    tabular_rows = []
    rejection_reasons = {}
    n_rejected = 0

    # Fix #5: Kein festes max_h_steps mehr — Timestamp-Suche erledigt die Begrenzung
    for i in range(ML_SEQUENCE_LENGTH - 1, len(frames)):
        seq_slice = frames[i - ML_SEQUENCE_LENGTH + 1 : i + 1]
        now_ts = seq_slice[-1][2]
        seq_obj_maps = [{str(o.get("id")): o for o in frm[3] if isinstance(o, dict) and "id" in o} for frm in seq_slice]

        common_ids = set(seq_obj_maps[0].keys())
        for m in seq_obj_maps[1:]:
            common_ids &= set(m.keys())

        if not common_ids:
            continue

        # Fix #5: Besten Frame per echtem Timestamp suchen
        future_obj_maps = []
        for h_min in ML_FORECAST_HORIZONS_MIN:
            target_ts = now_ts + _td_ds(minutes=h_min)
            tol       = _td_ds(minutes=max(h_min * _DS_TOL_FACTOR, _DS_MIN_TOL_MIN))
            best_idx, best_diff = None, _td_ds(days=999)
            for j in range(i + 1, len(frames)):
                diff = abs(frames[j][2] - target_ts)
                if diff < best_diff:
                    best_diff, best_idx = diff, j
                if frames[j][2] > target_ts + tol:
                    break  # frames sind sortiert → kein besserer Kandidat mehr
            if best_idx is not None and best_diff <= tol:
                fut_objs = frames[best_idx][3]
            else:
                fut_objs = []
                debug_log(f"[DATASET] Kein Frame für h={h_min}min nahe {target_ts} (best_diff={best_diff})")
            future_obj_maps.append(
                {str(o.get("id")): o for o in fut_objs
                 if isinstance(o, dict) and "id" in o}
            )

        for oid in common_ids:
            if any(oid not in fmap for fmap in future_obj_maps):
                continue

            seq_features = []
            seq_objects = []
            valid = True
            for op, wp, ts, objs, stations in seq_slice:
                obj = next((o for o in objs if str(o.get("id")) == oid), None)
                if obj is None:
                    valid = False
                    break
                seq_features.append(_frame_features(obj, stations, ts))
                seq_objects.append(obj)

            if not valid:
                continue

            targets = []
            for fmap in future_obj_maps:
                fo = fmap[oid]
                targets.extend([_safe_float(fo.get("x", 0.0)), _safe_float(fo.get("y", 0.0))])

            ok, reason = validate_sample(seq_features, targets, seq_context=seq_objects)
            if not ok:
                n_rejected += 1
                rejection_reasons[reason or "unknown"] = rejection_reasons.get(reason or "unknown", 0) + 1
                continue

            X_rows.append(seq_features)
            y_rows.append(targets)
            ids.append({"id": oid, "timestamp": now_ts.strftime("%Y-%m-%d_%H-%M-%S")})

            tab_row = {k: v for k, v in zip(ML_CELL_FEATURES + ML_STATION_FEATURES + ["hour_sin", "hour_cos", "month_sin", "month_cos"], seq_features[-1])}
            for h_min, (tx, ty) in zip(ML_FORECAST_HORIZONS_MIN, np.array(targets).reshape(-1, 2)):
                tab_row[f"target_x_{h_min}"] = tx
                tab_row[f"target_y_{h_min}"] = ty
            tab_row["id"] = oid
            tab_row["timestamp"] = now_ts.strftime("%Y-%m-%d_%H-%M-%S")
            tabular_rows.append(tab_row)

    if not X_rows:
        debug_log("[DATASET] Keine gültigen Sequenzen gefunden.")
        return _empty_result()

    X = np.asarray(X_rows, dtype=float)
    y_raw = np.asarray(y_rows, dtype=float)

    effective_model_dir = model_save_dir or os.path.join(
        SAVE_PATHS.get("models", "train_data/models"), "current"
    )
    os.makedirs(effective_model_dir, exist_ok=True)
    os.makedirs(SAVE_PATHS["dataset"], exist_ok=True)

    scaler_X = StandardScaler()
    X_flat = X.reshape(-1, X.shape[-1])
    X_scaled = scaler_X.fit_transform(X_flat).reshape(X.shape)

    scaler_y = StandardScaler()
    y_scaled = scaler_y.fit_transform(y_raw)

    joblib.dump(scaler_X, os.path.join(effective_model_dir, "scaler_X.joblib"))
    joblib.dump(scaler_y, os.path.join(effective_model_dir, "scaler_y.joblib"))

    np.savez(
        os.path.join(SAVE_PATHS["dataset"], "dataset.npz"),
        X=X_scaled,
        y=y_scaled,
        y_raw=y_raw,
        ids=np.asarray(ids, dtype=object),
    )

    pd.DataFrame(tabular_rows).to_parquet(os.path.join(SAVE_PATHS["dataset"], "tabular.parquet"), index=False)

    debug_log(f"[DATASET] Datensatz gebaut: X={X_scaled.shape}, y={y_scaled.shape}")
    debug_log(f"[DATASET] {len(X_rows)} kept, {n_rejected} rejected (reasons: {rejection_reasons})")
    return {"X": X_scaled, "y": y_scaled, "y_raw": y_raw, "ids": ids, "rejected_samples": n_rejected, "rejection_reasons": rejection_reasons}


def build_classification_dataset():
    missing_deps = _dependencies_available()
    if missing_deps:
        debug_log(f"[DATASET-CLS] Abbruch: fehlende Abhängigkeiten: {', '.join(missing_deps)}")
        return {"X": [], "y": [], "samples": 0, "positive_samples": 0}

    obj_files = sorted(glob.glob(os.path.join(SAVE_PATHS["objects"], "*.json")))
    wthr_files = sorted(glob.glob(os.path.join(SAVE_PATHS["weather"], "*.json")))
    weather_by_name = {os.path.basename(p): p for p in wthr_files}
    paired = [(op, weather_by_name[os.path.basename(op)]) for op in obj_files if os.path.basename(op) in weather_by_name]
    if not paired:
        debug_log("[DATASET-CLS] Keine passenden Objekt/Wetter-Dateipaare gefunden.")
        return {"X": [], "y": [], "samples": 0, "positive_samples": 0}

    # Fix R1: Timestamp-Suche statt fester 5-min-Annahme (analog build_dataset)
    from datetime import timedelta as _td_cls
    _CLS_HORIZON_MIN   = 20       # Intensivierungshorizont: 20 Minuten
    _CLS_TOL_FACTOR    = 0.5      # 50 % Toleranz
    _CLS_MIN_TOL_MIN   = 3.0      # mindestens 3 Minuten
    min_required = ML_SEQUENCE_LENGTH + 1
    if len(paired) < min_required:
        debug_log(f"[DATASET-CLS] Zu wenige Frames: {len(paired)} < {min_required}.")
        return {"X": [], "y": [], "samples": 0, "positive_samples": 0}

    frames = []
    for op, wp in paired:
        try:
            frames.append((op, wp, _parse_ts(op), _load_json(op), _load_json(wp)))
        except Exception as exc:
            debug_log(f"[DATASET-CLS] Fehler beim Laden von {op}: {exc}")

    rows = []
    # Fix R1: Kein festes horizon_step mehr — Timestamp-Suche
    for i in range(ML_SEQUENCE_LENGTH - 1, len(frames)):
        seq_slice = frames[i - ML_SEQUENCE_LENGTH + 1 : i + 1]
        now_ts = seq_slice[-1][2]
        now_map = {str(o.get("id")): o for o in seq_slice[-1][3]
                   if isinstance(o, dict) and "id" in o}

        # Besten Frame ~20 min in der Zukunft suchen (Timestamp-basiert)
        target_ts  = now_ts + _td_cls(minutes=_CLS_HORIZON_MIN)
        tol        = _td_cls(minutes=max(_CLS_HORIZON_MIN * _CLS_TOL_FACTOR, _CLS_MIN_TOL_MIN))
        best_idx, best_diff = None, _td_cls(days=999)
        for j in range(i + 1, len(frames)):
            diff = abs(frames[j][2] - target_ts)
            if diff < best_diff:
                best_diff, best_idx = diff, j
            if frames[j][2] > target_ts + tol:
                break
        if best_idx is None or best_diff > tol:
            continue
        fut_objs = frames[best_idx][3]
        fut_map  = {str(o.get("id")): o for o in fut_objs
                    if isinstance(o, dict) and "id" in o}

        common_ids = set(now_map.keys()) & set(fut_map.keys())
        if not common_ids:
            continue

        for oid in common_ids:
            seq_features = []
            seq_objects = []
            valid = True
            for _, _, ts, objs, stations in seq_slice:
                obj = next((o for o in objs if str(o.get("id")) == oid), None)
                if obj is None:
                    valid = False
                    break
                seq_features.append(_frame_features(obj, stations, ts))
                seq_objects.append(obj)
            if not valid:
                continue

            obj_now = now_map[oid]
            obj_fut = fut_map[oid]
            core_now = _safe_float(obj_now.get("core_ratio", 0.0))
            core_fut = _safe_float(obj_fut.get("core_ratio", 0.0))
            size_now = max(_safe_float(obj_now.get("size", 0.0)), 1e-6)
            size_fut = _safe_float(obj_fut.get("size", 0.0))
            intensified = int((core_fut - core_now) >= 0.05 or (size_fut / size_now) >= 1.2)

            row = {
                k: v for k, v in zip(
                    ML_CELL_FEATURES + ML_STATION_FEATURES + ["hour_sin", "hour_cos", "month_sin", "month_cos"],
                    seq_features[-1],
                )
            }
            row["intensified"] = intensified
            row["id"] = oid
            row["timestamp"] = now_ts.strftime("%Y-%m-%d_%H-%M-%S")
            rows.append(row)

    if not rows:
        debug_log("[DATASET-CLS] Keine gültigen Samples gefunden.")
        return {"X": [], "y": [], "samples": 0, "positive_samples": 0}

    df = pd.DataFrame(rows)
    out_path = os.path.join(SAVE_PATHS["dataset"], "tabular_classification.parquet")
    os.makedirs(SAVE_PATHS["dataset"], exist_ok=True)
    df.to_parquet(out_path, index=False)
    positives = int(df["intensified"].sum())
    debug_log(f"[DATASET-CLS] Datensatz gebaut: samples={len(df)}, positives={positives}")
    return {"X": df.drop(columns=["intensified", "id", "timestamp"]), "y": df["intensified"], "samples": len(df), "positive_samples": positives}


if __name__ == "__main__":
    build_dataset()


def build_regression_intensity_dataset():
    """Leitet an intensity_regression.py weiter (Stub für Importe aus dataset_builder)."""
    try:
        from intensity_regression import build_regression_intensity_dataset as _impl
        return _impl()
    except ImportError:
        debug_log("[DATASET] intensity_regression.py nicht gefunden")
        return None
