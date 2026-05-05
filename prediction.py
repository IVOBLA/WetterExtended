import glob
import json
import os
from datetime import datetime
from math import cos, pi, sin

import importlib
import importlib.util

np = importlib.import_module("numpy") if importlib.util.find_spec("numpy") else None

from config import ML_FORECAST_HORIZONS_MIN, ML_NUM_FEATURES, ML_SEQUENCE_LENGTH, SAVE_PATHS
from dataset_builder import load_scalers
from model_training import load_lgbm_models, load_lstm

lgb = importlib.import_module("lightgbm") if importlib.util.find_spec("lightgbm") else None

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


STATION_KEYS = [
    "station_temperature_c",
    "station_humidity_pct",
    "station_pressure_hpa",
    "station_wind_speed_kmh",
    "station_wind_direction_deg",
    "station_dew_point_c",
    "station_precip_mm",
    "station_visibility_km",
    "station_cloud_base_m",
]

CELL_KEYS = [
    "cell_area_px",
    "cell_mean_intensity",
    "cell_max_intensity",
    "cell_perimeter_px",
    "cell_circularity",
    "cell_solidity",
    "cell_eccentricity",
    "cell_velocity_kmh",
    "cell_direction_deg",
    "cell_growth_rate",
    "cell_lightning_density",
    "cell_cape_jkg",
    "cell_cloud_top_height_msl",
    "cell_missing_flag",
]


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _linear_point(obj, horizon):
    x = _safe_float(obj.get("x", 0.0)) + _safe_float(obj.get("vx", 0.0)) * horizon
    y = _safe_float(obj.get("y", 0.0)) + _safe_float(obj.get("vy", 0.0)) * horizon
    return x, y


def _append_linear(obj, forecasts):
    for horizon in ML_FORECAST_HORIZONS_MIN:
        x_pred, y_pred = _linear_point(obj, horizon)
        lat, lon = pixel_to_geo(x_pred, y_pred)
        obj[f"forecast_x_{horizon}"] = float(x_pred)
        obj[f"forecast_y_{horizon}"] = float(y_pred)
        obj[f"forecast_lat_{horizon}"] = float(lat)
        obj[f"forecast_lon_{horizon}"] = float(lon)
        forecasts[horizon].append(
            {
                "id": obj.get("id"),
                "x": float(x_pred),
                "y": float(y_pred),
                "lat": float(lat),
                "lon": float(lon),
                "size": _safe_float(obj.get("size", 0.0)),
            }
        )


def _predict_lgbm_vector(models, frame, suffix=""):
    preds = []
    for h in ML_FORECAST_HORIZONS_MIN:
        for axis in ["x", "y"]:
            preds.append(models[f"lgbm_h{h}_{axis}{suffix}"].predict(frame)[0])
    return np.asarray(preds, dtype=float)


def _linear_fallback(objects):
    forecasts = {h: [] for h in ML_FORECAST_HORIZONS_MIN}
    for obj in objects:
        obj["intensification_prob"] = 0.0
        _append_linear(obj, forecasts)
    return tuple(forecasts[h] for h in ML_FORECAST_HORIZONS_MIN)


def load_intensification_model():
    path = os.path.join(SAVE_PATHS["models"], "lgbm_intensification.txt")
    if lgb is None or not os.path.exists(path):
        return None
    return lgb.Booster(model_file=path)


def _load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _parse_ts_from_file(path):
    name = os.path.splitext(os.path.basename(path))[0]
    return datetime.strptime(name, "%Y-%m-%d_%H-%M-%S")


def _frame_features(obj, stations, ts_dt):
    cell_features = [_safe_float(obj.get(k, 0.0)) for k in CELL_KEYS]
    lat, lon = pixel_to_geo(_safe_float(obj.get("x", 0.0)), _safe_float(obj.get("y", 0.0)))
    nearest = find_nearest_station(lat, lon, stations) if stations else None
    station_features = [_safe_float(nearest.get(k, 0.0)) if nearest else 0.0 for k in STATION_KEYS]

    hour_fraction = (ts_dt.hour * 60 + ts_dt.minute) / (24 * 60)
    hour_angle = 2 * pi * hour_fraction
    month_fraction = (ts_dt.month - 1) / 12.0
    month_angle = 2 * pi * month_fraction
    time_features = [sin(hour_angle), cos(hour_angle), sin(month_angle), cos(month_angle)]

    feats = cell_features + station_features + time_features
    return feats if len(feats) == ML_NUM_FEATURES else None


def _build_sequence(obj_id, current_obj, stations, ts_dt):
    object_files = sorted(glob.glob(os.path.join(SAVE_PATHS["objects"], "*.json")))
    weather_files = sorted(glob.glob(os.path.join(SAVE_PATHS["weather"], "*.json")))
    weather_by_name = {os.path.basename(p): p for p in weather_files}

    predecessor = []
    for obj_file in object_files:
        base = os.path.basename(obj_file)
        w_path = weather_by_name.get(base)
        if not w_path:
            continue
        try:
            file_ts = _parse_ts_from_file(obj_file)
        except Exception:
            continue
        if file_ts < ts_dt:
            predecessor.append((file_ts, obj_file, w_path))

    predecessor = sorted(predecessor, key=lambda e: e[0])[-(ML_SEQUENCE_LENGTH - 1) :]
    if len(predecessor) < (ML_SEQUENCE_LENGTH - 1):
        return None

    seq = []
    for file_ts, obj_path, weather_path in predecessor:
        objs = _load_json(obj_path)
        obj_match = next((o for o in objs if str(o.get("id")) == str(obj_id)), None)
        if obj_match is None:
            return None
        stations_hist = _load_json(weather_path)
        feats = _frame_features(obj_match, stations_hist, file_ts)
        if feats is None:
            return None
        seq.append(feats)

    live_feats = _frame_features(current_obj, stations, ts_dt)
    if live_feats is None:
        return None
    seq.append(live_feats)

    if len(seq) != ML_SEQUENCE_LENGTH:
        return None
    if np is None:
        return None
    return np.asarray(seq, dtype=float)


