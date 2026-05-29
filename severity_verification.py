# severity_verification.py
"""
Closed-Loop-Verifikation der Schwere-Vorhersage (Regen/Boeen).

Fuer jede Zelle mit gespeicherter obj["severity"] wird der Frame ~+20 min spaeter gesucht
und der dann BEOBACHTETE Wert (severity_dataset._rain_mm_h / _gust_kmh) mit der Vorhersage
verglichen. Aggregiert MAE und Bias ueber ein Zeitfenster.

Nur lesend auf train_data/objects/*.json — kein API-Call, keine Modelle noetig.
"""

import os
import glob
from datetime import datetime, timedelta

from debug_utils import debug_log
from config import SAVE_PATHS
from severity_dataset import _rain_mm_h, _gust_kmh, SEVERITY_HORIZON_MIN

_TOL_MIN = max(SEVERITY_HORIZON_MIN * 0.5, 3.0)


def _parse_ts(path):
    name = os.path.splitext(os.path.basename(path))[0]
    return datetime.strptime(name, "%Y-%m-%d_%H-%M-%S")


def _load(path):
    import json
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def evaluate_severity(since_hours=24):
    obj_files = sorted(glob.glob(os.path.join(SAVE_PATHS["objects"], "*.json")))
    if len(obj_files) < 2:
        return {"samples": 0, "mae_rain_mm_h": None, "mae_gust_kmh": None,
                "bias_rain_mm_h": None, "bias_gust_kmh": None, "since_hours": since_hours}

    cutoff = datetime.utcnow() - timedelta(hours=since_hours)
    frames = []
    for p in obj_files:
        try:
            ts = _parse_ts(p)
            if ts >= cutoff - timedelta(minutes=SEVERITY_HORIZON_MIN + _TOL_MIN):
                frames.append((ts, p))
        except Exception:
            continue
    frames.sort(key=lambda e: e[0])

    err_rain, err_gust = [], []
    for i, (now_ts, now_path) in enumerate(frames):
        try:
            now_objs = _load(now_path)
        except Exception:
            continue
        preds = {str(o.get("id")): o for o in now_objs
                 if isinstance(o, dict) and "id" in o and isinstance(o.get("severity"), dict)}
        if not preds:
            continue

        target_ts = now_ts + timedelta(minutes=SEVERITY_HORIZON_MIN)
        tol = timedelta(minutes=_TOL_MIN)
        best = None
        best_diff = timedelta(days=999)
        for j in range(i + 1, len(frames)):
            diff = abs(frames[j][0] - target_ts)
            if diff < best_diff:
                best_diff, best = diff, frames[j]
            if frames[j][0] > target_ts + tol:
                break
        if best is None or best_diff > tol:
            continue
        try:
            fut_objs = _load(best[1])
        except Exception:
            continue
        fut_map = {str(o.get("id")): o for o in fut_objs if isinstance(o, dict) and "id" in o}

        for oid, pobj in preds.items():
            fo = fut_map.get(oid)
            if fo is None:
                continue
            sev = pobj["severity"]
            err_rain.append(abs(float(sev.get("rain_mm_h", 0.0)) - _rain_mm_h(fo)))
            err_gust.append(abs(float(sev.get("gust_kmh", 0.0)) - _gust_kmh(fo)))

    def _mean(xs):
        return round(sum(xs) / len(xs), 2) if xs else None

    result = {
        "samples": len(err_rain),
        "mae_rain_mm_h": _mean(err_rain),
        "mae_gust_kmh": _mean(err_gust),
        "since_hours": since_hours,
        "evaluated_at": datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S"),
    }
    debug_log(f"[SEVERITY-VERIFY] {result}")
    return result


if __name__ == "__main__":
    print(evaluate_severity(24))
