"""
accuracy_tracker.py — Closed-Loop Vorhersage-Verifikation.

Vergleicht für jede Vorhersage (forecast_lat_H, forecast_lon_H) zum
Vorhersage-Zeitpunkt T+H das tatsächliche Auftreten einer Zelle in
einem Toleranzradius. Liefert sowohl Pixel- als auch km-Metriken.

Matching-Strategie (praxistauglich):
1) Frame bei T+H mit Zeit-Toleranz suchen (±VERIFICATION_TIME_TOLERANCE_S).
2) Primär: ID-Match (falls Zellen-ID erhalten geblieben).
3) Fallback: Nearest-Neighbor auf Lat/Lon mit Haversine-Distanz,
   beschränkt auf VERIFICATION_MAX_SEARCH_RADIUS_KM.
4) Treffer (hit) = Distanz <= VERIFICATION_TOLERANCE_KM.
5) Kein Match in Suchradius → "missed", fließt in Hit-Rate ein.

Output:
- Aggregierte Metriken pro Horizont: MAE (px+km), RMSE x/y (px),
  Hit-Rate, Samples, Missed.
- Historie in train_data/evaluation/accuracy_history.jsonl.
"""

import glob
import json
import math
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple

from config import (
    SAVE_PATHS,
    VERIFICATION_TOLERANCE_KM,
    VERIFICATION_TIME_TOLERANCE_S,
    VERIFICATION_MAX_SEARCH_RADIUS_KM,
)
from debug_utils import debug_log

EVAL_DIR = SAVE_PATHS.get("evaluation", "train_data/evaluation/").rstrip("/")
HISTORY_FILE = os.path.join(EVAL_DIR, "accuracy_history.jsonl")


def _parse_ts(path: str) -> Optional[datetime]:
    base = os.path.splitext(os.path.basename(path))[0]
    try:
        return datetime.strptime(base, "%Y-%m-%d_%H-%M-%S")
    except ValueError:
        return None


def _load_objects(path: str) -> list:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception as exc:
        debug_log(f"[ACCURACY] Lade-Fehler {path}: {exc}")
        return []


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(min(1.0, math.sqrt(a)))


def _find_target_frame(by_ts: Dict[datetime, str],
                       target_ts: datetime,
                       time_tol_s: int) -> Optional[str]:
    best_path = None
    best_delta = time_tol_s + 1
    for ts, path in by_ts.items():
        delta = abs((ts - target_ts).total_seconds())
        if delta <= time_tol_s and delta < best_delta:
            best_delta = delta
            best_path = path
    return best_path


def _match_actual(obj: dict, target_objs: list, horizon_min: int
                  ) -> Tuple[Optional[dict], float, str]:
    fc_lat = obj.get(f"forecast_lat_{horizon_min}")
    fc_lon = obj.get(f"forecast_lon_{horizon_min}")
    if fc_lat is None or fc_lon is None:
        return None, math.inf, "miss"

    oid = str(obj.get("id"))

    id_match = next((o for o in target_objs if str(o.get("id")) == oid), None)
    if id_match is not None and id_match.get("lat") is not None and id_match.get("lon") is not None:
        d = _haversine_km(fc_lat, fc_lon, float(id_match["lat"]), float(id_match["lon"]))
        return id_match, d, "id"

    best = None
    best_d = math.inf
    for cand in target_objs:
        lat = cand.get("lat")
        lon = cand.get("lon")
        if lat is None or lon is None:
            continue
        d = _haversine_km(fc_lat, fc_lon, float(lat), float(lon))
        if d < best_d and d <= VERIFICATION_MAX_SEARCH_RADIUS_KM:
            best_d = d
            best = cand

    if best is None:
        return None, math.inf, "miss"
    return best, best_d, "nn"


