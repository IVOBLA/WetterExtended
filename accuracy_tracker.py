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
from typing import Optional, Dict, List, Tuple, Any, Set

from config import (
    SAVE_PATHS,
    VERIFICATION_TOLERANCE_KM,
    VERIFICATION_TIME_TOLERANCE_S,
    VERIFICATION_MAX_SEARCH_RADIUS_KM,
)
from debug_utils import debug_log

EVAL_DIR = SAVE_PATHS.get("evaluation", "train_data/evaluation/").rstrip("/")
HISTORY_FILE = os.path.join(EVAL_DIR, "accuracy_history.jsonl")
DETAILS_FILE = os.path.join(EVAL_DIR, "forecast_error_details.jsonl")


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



def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def direction_error_deg(a: Optional[float], b: Optional[float]) -> Optional[float]:
    """Minimaler Winkelabstand 0..180 Grad."""
    if a is None or b is None:
        return None
    diff = abs((float(a) - float(b)) % 360.0)
    return min(diff, 360.0 - diff)


def _bearing_deg(lat1, lon1, lat2, lon2) -> Optional[float]:
    vals = [_safe_float(v) for v in (lat1, lon1, lat2, lon2)]
    if any(v is None for v in vals):
        return None
    lat1, lon1, lat2, lon2 = vals
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlam = math.radians(lon2 - lon1)
    y = math.sin(dlam) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlam)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def _jsonl_append(path: str, rec: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, allow_nan=False) + "\n")
    except (TypeError, ValueError):
        clean = {k: (None if isinstance(v, float) and not math.isfinite(v) else v) for k, v in rec.items()}
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(clean, ensure_ascii=False, allow_nan=False) + "\n")



def _detail_key(rec: dict) -> tuple:
    return (
        rec.get("forecast_created_at_utc"), rec.get("target_timestamp_utc"), rec.get("horizon_min"),
        rec.get("object_id") or rec.get("cell_id"), rec.get("cell_id"),
        rec.get("forecast_lat"), rec.get("forecast_lon"), rec.get("actual_lat"), rec.get("actual_lon"),
        rec.get("match_type"),
    )


def _append_detail_once(path: str, rec: dict, seen: Set[tuple]) -> bool:
    key = _detail_key(rec)
    if key in seen:
        return False
    seen.add(key)
    _jsonl_append(path, rec)
    return True

def _match_type(raw: str) -> str:
    return {"nn": "nearest", "miss": "none"}.get(raw, raw or "none")


def _forecast_meta(obj: dict, horizon_min: int, key: str, default=None):
    return obj.get(f"{key}_{horizon_min}", obj.get(key, default))


