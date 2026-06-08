import glob
import json
import os
from datetime import datetime
from math import cos, pi, radians, sin

import importlib
import importlib.util

np = importlib.import_module("numpy") if importlib.util.find_spec("numpy") else None

if np is None:
    raise ImportError(
        "[prediction.py] numpy ist nicht installiert. "
        "Bitte ausführen: pip3 install numpy --break-system-packages"
    )

from config import (
    FRAME_INTERVAL_MIN as _FRAME_MIN,
    KINEMATIC_EWMA_ALPHA as _STATIC_EWMA_ALPHA,
    ML_CELL_FEATURES as CELL_KEYS,
    ML_FORECAST_HORIZONS_MIN as _STATIC_HORIZONS,
    ML_NUM_FEATURES,
    ML_SEQUENCE_LENGTH,
    ML_STATION_FEATURES as STATION_KEYS,
    PX_TO_KMH,
    SAVE_PATHS,
    UPSCALE_FACTOR as _UF,
)

try:
    import runtime_config as _runtime_cfg
except Exception:
    _runtime_cfg = None


def _get_horizons() -> list:
    """Gibt die aktuell konfigurierten Forecast-Horizonte zurück.
    Priorisiert runtime_config (Admin-Panel), Fallback: config.py."""
    if _runtime_cfg is not None:
        return _runtime_cfg.get("ML_FORECAST_HORIZONS_MIN", _STATIC_HORIZONS)
    return list(_STATIC_HORIZONS)
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



