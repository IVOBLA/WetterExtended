"""
size_regressor.py – LightGBM-basierter Size-Regresser für Storm-Cells.

Liefert area_km2 und radius_km für erkannte Radar-Zellen.

Phase A: LightGBM trainiert auf train_data/size_labels/size_labels.jsonl.
         Fallback: geometrische Formel (Pixel → km via Haversine).
Phase B: predict() wird durch U-Net-Output-Kanal ersetzt (gleiche Schnittstelle).

Training wird automatisch durch den Scheduler ausgelöst wenn LOCAL_TRAINING=True
und >= SIZE_REGRESSOR_MIN_SAMPLES Datenpunkte vorhanden sind.
"""

import json
import logging
import math
import os
import pickle
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ── Konstanten ────────────────────────────────────────────────────────────────
SIZE_LABELS_PATH = "train_data/size_labels/size_labels.jsonl"
SIZE_MODEL_PATH = "models/size_regressor.pkl"
SIZE_META_PATH = "models/size_regressor_meta.json"
SIZE_MIN_SAMPLES = 50        # Mindest-Samples für erstes Training
SIZE_RETRAIN_EVERY = 200     # Retraining alle N neuen Samples
SIZE_MAX_SAMPLES = 20000     # Maximales Sliding-Window für Training

# Radar-Bounds Fallback (werden aus config überschrieben)
_DEFAULT_BOUNDS = {"N": 47.42, "S": 44.67, "W": 12.1, "E": 17.44}


# ── Pixel → km Hilfsfunktionen ────────────────────────────────────────────────
def pixel_scale(img_w: int, img_h: int, bounds: dict) -> tuple[float, float]:
    """
    Gibt (km_per_px_x, km_per_px_y) zurück.
    bounds: dict mit Schlüsseln N, S, W, E (float, Dezimalgrad).
    """
    center_lat = (bounds["N"] + bounds["S"]) / 2.0
    lat_span_km = (bounds["N"] - bounds["S"]) * 111.32
    lon_span_km = (bounds["E"] - bounds["W"]) * 111.32 * math.cos(math.radians(center_lat))
    return lon_span_km / img_w, lat_span_km / img_h


def geometric_size(
    area_px: float,
    radius_px: float,
    bbox_wh: Optional[tuple],
    km_per_px_x: float,
    km_per_px_y: float,
) -> dict:
    """
    Geometrische Fallback-Berechnung ohne Modell.
    bbox_wh: (width_px, height_px) oder None.
    """
    km_iso = (km_per_px_x + km_per_px_y) / 2.0
    area_km2 = round(area_px * km_per_px_x * km_per_px_y, 3)
    radius_km = round(radius_px * km_iso, 3)
    aspect_ratio = None
    if bbox_wh and bbox_wh[0] > 0:
        aspect_ratio = round(bbox_wh[1] / bbox_wh[0], 3)
    return {
        "area_km2": area_km2,
        "radius_km": radius_km,
        "aspect_ratio": aspect_ratio,
        "size_source": "geometric",
    }


# ── Feature-Vektor ────────────────────────────────────────────────────────────
_FEATURE_KEYS = [
    "area_px", "radius_px", "aspect_ratio",
    "cape_jkg", "wind_speed_kmh", "wind_dir_deg",
    "temp_2m", "cloud_height_m",
    "lat", "lon",
    "hour_sin", "hour_cos",   # zyklische Tageszeit
    "doy_sin", "doy_cos",     # zyklischer Jahrestag
]