def _detail_record(obj: dict, ts: datetime, target_ts: datetime, horizon_min: int, matched: Optional[dict],
                   dist_km: Optional[float], match_src: str, no_target_frame: bool, stale: bool,
                   effective_lead_min: float, ex_px: Optional[float] = None, ey_px: Optional[float] = None) -> dict:
    f_lat = _safe_float(obj.get(f"forecast_lat_{horizon_min}")); f_lon = _safe_float(obj.get(f"forecast_lon_{horizon_min}"))
    o_lat = _safe_float(obj.get("origin_lat", obj.get("lat"))); o_lon = _safe_float(obj.get("origin_lon", obj.get("lon")))
    a_lat = _safe_float(matched.get("lat") if matched else None); a_lon = _safe_float(matched.get("lon") if matched else None)
    fc_disp = _haversine_km(o_lat, o_lon, f_lat, f_lon) if None not in (o_lat, o_lon, f_lat, f_lon) else None
    ac_disp = _haversine_km(o_lat, o_lon, a_lat, a_lon) if None not in (o_lat, o_lon, a_lat, a_lon) else None
    lead_h = effective_lead_min / 60.0 if effective_lead_min else (horizon_min / 60.0)
    fc_speed = fc_disp / lead_h if fc_disp is not None and lead_h else None
    ac_speed = ac_disp / lead_h if ac_disp is not None and lead_h else None
    fc_dir = _bearing_deg(o_lat, o_lon, f_lat, f_lon); ac_dir = _bearing_deg(o_lat, o_lon, a_lat, a_lon)
    return {
        "verified_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "forecast_created_at_utc": ts.isoformat(timespec="seconds") + "Z",
        "target_timestamp_utc": target_ts.isoformat(timespec="seconds") + "Z",
        "horizon_min": horizon_min, "effective_lead_min": round(effective_lead_min, 3), "stale": bool(stale),
        "object_id": str(obj.get("id", "")), "cell_id": str(obj.get("cell_id", obj.get("id", ""))), "track_id": str(obj.get("track_id", "")),
        "parent_cell_id": obj.get("parent_cell_id"), "lineage_status": obj.get("lineage_status"),
        "merged_from_cell_ids": obj.get("merged_from_cell_ids"),
        "forecast_mode": str(_forecast_meta(obj, horizon_min, "forecast_mode", "unknown") or "unknown"),
        "kinematic_source": str(_forecast_meta(obj, horizon_min, "kinematic_source", "unknown") or "unknown"),
        "of_available": int(obj.get("of_available", 0) or 0), "of_error_reason": obj.get("of_error_reason"),
        "forecast_lat": f_lat, "forecast_lon": f_lon, "actual_lat": a_lat, "actual_lon": a_lon, "origin_lat": o_lat, "origin_lon": o_lon,
        "forecast_error_km": round(dist_km, 6) if dist_km is not None and math.isfinite(dist_km) else None,
        "forecast_error_x_px": ex_px, "forecast_error_y_px": ey_px,
        "forecast_displacement_km": round(fc_disp, 6) if fc_disp is not None else None, "forecast_speed_kmh": round(fc_speed, 6) if fc_speed is not None else None,
        "actual_displacement_km": round(ac_disp, 6) if ac_disp is not None else None, "actual_speed_kmh": round(ac_speed, 6) if ac_speed is not None else None,
        "speed_error_kmh": round(abs(fc_speed - ac_speed), 6) if fc_speed is not None and ac_speed is not None else None,
        "forecast_direction_deg": round(fc_dir, 6) if fc_dir is not None else None, "actual_direction_deg": round(ac_dir, 6) if ac_dir is not None else None,
        "direction_error_deg": round(direction_error_deg(fc_dir, ac_dir), 6) if direction_error_deg(fc_dir, ac_dir) is not None else None,
        "match_type": _match_type(match_src), "matched_object_id": str(matched.get("id", "")) if matched else None,
        "matched_cell_id": str(matched.get("cell_id", matched.get("id", ""))) if matched else None,
        "match_distance_km": round(dist_km, 6) if dist_km is not None and math.isfinite(dist_km) else None,
        "radar_age_min": _safe_float(obj.get("radar_age_min"), 0.0), "no_target_frame": bool(no_target_frame),
        "id_lost": bool((not no_target_frame) and matched is not None and str(matched.get("id")) != str(obj.get("id"))),
        "missed": bool((not no_target_frame) and matched is None),
    }

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



def _is_synthetic_object(obj: dict) -> bool:
    if not isinstance(obj, dict):
        return True
    if any(str(obj.get(k) or "").startswith("cell-") for k in ("id", "cell_id")):
        return True
    lat = _safe_float(obj.get("lat"))
    lon = _safe_float(obj.get("lon"))
    return lat == 47.0 and lon == 15.0


def _forecast_has_sentinel_coordinates(obj: dict, horizon_min: int) -> bool:
    f_lat = _safe_float(obj.get(f"forecast_lat_{horizon_min}"))
    f_lon = _safe_float(obj.get(f"forecast_lon_{horizon_min}"))
    o_lat = _safe_float(obj.get("origin_lat", obj.get("lat")))
    o_lon = _safe_float(obj.get("origin_lon", obj.get("lon")))
    return (f_lat == 47.0 and f_lon == 15.0) or (o_lat == 47.0 and o_lon == 15.0)


def _is_real_forecast_object(obj: dict, horizon_min: int) -> bool:
    return not _is_synthetic_object(obj) and not _forecast_has_sentinel_coordinates(obj, horizon_min)