def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _append_kinematic(obj: dict, forecasts: dict) -> None:
    """
    Kinematischer Fallback wenn kein ML-Modell verfügbar oder Sequenz zu kurz.

    Geschwindigkeit wird aus ALLEN vorhandenen History-Einträgen (bis zu
    TRACK_HISTORY_LEN Frames) mit EWMA-Gewichtung berechnet (P27).
    Neuere Zeitintervalle erhalten exponentiell höheres Gewicht — ältere fließen
    gedämpft ein. Reagiert schnell auf Kursänderungen, dämpft Einzelausreißer.

    Gewichtungsformel für n Intervalle (Index 0 = ältestes):
      w[i] = alpha × (1−alpha)^(n−1−i)   normiert auf Summe 1

    Beispiel alpha=0.6, 3 Frames (2 Intervalle):
      w_norm = [0.2857, 0.7143]  → neuestes Intervall dominiert mit 71 %

    Wenn weniger als 2 History-Einträge vorhanden sind, wird der aktuelle
    Kalman-Wert (vx/vy) verwendet (src = "kalman_only").

    Konfiguration (runtime-überschreibbar):
      TRACK_HISTORY_LEN    — History-Buffer-Größe (default 6)
      KINEMATIC_EWMA_ALPHA — Glättungsfaktor     (default 0.6)
    """
    history = obj.get("history") or []
    n = len(history)

    # EWMA-Alpha aus runtime_config lesen (P27)
    _ewma_alpha = float(
        _runtime_cfg.get("KINEMATIC_EWMA_ALPHA", _STATIC_EWMA_ALPHA)
        if _runtime_cfg else _STATIC_EWMA_ALPHA
    )
    _ewma_alpha = max(0.01, min(0.99, _ewma_alpha))   # Bereich [0.01, 0.99] erzwingen

    avg_vx: float = 0.0
    avg_vy: float = 0.0
    src: str = "kalman_only"

    if n >= 2:
        # P26 + P27: Prüfe ob alle Einträge Timestamp + x/y haben
        _has_xy_ts = all(
            h.get("timestamp") and "x" in h and "y" in h
            for h in history
        )
        if _has_xy_ts:
            # Echte px/min aus Timestamp-Differenzen + EWMA-Gewichtung
            try:
                _vx_list, _vy_list = [], []
                for _i in range(1, n):
                    _h0, _h1 = history[_i - 1], history[_i]
                    _t0 = datetime.strptime(_h0["timestamp"], "%Y-%m-%d_%H-%M-%S")
                    _t1 = datetime.strptime(_h1["timestamp"], "%Y-%m-%d_%H-%M-%S")
                    _dt_min = (_t1 - _t0).total_seconds() / 60.0
                    if _dt_min >= 0.5:   # Mindestintervall 30 s — robuster gegen gleiche Timestamps
                        _vx_list.append((_h1["x"] - _h0["x"]) / _dt_min)
                        _vy_list.append((_h1["y"] - _h0["y"]) / _dt_min)
                if _vx_list:
                    _n_v = len(_vx_list)
                    # EWMA: Index 0 = ältestes Intervall → geringstes Gewicht
                    _weights = [
                        _ewma_alpha * (1.0 - _ewma_alpha) ** (_n_v - 1 - _i)
                        for _i in range(_n_v)
                    ]
                    _w_sum = sum(_weights) or 1.0
                    _weights = [_w / _w_sum for _w in _weights]
                    avg_vx = sum(_w * _v for _w, _v in zip(_weights, _vx_list))
                    avg_vy = sum(_w * _v for _w, _v in zip(_weights, _vy_list))
                    src = f"ewma_{n}f_a{round(_ewma_alpha, 2)}"
                else:
                    raise ValueError("keine gültigen Intervalle")
            except Exception:
                # Fallback: einfaches Mittel vx/vy (px/Frame) → px/min
                _frame_min_fb = float(_FRAME_MIN) if _FRAME_MIN else 2.0
                avg_vx = (sum(float(h.get("vx", 0.0)) for h in history) / n) / _frame_min_fb
                avg_vy = (sum(float(h.get("vy", 0.0)) for h in history) / n) / _frame_min_fb
                src = f"history_{n}_fallback"
        else:
            # History ohne x/y-Timestamps: EWMA auf gespeicherte vx/vy-Werte
            _frame_min_fb = float(_FRAME_MIN) if _FRAME_MIN else 2.0
            _vx_vals = [float(h.get("vx", 0.0)) for h in history]
            _vy_vals = [float(h.get("vy", 0.0)) for h in history]
            _n_v = len(_vx_vals)
            _weights = [
                _ewma_alpha * (1.0 - _ewma_alpha) ** (_n_v - 1 - _i)
                for _i in range(_n_v)
            ]
            _w_sum = sum(_weights) or 1.0
            _weights = [_w / _w_sum for _w in _weights]
            avg_vx = sum(_w * _v for _w, _v in zip(_weights, _vx_vals)) / _frame_min_fb
            avg_vy = sum(_w * _v for _w, _v in zip(_weights, _vy_vals)) / _frame_min_fb
            src = f"ewma_novts_{n}f"
    else:
        # < 2 History-Einträge: Kalman-Werte (px/Frame) → px/min
        _frame_min_fb = float(_FRAME_MIN) if _FRAME_MIN else 2.0
        avg_vx = _safe_float(obj.get("vx", 0.0)) / _frame_min_fb
        avg_vy = _safe_float(obj.get("vy", 0.0)) / _frame_min_fb
        src = "kalman_only"

    obj["forecast_mode"]      = "kinematic"
    obj["has_ml_forecast"]    = False
    obj["kinematic_source"]   = src
    obj["kinematic_vx"]       = avg_vx
    obj["kinematic_vy"]       = avg_vy

    for horizon in _get_horizons():
        # EINHEITEN (Fix P01 + P26):
        # avg_vx/vy = px/min (echte Zeitdifferenz oder Fallback via FRAME_INTERVAL_MIN).
        # → x_pred  = x0 + avg_vx * horizon  (direkte Multiplikation — kein Frame-Divisor)
        # pixel_to_geo() erwartet SKALIERTE Koordinaten (teilt intern durch _UF).
        _x0 = _safe_float(obj.get("x", 0.0))
        _y0 = _safe_float(obj.get("y", 0.0))
        x_pred   = (_x0 + avg_vx * float(horizon)) * _UF
        y_pred   = (_y0 + avg_vy * float(horizon)) * _UF
        origin_x = _x0 * _UF
        origin_y = _y0 * _UF
        if origin_x == 0.0 and origin_y == 0.0:
            base_lat = _safe_float(obj.get("lat", 0.0))
            base_lon = _safe_float(obj.get("lon", 0.0))
            if base_lat == 0.0 and base_lon == 0.0:
                lat, lon = 0.0, 0.0
            else:
                # avg_vx/vy in px/min; horizon in min → px Versatz = avg_vx * horizon
                # KM_PER_PX_PER_MIN = PX_TO_KMH / 60  (km/h pro (px/Frame)) / (60 min/h)
                _KM_PER_PX_MIN = PX_TO_KMH / 60.0   # km pro (px·min)
                _dlat = -(avg_vy * float(horizon) * _KM_PER_PX_MIN) / 111.0
                _dlon = (avg_vx * float(horizon) * _KM_PER_PX_MIN) / (
                    111.0 * cos(radians(max(abs(base_lat), 0.001)))
                )
                lat = base_lat + _dlat
                lon = base_lon + _dlon
        else:
            lat, lon = pixel_to_geo(x_pred, y_pred)
        obj[f"forecast_x_{horizon}"]   = float(x_pred)
        obj[f"forecast_y_{horizon}"]   = float(y_pred)
        obj[f"forecast_lat_{horizon}"] = float(lat)
        obj[f"forecast_lon_{horizon}"] = float(lon)
        forecasts[horizon].append({
            "id":               obj.get("id"),
            "x":                float(x_pred),
            "y":                float(y_pred),
            "lat":              float(lat),
            "lon":              float(lon),
            "size":             _safe_float(obj.get("size", 0.0)),
            "origin_lat":       _safe_float(obj.get("lat", 0.0)),
            "origin_lon":       _safe_float(obj.get("lon", 0.0)),
            "forecast_mode":    "kinematic",
            "kinematic_source": src,
        })