def _to_feature_vector(record: dict) -> list[float]:
    """
    Baut einen Feature-Vektor aus einem Label-Record oder Objekt-Dict.
    Fehlende Werte werden mit 0.0 ersetzt.
    """
    # Zeitfeatures aus ts oder jetzt
    ts_str = record.get("ts", "")
    try:
        dt = datetime.strptime(ts_str[:16], "%Y-%m-%d_%H-%M")
    except Exception:
        dt = datetime.utcnow()
    hour_rad = 2 * math.pi * dt.hour / 24.0
    doy_rad = 2 * math.pi * dt.timetuple().tm_yday / 365.0

    vals = {
        "area_px": float(record.get("area_px") or record.get("area") or 0),
        "radius_px": float(record.get("radius_px") or record.get("size") or 0),
        "aspect_ratio": float(record.get("aspect_ratio") or 1.0),
        "cape_jkg": float(record.get("cape_jkg") or record.get("cape") or 0),
        "wind_speed_kmh": float(record.get("wind_speed_kmh") or record.get("wind_speed_700hPa") or 0),
        "wind_dir_deg": float(record.get("wind_dir_deg") or record.get("wind_dir_700hPa") or 0),
        "temp_2m": float(record.get("temp_2m") or record.get("arome_t2m") or 15.0),
        "cloud_height_m": float(record.get("cloud_height_m") or record.get("cloud_top_height_m") or 0),
        "lat": float(record.get("lat") or 46.6),
        "lon": float(record.get("lon") or 14.3),
        "hour_sin": math.sin(hour_rad),
        "hour_cos": math.cos(hour_rad),
        "doy_sin": math.sin(doy_rad),
        "doy_cos": math.cos(doy_rad),
    }
    return [vals[k] for k in _FEATURE_KEYS]