def _match_actual(obj: dict, target_objs: list, horizon_min: int
                  ) -> Tuple[Optional[dict], float, str]:
    fc_lat = obj.get(f"forecast_lat_{horizon_min}")
    fc_lon = obj.get(f"forecast_lon_{horizon_min}")
    if fc_lat is None or fc_lon is None:
        return None, math.inf, "miss"

    oid = str(obj.get("id"))
    cell_id = str(obj.get("cell_id", obj.get("id", "")))

    id_match = next((o for o in target_objs if str(o.get("id")) == oid), None)
    if id_match is not None and id_match.get("lat") is not None and id_match.get("lon") is not None:
        d = _haversine_km(fc_lat, fc_lon, float(id_match["lat"]), float(id_match["lon"]))
        return id_match, d, "id"

    if cell_id:
        cell_match = next((o for o in target_objs if str(o.get("cell_id", o.get("id", ""))) == cell_id), None)
        if cell_match is not None and cell_match.get("lat") is not None and cell_match.get("lon") is not None:
            d = _haversine_km(fc_lat, fc_lon, float(cell_match["lat"]), float(cell_match["lon"]))
            return cell_match, d, "cell_id"

    best = None
    best_d = math.inf
    for cand in target_objs:
        if _is_synthetic_object(cand):
            continue
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


def _percentile(values: list, p: float) -> Optional[float]:
    vals = sorted(float(v) for v in values if v is not None)
    if not vals:
        return None
    idx = min(len(vals) - 1, max(0, math.ceil((p / 100.0) * len(vals)) - 1))
    return vals[idx]


