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


if importlib.util.find_spec("cv2") and importlib.util.find_spec("debug_utils"):
    debug_log = importlib.import_module("debug_utils").debug_log
else:
    def debug_log(message):
        print(message)

if importlib.util.find_spec("cv2") and importlib.util.find_spec("geo_utils"):
    pixel_to_geo = importlib.import_module("geo_utils").pixel_to_geo
else:
    def pixel_to_geo(x, y):
        return 0.0, 0.0

if importlib.util.find_spec("utils") and importlib.util.find_spec("geopy"):
    find_nearest_station = importlib.import_module("utils").find_nearest_station
else:
    def find_nearest_station(lat, lon, stations):
        return None

from config import (
    ML_CELL_FEATURES,
    ML_FORECAST_HORIZONS_MIN,
    ML_SEQUENCE_LENGTH,
    ML_STATION_FEATURES,
    SAVE_PATHS,
)


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

    lat, lon = pixel_to_geo(obj.get("x", 0), obj.get("y", 0))
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
    return {"X": [], "y": [], "y_raw": [], "ids": []}


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

def load_scalers():
    if joblib is None:
        return None, None

    scaler_x_path = os.path.join(SAVE_PATHS["models"], "scaler_X.joblib")
    scaler_y_path = os.path.join(SAVE_PATHS["models"], "scaler_y.joblib")
    if not (os.path.exists(scaler_x_path) and os.path.exists(scaler_y_path)):
        return None, None
    return joblib.load(scaler_x_path), joblib.load(scaler_y_path)


def build_dataset():
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

    horizon_steps = [max(1, int(h // 5)) for h in ML_FORECAST_HORIZONS_MIN]
    max_h_steps = max(horizon_steps)
    min_required = ML_SEQUENCE_LENGTH + max_h_steps + 1
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

    for i in range(ML_SEQUENCE_LENGTH - 1, len(frames) - max_h_steps):
        seq_slice = frames[i - ML_SEQUENCE_LENGTH + 1 : i + 1]
        now_ts = seq_slice[-1][2]
        seq_obj_maps = [{str(o.get("id")): o for o in frm[3] if isinstance(o, dict) and "id" in o} for frm in seq_slice]

        common_ids = set(seq_obj_maps[0].keys())
        for m in seq_obj_maps[1:]:
            common_ids &= set(m.keys())

        if not common_ids:
            continue

        future_obj_maps = []
        for h_step in horizon_steps:
            fut_objs = frames[i + h_step][3]
            future_obj_maps.append({str(o.get("id")): o for o in fut_objs if isinstance(o, dict) and "id" in o})

        for oid in common_ids:
            if any(oid not in fmap for fmap in future_obj_maps):
                continue

            seq_features = []
            valid = True
            for op, wp, ts, objs, stations in seq_slice:
                obj = next((o for o in objs if str(o.get("id")) == oid), None)
                if obj is None:
                    valid = False
                    break
                seq_features.append(_frame_features(obj, stations, ts))

            if not valid:
                continue

            targets = []
            for fmap in future_obj_maps:
                fo = fmap[oid]
                targets.extend([_safe_float(fo.get("x", 0.0)), _safe_float(fo.get("y", 0.0))])

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

    os.makedirs(SAVE_PATHS["models"], exist_ok=True)
    os.makedirs(SAVE_PATHS["dataset"], exist_ok=True)

    scaler_X = StandardScaler()
    X_flat = X.reshape(-1, X.shape[-1])
    X_scaled = scaler_X.fit_transform(X_flat).reshape(X.shape)

    scaler_y = StandardScaler()
    y_scaled = scaler_y.fit_transform(y_raw)

    joblib.dump(scaler_X, os.path.join(SAVE_PATHS["models"], "scaler_X.joblib"))
    joblib.dump(scaler_y, os.path.join(SAVE_PATHS["models"], "scaler_y.joblib"))

    np.savez(
        os.path.join(SAVE_PATHS["dataset"], "dataset.npz"),
        X=X_scaled,
        y=y_scaled,
        y_raw=y_raw,
    )

    pd.DataFrame(tabular_rows).to_parquet(os.path.join(SAVE_PATHS["dataset"], "tabular.parquet"), index=False)

    debug_log(f"[DATASET] Datensatz gebaut: X={X_scaled.shape}, y={y_scaled.shape}")
    return {"X": X_scaled, "y": y_scaled, "y_raw": y_raw, "ids": ids}


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

    horizon_step = 4  # 20 Minuten bei 5-Minuten-Frames
    min_required = ML_SEQUENCE_LENGTH + horizon_step + 1
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
    for i in range(ML_SEQUENCE_LENGTH - 1, len(frames) - horizon_step):
        seq_slice = frames[i - ML_SEQUENCE_LENGTH + 1 : i + 1]
        now_ts = seq_slice[-1][2]
        now_map = {str(o.get("id")): o for o in seq_slice[-1][3] if isinstance(o, dict) and "id" in o}
        fut_map = {str(o.get("id")): o for o in frames[i + horizon_step][3] if isinstance(o, dict) and "id" in o}
        common_ids = set(now_map.keys()) & set(fut_map.keys())
        if not common_ids:
            continue

        for oid in common_ids:
            seq_features = []
            valid = True
            for _, _, ts, objs, stations in seq_slice:
                obj = next((o for o in objs if str(o.get("id")) == oid), None)
                if obj is None:
                    valid = False
                    break
                seq_features.append(_frame_features(obj, stations, ts))
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
