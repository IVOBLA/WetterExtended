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
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Optional, Dict, List, Tuple, Any, Set

from config import (
    SAVE_PATHS,
    VERIFICATION_TOLERANCE_KM,
    VERIFICATION_TIME_TOLERANCE_S,
    VERIFICATION_MAX_SEARCH_RADIUS_KM,
    VERIFICATION_NN_MAX_MATCH_KM,
    VERIFICATION_NN_MAX_MATCH_KM_BY_HORIZON,
    VERIFICATION_MATCH_MAX_ACTUAL_SPEED_KMH,
    VERIFICATION_CORE_MIN_RATIO,
    VERIFICATION_NEAREST_FRAME_TOLERANCE_S,
    DIRECTION_ERROR_MIN_DISPLACEMENT_KM,
    VERIFICATION_INTERPOLATION_MAX_GAP_S,
    FRAME_INTERVAL_MIN,
)
from debug_utils import debug_log

_VIENNA_TZ = ZoneInfo("Europe/Vienna")


def _local_naive_to_utc_iso_z(dt) -> str:
    """B230: Frame-Zeit (naiv = Europe/Vienna-Lokalzeit) -> echtes UTC-ISO mit Z.
    Bereits tz-aware -> nach UTC konvertiert. Format: YYYY-MM-DDTHH:MM:SSZ."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_VIENNA_TZ)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

try:
    import runtime_config as _runtime_cfg
except Exception:  # pragma: no cover
    _runtime_cfg = None


def _nn_max_match_km(horizon_min: Optional[int] = None) -> float:
    """B228/B279: NN-Akzeptanzschwelle, runtime-ueberschreibbar und horizontabhängig gedeckelt."""
    hard_limit = float(VERIFICATION_NN_MAX_MATCH_KM)
    threshold = hard_limit
    if horizon_min is not None:
        threshold = float(VERIFICATION_NN_MAX_MATCH_KM_BY_HORIZON.get(str(horizon_min), hard_limit))
    if _runtime_cfg is not None:
        try:
            # B296: runtime_config.get() fällt auf config.VERIFICATION_NN_MAX_MATCH_KM
            # zurück; das darf die horizontabhängige Tabelle nicht implizit wieder
            # auf die harte Obergrenze anheben. Nur echte Runtime-Overrides ersetzen
            # den Horizontwert. Test-Stubs ohne _OVERRIDES nutzen weiterhin get().
            overrides = getattr(_runtime_cfg, "_OVERRIDES", None)
            if isinstance(overrides, dict):
                if "VERIFICATION_NN_MAX_MATCH_KM" in overrides:
                    threshold = float(overrides["VERIFICATION_NN_MAX_MATCH_KM"])
            else:
                threshold = float(_runtime_cfg.get("VERIFICATION_NN_MAX_MATCH_KM", threshold))
        except Exception:
            pass
    return min(float(threshold), hard_limit)


def _max_actual_speed_kmh() -> float:
    """B247: Maximale implizite Ist-Geschwindigkeit für einen gültigen Match, runtime-überschreibbar."""
    if _runtime_cfg is not None:
        try:
            return float(_runtime_cfg.get("VERIFICATION_MATCH_MAX_ACTUAL_SPEED_KMH", VERIFICATION_MATCH_MAX_ACTUAL_SPEED_KMH))
        except Exception:
            pass
    return float(VERIFICATION_MATCH_MAX_ACTUAL_SPEED_KMH)


def _core_min_ratio() -> float:
    """B247: Mindest-core_ratio des Zielobjekts für Match-Akzeptanz, runtime-überschreibbar."""
    if _runtime_cfg is not None:
        try:
            return float(_runtime_cfg.get("VERIFICATION_CORE_MIN_RATIO", VERIFICATION_CORE_MIN_RATIO))
        except Exception:
            pass
    return float(VERIFICATION_CORE_MIN_RATIO)


def _match_valid_b247(obj: dict, matched: dict, horizon_min: int) -> bool:
    """B247: True wenn Match physikalisch plausibel ist (Speed-Gate + Core-Anforderung).
    Speed-Gate: implizite Ist-Geschwindigkeit Origin→Actual ≤ VERIFICATION_MATCH_MAX_ACTUAL_SPEED_KMH.
    Core-Gate:  wenn Origin konvektiv (core_ratio > 0) muss Actual ebenfalls konvektiv sein.
    Beide Gates können durch Runtime-Konfiguration deaktiviert/gelockert werden.
    """
    # Speed-Gate
    _spd_limit = _max_actual_speed_kmh()
    if _spd_limit > 0.0 and horizon_min > 0:
        o_lat = _safe_float(obj.get("origin_lat", obj.get("lat")))
        o_lon = _safe_float(obj.get("origin_lon", obj.get("lon")))
        a_lat = _safe_float(matched.get("lat"))
        a_lon = _safe_float(matched.get("lon"))
        if None not in (o_lat, o_lon, a_lat, a_lon):
            _disp_km = _haversine_km(o_lat, o_lon, a_lat, a_lon)
            if _disp_km is not None:
                _speed = _disp_km / (float(horizon_min) / 60.0)
                if _speed > _spd_limit:
                    return False

    # Core-Gate: nur wenn Origin konvektiv ist
    _min_core = _core_min_ratio()
    if _min_core > 0.0:
        _origin_core = float(obj.get("core_ratio") or 0.0)
        if _origin_core > 0.0:
            _actual_core = float(matched.get("core_ratio") or 0.0)
            if _actual_core < _min_core:
                return False

    return True


def _is_nn_rejected(match_src, matched, dist_km, threshold_km) -> bool:
    """B228: True, wenn NN-Treffer die strenge Akzeptanzschwelle ueberschreitet."""
    return match_src == "nn" and matched is not None and dist_km is not None and dist_km > threshold_km

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


def _load_detail_keys(path: str, since_hours: int = 24) -> Set[tuple]:
    """B258: Liest bestehende Einträge aus forecast_error_details.jsonl und
    gibt deren Schlüssel-Set zurück. Nur Einträge innerhalb von since_hours
    werden berücksichtigt (Fenster identisch zu evaluate_for_horizon).
    Verhindert Duplikate bei nachfolgenden _append_detail_once-Aufrufen."""
    seen: Set[tuple] = set()
    if not os.path.exists(path):
        return seen
    cutoff = datetime.utcnow() - timedelta(hours=since_hours)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    ts_str = str(rec.get("verified_at_utc", "")).replace("Z", "")
                    if ts_str:
                        ts = datetime.fromisoformat(ts_str)
                        if ts < cutoff:
                            continue
                    seen.add(_detail_key(rec))
                except Exception:
                    continue
    except Exception as exc:
        debug_log(f"[ACCURACY] _load_detail_keys Fehler: {exc}")
    return seen

def _match_type(raw: str) -> str:
    # B279: Lineage-Match-Typen werden 1:1 durchgereicht (keine Umschreibung auf "none"/"nn").
    if raw in ("lineage_parent", "lineage_merged_from", "lineage_split_child"):
        return raw
    return {"nn": "nearest", "miss": "none"}.get(raw, raw or "none")


def _forecast_meta(obj: dict, horizon_min: int, key: str, default=None):
    return obj.get(f"{key}_{horizon_min}", obj.get(key, default))


def _detail_record(obj: dict, ts: datetime, target_ts: datetime, horizon_min: int, matched: Optional[dict],
                   dist_km: Optional[float], match_src: str, no_target_frame: bool, stale: bool,
                   effective_lead_min: float, ex_px: Optional[float] = None, ey_px: Optional[float] = None,
                   target_frame_delta_min: Optional[float] = None,
                   missing_target_frame_reason: Optional[str] = None,
                   frame_empty: bool = False) -> dict:
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
        "forecast_created_at_utc": _local_naive_to_utc_iso_z(ts),
        "target_timestamp_utc": _local_naive_to_utc_iso_z(target_ts),
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
        "frame_empty": bool(frame_empty),
        "target_frame_delta_min": target_frame_delta_min,
        "missing_target_frame_reason": missing_target_frame_reason,
        "id_lost": bool((not no_target_frame) and (not frame_empty) and matched is not None and str(matched.get("id")) != str(obj.get("id"))),
        "missed": bool((not no_target_frame) and (not frame_empty) and matched is None),
        # B249: DEM-Features aus Tracking-Objekt für Fehler-Attribution (Diagnose + ML).
        # Werte 0.0/None wenn DEM-Tiles beim Forecast-Zeitpunkt nicht geladen waren.
        "dem_elevation_m":       _safe_float(obj.get("dem_elevation_m")),
        "dem_slope_toward_cell": _safe_float(obj.get("dem_slope_toward_cell")),
        "dem_barrier_ahead":     _safe_float(obj.get("dem_barrier_ahead")),
        # B299: unterscheidet dem_unavailable/no_movement_vector/computed —
        # damit ein Nullwert nicht faelschlich als Datenausfall gilt.
        "dem_slope_barrier_status": obj.get("dem_slope_barrier_status"),
        "valley_alignment":      _safe_float(obj.get("valley_alignment")),
        "terrain_blocking_score":_safe_float(obj.get("terrain_blocking_score")),
        "orographic_lift_score": _safe_float(obj.get("orographic_lift_score")),
        # B249: Wetter-Features aus Tracking-Objekt (700-hPa-Wind, AROME, Nowcast).
        "wind_speed_700hPa":     _safe_float(obj.get("wind_speed_700hPa")),
        "wind_dir_cos":          _safe_float(obj.get("wind_dir_cos")),
        "wind_dir_sin":          _safe_float(obj.get("wind_dir_sin")),
        "cape":                  _safe_float(obj.get("cape")),
        "arome_li":              _safe_float(obj.get("arome_li")),
        "arome_t2m":             _safe_float(obj.get("arome_t2m")),
        "wind_speed_500hPa":     _safe_float(obj.get("wind_speed_500hPa")),
        # B344: Fallback-Marker fuer Open-Meteo-0.0-Platzhalter (API-Fehler/
        # fehlender Zeitslot) -- macht Ausfaelle fuer
        # tools/diagnose_forecast_quality.py::_feature_stats (fallback_ratio)
        # sichtbar, statt ununterscheidbar von echten Nullwerten zu sein.
        "wind_speed_700hPa_fallback": bool(obj.get("wind_speed_700hPa_fallback")),
        "wind_dir_cos_fallback":      bool(obj.get("wind_dir_cos_fallback")),
        "wind_dir_sin_fallback":      bool(obj.get("wind_dir_sin_fallback")),
        "arome_t2m_fallback":         bool(obj.get("arome_t2m_fallback")),
        "arome_li_fallback":          bool(obj.get("arome_li_fallback")),
        "wind_speed_500hPa_fallback": bool(obj.get("wind_speed_500hPa_fallback")),
        "nowcast_rr_mm15":       _safe_float(obj.get("nowcast_rr_mm15")),
        "lightning_count_10km":  _safe_float(obj.get("lightning_count_10km")),
        "kinematic_speed_kmh":   _safe_float(obj.get("kinematic_speed_kmh")),
        # B348: Diagnose-Proxy fuer die Drift-Root-Cause-Validierung (B349).
        "kinematic_accel_proxy_kmh":      _safe_float(obj.get("kinematic_accel_proxy_kmh")),
        "kinematic_acceleration_applied": bool(obj.get("kinematic_acceleration_applied")),
        "core_ratio":            _safe_float(obj.get("core_ratio")),
        "area":                  _safe_float(obj.get("area")),
    }

def _effective_target_tolerance_s(time_tol_s: int,
                                   by_ts: Optional[Dict[datetime, str]] = None) -> int:
    """Deckt ARSO-Frames mit der gemessenen Halbtakt-Kadenz ab.

    B260: Wenn by_ts übergeben wird, wird der Median der tatsächlich
    beobachteten Inter-Frame-Abstände gemessen. Die effektive Toleranz
    ist dann max(time_tol_s, gemessene_halb_kadenz_s, nominaler_halbtakt_s),
    sodass Kurz-Horizont-Forecasts auch bei 15-min-Radarkadenz verifizierbar
    bleiben (missing_target_frames ratio sinkt).
    """
    frame_half_s = int(round(float(FRAME_INTERVAL_MIN) * 60.0 / 2.0))
    nearest_tol_s = float(VERIFICATION_NEAREST_FRAME_TOLERANCE_S)
    if _runtime_cfg is not None:
        try:
            nearest_tol_s = float(
                _runtime_cfg.get(
                    "VERIFICATION_NEAREST_FRAME_TOLERANCE_S",
                    VERIFICATION_NEAREST_FRAME_TOLERANCE_S,
                )
            )
        except Exception:
            pass
    nearest_tol_i = int(round(nearest_tol_s))
    if by_ts and len(by_ts) == 1:
        frame_half_s = max(frame_half_s, int(round(float(FRAME_INTERVAL_MIN) * 60.0)))
    if by_ts and len(by_ts) >= 2:
        sorted_ts = sorted(by_ts.keys())
        gaps_s = [
            (sorted_ts[i + 1] - sorted_ts[i]).total_seconds()
            for i in range(len(sorted_ts) - 1)
        ]
        if gaps_s:
            import statistics as _statistics
            measured_half_s = int(round(_statistics.median(gaps_s) / 2.0))
            frame_half_s = max(frame_half_s, min(measured_half_s, nearest_tol_i))
    return max(int(time_tol_s), frame_half_s, nearest_tol_i)


def _classify_missing_target_frame(by_ts: Dict[datetime, str], target_ts: datetime, effective_tol_s: int, now_utc: datetime) -> str:
    """B278: Klassifiziert, warum kein Ziel-Frame gefunden wurde."""
    if not by_ts:
        return "missing_due_to_ingest_gap"
    if target_ts > now_utc:
        return "missing_due_to_future_not_available"
    nearest_delta = min((abs((ts - target_ts).total_seconds()) for ts in by_ts.keys()), default=None)
    if nearest_delta is None:
        return "missing_due_to_ingest_gap"
    if nearest_delta > effective_tol_s:
        # Unterscheidung: liegt die nächste vorhandene Aufnahme weiter als das
        # 2-fache der Toleranz entfernt -> echte Ingest-Lücke, sonst Toleranzproblem.
        return "missing_due_to_ingest_gap" if nearest_delta > 2 * effective_tol_s else "missing_due_to_tolerance"
    return "missing_due_to_tolerance"


def _find_target_frame(by_ts: Dict[datetime, str],
                       target_ts: datetime,
                       time_tol_s: int) -> tuple[Optional[str], Optional[float], Optional[str]]:
    """B260: nächstgelegener Frame innerhalb adaptiver Toleranz (UNVERÄNDERT).
    B278: liefert zusätzlich target_frame_delta_min und ggf. Ablehnungsgrund.
    """
    effective_tol_s = _effective_target_tolerance_s(time_tol_s, by_ts)
    best_path = None
    best_delta = effective_tol_s + 1
    for ts, path in by_ts.items():
        delta = abs((ts - target_ts).total_seconds())
        if delta <= effective_tol_s and delta < best_delta:
            best_delta = delta
            best_path = path
    if best_path is not None:
        return best_path, round(best_delta / 60.0, 3), None
    reason = _classify_missing_target_frame(by_ts, target_ts, effective_tol_s, datetime.utcnow())
    return None, None, reason



def _interpolate_target_objects(by_ts: Dict[datetime, str],
                                 target_ts: datetime,
                                 max_gap_s: int) -> Optional[list]:
    """B295: Rekonstruiert eine Ziel-Objektliste durch lineare Interpolation
    zwischen den beiden real vorhandenen Radarframes, die target_ts einschliessen.

    Wird nur aufgerufen, wenn _find_target_frame keinen Frame innerhalb der
    adaptiven Toleranz gefunden hat (missing_due_to_tolerance). max_gap_s
    verhindert Interpolation über echte Ingest-Lücken hinweg. Objekte werden
    über 'id', ersatzweise 'cell_id', zwischen den Frames gepaart; nur Paare
    mit identischer ID/Cell-ID werden interpoliert.
    """
    before_ts = max((ts for ts in by_ts if ts <= target_ts), default=None)
    after_ts = min((ts for ts in by_ts if ts >= target_ts), default=None)
    if before_ts is None or after_ts is None or before_ts == after_ts:
        return None
    gap_s = (after_ts - before_ts).total_seconds()
    if gap_s <= 0 or gap_s > max_gap_s:
        return None
    frac = (target_ts - before_ts).total_seconds() / gap_s

    def _key(o: dict) -> str:
        return str(o.get("id") or o.get("cell_id") or "")

    before_objs = {_key(o): o for o in _load_objects(by_ts[before_ts]) if _key(o)}
    after_objs = {_key(o): o for o in _load_objects(by_ts[after_ts]) if _key(o)}

    interpolated = []
    for key, a_obj in after_objs.items():
        b_obj = before_objs.get(key)
        if b_obj is None:
            continue
        b_lat = _safe_float(b_obj.get("lat")); b_lon = _safe_float(b_obj.get("lon"))
        a_lat = _safe_float(a_obj.get("lat")); a_lon = _safe_float(a_obj.get("lon"))
        if None in (b_lat, b_lon, a_lat, a_lon):
            continue
        i_obj = dict(a_obj)
        i_obj["lat"] = b_lat + (a_lat - b_lat) * frac
        i_obj["lon"] = b_lon + (a_lon - b_lon) * frac
        i_obj["_interpolated_target"] = True
        interpolated.append(i_obj)
    return interpolated or None


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

    # B279: Lineage-aware Match VOR dem B247-Speed/Core-Gate. Wenn ein direkter
    # ID-Match am Speed/Core-Gate scheitert, aber die Lineage (parent_cell_id,
    # merged_from_cell_ids) den Zusammenhang erklärt, wird der Match trotzdem
    # akzeptiert — mit eigenem match_type statt NN-Fallback.
    def _lineage_values(value) -> List[str]:
        if value is None:
            return []
        if isinstance(value, (list, tuple, set)):
            return [str(x) for x in value]
        if isinstance(value, str) and "," in value:
            return [x.strip() for x in value.split(",") if x.strip()]
        return [str(value)]

    def _lineage_explains_match(obj: dict, matched: dict) -> Optional[str]:
        obj_id = str(obj.get("cell_id", obj.get("id", "")))
        matched_id = str(matched.get("cell_id", matched.get("id", "")))
        if str(matched.get("parent_cell_id", "")) == obj_id:
            return "lineage_split_child"
        merged_from = _lineage_values(obj.get("merged_from_cell_ids"))
        if matched_id in merged_from:
            return "lineage_merged_from"
        matched_merged_from = _lineage_values(matched.get("merged_from_cell_ids"))
        if obj_id in matched_merged_from:
            return "lineage_merged_from"
        if str(obj.get("parent_cell_id", "")) == matched_id:
            return "lineage_parent"
        return None

    # B247: ID-Match mit Speed-Gate + Core-Anforderung.
    # Besteht der Match die Validierung nicht, wird auf NN-Suche zurückgefallen statt
    # ein physikalisch unplausibler Treffer zu zählen (Merge-Inheritance-Schutz).
    id_match = next((o for o in target_objs if str(o.get("id")) == oid), None)
    if id_match is not None and id_match.get("lat") is not None and id_match.get("lon") is not None:
        d = _haversine_km(fc_lat, fc_lon, float(id_match["lat"]), float(id_match["lon"]))
        if _match_valid_b247(obj, id_match, horizon_min):
            return id_match, d, "id"
        lineage_reason = _lineage_explains_match(obj, id_match) if id_match else None
        if lineage_reason:
            debug_log(f"[MATCH][B279] {oid}: Speed/Core-Gate verworfen, aber Lineage erklärt Match ({lineage_reason}) — akzeptiert")
            return id_match, d, lineage_reason
        debug_log(
            f"[MATCH][B247] ID-Match {oid} verworfen: Speed/Core-Validierung fehlgeschlagen "
            f"(h={horizon_min}, match_dist={d:.1f} km) — NN-Fallback"
        )

    if cell_id:
        cell_match = next((o for o in target_objs if str(o.get("cell_id", o.get("id", ""))) == cell_id), None)
        if cell_match is not None and cell_match.get("lat") is not None and cell_match.get("lon") is not None:
            d = _haversine_km(fc_lat, fc_lon, float(cell_match["lat"]), float(cell_match["lon"]))
            if _match_valid_b247(obj, cell_match, horizon_min):
                return cell_match, d, "cell_id"
            lineage_reason = _lineage_explains_match(obj, cell_match) if cell_match else None
            if lineage_reason:
                debug_log(f"[MATCH][B279] {cell_id}: Speed/Core-Gate verworfen, aber Lineage erklärt Match ({lineage_reason}) — akzeptiert")
                return cell_match, d, lineage_reason
            debug_log(
                f"[MATCH][B247] cell_id-Match {cell_id} verworfen: Speed/Core-Validierung fehlgeschlagen "
                f"(h={horizon_min}) — NN-Fallback"
            )

    # B282: Lineage-Nachfolger koennen eine abweichende id/cell_id haben
    # (record_cell_split() vergibt neue cell_id + parent_cell_id an Kinder;
    # record_cell_merge() haelt nur die primaere cell_id, andere Eltern stehen
    # in merged_from_cell_ids). Diese Kandidaten wuerden vom id/cell_id-exakten
    # Match oben NIE gefunden. Deshalb hier eine eigene Lineage-Kandidatensuche
    # VOR dem generischen NN-Fallback, unabhaengig von id/cell_id-Gleichheit.
    lineage_candidate = None
    lineage_candidate_reason = None
    lineage_candidate_d = math.inf
    for cand in target_objs:
        if _is_synthetic_object(cand):
            continue
        lat = cand.get("lat")
        lon = cand.get("lon")
        if lat is None or lon is None:
            continue
        reason = _lineage_explains_match(obj, cand)
        if reason is None:
            continue
        d = _haversine_km(fc_lat, fc_lon, float(lat), float(lon))
        if d <= VERIFICATION_MAX_SEARCH_RADIUS_KM and d < lineage_candidate_d:
            lineage_candidate_d = d
            lineage_candidate = cand
            lineage_candidate_reason = reason
    if lineage_candidate is not None:
        debug_log(
            f"[MATCH][B282] {oid}/{cell_id}: Lineage-Nachfolger mit abweichender ID gefunden "
            f"({lineage_candidate_reason}, dist={lineage_candidate_d:.1f} km) — vor NN-Fallback akzeptiert"
        )
        return lineage_candidate, lineage_candidate_d, lineage_candidate_reason

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
        # B247: NN-Kandidaten ebenfalls auf Plausibilität prüfen
        if d < best_d and d <= VERIFICATION_MAX_SEARCH_RADIUS_KM and _match_valid_b247(obj, cand, horizon_min):
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
    return {"count": len(values), f"median_{prefix}_error_{unit}": round(_percentile(values, 50), 3), f"p90_{prefix}_error_{unit}": round(_percentile(values, 90), 3)}


def _accumulate_ml_shadow(by_mode, obj, horizon_min, matched, tol_km):
    """P53: bewertet den ML-Schatten (forecast_ml_*) gegen das Champion-Actual und
    bucht ihn AUSSCHLIESSLICH in by_mode['ml'] (Champion/global/Drift unveraendert).
    Liefert die Schatten-Distanz (km) oder None."""
    if matched is None:
        return None
    if obj.get(f"forecast_mode_{horizon_min}", obj.get("forecast_mode")) == "ml":
        return None
    _ml_lat = _safe_float(obj.get(f"forecast_ml_lat_{horizon_min}"))
    _ml_lon = _safe_float(obj.get(f"forecast_ml_lon_{horizon_min}"))
    if _ml_lat is None or _ml_lon is None:
        return None
    _a_lat = _safe_float(matched.get("lat"))
    _a_lon = _safe_float(matched.get("lon"))
    if _a_lat is None or _a_lon is None:
        return None
    d = _haversine_km(_ml_lat, _ml_lon, _a_lat, _a_lon)
    if d is None:
        return None
    b = by_mode.setdefault("ml", {"samples": 0, "verified": 0, "hits": 0, "missed": 0, "no_target_frame": 0, "frame_empty": 0, "sum_km": 0.0, "sum_km2": 0.0})
    b["samples"] += 1
    b["verified"] += 1
    b["sum_km"] += d
    b["sum_km2"] += d * d
    if d <= tol_km:
        b["hits"] += 1
    return d


def _direction_error_min_displacement_km() -> float:
    """B315: Runtime-ueberschreibbare Mindest-Ist-Verschiebung, unterhalb derer
    direction_error_deg/speed_error_kmh als geometrisches Rauschen gelten und aus
    der Aggregation ausgeklammert werden (siehe DIRECTION_ERROR_MIN_DISPLACEMENT_KM)."""
    if _runtime_cfg is not None:
        try:
            return float(_runtime_cfg.get("DIRECTION_ERROR_MIN_DISPLACEMENT_KM", DIRECTION_ERROR_MIN_DISPLACEMENT_KM))
        except Exception:
            pass
    return DIRECTION_ERROR_MIN_DISPLACEMENT_KM


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
    delivered_mode_counts: dict = {}
    by_source = {}
    by_match = {}
    direction_errors = []
    speed_errors = []
    details = []
    # B258: Bestehende Schlüssel laden — verhindert Duplikate bei Scheduler-Wiederholung.
    detail_keys_seen: Set[tuple] = _load_detail_keys(DETAILS_FILE, since_hours)

    def _bucket(store, key):
        k = str(key or "unknown")
        return store.setdefault(k, {"samples": 0, "verified": 0, "hits": 0, "missed": 0, "no_target_frame": 0, "frame_empty": 0, "sum_km": 0.0, "sum_km2": 0.0})


    def _mode_for(obj):
        return obj.get(f"forecast_mode_{horizon_min}", obj.get("forecast_mode"))

    def _source_for(obj):
        return obj.get(f"kinematic_source_{horizon_min}", obj.get("kinematic_source"))

    def _finish(store):
        out = {}
        for k, v in store.items():
            total = int(v.get("samples", 0)) + int(v.get("no_target_frame", 0)) + int(v.get("frame_empty", 0))
            ver = int(v.get("verified", 0))
            out[k] = {
                "samples": total, "verified": ver, "missed": int(v.get("missed", 0)),
                "no_target_frame": int(v.get("no_target_frame", 0)),
                "frame_empty": int(v.get("frame_empty", 0)),
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
        "frame_empty": 0,
        "id_lost": 0,
        "nn_rejected": 0,
        "hit_rate": None,
        "mae_km": None,
        "rmse_km": None,
        "mae_px": None,
        "rmse_x_px": None,
        "rmse_y_px": None,
        "since_hours": since_hours,
        "tolerance_km": VERIFICATION_TOLERANCE_KM,
        "by_forecast_mode": _finish(by_mode),
        "delivered_mode_counts": delivered_mode_counts,
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

    n_total = hits = verified = missed = no_target_frame = frame_empty = id_lost = nn_rejected = 0
    _nn_threshold = _nn_max_match_km(horizon_min)
    sum_km = sum_km2 = sum_abs_px = sum_sx2 = sum_sy2 = 0.0
    km_values: list = []  # B296: für robuste Median-Kennzahl neben der MAE
    for fpath, ts in fts:
        if ts < cutoff:
            continue
        objs = _load_objects(fpath)
        if not objs:
            continue
        target_ts = ts + timedelta(minutes=horizon_min)
        target_path, target_frame_delta_min, missing_target_frame_reason = _find_target_frame(by_ts, target_ts, VERIFICATION_TIME_TOLERANCE_S)

        # Anzahl Forecasts in diesem Quell-Frame (für no_target_frame-Buchhaltung)
        forecast_count_this_frame = sum(
            1 for o in objs
            if o.get(f"forecast_lat_{horizon_min}") is not None
            and o.get(f"forecast_lon_{horizon_min}") is not None
            and _is_real_forecast_object(o, horizon_min)
        )

        interpolated_objs = None
        if target_path is None and missing_target_frame_reason == "missing_due_to_tolerance":
            interpolated_objs = _interpolate_target_objects(by_ts, target_ts, VERIFICATION_INTERPOLATION_MAX_GAP_S)

        if target_path is None and interpolated_objs is None:
            no_target_frame += forecast_count_this_frame
            n_total += forecast_count_this_frame
            for _o in objs:
                if _o.get(f"forecast_lat_{horizon_min}") is not None and _o.get(f"forecast_lon_{horizon_min}") is not None and _is_real_forecast_object(_o, horizon_min):
                    _bucket(by_mode, _mode_for(_o))["no_target_frame"] += 1
                    _bucket(by_source, _source_for(_o))["no_target_frame"] += 1
                    _bucket(by_match, "none")["no_target_frame"] += 1
                    # B288: delivered_mode_counts zaehlt JEDEN real ausgelieferten
                    # Forecast, unabhaengig davon, ob spaeter ein Ziel-Frame zur
                    # Verifikation gefunden wurde. Sonst verschwinden Forecasts bei
                    # Horizont-Ende/Ingest-Luecken aus ml_usage_ratio (B284-Review).
                    delivered_mode_counts[_mode_for(_o)] = delivered_mode_counts.get(_mode_for(_o), 0) + 1
                    rec = _detail_record(_o, ts, target_ts, horizon_min, None, None, "none", True, False, horizon_min, target_frame_delta_min=target_frame_delta_min, missing_target_frame_reason=missing_target_frame_reason)
                    details.append(rec); _append_detail_once(DETAILS_FILE, rec, detail_keys_seen)
            continue

        # B295: Bei erfolgreicher Interpolation gibt es keinen einzelnen target_path;
        # target_objs stammt dann direkt aus der linearen Interpolation zwischen den
        # zwei umgebenden echten Radarframes (exakter Ziel-Zeitpunkt, delta=0).
        if interpolated_objs is not None:
            target_objs = interpolated_objs
            target_frame_delta_min = 0.0
        else:
            target_objs = [o for o in _load_objects(target_path) if not _is_synthetic_object(o)]
        if not target_objs:
            # B303: Radar-Frame wurde gefunden, zeigt aber 0 Zellen (Zelle real
            # aufgeloest oder Wetterlage beruhigt) -> KEIN Datenluecken-Fall.
            # Getrennt von no_target_frame gezaehlt, damit die Coverage-Diagnose
            # nicht faelschlich echte Radar-Ausfaelle/Luecken meldet.
            frame_empty += forecast_count_this_frame
            n_total += forecast_count_this_frame
            for _o in objs:
                if _o.get(f"forecast_lat_{horizon_min}") is not None and _o.get(f"forecast_lon_{horizon_min}") is not None and _is_real_forecast_object(_o, horizon_min):
                    _bucket(by_mode, _mode_for(_o))["frame_empty"] += 1
                    _bucket(by_source, _source_for(_o))["frame_empty"] += 1
                    _bucket(by_match, "frame_empty")["frame_empty"] += 1
                    # B288: siehe Kommentar im ersten no_target_frame-Zweig oben.
                    delivered_mode_counts[_mode_for(_o)] = delivered_mode_counts.get(_mode_for(_o), 0) + 1
                    rec = _detail_record(_o, ts, target_ts, horizon_min, None, None, "frame_empty", False, False, horizon_min, target_frame_delta_min=target_frame_delta_min, missing_target_frame_reason=missing_target_frame_reason, frame_empty=True)
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
            # B228: NN-Treffer jenseits der strengen Akzeptanzschwelle = Fehlzuordnung.
            if _is_nn_rejected(_match_src, matched, dist_km, _nn_threshold):
                _match_src = "nn_rejected"
            n_total += 1
            _bm = _bucket(by_mode, _mode_for(obj)); _bs = _bucket(by_source, _source_for(obj)); _bt = _bucket(by_match, _match_type(_match_src))
            _bm["samples"] += 1; _bs["samples"] += 1; _bt["samples"] += 1
            # B284: separater, schatten-freier Zaehler der TATSAECHLICH ausgelieferten
            # Modi. _mode_for(obj) ist der real ausgelieferte forecast_mode — im
            # Gegensatz zu by_mode["ml"], das durch _accumulate_ml_shadow() zusaetzlich
            # Schatten-Bewertungen fuer kinematic_fallback-Forecasts enthaelt.
            delivered_mode_counts[_mode_for(obj)] = delivered_mode_counts.get(_mode_for(obj), 0) + 1
            ex = ey = None

            if _match_src == "nn_rejected":
                nn_rejected += 1
                _bm["missed"] += 1; _bs["missed"] += 1; _bt["missed"] += 1
                # B232: keine Distanz als forecast_error_km/match_distance_km schreiben,
                # sonst zaehlt die Fehler-Diagnose die verworfene Zelle faelschlich als verifiziert.
                rec = _detail_record(obj, ts, target_ts, horizon_min, None, None, "nn_rejected", False, False, horizon_min, target_frame_delta_min=target_frame_delta_min)
                details.append(rec); _append_detail_once(DETAILS_FILE, rec, detail_keys_seen)
                continue

            if matched is None:
                missed += 1
                _bm["missed"] += 1; _bs["missed"] += 1; _bt["missed"] += 1
                rec = _detail_record(obj, ts, target_ts, horizon_min, None, None, _match_src, False, False, horizon_min, target_frame_delta_min=target_frame_delta_min)
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
            km_values.append(dist_km)
            verified += 1
            _bm["verified"] += 1; _bs["verified"] += 1; _bt["verified"] += 1
            _bm["sum_km"] += dist_km; _bs["sum_km"] += dist_km; _bt["sum_km"] += dist_km
            _bm["sum_km2"] += dist_km * dist_km; _bs["sum_km2"] += dist_km * dist_km; _bt["sum_km2"] += dist_km * dist_km
            rec = _detail_record(obj, ts, target_ts, horizon_min, matched, dist_km, _match_src, False, False, horizon_min, ex, ey, target_frame_delta_min=target_frame_delta_min)
            # B315: Bei quasi-stationaeren Zellen (actual_displacement_km unter
            # Schwelle) ist die "Ist-Richtung" geometrisch instabil und erzeugt
            # Schein-Richtungs-/Geschwindigkeitsfehler. forecast_error_km/MAE bleibt
            # unveraendert vollstaendig erfasst; nur Richtung/Geschwindigkeit werden
            # aus der Aggregation ausgeklammert, damit sie die Drift-Metrik nicht
            # verzerren. rec selbst behaelt die Rohwerte (keine Datenverfaelschung).
            _ac_disp_km = rec.get("actual_displacement_km")
            _stationary_actual = _ac_disp_km is not None and _ac_disp_km < _direction_error_min_displacement_km()
            if not _stationary_actual:
                if rec.get("direction_error_deg") is not None: direction_errors.append(float(rec["direction_error_deg"]))
                if rec.get("speed_error_kmh") is not None: speed_errors.append(float(rec["speed_error_kmh"]))
            details.append(rec); _append_detail_once(DETAILS_FILE, rec, detail_keys_seen)
            if dist_km <= VERIFICATION_TOLERANCE_KM:
                hits += 1
                _bm["hits"] += 1; _bs["hits"] += 1; _bt["hits"] += 1
            # P53: ML-Shadow-Scoring — Challenger gegen dasselbe Actual, nur by_mode["ml"].
            _accumulate_ml_shadow(by_mode, obj, horizon_min, matched, VERIFICATION_TOLERANCE_KM)

    if n_total == 0:
        debug_log(f"[ACCURACY] horizon=+{horizon_min}m: 0 verifizierbare Samples in den letzten {since_hours}h")
        return base

    # P24: coverage_rate = Anteil verifizierbarer Forecasts an allen.
    # Hohe hit_rate ist nur aussagekräftig wenn coverage_rate hoch ist.
    # coverage_rate < 0.3 → Metriken unzuverlässig (zu viele not_found frames).
    _coverage = round(verified / n_total, 4) if n_total > 0 else None

    _mt_counts = {k: int(v.get("samples", 0)) for k, v in by_match.items()}
    debug_log(
        f"[ACCURACY][MATCH] h=+{horizon_min}m match_types={_mt_counts} "
        f"nn_rejected={nn_rejected} (NN-Akzeptanz {_nn_threshold:.1f} km)"
    )

    return {
        "horizon": horizon_min,
        "samples": n_total,
        "hits": hits,
        "verified": verified,
        "missed": missed,
        "no_target_frame": no_target_frame,
        "frame_empty": frame_empty,
        "id_lost": id_lost,
        "nn_rejected": nn_rejected,
        "hit_rate": round(hits / verified, 4) if verified else None,
        "coverage_rate": _coverage,          # verified / n_total
        "mae_km": round(sum_km / verified, 3) if verified else None,
        # B296: Median neben MAE — einzelne lineage-lose NN-Ausreisser sollen
        # die Horizont-Bewertung nicht dominieren (Datenbefund WX-20260703-0002).
        "median_km": round(_percentile(km_values, 50), 3) if km_values else None,
        "rmse_km": round(math.sqrt(sum_km2 / verified), 3) if verified else None,
        "mae_px": round(sum_abs_px / verified, 2) if verified else None,
        "rmse_x_px": round(math.sqrt(sum_sx2 / verified), 2) if verified else None,
        "rmse_y_px": round(math.sqrt(sum_sy2 / verified), 2) if verified else None,
        "since_hours": since_hours,
        "tolerance_km": VERIFICATION_TOLERANCE_KM,
        "by_forecast_mode": _finish(by_mode),
        "delivered_mode_counts": delivered_mode_counts,
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
    summary["delivered_mode_counts"] = {str(r["horizon"]): r.get("delivered_mode_counts", {}) for r in rows}
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


def get_runtime_kinematic_mae_by_horizon(min_samples: int = 20) -> dict:
    """B277: Liefert je Horizont die jüngste, ausreichend abgesicherte reale
    Betriebs-Kinematik-MAE aus accuracy_history.jsonl (breakdown_by_forecast_mode).
    Einzige Quelle der Wahrheit für Runtime-Gate UND Modell-Promotion.
    Rückgabe: {"10": {"kinematic_mae": float, "kinematic_samples": int}, ...}
    """
    path = os.path.join(SAVE_PATHS.get("evaluation", "train_data/evaluation").rstrip("/"), "accuracy_history.jsonl")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
    except Exception as exc:
        debug_log(f"[BASELINE][B277] accuracy_history nicht lesbar: {exc}")
        return {}
    out = {}
    for rec in reversed(rows):
        modes_by_h = rec.get("breakdown_by_forecast_mode") or {}
        if not isinstance(modes_by_h, dict):
            continue
        for h, modes in modes_by_h.items():
            try:
                key = str(int(float(h)))
            except Exception:
                continue
            if key in out or not isinstance(modes, dict):
                continue
            kin_candidates = [modes.get("kinematic"), modes.get("kinematic_fallback")]
            kin_stats = next((m for m in kin_candidates if isinstance(m, dict) and m.get("mae_km") is not None), None)
            if not kin_stats:
                continue
            kin_n = int(kin_stats.get("verified", kin_stats.get("samples", 0)) or 0)
            if kin_n < min_samples:
                continue
            kin_mae = _safe_float(kin_stats.get("mae_km"))
            if kin_mae and kin_mae > 0:
                out[key] = {"kinematic_mae": kin_mae, "kinematic_samples": kin_n}
    return out


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


def verification_coverage_by_horizon(history: list, horizons: list) -> dict:
    """P69: Anteil verifizierbarer (nicht no_target_frame) Forecasts je Horizont.
    B283-Fix: `samples` in breakdown_by_forecast_mode enthaelt bereits
    no_target_frame (siehe _finish() in evaluate_for_horizon: total = samples +
    no_target_frame VOR dem Persistieren). Hier NICHT erneut addieren, sonst
    Doppelzaehlung und kuenstlich niedrige Coverage (z.B. 8/12 statt 8/10)."""
    out = {}
    for h in horizons:
        hk = str(int(h))
        total = verified = 0
        for rec in history:
            modes = (rec.get("breakdown_by_forecast_mode") or {}).get(hk, {})
            if not isinstance(modes, dict):
                continue
            for stats in modes.values():
                if not isinstance(stats, dict):
                    continue
                total += int(stats.get("samples", 0) or 0)
                verified += int(stats.get("verified", stats.get("samples", 0)) or 0)
        out[hk] = round(verified / total, 4) if total else None
    return out


def ml_quality_series(history, horizons):
    """P54: Champion(Kinematik)- vs. Challenger(ML)-MAE je Horizont ueber die Zeit,
    aus breakdown_by_forecast_mode der Accuracy-History. Liefert
    {str(h): [{"idx","ts","champion_mae_km","challenger_mae_km","challenger_samples"}]}."""
    series = {str(int(h)): [] for h in (horizons or [])}
    for i, rec in enumerate(history or []):
        bd = rec.get("breakdown_by_forecast_mode") or {}
        ts = rec.get("timestamp_utc")
        for h in (horizons or []):
            hk = str(int(h))
            modes = bd.get(hk) or {}
            ml = modes.get("ml") if isinstance(modes.get("ml"), dict) else {}
            kin = modes.get("kinematic_fallback") if isinstance(modes.get("kinematic_fallback"), dict) else {}
            if not kin:
                kin = modes.get("kinematic") if isinstance(modes.get("kinematic"), dict) else {}
            series[hk].append({
                "idx": i + 1,
                "ts": ts,
                "champion_mae_km": kin.get("mae_km"),
                "challenger_mae_km": ml.get("mae_km"),
                "challenger_samples": ml.get("verified", 0),
            })
    return series


if __name__ == "__main__":
    from config import ML_FORECAST_HORIZONS_MIN
    result = evaluate_all(ML_FORECAST_HORIZONS_MIN, 24)
    print(json.dumps(result, indent=2, ensure_ascii=False))
