import glob
import json
import os
from datetime import datetime
from math import asin, cos, pi, radians, sin, sqrt

import importlib
import importlib.util
import sys


def _optional_import(name):
    """Importiert optionale Abhängigkeiten robust ohne Modulimport-Crash."""
    try:
        if name not in sys.modules and importlib.util.find_spec(name) is None:
            return None
    except Exception as exc:
        _prediction_debug_log(f"[OPTIONAL_IMPORT] {name}: find_spec fehlgeschlagen: {exc}")
        return None
    try:
        return importlib.import_module(name)
    except Exception as exc:
        _prediction_debug_log(f"[OPTIONAL_IMPORT] {name}: Import fehlgeschlagen: {exc}")
        return None


def _prediction_debug_log(message):
    try:
        from debug_utils import debug_log as _debug_log
        _debug_log(message)
    except Exception:
        print(message)


np = _optional_import("numpy")

from config import (
    FRAME_INTERVAL_MIN as _FRAME_MIN,
    KINEMATIC_EWMA_ALPHA as _STATIC_EWMA_ALPHA,
    ML_CELL_FEATURES as CELL_KEYS,
    ML_FORECAST_HORIZONS_MIN as _STATIC_HORIZONS,
    ML_NUM_FEATURES,
    ML_SEQUENCE_LENGTH,
    ML_STATION_FEATURES as STATION_KEYS,
    TENDENCY_AREA_PCT_STABLE as _TENDENCY_AREA_TH,
    TENDENCY_CORE_DELTA_STABLE as _TENDENCY_CORE_TH,
    SAVE_PATHS,
    UPSCALE_FACTOR as _UF,
)

try:
    import runtime_config as _runtime_cfg
except Exception:
    _runtime_cfg = None


def _lgbm_feat_ok(model, frame) -> bool:
    """B116: Prüft LightGBM-Featurebreite vor predict(), um Fatal-Logspam zu vermeiden."""
    try:
        expected = None
        num_feature = getattr(model, "num_feature", None)
        if callable(num_feature):
            expected = num_feature()
        elif hasattr(model, "n_features_"):
            expected = getattr(model, "n_features_", None)
        elif hasattr(model, "n_features_in_"):
            expected = getattr(model, "n_features_in_", None)
        if expected is None:
            return True
        actual = frame.shape[-1]
        if int(expected) != int(actual):
            _prediction_debug_log(
                f"[LightGBM] B116: Feature-Mismatch — Modell erwartet {expected}, "
                f"Frame hat {actual}. Inferenz übersprungen."
            )
            return False
        return True
    except Exception:
        return True


def _get_horizons() -> list:
    """Gibt die aktuell konfigurierten Forecast-Horizonte zurück.
    Priorisiert runtime_config (Admin-Panel), Fallback: config.py."""
    if _runtime_cfg is not None:
        return _runtime_cfg.get("ML_FORECAST_HORIZONS_MIN", _STATIC_HORIZONS)
    return list(_STATIC_HORIZONS)
try:
    from dataset_builder import load_scalers
except Exception as exc:
    _prediction_debug_log(f"[OPTIONAL_IMPORT] dataset_builder.load_scalers: Import fehlgeschlagen: {exc}")

    def load_scalers():
        return None, None

try:
    from model_training import load_lgbm_models, load_lstm
except Exception as exc:
    _prediction_debug_log(f"[OPTIONAL_IMPORT] model_training: Import fehlgeschlagen: {exc}")

    def load_lgbm_models():
        return {}

    def load_lstm():
        return None

lgb = _optional_import("lightgbm")

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




def _lstm_feature_dimensions_ok(lstm_model, seq_scaled):
    """Prüft, ob das geladene LSTM dieselbe Feature-Anzahl wie die Sequenz erwartet."""
    expected = getattr(lstm_model, "input_shape", None)
    expected_feats = None
    if expected is not None:
        expected_last = expected[-1]
        if expected_last is not None:
            expected_feats = int(expected_last)
    actual_feats = int(seq_scaled.shape[-1])
    return expected_feats is None or expected_feats == actual_feats, expected_feats, actual_feats