def _stat_errors(values: list, name: str) -> dict:
    if not values:
        return {}
    prefix = "direction" if "direction" in name else "speed"
    unit = "deg" if prefix == "direction" else "kmh"
    return {f"median_{prefix}_error_{unit}": round(_percentile(values, 50), 3), f"p90_{prefix}_error_{unit}": round(_percentile(values, 90), 3)}


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

    by_mode = {}
    by_source = {}
    by_match = {}
    direction_errors = []
    speed_errors = []
    details = []
    detail_keys_seen: Set[tuple] = set()

    def _bucket(store, key):
        k = str(key or "unknown")
        return store.setdefault(k, {"samples": 0, "verified": 0, "hits": 0, "missed": 0, "no_target_frame": 0, "sum_km": 0.0, "sum_km2": 0.0})


    def _mode_for(obj):
        return obj.get(f"forecast_mode_{horizon_min}", obj.get("forecast_mode"))

    def _source_for(obj):
        return obj.get(f"kinematic_source_{horizon_min}", obj.get("kinematic_source"))

    def _finish(store):
        out = {}
        for k, v in store.items():
            total = int(v.get("samples", 0)) + int(v.get("no_target_frame", 0))
            ver = int(v.get("verified", 0))
            out[k] = {
                "samples": total, "verified": ver, "missed": int(v.get("missed", 0)),
                "no_target_frame": int(v.get("no_target_frame", 0)),
                "mae_km": round(v["sum_km"] / ver, 3) if ver else None,
                "rmse_km": round(math.sqrt(v.get("sum_km2", 0.0) / ver), 3) if ver else None,
                "hit_rate": round(v["hits"] / ver, 4) if ver else None,
                "coverage_rate": round(ver / total, 4) if total else None,
            }
        return out

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
        "by_forecast_mode": _finish(by_mode),
        "by_kinematic_source": _finish(by_source),
        "by_match_type": _finish(by_match),
        "direction_stats": {},
        "speed_stats": {},
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
            and _is_real_forecast_object(o, horizon_min)
        )

        if target_path is None:
            no_target_frame += forecast_count_this_frame
            n_total += forecast_count_this_frame
            for _o in objs:
                if _o.get(f"forecast_lat_{horizon_min}") is not None and _o.get(f"forecast_lon_{horizon_min}") is not None and _is_real_forecast_object(_o, horizon_min):
                    _bucket(by_mode, _mode_for(_o))["no_target_frame"] += 1
                    _bucket(by_source, _source_for(_o))["no_target_frame"] += 1
                    _bucket(by_match, "none")["no_target_frame"] += 1
                    rec = _detail_record(_o, ts, target_ts, horizon_min, None, None, "none", True, False, horizon_min)
                    details.append(rec); _append_detail_once(DETAILS_FILE, rec, detail_keys_seen)
            continue

        target_objs = [o for o in _load_objects(target_path) if not _is_synthetic_object(o)]
        if not target_objs:
            no_target_frame += forecast_count_this_frame
            n_total += forecast_count_this_frame
            for _o in objs:
                if _o.get(f"forecast_lat_{horizon_min}") is not None and _o.get(f"forecast_lon_{horizon_min}") is not None and _is_real_forecast_object(_o, horizon_min):
                    _bucket(by_mode, _mode_for(_o))["no_target_frame"] += 1
                    _bucket(by_source, _source_for(_o))["no_target_frame"] += 1
                    _bucket(by_match, "none")["no_target_frame"] += 1
                    rec = _detail_record(_o, ts, target_ts, horizon_min, None, None, "none", True, False, horizon_min)
                    details.append(rec); _append_detail_once(DETAILS_FILE, rec, detail_keys_seen)
            continue

        for obj in objs:
            fx = obj.get(f"forecast_x_{horizon_min}")
            fy = obj.get(f"forecast_y_{horizon_min}")
            f_lat = obj.get(f"forecast_lat_{horizon_min}")
            f_lon = obj.get(f"forecast_lon_{horizon_min}")
            if any(v is None for v in (fx, fy, f_lat, f_lon)):
                continue
            if not _is_real_forecast_object(obj, horizon_min):
                continue

            matched, dist_km, _match_src = _match_actual(obj, target_objs, horizon_min)
            n_total += 1
            _bm = _bucket(by_mode, _mode_for(obj)); _bs = _bucket(by_source, _source_for(obj)); _bt = _bucket(by_match, _match_type(_match_src))
            _bm["samples"] += 1; _bs["samples"] += 1; _bt["samples"] += 1
            ex = ey = None

            if matched is None:
                missed += 1
                _bm["missed"] += 1; _bs["missed"] += 1; _bt["missed"] += 1
                rec = _detail_record(obj, ts, target_ts, horizon_min, None, None, _match_src, False, False, horizon_min)
                details.append(rec); _append_detail_once(DETAILS_FILE, rec, detail_keys_seen)
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
            _bm["verified"] += 1; _bs["verified"] += 1; _bt["verified"] += 1
            _bm["sum_km"] += dist_km; _bs["sum_km"] += dist_km; _bt["sum_km"] += dist_km
            _bm["sum_km2"] += dist_km * dist_km; _bs["sum_km2"] += dist_km * dist_km; _bt["sum_km2"] += dist_km * dist_km
            rec = _detail_record(obj, ts, target_ts, horizon_min, matched, dist_km, _match_src, False, False, horizon_min, ex, ey)
            if rec.get("direction_error_deg") is not None: direction_errors.append(float(rec["direction_error_deg"]))
            if rec.get("speed_error_kmh") is not None: speed_errors.append(float(rec["speed_error_kmh"]))
            details.append(rec); _append_detail_once(DETAILS_FILE, rec, detail_keys_seen)
            if dist_km <= VERIFICATION_TOLERANCE_KM:
                hits += 1
                _bm["hits"] += 1; _bs["hits"] += 1; _bt["hits"] += 1

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
        "by_forecast_mode": _finish(by_mode),
        "by_kinematic_source": _finish(by_source),
        "by_match_type": _finish(by_match),
        "direction_stats": _stat_errors(direction_errors, "direction_error_deg"),
        "speed_stats": _stat_errors(speed_errors, "speed_error_kmh"),
    }


