# severity_predict.py
"""
Schwere-Vorhersage pro Zelle. Wird in der Live-Pipeline nach den Erweiterungs-Features
aufgerufen und schreibt obj["severity"].

  rain_mm_h, gust_kmh : LightGBM-Regression (Fallback: Nowcast/TAWES-Persistenz)
  hail_prob, hail_cat : PHYSIKALISCHER Index (kein ML-Target vorhanden)
  level               : Gesamtstufe 1-4

Der Feature-Vektor wird mit demselben Helfer wie beim Training gebaut
(dataset_builder._frame_features) -> garantiert identische Reihenfolge.
"""

import os
import math
import importlib.util
from datetime import datetime

from debug_utils import debug_log
from config import SAVE_PATHS, HAIL_VIOLET_RATIO_SATURATION
from dataset_builder import _frame_features
from severity_dataset import _rain_mm_h, _gust_kmh

lgb = importlib.import_module("lightgbm") if importlib.util.find_spec("lightgbm") else None

_MODEL_DIR  = os.path.join(SAVE_PATHS["models"], "current")
_RAIN_MODEL = os.path.join(_MODEL_DIR, "lgbm_severity_rain.txt")
_GUST_MODEL = os.path.join(_MODEL_DIR, "lgbm_severity_gust.txt")

_cache = {"rain": None, "gust": None, "loaded": False}


def _f(v, d=0.0):
    try:
        out = float(v)
        return d if (math.isnan(out) or math.isinf(out)) else out
    except (TypeError, ValueError):
        return d


def _load():
    if _cache["loaded"]:
        return
    _cache["loaded"] = True
    if lgb is None:
        return
    try:
        if os.path.exists(_RAIN_MODEL):
            _cache["rain"] = lgb.Booster(model_file=_RAIN_MODEL)
        if os.path.exists(_GUST_MODEL):
            _cache["gust"] = lgb.Booster(model_file=_GUST_MODEL)
        debug_log(f"[SEVERITY] Modelle geladen: rain={_cache['rain'] is not None}, gust={_cache['gust'] is not None}")
    except Exception as exc:
        debug_log(f"[SEVERITY] Modell-Ladefehler: {exc}")


def reload_models():
    """Fuer /api/hailo/reload-Hook nach Modell-Sync."""
    _cache.update(loaded=False, rain=None, gust=None)


def _hail_index(obj):
    """
    Physikalischer Hagel-Index (transparent, keine ML-Pseudolabels).
    SHIP ~2 gilt als signifikant; niedrige Gefriergrenze laesst Hagel den Boden erreichen;
    Overshooting Top und hohe core_ratio/VIL erhoehen die Wahrscheinlichkeit.

    B339: core_violet_ratio (P72, reine >=57-dBZ-Pixel) fliesst zusaetzlich als
    Floor ein - identische Logik zu main.py._compute_hail_warning()s
    hail_prob_violet, hier auf den severity-Anzeigepfad angewendet. Ohne
    diesen Floor blieb hail_cat bei kompakten Violett-Kernen faelschlich
    "keiner", weil core_ratio Rot+Violett undifferenziert zusammenfasst und
    SHIP bei geringem CAPE niedrig bleibt, obwohl das Radar bereits >=57 dBZ
    zeigt (Diskrepanz reproduziert: core_ratio=0.48, CAPE=362 J/kg -> hail_prob
    ~5%, obwohl die Zelle einen deutlich sichtbaren violetten Kern hatte).
    """
    ship = _f(obj.get("ship_index"))
    fl   = _f(obj.get("arome_fl_height"))            # m MSL
    core = min(max(_f(obj.get("core_ratio")), 0.0), 1.0)
    vil  = min(_f(obj.get("vil_proxy")), 1.0)
    oz   = 1.0 if _f(obj.get("overshooting_top")) >= 0.5 else 0.0
    violet = min(max(_f(obj.get("core_violet_ratio")), 0.0), 1.0)

    base = min(ship / 2.0, 1.0)
    fl_factor = min(max((3500.0 - fl) / 2000.0, 0.0), 1.0) if fl > 0 else 0.5
    score = 0.50 * base + 0.20 * core + 0.15 * vil + 0.15 * oz
    score *= (0.6 + 0.4 * fl_factor)
    violet_floor = (
        min(violet / HAIL_VIOLET_RATIO_SATURATION, 1.0)
        if HAIL_VIOLET_RATIO_SATURATION > 0 else 0.0
    )
    prob = round(min(max(max(score, violet_floor), 0.0), 1.0), 3)
    if prob < 0.25:
        cat = "keiner"
    elif prob < 0.55:
        cat = "klein"      # < 2 cm
    else:
        cat = "gross"      # >= 2 cm
    return prob, cat


def _level(rain, gust, hail_cat):
    s = 0
    if rain > 40: s += 2
    elif rain > 20: s += 1
    if gust > 90: s += 2
    elif gust > 60: s += 1
    if hail_cat == "gross": s += 2
    elif hail_cat == "klein": s += 1
    return 1 + min(s, 3)   # 1..4


def assign_severity(objects, stations=None, ts=None):
    if not objects:
        return objects
    _load()
    if ts is None:
        ts = datetime.utcnow()
    stations = stations or []
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        try:
            feat = _frame_features(obj, stations, ts)
            if _cache["rain"] is not None:
                rain = float(_cache["rain"].predict([feat])[0])
            else:
                rain = _rain_mm_h(obj)
            if _cache["gust"] is not None:
                gust = float(_cache["gust"].predict([feat])[0])
            else:
                gust = _gust_kmh(obj)
            rain = round(max(0.0, rain), 1)
            gust = round(max(0.0, gust), 1)
            hp, hc = _hail_index(obj)
            obj["severity"] = {
                "rain_mm_h": rain,
                "gust_kmh": gust,
                "hail_prob": hp,
                "hail_cat": hc,
                "level": _level(rain, gust, hc),
                "mode": "ml" if _cache["rain"] is not None else "fallback",
            }
        except Exception as exc:
            debug_log(f"[SEVERITY] Fehler Zelle {obj.get('id')}: {exc}")
            obj["severity"] = {"rain_mm_h": 0.0, "gust_kmh": 0.0, "hail_prob": 0.0,
                               "hail_cat": "keiner", "level": 1, "mode": "fallback"}
    return objects