def _actual_frame_min(history: list, default: float) -> float:
    """
    B115: Mittleres echtes Frame-Intervall (min) aus den History-Timestamps.
    Ersetzt die nominale FRAME_INTERVAL_MIN-Annahme in den Fallback-Pfaden, damit
    der reale ARSO-Takt (~5 min, mit Lücken variabel) zugrunde liegt.
    Nutzt nur Paare mit 1 min <= dt <= 30 min. Fällt auf `default` zurück.
    """
    dts = []
    for i in range(1, len(history)):
        t0_raw = history[i - 1].get("timestamp")
        t1_raw = history[i].get("timestamp")
        if not t0_raw or not t1_raw:
            continue
        try:
            t0 = datetime.strptime(t0_raw, "%Y-%m-%d_%H-%M-%S")
            t1 = datetime.strptime(t1_raw, "%Y-%m-%d_%H-%M-%S")
            dt = (t1 - t0).total_seconds() / 60.0
            if 1.0 <= dt <= 30.0:
                dts.append(dt)
        except Exception:
            continue
    if dts:
        return sum(dts) / len(dts)
    return default



def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    try:
        lat1, lon1, lat2, lon2 = map(float, (lat1, lon1, lat2, lon2))
        r = 6371.0
        dlat = radians(lat2 - lat1)
        dlon = radians(lon2 - lon1)
        a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
        return 2 * r * asin(sqrt(max(0.0, min(1.0, a))))
    except Exception:
        return 0.0

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

    # B166: Merge/Split-Glättung. Bei einem Merge/Split-Frame springt der
    # Zell-Schwerpunkt → die gespeicherte vx/vy des JÜNGSTEN History-Eintrags ist
    # diskontinuierlich. Dieser Eintrag wird für die kinematische Geschwindigkeit
    # ausgeschlossen (sofern genug History übrig bleibt), damit die Vorhersage der
    # Vor-Merge-Bewegung folgt statt dem Sprung. Der optische Fluss (P-M02) bleibt
    # Vorrang (bereits sprung-robust) und wird hiervon NICHT beeinflusst.
    _merge_guard = (
        int(obj.get("merge_discontinuity", 0) or 0) == 1
        or float(obj.get("is_merged", 0.0) or 0.0) >= 0.5
        or float(obj.get("is_split", 0.0) or 0.0) >= 0.5
    )
    # B208/Codex: Ungekürzte History für das Optflow-Timing bewahren. Die
    # Merge/Split-Kürzung (history[:-1]) darf NUR den History/EWMA-Pfad betreffen.
    # _actual_frame_min für den optischen Fluss muss das ECHTE jüngste Frame-Intervall
    # sehen, sonst wird der OF-Vektor durch die falsche Frame-Dauer geteilt.
    _history_full = list(history)
    _merge_guard_applied = False
    if _merge_guard and n >= 3:
        history = history[:-1]
        n = len(history)
        _merge_guard_applied = True

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
                # B115: mittleres echtes Intervall als Ersatz für dt=0-Paare
                # (doppelte KML-Timestamps). Verhindert Kippen in den Fallback.
                _fm_recon = _actual_frame_min(history, float(_FRAME_MIN) if _FRAME_MIN else 5.0)
                _vx_list, _vy_list = [], []
                for _i in range(1, n):
                    _h0, _h1 = history[_i - 1], history[_i]
                    _t0 = datetime.strptime(_h0["timestamp"], "%Y-%m-%d_%H-%M-%S")
                    _t1 = datetime.strptime(_h1["timestamp"], "%Y-%m-%d_%H-%M-%S")
                    _dt_min = (_t1 - _t0).total_seconds() / 60.0
                    if _dt_min < 0.5:
                        _dt_min = _fm_recon   # B115: doppelter Timestamp → echtes Mittel
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
                # B115: Fallback mit ECHTEM Frame-Intervall (statt nominalem 2.0).
                _frame_min_fb = _actual_frame_min(history, float(_FRAME_MIN) if _FRAME_MIN else 5.0)
                avg_vx = (sum(float(h.get("vx", 0.0)) for h in history) / n) / _frame_min_fb
                avg_vy = (sum(float(h.get("vy", 0.0)) for h in history) / n) / _frame_min_fb
                src = f"history_{n}_fallback_fm{round(_frame_min_fb, 1)}"
        else:
            # History ohne x/y-Timestamps: EWMA auf gespeicherte vx/vy-Werte
            # B115: echtes Frame-Intervall statt nominalem 2.0.
            _frame_min_fb = _actual_frame_min(history, float(_FRAME_MIN) if _FRAME_MIN else 5.0)
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
        # < 2 History-Einträge: Kalman-Werte (px/Frame) → px/min.
        # B115: keine History für _actual_frame_min → nominales FRAME_INTERVAL_MIN
        # (jetzt 5.0) ist der korrekte Default; Zelle ohnehin zu jung für robuste v.
        _frame_min_fb = float(_FRAME_MIN) if _FRAME_MIN else 5.0
        avg_vx = _safe_float(obj.get("vx", 0.0)) / _frame_min_fb
        avg_vy = _safe_float(obj.get("vy", 0.0)) / _frame_min_fb
        src = "kalman_only"

    # ── P-M02: Feldbasierte Zuggeschwindigkeit (optischer Fluss) hat Vorrang ──
    # of_vx/of_vy = flächengemittelter Lucas-Kanade-Flow (P-M01), ORIGINAL-px je
    # FRAME. In px/min umrechnen über das ECHTE Frame-Intervall (gleiche Basis
    # wie der EWMA-Pfad). TRT/ETITAN: Mittel des Bewegungsfeldes in der Zellfläche
    # statt Centroid-Verschiebung → robust gegen Merge-Schwerpunktsprünge.
    # Kalman/EWMA bleibt Fallback (of_available=0, z. B. historische JSONs ohne Flow).
    if int(obj.get("of_available", 0)) == 1:
        _fm_of = _actual_frame_min(_history_full, float(_FRAME_MIN) if _FRAME_MIN else 5.0)
        if not _fm_of or _fm_of <= 0.0:
            _fm_of = 5.0
        avg_vx = _safe_float(obj.get("of_vx", 0.0)) / _fm_of
        avg_vy = _safe_float(obj.get("of_vy", 0.0)) / _fm_of
        src = f"optflow_fm{round(_fm_of, 1)}"

    # B166: Diagnose-Marker — Merge/Split-Glättung wurde auf den History/EWMA-Pfad
    # angewandt (beim optischen Fluss nicht relevant, da feldbasiert/sprung-robust).
    if _merge_guard_applied and not src.startswith("optflow"):
        src = f"{src}+mguard"

    obj["forecast_mode"]      = "kinematic"
    obj["has_ml_forecast"]    = False
    obj["kinematic_source"]   = src
    obj["kinematic_vx"]       = avg_vx
    obj["kinematic_vy"]       = avg_vy
    try:
        obj["kinematic_speed_kmh"] = round((float(_UF or 1.0) and (avg_vx ** 2 + avg_vy ** 2) ** 0.5 / float(_UF or 1.0) * 60.0), 3)
    except Exception:
        obj["kinematic_speed_kmh"] = 0.0

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
                # B117: avg_vx/vy sind ORIGINAL-px/min (history x = original_cx),
                # horizon in min → (avg_vx * horizon) = Pixelversatz in Original-px.
                # Umrechnung in km über die GEOMETRIE-Auflösung km/px = 1/UPSCALE_FACTOR,
                # NICHT über PX_TO_KMH/60 (PX_TO_KMH ist km/h pro px/Frame — eine
                # Geschwindigkeit, keine Längenauflösung). Konsistent mit dem
                # Normalpfad pixel_to_geo() (1 Original-px ≙ 1/UPSCALE_FACTOR km).
                _KM_PER_PX = 1.0 / float(_UF or 1.0)
                _dlat = -(avg_vy * float(horizon) * _KM_PER_PX) / 111.0
                _dlon = (avg_vx * float(horizon) * _KM_PER_PX) / (
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
        _origin_lat = _safe_float(obj.get("lat", 0.0))
        _origin_lon = _safe_float(obj.get("lon", 0.0))
        _disp_km = _haversine_km(_origin_lat, _origin_lon, lat, lon) if (_origin_lat or _origin_lon) else 0.0
        obj[f"forecast_displacement_km_{horizon}"] = round(_disp_km, 3)
        obj[f"forecast_speed_kmh_{horizon}"] = round(_disp_km / (float(horizon) / 60.0), 3) if float(horizon) > 0 else 0.0
        obj[f"forecast_mode_{horizon}"] = "kinematic"
        obj[f"kinematic_source_{horizon}"] = src
        obj[f"of_available_{horizon}"] = int(obj.get("of_available", 0) or 0)
        _radar_age = obj.get("radar_age_min")
        _staleness = {}
        if _radar_age is not None:
            _eff_lead = float(horizon) - _safe_float(_radar_age)
            _staleness = {
                "radar_age_min": round(_safe_float(_radar_age), 1),
                "effective_lead_min": round(_eff_lead, 1),
                "stale": _eff_lead <= 0.0,
            }
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
            "forecast_mode_horizon": "kinematic",
            "kinematic_source": src,
            "of_available": int(obj.get("of_available", 0) or 0),
            "of_error_reason": obj.get("of_error_reason"),
            "kinematic_speed_kmh": obj.get("kinematic_speed_kmh"),
            "forecast_displacement_km": obj.get(f"forecast_displacement_km_{horizon}"),
            "forecast_speed_kmh": obj.get(f"forecast_speed_kmh_{horizon}"),
            **_staleness,
        })