def _predict_lgbm_vector(models, frame, suffix=""):
    preds = []
    for h in _get_horizons():
        for axis in ["x", "y"]:
            preds.append(models[f"lgbm_h{h}_{axis}{suffix}"].predict(frame)[0])
    return np.asarray(preds, dtype=float)


def _kinematic_fallback(objects: list) -> tuple:
    """Kinematischer Fallback für alle Objekte (keine Modelle geladen)."""
    _horizons = _get_horizons()
    forecasts = {h: [] for h in _horizons}
    for obj in objects:
        obj["intensification_prob"]  = 0.0
        obj["delta_core_ratio_pred"] = 0.0
        obj["delta_area_pred"]       = 0.0
        _append_kinematic(obj, forecasts)
    return tuple(forecasts[h] for h in _horizons)


def load_intensification_model():
    path = os.path.join(SAVE_PATHS["models"], "current", "lgbm_intensification.txt")
    if lgb is None or not os.path.exists(path):
        return None
    return lgb.Booster(model_file=path)


def _load_intensity_regressors():
    """Lädt delta_core und delta_area Regressionsmodelle."""
    try:
        from intensity_regression import load_intensity_regressors
        return load_intensity_regressors()
    except ImportError:
        return None, None


def _load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _parse_ts_from_file(path):
    name = os.path.splitext(os.path.basename(path))[0]
    return datetime.strptime(name, "%Y-%m-%d_%H-%M-%S")