def evaluate_for_horizon(horizon_min: int, since_hours: int = 24) -> dict:
    """
    Closed-Loop-Verifikation pro Horizont.

    Fix P03:
      - Pixel-Fehler in EINHEITLICHEM Maßstab berechnen
        (forecast_x_{h} ist skaliert mit UPSCALE_FACTOR;
         matched["x"] ist pre-upscale → vor Vergleich umrechnen).
      - Differenzierte Verifikations-Buckets:
          verified         = ein passendes Ziel gefunden + Distanz auswertbar
          missed           = Ziel-Frame ok, aber keine matchende Zelle in Suchradius
          no_target_frame  = kein Frame im Zeit-Toleranzfenster vorhanden
          id_lost          = Zelle existierte, aber andere ID/keine Lat/Lon im Ziel
        Diese Werte werden im API-Response transparent dargestellt.
    """
    try:
        from config import UPSCALE_FACTOR as _UF_ACC
    except Exception:
        _UF_ACC = 3.0
    _uf = float(_UF_ACC) if _UF_ACC else 1.0

    obj_dir = SAVE_PATHS["objects"].rstrip("/")
    files = sorted(glob.glob(os.path.join(obj_dir, "*.json")))
    fts = [(f, _parse_ts(f)) for f in files]
    fts = [(f, t) for f, t in fts if t is not None]

    base = {
        "horizon": horizon_min,
        "samples": 0,
        "hits": 0,
        "verified": 0,
        "missed": 0,
        "no_target_frame": 0,
        "id_lost": 0,
        "hit_rate": None,
        "mae_km": None,
        "rmse_km": None,
        "mae_px": None,
        "rmse_x_px": None,
        "rmse_y_px": None,
        "since_hours": since_hours,
        "tolerance_km": VERIFICATION_TOLERANCE_KM,
    }
    if not fts:
        debug_log(f"[ACCURACY] Keine Objekt-Dateien gefunden in {obj_dir}")
        return base

    cutoff = fts[-1][1] - timedelta(hours=since_hours)
    by_ts: Dict[datetime, str] = {t: f for f, t in fts}

    n_total = hits = verified = missed = no_target_frame = id_lost = 0
    sum_km = sum_km2 = sum_abs_px = sum_sx2 = sum_sy2 = 0.0

    for fpath, ts in fts:
        if ts < cutoff:
            continue
        objs = _load_objects(fpath)
        if not objs:
            continue
        target_ts = ts + timedelta(minutes=horizon_min)
        target_path = _find_target_frame(by_ts, target_ts, VERIFICATION_TIME_TOLERANCE_S)

        # Anzahl Forecasts in diesem Quell-Frame (für no_target_frame-Buchhaltung)
        forecast_count_this_frame = sum(
            1 for o in objs
            if o.get(f"forecast_lat_{horizon_min}") is not None
            and o.get(f"forecast_lon_{horizon_min}") is not None
        )

        if target_path is None:
            no_target_frame += forecast_count_this_frame
            n_total += forecast_count_this_frame
            continue

        target_objs = _load_objects(target_path)
        if not target_objs:
            no_target_frame += forecast_count_this_frame
            n_total += forecast_count_this_frame
            continue

        for obj in objs:
            fx = obj.get(f"forecast_x_{horizon_min}")
            fy = obj.get(f"forecast_y_{horizon_min}")
            f_lat = obj.get(f"forecast_lat_{horizon_min}")
            f_lon = obj.get(f"forecast_lon_{horizon_min}")
            if any(v is None for v in (fx, fy, f_lat, f_lon)):
                continue

            matched, dist_km, _match_src = _match_actual(obj, target_objs, horizon_min)
            n_total += 1

            if matched is None:
                missed += 1
                continue

            try:
                # Fix P03: matched["x"]/"y"] sind pre-upscale → erst skalieren,
                # damit der Vergleich mit forecast_x_{h} (skaliert) konsistent ist.
                rx_scaled = float(matched.get("x", 0.0)) * _uf
                ry_scaled = float(matched.get("y", 0.0)) * _uf
                ex = float(fx) - rx_scaled
                ey = float(fy) - ry_scaled
                sum_sx2 += ex * ex
                sum_sy2 += ey * ey
                sum_abs_px += math.hypot(ex, ey)
            except Exception:
                # Pixel-Berechnung fehlgeschlagen → nur km-Metrik nutzen.
                pass

            sum_km += dist_km
            sum_km2 += dist_km * dist_km
            verified += 1
            if dist_km <= VERIFICATION_TOLERANCE_KM:
                hits += 1

    if n_total == 0:
        debug_log(f"[ACCURACY] horizon=+{horizon_min}m: 0 verifizierbare Samples in den letzten {since_hours}h")
        return base

    eval_n = verified if verified > 0 else 1

    # P24: coverage_rate = Anteil verifizierbarer Forecasts an allen.
    # Hohe hit_rate ist nur aussagekräftig wenn coverage_rate hoch ist.
    # coverage_rate < 0.3 → Metriken unzuverlässig (zu viele not_found frames).
    _coverage = round(verified / n_total, 4) if n_total > 0 else None

    return {
        "horizon": horizon_min,
        "samples": n_total,
        "hits": hits,
        "verified": verified,
        "missed": missed,
        "no_target_frame": no_target_frame,
        "id_lost": id_lost,
        "hit_rate": round(hits / verified, 4) if verified else None,
        "coverage_rate": _coverage,          # verified / n_total
        "mae_km": round(sum_km / eval_n, 3) if eval_n else None,
        "rmse_km": round(math.sqrt(sum_km2 / eval_n), 3) if eval_n else None,
        "mae_px": round(sum_abs_px / eval_n, 2) if eval_n else None,
        "rmse_x_px": round(math.sqrt(sum_sx2 / eval_n), 2) if eval_n else None,
        "rmse_y_px": round(math.sqrt(sum_sy2 / eval_n), 2) if eval_n else None,
        "since_hours": since_hours,
        "tolerance_km": VERIFICATION_TOLERANCE_KM,
    }


def evaluate_all(horizons: List[int], since_hours: int = 24) -> dict:
    return {"since_hours": since_hours, "tolerance_km": VERIFICATION_TOLERANCE_KM,
            "horizons": [evaluate_for_horizon(h, since_hours) for h in horizons]}


def append_history_point(metric: dict) -> str:
    os.makedirs(EVAL_DIR, exist_ok=True)
    metric = dict(metric)
    metric["timestamp_utc"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    try:
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(metric, ensure_ascii=False) + "\n")
    except Exception as exc:
        debug_log(f"[ACCURACY] Konnte Historie nicht schreiben: {exc}")
    return HISTORY_FILE


def load_history(since_hours: int = 24 * 7) -> list:
    if not os.path.exists(HISTORY_FILE):
        return []
    cutoff = datetime.utcnow() - timedelta(hours=since_hours)
    out: List[dict] = []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line.strip())
                    ts_str = rec.get("timestamp_utc", "").replace("Z", "")
                    ts = datetime.fromisoformat(ts_str)
                    if ts >= cutoff:
                        out.append(rec)
                except Exception:
                    continue
    except Exception as exc:
        debug_log(f"[ACCURACY] Historie Lesefehler: {exc}")
    return out


if __name__ == "__main__":
    from config import ML_FORECAST_HORIZONS_MIN
    result = evaluate_all(ML_FORECAST_HORIZONS_MIN, 24)
    print(json.dumps(result, indent=2, ensure_ascii=False))