def _predict_lgbm_vector(models, frame, suffix=""):
    # P-T08: Voll-Länge-Vektor über ALLE konfigurierten Horizonte. Horizonte ohne
    # Modell → NaN (Layout passt zu scaler_y). Der Aufrufer ersetzt NaN-Horizonte
    # durch den kinematischen Forecast.
    if np is None:
        raise RuntimeError("numpy is required for LightGBM vector prediction")

    preds = []
    for h in _get_horizons():
        for axis in ("x", "y"):
            key = f"lgbm_h{h}_{axis}{suffix}"
            model = models.get(key)
            if model is None:
                preds.append(float("nan"))
            else:
                preds.append(float(model.predict(frame)[0]))
    return np.asarray(preds, dtype=float)


def _classify_tendency(obj: dict, has_ml: bool) -> None:
    """B92: Setzt intensity_tendency, size_tendency, tendency_source am Objekt.

    has_ml=True  → nutzt delta_core_ratio_pred / delta_area_pred (Regressoren).
    has_ml=False → nutzt trend (-1/0/+1) und size_trend (-1/0/+1) aus dem Tracker.

    Werte: "staerker" | "schwaecher" | "stabil"  bzw.
           "waechst"  | "schrumpft"  | "stabil".
    """
    if has_ml:
        dc = _safe_float(obj.get("delta_core_ratio_pred", 0.0))
        da = _safe_float(obj.get("delta_area_pred", 0.0))
        obj["intensity_tendency"] = (
            "staerker" if dc > _TENDENCY_CORE_TH else "schwaecher" if dc < -_TENDENCY_CORE_TH else "stabil"
        )
        obj["size_tendency"] = (
            "waechst" if da > _TENDENCY_AREA_TH else "schrumpft" if da < -_TENDENCY_AREA_TH else "stabil"
        )
        obj["tendency_source"] = "ml"
    else:
        t = int(obj.get("trend", 0) or 0)
        st = int(obj.get("size_trend", 0) or 0)
        # P-M03: Feldbasierte Divergenz als merge-robustes Intensitätssignal.
        # Konvergenz (negativ) → Intensivierung; Divergenz (positiv) → Abschwächung.
        # Nur als Tie-Breaker bei neutraler Tracker-Tendenz (t == 0), damit
        # eindeutige core_ratio-Trends Vorrang behalten.
        _OF_DIV_TH = 0.02
        if t == 0 and int(obj.get("of_available", 0)) == 1:
            _div = _safe_float(obj.get("of_divergence", 0.0))
            if _div < -_OF_DIV_TH:
                t = 1
            elif _div > _OF_DIV_TH:
                t = -1
        obj["intensity_tendency"] = (
            "staerker" if t > 0 else "schwaecher" if t < 0 else "stabil"
        )
        obj["size_tendency"] = (
            "waechst" if st > 0 else "schrumpft" if st < 0 else "stabil"
        )
        obj["tendency_source"] = "kinematic"