def _frame_features(obj, stations, ts_dt):
    cell_features = [_safe_float(obj.get(k, 0.0)) for k in CELL_KEYS]
    # Fix P02: obj["lat"]/ ["lon"] direkt nehmen — pixel_to_geo() würde
    # obj["x"]/ ["y"] als skaliert interpretieren und falsch herunterskalieren.
    _lat_obj = obj.get("lat")
    _lon_obj = obj.get("lon")
    if _lat_obj is not None and _lon_obj is not None:
        lat = float(_lat_obj)
        lon = float(_lon_obj)
    else:
        # Fallback: pixel_to_geo mit korrekt skalierten Koordinaten
        _ox = _safe_float(obj.get("x", 0.0)) * float(_UF)
        _oy = _safe_float(obj.get("y", 0.0)) * float(_UF)
        lat, lon = pixel_to_geo(_ox, _oy)
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
        return _kinematic_fallback(objects)

    scaler_X, scaler_y = load_scalers()
    lgbm_models = load_lgbm_models()
    lstm_model = load_lstm()
    intensification_model = load_intensification_model()
    reg_core, reg_area = _load_intensity_regressors()

    _horizons = _get_horizons()

    has_lgbm = all(
        f"lgbm_h{h}_{axis}" in lgbm_models for h in _horizons for axis in ["x", "y"]
    )
    has_lgbm_q = {
        "q10": all(f"lgbm_h{h}_{axis}_q10" in lgbm_models for h in _horizons for axis in ["x", "y"]),
        "q90": all(f"lgbm_h{h}_{axis}_q90" in lgbm_models for h in _horizons for axis in ["x", "y"]),
    }
    has_lstm = lstm_model is not None
    if scaler_X is None or scaler_y is None or (not has_lgbm and not has_lstm):
        debug_log("[PREDICT] Fehlende Scaler/Modelle, nutze linearen Fallback.")
        return _kinematic_fallback(objects)

    ts_dt = datetime.strptime(timestamp, "%Y-%m-%d_%H-%M-%S")
    forecasts = {h: [] for h in _horizons}

    for obj in objects:
        seq = _build_sequence(obj.get("id"), obj, stations, ts_dt)
        if seq is None:
            _append_kinematic(obj, forecasts)
            continue

        seq_scaled = scaler_X.transform(seq).reshape(1, ML_SEQUENCE_LENGTH, ML_NUM_FEATURES)
        last_frame = seq_scaled[:, -1, :]

        if intensification_model is not None:
            try:
                obj["intensification_prob"] = float(intensification_model.predict(last_frame)[0])
            except Exception:
                obj["intensification_prob"] = 0.0
        else:
            obj["intensification_prob"] = 0.0

        core_key = "delta_core_ratio_pred"
        if reg_core is not None:
            try:
                obj["delta_core_ratio_pred"] = float(reg_core.predict(last_frame)[0])
            except Exception:
                obj[core_key] = 0.0
        else:
            obj[core_key] = 0.0

        if reg_area is not None:
            try:
                obj["delta_area_pred"] = float(reg_area.predict(last_frame)[0])
            except Exception:
                obj["delta_area_pred"] = 0.0
        else:
            obj["delta_area_pred"] = 0.0

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

        if prediction_scaled is None or prediction_scaled.shape[0] != len(_get_horizons()) * 2:
            _append_kinematic(obj, forecasts)
            continue

        prediction = scaler_y.inverse_transform(prediction_scaled.reshape(1, -1))[0]
        obj["forecast_mode"]   = "ml"
        obj["has_ml_forecast"] = True
        prediction_q10 = scaler_y.inverse_transform(prediction_q10_scaled.reshape(1, -1))[0] if prediction_q10_scaled is not None else None
        prediction_q90 = scaler_y.inverse_transform(prediction_q90_scaled.reshape(1, -1))[0] if prediction_q90_scaled is not None else None

        for idx, horizon in enumerate(_get_horizons()):
            # ML-Modell trainiert auf pre-upscale obj["x"]/ ["y"] → _UF anwenden
            x_pred = float(prediction[idx * 2])     * _UF
            y_pred = float(prediction[idx * 2 + 1]) * _UF
            lat, lon = pixel_to_geo(x_pred, y_pred)
            obj[f"forecast_x_{horizon}"] = x_pred
            obj[f"forecast_y_{horizon}"] = y_pred
            obj[f"forecast_lat_{horizon}"] = float(lat)
            obj[f"forecast_lon_{horizon}"] = float(lon)
            if prediction_q10 is not None and prediction_q90 is not None:
                # Fix #7: _UF anwenden wie bei x_pred/y_pred,
                # dann pixel_to_geo für lat/lon-Felder (app.py liest forecast_lat_{h}_q10/q90)
                x_q10 = float(prediction_q10[idx * 2])     * _UF
                y_q10 = float(prediction_q10[idx * 2 + 1]) * _UF
                x_q90 = float(prediction_q90[idx * 2])     * _UF
                y_q90 = float(prediction_q90[idx * 2 + 1]) * _UF
                lat_q10, lon_q10 = pixel_to_geo(x_q10, y_q10)
                lat_q90, lon_q90 = pixel_to_geo(x_q90, y_q90)
                obj[f"forecast_x_{horizon}_q10"]   = x_q10
                obj[f"forecast_y_{horizon}_q10"]   = y_q10
                obj[f"forecast_x_{horizon}_q90"]   = x_q90
                obj[f"forecast_y_{horizon}_q90"]   = y_q90
                obj[f"forecast_lat_{horizon}_q10"] = float(lat_q10)
                obj[f"forecast_lon_{horizon}_q10"] = float(lon_q10)
                obj[f"forecast_lat_{horizon}_q90"] = float(lat_q90)
                obj[f"forecast_lon_{horizon}_q90"] = float(lon_q90)
            forecasts[horizon].append(
                {
                    "id": obj.get("id"),
                    "x": x_pred,
                    "y": y_pred,
                    "lat": float(lat),
                    "lon": float(lon),
                    "size": _safe_float(obj.get("size", 0.0)),
                    "origin_lat": _safe_float(obj.get("lat", 0.0)),
                    "origin_lon": _safe_float(obj.get("lon", 0.0)),
                    "forecast_mode": "ml",
                    **(
                        {
                            # Fix #7: _UF wie bei x_pred/y_pred — kmz_export.py
                            # erwartet skalierte Pixelkoordinaten für pixel_to_geo()
                            "x_q10": float(prediction_q10[idx * 2])     * _UF,
                            "y_q10": float(prediction_q10[idx * 2 + 1]) * _UF,
                            "x_q90": float(prediction_q90[idx * 2])     * _UF,
                            "y_q90": float(prediction_q90[idx * 2 + 1]) * _UF,
                        }
                        if prediction_q10 is not None and prediction_q90 is not None
                        else {}
                    ),
                }
            )

    return tuple(forecasts[h] for h in _horizons)