# ── Label-Sink ────────────────────────────────────────────────────────────────
def record_size_label(obj: dict, ts: str) -> None:
    """
    Schreibt ein Size-Label in SIZE_LABELS_PATH (JSONL, append).
    Wird nur aufgerufen wenn area_km2 > 0.
    """
    area_km2 = obj.get("area_km2") or 0
    if area_km2 <= 0:
        return
    record = {
        "ts": ts,
        "cell_id": obj.get("id"),
        "area_px": obj.get("area_px") or obj.get("area"),
        "radius_px": obj.get("radius_px") or obj.get("size"),
        "aspect_ratio": obj.get("aspect_ratio"),
        "area_km2": obj.get("area_km2"),
        "radius_km": obj.get("radius_km"),
        "cape_jkg": obj.get("cape_jkg") or obj.get("cape"),
        "wind_speed_kmh": obj.get("wind_speed_kmh") or obj.get("wind_speed_700hPa"),
        "wind_dir_deg": obj.get("wind_dir_deg") or obj.get("wind_dir_700hPa"),
        "temp_2m": obj.get("temp_2m") or obj.get("arome_t2m"),
        "cloud_height_m": obj.get("cloud_height_m") or obj.get("cloud_top_height_m"),
        "lat": obj.get("lat"),
        "lon": obj.get("lon"),
    }
    os.makedirs(os.path.dirname(SIZE_LABELS_PATH), exist_ok=True)
    with open(SIZE_LABELS_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def count_size_labels() -> int:
    """Gibt die Anzahl der gespeicherten Size-Labels zurück."""
    if not os.path.isfile(SIZE_LABELS_PATH):
        return 0
    with open(SIZE_LABELS_PATH, encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


# ── Training ──────────────────────────────────────────────────────────────────
def train_size_regressor(force: bool = False) -> dict:
    """
    Trainiert zwei LightGBM-Regresser: einen für area_km2, einen für radius_km.
    Speichert das Modell unter SIZE_MODEL_PATH.

    Returns: dict mit Trainings-Metriken (mae_area, mae_radius, n_samples)
             oder {"skipped": reason} wenn nicht genug Daten.
    """
    import lightgbm as lgb
    import numpy as np

    n = count_size_labels()
    if n < SIZE_MIN_SAMPLES and not force:
        logger.debug(f"[SIZE-REG] Training übersprungen: nur {n}/{SIZE_MIN_SAMPLES} Samples.")
        return {"skipped": f"only_{n}_samples"}

    logger.debug(f"[SIZE-REG] Starte Training mit {n} Samples...")

    # Labels laden (Sliding Window)
    records = []
    with open(SIZE_LABELS_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass
    records = records[-SIZE_MAX_SAMPLES:]

    X, y_area, y_radius = [], [], []
    for r in records:
        a = r.get("area_km2")
        rad = r.get("radius_km")
        if a is None or rad is None or a <= 0 or rad <= 0:
            continue
        X.append(_to_feature_vector(r))
        y_area.append(float(a))
        y_radius.append(float(rad))

    n_valid = len(X)
    if n_valid < SIZE_MIN_SAMPLES and not force:
        logger.debug(f"[SIZE-REG] Training übersprungen: nur {n_valid} gültige Samples.")
        return {"skipped": f"only_{n_valid}_valid_samples"}
    if n_valid < 2:
        return {"skipped": f"only_{n_valid}_valid_samples"}

    X = np.array(X, dtype=np.float32)
    ya = np.array(y_area, dtype=np.float32)
    yr = np.array(y_radius, dtype=np.float32)

    # Train/Val Split (80/20)
    split = max(1, int(len(X) * 0.8))
    split = min(split, len(X) - 1)
    X_tr, X_val = X[:split], X[split:]
    ya_tr, ya_val = ya[:split], ya[split:]
    yr_tr, yr_val = yr[:split], yr[split:]

    params = {
        "objective": "regression_l1",
        "metric": "mae",
        "learning_rate": 0.05,
        "num_leaves": 31,
        "min_data_in_leaf": 5,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 5,
        "verbose": -1,
        "n_jobs": 2,
    }

    # Modell für area_km2
    ds_tr_a = lgb.Dataset(X_tr, ya_tr)
    ds_val_a = lgb.Dataset(X_val, ya_val, reference=ds_tr_a)
    model_area = lgb.train(
        params, ds_tr_a,
        num_boost_round=300,
        valid_sets=[ds_val_a],
        callbacks=[lgb.early_stopping(30, verbose=False), lgb.log_evaluation(-1)],
    )

    # Modell für radius_km
    ds_tr_r = lgb.Dataset(X_tr, yr_tr)
    ds_val_r = lgb.Dataset(X_val, yr_val, reference=ds_tr_r)
    model_radius = lgb.train(
        params, ds_tr_r,
        num_boost_round=300,
        valid_sets=[ds_val_r],
        callbacks=[lgb.early_stopping(30, verbose=False), lgb.log_evaluation(-1)],
    )

    # MAE auswerten
    pred_area = model_area.predict(X_val)
    pred_radius = model_radius.predict(X_val)
    mae_area = float(np.mean(np.abs(pred_area - ya_val)))
    mae_radius = float(np.mean(np.abs(pred_radius - yr_val)))

    # Modell speichern
    os.makedirs(os.path.dirname(SIZE_MODEL_PATH), exist_ok=True)
    with open(SIZE_MODEL_PATH, "wb") as f:
        pickle.dump({"area": model_area, "radius": model_radius, "feature_keys": _FEATURE_KEYS}, f)

    meta = {
        "trained_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "n_samples": n_valid,
        "mae_area_km2": round(mae_area, 4),
        "mae_radius_km": round(mae_radius, 4),
        "model_version": "lgbm-phase-a",
    }
    with open(SIZE_META_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    logger.debug(
        f"[SIZE-REG] Training abgeschlossen: n={n_valid} "
        f"MAE_area={mae_area:.3f} km² MAE_radius={mae_radius:.3f} km"
    )
    return meta


# ── Inference ─────────────────────────────────────────────────────────────────
class SizeRegressor:
    """
    Hauptklasse für Size-Regression.
    Lädt das trainierte LightGBM-Modell beim ersten Aufruf.
    Fallback: geometrische Formel.

    Phase B: predict() wird durch U-Net-Output-Kanal ersetzt.
    """

    def __init__(self):
        self._model = None
        self._meta = {}
        self._n_since = 0   # Samples seit letztem Retraining
        self._load_model()

    def _load_model(self) -> None:
        if not os.path.isfile(SIZE_MODEL_PATH):
            logger.debug("[SIZE-REG] Kein Modell vorhanden — geometrischer Fallback aktiv.")
            return
        try:
            with open(SIZE_MODEL_PATH, "rb") as f:
                self._model = pickle.load(f)
            if os.path.isfile(SIZE_META_PATH):
                with open(SIZE_META_PATH, encoding="utf-8") as f:
                    self._meta = json.load(f)
            logger.debug(
                f"[SIZE-REG] Modell geladen: {self._meta.get('trained_at','')} "
                f"n={self._meta.get('n_samples',0)} "
                f"MAE_area={self._meta.get('mae_area_km2','?')} km²"
            )
        except Exception as e:
            logger.warning(f"[SIZE-REG] Modell laden fehlgeschlagen: {e}")
            self._model = None

    def reload(self) -> None:
        """Lädt das Modell neu (nach Training durch Scheduler)."""
        self._model = None
        self._load_model()

    def is_trained(self) -> bool:
        return self._model is not None

    def predict(self, obj: dict, ts: str, km_per_px_x: float, km_per_px_y: float) -> dict:
        """
        Berechnet area_km2, radius_km, aspect_ratio für ein Objekt-Dict.

        Reihenfolge:
          1. LightGBM-Modell (wenn geladen)
          2. Geometrischer Fallback (Pixel→km)

        Gibt immer ein Dict zurück (niemals None).

        Phase B: Dieser Aufruf wird durch U-Net-Output-Kanal ersetzt
                 (gleiche Schnittstelle, source="unet").
        """
        area_px = obj.get("area_px") or obj.get("area") or 0
        radius_px = obj.get("radius_px") or obj.get("size") or 0
        bbox = obj.get("bbox_px")
        bbox_wh = (bbox[2], bbox[3]) if bbox and len(bbox) >= 4 else None

        # Geometrischer Fallback (immer berechnen als Basis/Fallback)
        geo = geometric_size(area_px, radius_px, bbox_wh, km_per_px_x, km_per_px_y)

        if self._model is None:
            return geo

        # LightGBM-Prediction
        try:
            import numpy as np

            record = dict(obj)
            record["ts"] = ts
            record.setdefault("area_px", area_px)
            record.setdefault("radius_px", radius_px)
            record.setdefault("aspect_ratio", geo["aspect_ratio"] or 1.0)
            fv = np.array([_to_feature_vector(record)], dtype=np.float32)

            area_pred = float(self._model["area"].predict(fv)[0])
            radius_pred = float(self._model["radius"].predict(fv)[0])

            # Plausibilitätscheck: Modell darf max. 10× vom geometrischen Wert abweichen
            if geo["area_km2"] > 0:
                ratio_a = area_pred / geo["area_km2"]
                ratio_r = radius_pred / geo["radius_km"] if geo["radius_km"] > 0 else 1.0
                if not (0.1 < ratio_a < 10.0 and 0.1 < ratio_r < 10.0):
                    logger.debug(
                        f"[SIZE-REG] Plausibilitätsfehler (ratio_a={ratio_a:.2f} "
                        f"ratio_r={ratio_r:.2f}) → Fallback auf geometrisch"
                    )
                    return geo

            return {
                "area_km2": round(max(0.0, area_pred), 3),
                "radius_km": round(max(0.0, radius_pred), 3),
                "aspect_ratio": geo["aspect_ratio"],
                "size_source": "lgbm",
            }
        except Exception as e:
            logger.debug(f"[SIZE-REG] Prediction-Fehler: {e} → Fallback")
            return geo

    def maybe_trigger_training(self) -> None:
        """
        Prüft ob ein Retraining fällig ist und löst es ggf. aus.
        Wird vom Scheduler aufgerufen (LOCAL_TRAINING=True).
        """
        n = count_size_labels()
        if n < SIZE_MIN_SAMPLES:
            return
        if self._model is None:
            # Erstes Training
            logger.debug("[SIZE-REG] Erstes Training wird ausgelöst...")
            meta = train_size_regressor()
            if "skipped" not in meta:
                self.reload()
            return
        trained_n = self._meta.get("n_samples", 0)
        if (n - trained_n) >= SIZE_RETRAIN_EVERY:
            logger.debug(
                f"[SIZE-REG] Retraining: {n - trained_n} neue Samples seit letztem Training."
            )
            meta = train_size_regressor()
            if "skipped" not in meta:
                self.reload()


# ── Singleton ─────────────────────────────────────────────────────────────────
_size_regressor: Optional[SizeRegressor] = None


def get_size_regressor() -> SizeRegressor:
    """Gibt die globale SizeRegressor-Instanz zurück (lazy init)."""
    global _size_regressor
    if _size_regressor is None:
        _size_regressor = SizeRegressor()
    return _size_regressor