def _kinematic_fallback(objects: list) -> tuple:
    """Kinematischer Fallback für alle Objekte (keine Modelle geladen)."""
    _horizons = _get_horizons()
    forecasts = {h: [] for h in _horizons}
    for obj in objects:
        obj["intensification_prob"]  = 0.0
        obj["delta_core_ratio_pred"] = 0.0
        obj["delta_area_pred"]       = 0.0
        _classify_tendency(obj, has_ml=False)  # B92
        _append_kinematic(obj, forecasts)

    # ── B95: Pfad-Wetter aus atmosphere_latest.json (kein API-Call, Z.28) ──
    try:
        from config import PATH_ATM_MAX_DIST_KM as _PATM
        _atm_snap = _load_atmosphere_snapshot()
        for _o in objects:
            _compute_path_weather(_o, _horizons, _atm_snap, _PATM)
    except Exception as _e_b95:
        debug_log(f"[B95] Pfad-Wetter übersprungen: {_e_b95}")

    return tuple(forecasts[h] for h in _horizons)


def _compute_path_weather(obj, horizons, snapshot, max_dist_km):
    """B95: Atmosphäre an den vorhergesagten Forecast-Positionen.

    snapshot: dict aus atmosphere_latest.json (Schlüssel "locations").
    Liest pro Forecast-Punkt den nächsten Snapshot-Gitterpunkt (≤ max_dist_km).
    Setzt path_*-Felder am obj. Bei fehlenden Daten → 0.0 (Modell lernt 'fehlend').
    """
    import math

    fields = (
        "path_cape_end", "path_li_end", "path_cape_mean", "path_li_min",
        "path_cin_end", "path_lapse_end", "path_wind700_end", "path_cape_trend",
    )
    for f in fields:
        obj[f] = 0.0

    locs = (snapshot or {}).get("locations", [])
    if not locs:
        return

    def _nearest(lat, lon):
        best_d = float("inf")
        best = None
        for L in locs:
            dlat = (float(L.get("lat", 0)) - lat) * 111.0
            dlon = (float(L.get("lon", 0)) - lon) * 111.0 * (math.cos(math.radians(lat)) or 1e-6)
            d = math.hypot(dlat, dlon)
            if d < best_d:
                best_d = d
                best = L
        return (best, best_d) if best_d <= max_dist_km else (None, best_d)

    hs = sorted(int(h) for h in horizons)
    if not hs:
        return

    # Start-CAPE am Origin
    start_loc, _ = _nearest(float(obj.get("lat") or 0.0), float(obj.get("lon") or 0.0))
    start_cape = float(start_loc.get("cape", 0.0) or 0.0) if start_loc else 0.0

    cape_vals = []
    li_vals = []
    end_loc = None
    for h in hs:
        flat = obj.get(f"forecast_lat_{h}")
        flon = obj.get(f"forecast_lon_{h}")
        if flat is None or flon is None:
            continue
        loc, _d = _nearest(float(flat), float(flon))
        if loc is None:
            continue
        cape_vals.append(float(loc.get("cape", 0.0) or 0.0))
        li_vals.append(float(loc.get("li", 0.0) or 0.0))
        end_loc = loc  # letzter gültiger = Pfad-Ende

    if end_loc is not None:
        obj["path_cape_end"] = float(end_loc.get("cape", 0.0) or 0.0)
        obj["path_li_end"] = float(end_loc.get("li", 0.0) or 0.0)
        obj["path_cin_end"] = float(end_loc.get("cin", 0.0) or 0.0)
        obj["path_lapse_end"] = float(end_loc.get("lapse_700_500", 0.0) or 0.0)
        obj["path_wind700_end"] = float(end_loc.get("wind_700hpa", 0.0) or 0.0)
        obj["path_cape_trend"] = float(end_loc.get("cape", 0.0) or 0.0) - start_cape
    if cape_vals:
        obj["path_cape_mean"] = float(sum(cape_vals) / len(cape_vals))
    if li_vals:
        obj["path_li_min"] = float(min(li_vals))