def predict_positions(objects: list, timestamp: str, stations: list):
    if np is None:
        debug_log("[PREDICT] numpy fehlt, nutze linearen Fallback.")
        return _linear_fallback(objects)

    scaler_X, scaler_y = load_scalers()
    lgbm_models = load_lgbm_models()
    lstm_model = load_lstm()
    intensification_model = load_intensification_model()

    has_lgbm = all(
        f"lgbm_h{h}_{axis}" in lgbm_models for h in ML_FORECAST_HORIZONS_MIN for axis in ["x", "y"]
    )
    has_lgbm_q = {
        "q10": all(f"lgbm_h{h}_{axis}_q10" in lgbm_models for h in ML_FORECAST_HORIZONS_MIN for axis in ["x", "y"]),
        "q90": all(f"lgbm_h{h}_{axis}_q90" in lgbm_models for h in ML_FORECAST_HORIZONS_MIN for axis in ["x", "y"]),
    }
    has_lstm = lstm_model is not None
    if scaler_X is None or scaler_y is None or (not has_lgbm and not has_lstm):
        debug_log("[PREDICT] Fehlende Scaler/Modelle, nutze linearen Fallback.")
        return _linear_fallback(objects)

    ts_dt = datetime.strptime(timestamp, "%Y-%m-%d_%H-%M-%S")
    forecasts = {h: [] for h in ML_FORECAST_HORIZONS_MIN}

    for obj in objects:
        seq = _build_sequence(obj.get("id"), obj, stations, ts_dt)
        if seq is None:
            _append_linear(obj, forecasts)
            continue

        seq_scaled = scaler_X.transform(seq).reshape(1, ML_SEQUENCE_LENGTH, ML_NUM_FEATURES)
        if intensification_model is not None:
            try:
                obj["intensification_prob"] = float(intensification_model.predict(seq_scaled[:, -1, :])[0])
            except Exception:
                obj["intensification_prob"] = 0.0
        else:
            obj["intensification_prob"] = 0.0

        prediction_scaled = None
        prediction_q10_scaled = None
        prediction_q90_scaled = None
        if has_lgbm:
            last_frame = seq_scaled[:, -1, :]
            prediction_scaled = _predict_lgbm_vector(lgbm_models, last_frame)
            if has_lgbm_q["q10"]:
                prediction_q10_scaled = _predict_lgbm_vector(lgbm_models, last_frame, "_q10")
            if has_lgbm_q["q90"]:
                prediction_q90_scaled = _predict_lgbm_vector(lgbm_models, last_frame, "_q90")
        elif has_lstm:
            prediction_scaled = np.asarray(lstm_model.predict(seq_scaled, verbose=0)[0], dtype=float)

        if prediction_scaled is None or prediction_scaled.shape[0] != len(ML_FORECAST_HORIZONS_MIN) * 2:
            _append_linear(obj, forecasts)
            continue

        prediction = scaler_y.inverse_transform(prediction_scaled.reshape(1, -1))[0]
        prediction_q10 = scaler_y.inverse_transform(prediction_q10_scaled.reshape(1, -1))[0] if prediction_q10_scaled is not None else None
        prediction_q90 = scaler_y.inverse_transform(prediction_q90_scaled.reshape(1, -1))[0] if prediction_q90_scaled is not None else None

        for idx, horizon in enumerate(ML_FORECAST_HORIZONS_MIN):
            x_pred = float(prediction[idx * 2])
            y_pred = float(prediction[idx * 2 + 1])
            lat, lon = pixel_to_geo(x_pred, y_pred)
            obj[f"forecast_x_{horizon}"] = x_pred
            obj[f"forecast_y_{horizon}"] = y_pred
            obj[f"forecast_lat_{horizon}"] = float(lat)
            obj[f"forecast_lon_{horizon}"] = float(lon)
            if prediction_q10 is not None and prediction_q90 is not None:
                x_q10 = float(prediction_q10[idx * 2])
                y_q10 = float(prediction_q10[idx * 2 + 1])
                x_q90 = float(prediction_q90[idx * 2])
                y_q90 = float(prediction_q90[idx * 2 + 1])
                obj[f"forecast_x_{horizon}_q10"] = x_q10
                obj[f"forecast_y_{horizon}_q10"] = y_q10
                obj[f"forecast_x_{horizon}_q90"] = x_q90
                obj[f"forecast_y_{horizon}_q90"] = y_q90
            forecasts[horizon].append(
                {
                    "id": obj.get("id"),
                    "x": x_pred,
                    "y": y_pred,
                    "lat": float(lat),
                    "lon": float(lon),
                    "size": _safe_float(obj.get("size", 0.0)),
                    **(
                        {
                            "x_q10": float(prediction_q10[idx * 2]),
                            "y_q10": float(prediction_q10[idx * 2 + 1]),
                            "x_q90": float(prediction_q90[idx * 2]),
                            "y_q90": float(prediction_q90[idx * 2 + 1]),
                        }
                        if prediction_q10 is not None and prediction_q90 is not None
                        else {}
                    ),
                }
            )

    return tuple(forecasts[h] for h in ML_FORECAST_HORIZONS_MIN)