def _diagnosis(summary: dict) -> list:
    out = []
    for h, modes in summary.get("breakdown_by_forecast_mode", {}).items():
        ml = modes.get("ml", {}).get("mae_km"); kin = modes.get("kinematic", {}).get("mae_km")
        if ml is not None and kin is not None and ml > kin * 1.5:
            out.append("ML forecast performs worse than kinematic fallback."); break
    if any((v.get("p90_direction_error_deg") or 0) >= 90 for v in summary.get("direction_stats_by_horizon", {}).values()):
        out.append("Forecast direction error dominates.")
    if any((v.get("p90_speed_error_kmh") or 0) >= 30 for v in summary.get("speed_stats_by_horizon", {}).values()):
        out.append("Forecast speed error dominates.")
    for h, mt in summary.get("breakdown_by_match_type", {}).items():
        nn = mt.get("nearest", {}).get("mae_km"); iid = mt.get("id", {}).get("mae_km")
        if nn is not None and iid is not None and nn > iid * 1.5:
            out.append("Verification likely affected by ID/split/merge matching."); break
    for row in summary.get("horizons", []):
        if row.get("samples") and (row.get("no_target_frame", 0) / row.get("samples", 1)) >= 0.3:
            out.append("Coverage limited by missing target frames."); break
    return list(dict.fromkeys(out))


def evaluate_all(horizons: List[int], since_hours: int = 24) -> dict:
    rows = [evaluate_for_horizon(h, since_hours) for h in horizons]
    summary = {"since_hours": since_hours, "tolerance_km": VERIFICATION_TOLERANCE_KM, "horizons": rows}
    summary["breakdown_by_forecast_mode"] = {str(r["horizon"]): r.get("by_forecast_mode", {}) for r in rows}
    summary["breakdown_by_kinematic_source"] = {str(r["horizon"]): r.get("by_kinematic_source", {}) for r in rows}
    summary["breakdown_by_match_type"] = {str(r["horizon"]): r.get("by_match_type", {}) for r in rows}
    summary["direction_stats_by_horizon"] = {str(r["horizon"]): r.get("direction_stats", {}) for r in rows}
    summary["speed_stats_by_horizon"] = {str(r["horizon"]): r.get("speed_stats", {}) for r in rows}
    summary["worst_forecasts"] = load_error_details(limit=10, since_hours=since_hours, sort_worst=True)
    summary["diagnosis"] = _diagnosis(summary)
    return summary


def load_error_details(limit: int = 1000, since_hours: int = 24 * 7, sort_worst: bool = False) -> list:
    if not os.path.exists(DETAILS_FILE):
        return []
    cutoff = datetime.utcnow() - timedelta(hours=since_hours)
    out = []
    with open(DETAILS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
                ts = datetime.fromisoformat(str(rec.get("verified_at_utc", "")).replace("Z", ""))
                if ts >= cutoff:
                    out.append(rec)
            except Exception:
                continue
    if sort_worst:
        out.sort(key=lambda r: r.get("forecast_error_km") if r.get("forecast_error_km") is not None else -1, reverse=True)
    return out[:limit]


def classify_zero_sample_health(obj_dir: str, since_hours: int = 24) -> dict:
    """
    B126: Klassifiziert eine Null-Sample-Accuracy-Lage, um Schönwetter
    (legitime Ruhephase) von einem echten Pipeline-Defekt zu unterscheiden.
    Rein lesend, kein Logging.

      total_cells == 0                       → 'no_cells_quiet'              (info)
      total_cells > 0, keine forecast_lat_*  → 'missing_forecast_fields'     (warning)
      sonst                                  → 'zero_samples_despite_forecast'(warning)
    """
    cutoff = datetime.utcnow() - timedelta(hours=since_hours)
    files = glob.glob(os.path.join(obj_dir, "*.json"))
    total_cells = 0
    cells_with_forecast = 0
    for p in files:
        ts = _parse_ts(p)
        if ts is None or ts < cutoff:
            continue
        for o in _load_objects(p):
            if not isinstance(o, dict) or "id" not in o:
                continue
            total_cells += 1
            if any(str(k).startswith("forecast_lat_") for k in o.keys()):
                cells_with_forecast += 1
    if total_cells == 0:
        event, severity = "no_cells_quiet", "info"
    elif cells_with_forecast == 0:
        event, severity = "missing_forecast_fields", "warning"
    else:
        event, severity = "zero_samples_despite_forecast", "warning"
    return {
        "event": event,
        "severity": severity,
        "obj_files": len(files),
        "total_cells": total_cells,
        "cells_with_forecast": cells_with_forecast,
    }


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