def _load_atmosphere_snapshot():
    """Lädt atmosphere_latest.json (B95). Leeres dict wenn nicht vorhanden."""
    try:
        from config import SAVE_PATHS as _SP
        _dir = _SP.get("evaluation", "train_data/evaluation")
    except Exception:
        _dir = "train_data/evaluation"
    path = os.path.join(_dir.rstrip("/"), "atmosphere_latest.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


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

    # P-T08: Partielle Horizont-Abdeckung. Ein Horizont ist ML-fähig, wenn x- UND
    # y-Modell vorhanden sind. has_lgbm = mindestens ein Horizont (statt alle).
    _lgbm_horizons = [
        h for h in _horizons
        if f"lgbm_h{h}_x" in lgbm_models and f"lgbm_h{h}_y" in lgbm_models
    ]
    has_lgbm = len(_lgbm_horizons) > 0
    has_lgbm_q = {
        "q10": has_lgbm and all(f"lgbm_h{h}_{axis}_q10" in lgbm_models for h in _lgbm_horizons for axis in ["x", "y"]),
        "q90": has_lgbm and all(f"lgbm_h{h}_{axis}_q90" in lgbm_models for h in _lgbm_horizons for axis in ["x", "y"]),
    }
    has_lstm = lstm_model is not None
    if scaler_X is None or scaler_y is None or (not has_lgbm and not has_lstm):
        debug_log("[PREDICT] Fehlende Scaler/Modelle, nutze linearen Fallback.")
        return _kinematic_fallback(objects)

    if has_lgbm and len(_lgbm_horizons) < len(_horizons):
        debug_log(
            f"[PREDICT] Partielle ML-Abdeckung: Modelle für {_lgbm_horizons} von "
            f"{list(_horizons)} min — übrige Horizonte kinematisch."
        )

    # P-T08: Radarbild-Alter (Staleness der Eingabe). Bei ARSO-Lücken ist das
    # letzte Radarbild älter als der Loop-Takt → ein +10-Forecast ist effektiv
    # ein Nowcast der Vergangenheit. (Pi läuft in lokaler Zeit; Dateinamen lokal.)
    try:
        _radar_age_min = max(
            0.0,
            (datetime.now() - datetime.strptime(timestamp, "%Y-%m-%d_%H-%M-%S")).total_seconds() / 60.0,
        )
    except Exception:
        _radar_age_min = 0.0

    ts_dt = datetime.strptime(timestamp, "%Y-%m-%d_%H-%M-%S")
    forecasts = {h: [] for h in _horizons}

    # B108: Atmosphären-Snapshot einmalig VOR dem Objekt-Loop laden.
    # _compute_path_weather() braucht forecast_lat_H/forecast_lon_H bereits
    # auf obj gesetzt → kinematische Erstschätzung via _append_kinematic().
    try:
        from config import PATH_ATM_MAX_DIST_KM as _PATM_B108
        _atm_snap_b108 = _load_atmosphere_snapshot()
    except Exception as _e_atm:
        debug_log(f"[B108] Atmosphären-Snapshot nicht ladbar: {_e_atm}")
        _atm_snap_b108 = {}
        _PATM_B108 = 50.0

    for obj in objects:
        obj["radar_age_min"] = round(_radar_age_min, 1)
        # B108: Kinematic-First: kinematische Erstschätzung → path_*-Features
        # deterministisch setzen BEVOR _build_sequence() den Feature-Vektor liest.
        # _append_kinematic() setzt forecast_lat_H/forecast_lon_H aus vx/vy.
        # _compute_path_weather() liest diese Positionen → path_* auf obj.
        # Train-Konsistenz: Gespeicherte JSONs nutzen ebenfalls kinematische path_*.
        _temp_fc = {h: [] for h in _horizons}
        try:
            _append_kinematic(obj, _temp_fc)
            if _atm_snap_b108:
                _compute_path_weather(obj, _horizons, _atm_snap_b108, _PATM_B108)
        except Exception as _e_b108:
            debug_log(f"[B108] path_*-Vorbelegung fehlgeschlagen (obj={obj.get('id')}): {_e_b108}")

        seq = _build_sequence(obj.get("id"), obj, stations, ts_dt)
        if seq is None:
            _classify_tendency(obj, has_ml=False)
            # forecast_lat_H/forecast_lon_H bereits durch _append_kinematic gesetzt.
            # Kinematische Forecasts in echtes forecasts-Dict übernehmen.
            for _h in _horizons:
                forecasts[_h].extend(_temp_fc.get(_h, []))
            continue

        seq_scaled = scaler_X.transform(seq).reshape(1, ML_SEQUENCE_LENGTH, ML_NUM_FEATURES)
        last_frame = seq_scaled[:, -1, :]

        if intensification_model is not None and _lgbm_feat_ok(intensification_model, last_frame):
            try:
                obj["intensification_prob"] = float(intensification_model.predict(last_frame)[0])
            except Exception:
                obj["intensification_prob"] = 0.0
        else:
            obj["intensification_prob"] = 0.0

        core_key = "delta_core_ratio_pred"
        reg_core_ok = reg_core is not None and _lgbm_feat_ok(reg_core, last_frame)
        if reg_core_ok:
            try:
                obj["delta_core_ratio_pred"] = float(reg_core.predict(last_frame)[0])
            except Exception:
                obj[core_key] = 0.0
                reg_core_ok = False
        else:
            obj[core_key] = 0.0

        reg_area_ok = reg_area is not None and _lgbm_feat_ok(reg_area, last_frame)
        if reg_area_ok:
            try:
                obj["delta_area_pred"] = float(reg_area.predict(last_frame)[0])
            except Exception:
                obj["delta_area_pred"] = 0.0
                reg_area_ok = False
        else:
            obj["delta_area_pred"] = 0.0

        # B92: Tendenz aus ML-Deltas wenn beide Regressoren vorhanden,
        # sonst kinematischer Fallback (trend/size_trend).
        _classify_tendency(obj, has_ml=(reg_core_ok and reg_area_ok))

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
            # B100: Feature-Dimension-Guard — verhindert Service-Crash bei
            # veraltetem LSTM-Modell (trainiert mit anderer Feature-Anzahl).
            # Lösung: graceful Fallback auf kinematisch statt ungefangener Exception.
            _lstm_ok = True
            try:
                _lstm_ok, _expected_feats, _actual_feats = _lstm_feature_dimensions_ok(
                    lstm_model, seq_scaled
                )
                if not _lstm_ok:
                    debug_log(
                        f"[LSTM] B100: Feature-Mismatch — Modell erwartet {_expected_feats}, "
                        f"Sequenz hat {_actual_feats} (ML_NUM_FEATURES={ML_NUM_FEATURES}). "
                        f"Kinematischer Fallback für alle Objekte dieses Laufs. "
                        f"Modell nach neuem Training (≥50 Sequenzen) automatisch aktualisiert."
                    )
                    has_lstm = False   # Für alle weiteren Objekte dieses Laufs deaktivieren
            except Exception as _chk_exc:
                debug_log(f"[LSTM] B100: Dimension-Check fehlgeschlagen ({_chk_exc}) — kinematisch")
                has_lstm = False
                _lstm_ok = False

            if not _lstm_ok:
                _classify_tendency(obj, has_ml=False)
                _append_kinematic(obj, forecasts)
                continue

            try:
                prediction_scaled = np.asarray(
                    lstm_model.predict(seq_scaled, verbose=0)[0], dtype=float
                )
            except Exception as _lstm_exc:
                # Catches z.B. TF-interne Dimension-Fehler die den Guard umgehen
                debug_log(
                    f"[LSTM] B100: Vorhersage fehlgeschlagen: {_lstm_exc} — "
                    f"kinematischer Fallback, has_lstm=False für restliche Objekte"
                )
                has_lstm = False
                _classify_tendency(obj, has_ml=False)
                _append_kinematic(obj, forecasts)
                continue

        if prediction_scaled is None or prediction_scaled.shape[0] != len(_get_horizons()) * 2:
            _classify_tendency(obj, has_ml=False)
            _append_kinematic(obj, forecasts)
            continue

        prediction = scaler_y.inverse_transform(prediction_scaled.reshape(1, -1))[0]
        obj["has_ml_forecast"] = True
        obj["radar_age_min"]   = round(_radar_age_min, 1)
        prediction_q10 = scaler_y.inverse_transform(prediction_q10_scaled.reshape(1, -1))[0] if prediction_q10_scaled is not None else None
        prediction_q90 = scaler_y.inverse_transform(prediction_q90_scaled.reshape(1, -1))[0] if prediction_q90_scaled is not None else None

        _ml_horizon_count = 0
        for idx, horizon in enumerate(_get_horizons()):
            _x_raw = prediction[idx * 2]
            _y_raw = prediction[idx * 2 + 1]
            _eff_lead = float(horizon) - _radar_age_min   # effektive Vorlaufzeit
            _stale = _eff_lead <= 0.0

            # P-T08: Horizont ohne ML-Modell (NaN) → kinematischer Fallback aus
            # _temp_fc (bereits per _append_kinematic für diesen obj befüllt).
            if (_x_raw != _x_raw) or (_y_raw != _y_raw):   # NaN-Test
                _kin = _temp_fc.get(horizon) or []
                if _kin:
                    k = _kin[0]
                    obj[f"forecast_x_{horizon}"]   = k["x"]
                    obj[f"forecast_y_{horizon}"]   = k["y"]
                    obj[f"forecast_lat_{horizon}"] = k["lat"]
                    obj[f"forecast_lon_{horizon}"] = k["lon"]
                    obj[f"forecast_displacement_km_{horizon}"] = k.get("forecast_displacement_km")
                    obj[f"forecast_speed_kmh_{horizon}"] = k.get("forecast_speed_kmh")
                    obj[f"forecast_mode_{horizon}"] = "kinematic"
                    obj[f"kinematic_source_{horizon}"] = obj.get("kinematic_source")
                    obj[f"of_available_{horizon}"] = int(obj.get("of_available", 0) or 0)
                    forecasts[horizon].append({
                        "id": obj.get("id"),
                        "x": k["x"], "y": k["y"],
                        "lat": k["lat"], "lon": k["lon"],
                        "size": _safe_float(obj.get("size", 0.0)),
                        "origin_lat": _safe_float(obj.get("lat", 0.0)),
                        "origin_lon": _safe_float(obj.get("lon", 0.0)),
                        "forecast_mode": "kinematic",
                        "forecast_mode_horizon": "kinematic",
                        "kinematic_source": k.get("kinematic_source"),
                        "of_available": int(obj.get("of_available", 0) or 0),
                        "of_error_reason": obj.get("of_error_reason"),
                        "kinematic_speed_kmh": obj.get("kinematic_speed_kmh"),
                        "forecast_displacement_km": k.get("forecast_displacement_km"),
                        "forecast_speed_kmh": k.get("forecast_speed_kmh"),
                        "radar_age_min": round(_radar_age_min, 1),
                        "effective_lead_min": round(_eff_lead, 1),
                        "stale": _stale,
                    })
                continue

            _ml_horizon_count += 1
            # ML-Modell trainiert auf pre-upscale obj["x"]/ ["y"] → _UF anwenden
            x_pred = float(_x_raw) * _UF
            y_pred = float(_y_raw) * _UF
            lat, lon = pixel_to_geo(x_pred, y_pred)
            obj[f"forecast_x_{horizon}"] = x_pred
            obj[f"forecast_y_{horizon}"] = y_pred
            obj[f"forecast_lat_{horizon}"] = float(lat)
            obj[f"forecast_lon_{horizon}"] = float(lon)
            _ml_disp_km = _haversine_km(_safe_float(obj.get("lat", 0.0)), _safe_float(obj.get("lon", 0.0)), lat, lon)
            obj[f"forecast_displacement_km_{horizon}"] = round(_ml_disp_km, 3)
            obj[f"forecast_speed_kmh_{horizon}"] = round(_ml_disp_km / (float(horizon) / 60.0), 3) if float(horizon) > 0 else 0.0
            obj[f"forecast_mode_{horizon}"] = "ml"
            obj[f"kinematic_source_{horizon}"] = None
            obj[f"of_available_{horizon}"] = int(obj.get("of_available", 0) or 0)
            if prediction_q10 is not None and prediction_q90 is not None:
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
                    "forecast_mode_horizon": "ml",
                    "kinematic_source": None,
                    "of_available": int(obj.get("of_available", 0) or 0),
                    "of_error_reason": obj.get("of_error_reason"),
                    "kinematic_speed_kmh": obj.get("kinematic_speed_kmh"),
                    "forecast_displacement_km": obj.get(f"forecast_displacement_km_{horizon}"),
                    "forecast_speed_kmh": obj.get(f"forecast_speed_kmh_{horizon}"),
                    "radar_age_min": round(_radar_age_min, 1),
                    "effective_lead_min": round(_eff_lead, 1),
                    "stale": _stale,
                    **(
                        {
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
        # P-T08: obj-Level forecast_mode = "ml" nur wenn ≥1 Horizont ML war.
        obj["forecast_mode"] = "ml" if _ml_horizon_count > 0 else "kinematic"

    # B108: B95-Pfad-Wetter-Berechnung wurde in den Objekt-Loop VORGEZOGEN
    # (Kinematic-First vor _build_sequence). Hier kein zweiter Durchlauf nötig.
    # path_*-Werte sind bereits deterministisch (kinematisch) auf allen Objekten.

    return tuple(forecasts[h] for h in _horizons)
