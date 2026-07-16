"""Eigenständige Hydro-Flood-ML-/Fallback-Bewertung.

Der Modulpfad ist bewusst getrennt vom Zellbewegungs-ML: er liest keine
Bewegungsmodell-Artefakte und schreibt ausschließlich unter train_data/hydro
bzw. train_data/models/hydro_flood.
"""
from __future__ import annotations

import hashlib, json, math, os, pickle, tempfile, sqlite3, shutil, threading
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import config
import runtime_config

HYDRO_HISTORY_PATH = Path("train_data/hydro/live/hydro_history.jsonl")
HYDRO_ML_DIR = Path("train_data/hydro/ml")
HYDRO_DATASET_PATH = HYDRO_ML_DIR / "hydro_flood_legacy_q_dataset.jsonl"
HYDRO_PENDING_SAMPLES_PATH = HYDRO_ML_DIR / "hydro_flood_pending_samples.jsonl"
HYDRO_DATASET_JSONL_PATH = HYDRO_ML_DIR / "hydro_flood_dataset.jsonl"
HYDRO_TRAINING_META_PATH = HYDRO_ML_DIR / "hydro_flood_training_meta.json"
HYDRO_ACCURACY_HISTORY_PATH = HYDRO_ML_DIR / "hydro_flood_accuracy_history.jsonl"
HYDRO_RISK_PATH = Path("train_data/hydro/impact/latest_hydro_flood_risk.json")
HYDRO_MODEL_CURRENT_DIR = Path("train_data/models/hydro_flood/current")
MIN_TRAINING_SAMPLES = int(os.getenv("HYDRO_FLOOD_ML_MIN_SAMPLES", "20"))
FEATURE_SCHEMA_VERSION = "b411_live_catchment_v3"
HYDRO_SAMPLE_DB_PATH = HYDRO_ML_DIR / "hydro_flood_samples.sqlite3"
_DEFAULT_HYDRO_SAMPLE_DB_PATH = HYDRO_SAMPLE_DB_PATH
_DEFAULT_HYDRO_DATASET_JSONL_PATH = HYDRO_DATASET_JSONL_PATH
HYDRO_MODEL_ROOT_DIR = Path("train_data/models/hydro_flood")
HYDRO_MODEL_CANDIDATES_DIR = HYDRO_MODEL_ROOT_DIR / "candidates"
HYDRO_MODEL_PREVIOUS_DIR = HYDRO_MODEL_ROOT_DIR / "previous"
HYDRO_MODEL_HISTORY_DIR = HYDRO_MODEL_ROOT_DIR / "history"
HYDRO_MODEL_FILENAME = "model.joblib"
HYDRO_FLOOD_ML_FEATURES = list(getattr(config, "HYDRO_FLOOD_ML_FEATURES", [
    "current_q_m3s", "current_q_ratio_threshold", "current_q_distance_to_threshold_m3s",
    "q_trend_delta_m3s", "q_trend_reference_window_min", "already_rising_flag",
    "catchment_area_km2", "upstream_catchment_count", "routing_tau_min",
    "contributing_cell_count", "current_cell_count", "incoming_cell_count",
    "total_rain_volume_m3", "total_runoff_volume_m3", "total_dwell_time_min",
    "max_cell_dwell_time_min", "effective_overlap_area_km2", "overlap_area_time_km2_min",
    "cell_catchment_area_km2_sum", "rain_rate_mm_h_max", "rain_rate_mm_h_mean",
    "rain_rate_mm_h_area_weighted", "first_entry_offset_min", "last_exit_offset_min",
    "physical_predicted_q_delta_m3s", "physical_predicted_q_max_m3s", "data_age_min",
]))

HYDRO_OPTIONAL_FEATURES = {
    "current_q_ratio_threshold", "current_q_distance_to_threshold_m3s",
    "q_trend_delta_m3s", "q_trend_reference_window_min",
    "first_entry_offset_min", "last_exit_offset_min", "data_age_min",
}
HYDRO_MISSING_INDICATOR_FEATURES = [
    "threshold_available_flag", "q_trend_available_flag",
    "cell_entry_available_flag", "data_age_available_flag",
]
HYDRO_REQUIRED_FEATURES = [f for f in HYDRO_FLOOD_ML_FEATURES if f not in HYDRO_OPTIONAL_FEATURES]
HYDRO_FEATURE_IMPUTATION = {
    "current_q_ratio_threshold": 0.0,
    "current_q_distance_to_threshold_m3s": 0.0,
    "q_trend_delta_m3s": 0.0,
    "q_trend_reference_window_min": 0.0,
    "first_entry_offset_min": 0.0,
    "last_exit_offset_min": 0.0,
    "data_age_min": 0.0,
}
for _flag in HYDRO_MISSING_INDICATOR_FEATURES:
    if _flag not in HYDRO_FLOOD_ML_FEATURES:
        HYDRO_FLOOD_ML_FEATURES.append(_flag)

SOURCE_PRIORITY = {"measured": 0, "nowcast": 1, "radar_derived": 2, "cell_derived": 3, "proxy": 4, "missing": 9}
QUALITY_SCORE = {"high": 1.0, "medium": 0.7, "low": 0.4, "missing": 0.0}
INTENSITY_MM = {"heavy": 8.0, "strong": 12.0, "rot": 12.0, "red": 12.0, "severe": 20.0, "violett": 25.0, "purple": 25.0, "extreme": 35.0}
SAMPLE_KIND_LIVE = "live_catchment_snapshot"
SAMPLE_KIND_LEGACY = "legacy_q_only"
_MODEL_CACHE_LOCK = threading.RLock()
_MODEL_CACHE: dict[str, Any] = {}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _dt(v):
    if not v: return None
    try: return datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception: return None


def _atomic_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        try:
            if os.path.exists(tmp): os.unlink(tmp)
        except Exception: pass


def _read_json(path: Path, default: Any):
    try: return json.loads(path.read_text(encoding="utf-8"))
    except Exception: return default


def _path_mtime(path: Path) -> float | None:
    try: return path.stat().st_mtime
    except OSError: return None


def _hash_obj(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()[:16]

def _objects_signature(cells: list[dict] | None) -> dict:
    items = []
    for c in cells or []:
        if not isinstance(c, dict):
            continue
        fc = {k: c.get(k) for k in c.keys() if str(k).startswith(("forecast_lat_", "forecast_lon_", "forecast_mode_"))}
        polygon = c.get("contour_geo") or c.get("polygon_geo") or c.get("geo_contour") or c.get("geometry")
        items.append({
            "id": c.get("id") or c.get("cell_id"),
            "ts": c.get("timestamp") or c.get("source_timestamp") or c.get("last_seen"),
            "rain_rate": c.get("nowcast_rain_rate_1h") or c.get("rain_rate_mm_h") or c.get("precip_rate_mm_h") or c.get("nowcast_rr_mm15"),
            "polygon_hash": _hash_obj(polygon),
            "forecast_hash": _hash_obj(fc),
            "status": {"inactive": c.get("inactive"), "expired": c.get("expired"), "tracking_state": c.get("tracking_state"), "silent_tracking": c.get("silent_tracking"), "missing": c.get("missing")},
        })
    digest = _hash_obj(items)
    return {"count": len(items), "hash": digest, "items": items}

def is_hydro_relevant_cell(cell: dict) -> bool:
    if not isinstance(cell, dict):
        return False
    if not (cell.get("id") or cell.get("cell_id") or cell.get("track_id")):
        return False
    state = str(cell.get("tracking_state") or "").lower()
    if cell.get("inactive") is True or cell.get("expired") is True or state == "inactive_rain" or cell.get("silent_tracking") is True:
        return False
    if _f(cell.get("missing"), 0) and state != "reactivated":
        return False
    try:
        import hydro_impact
        poly = hydro_impact._cell_polygon(cell)
        if poly is None or getattr(poly, "is_empty", True):
            contour = cell.get("contour_geo") or cell.get("polygon_geo") or cell.get("geo_contour")
            if not (isinstance(contour, list) and len(contour) >= 3):
                return False
    except Exception:
        # In Minimalumgebungen ohne Shapely reicht eine vorhandene Kontur als
        # Strukturprüfung; der Produktionspfad validiert mit Shapely.
        contour = cell.get("contour_geo") or cell.get("polygon_geo") or cell.get("geo_contour")
        if not (isinstance(contour, list) and len(contour) >= 3):
            return False
    return True

def _parse_frame_timestamp(data: Any, path: Path) -> datetime | None:
    candidates = []
    if isinstance(data, dict):
        for key in ("timestamp", "generated_at", "frame_time", "created_at", "fetched_at", "source_timestamp"):
            if data.get(key):
                candidates.append(data.get(key))
    candidates.append(path.stem)
    for raw in candidates:
        text = str(raw)
        dt = _dt(text)
        if dt:
            return dt
        for fmt in ("%Y%m%d_%H%M%S", "%Y%m%d%H%M%S", "%Y-%m-%d_%H-%M-%S", "%Y-%m-%dT%H-%M-%S"):
            try:
                from zoneinfo import ZoneInfo
                return datetime.strptime(text[:len(datetime.now().strftime(fmt))], fmt).replace(tzinfo=ZoneInfo("Europe/Vienna")).astimezone(timezone.utc)
            except Exception:
                continue
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    except OSError:
        return None


def load_latest_cell_frame() -> tuple[list[dict] | None, dict]:
    obj_dir = Path(config.SAVE_PATHS.get("objects", "train_data/objects"))
    max_age = _cfg_int("HYDRO_CELL_FRAME_MAX_AGE_MIN", 30, 5, 180)
    try:
        files = sorted(obj_dir.glob("*.json"))
        if not files:
            return None, {"status": "missing", "cell_frame_status": "missing", "path": None, "max_age_min": max_age}
        path = files[-1]
        data = json.loads(path.read_text(encoding="utf-8"))
        cells = data.get("objects") if isinstance(data, dict) else data
        if not isinstance(cells, list):
            return None, {"status": "invalid", "cell_frame_status": "invalid", "path": str(path), "max_age_min": max_age}
        ts = _parse_frame_timestamp(data, path)
        age = (datetime.now(timezone.utc) - ts).total_seconds()/60.0 if ts else None
        st = path.stat()
        if age is not None and age > max_age:
            return None, {"status": "stale", "cell_frame_status": "stale", "path": str(path), "frame_timestamp": ts.isoformat().replace("+00:00","Z") if ts else None, "frame_age_min": round(age, 3), "max_age_min": max_age, "mtime_ns": st.st_mtime_ns, "size": st.st_size}
        active = [c for c in cells if is_hydro_relevant_cell(c)]
        return active, {"status": "ok", "cell_frame_status": "ok", "path": str(path), "mtime_ns": st.st_mtime_ns, "size": st.st_size, "frame_timestamp": ts.isoformat().replace("+00:00","Z") if ts else None, "frame_age_min": round(age,3) if age is not None else None, "max_age_min": max_age, "cell_count": len(active), "raw_cell_count": len(cells)}
    except Exception as exc:
        return None, {"status": "error", "cell_frame_status": "error", "error": f"{type(exc).__name__}: {exc}"}


def _trend_cache_signature() -> dict:
    return {
        "history_mtime": _path_mtime(HYDRO_HISTORY_PATH),
        "min_delta_m3s": runtime_config.get("HYDRO_TREND_MIN_DELTA_M3S", getattr(config, "HYDRO_TREND_MIN_DELTA_M3S", 0.02)),
        "min_delta_rel_pct": runtime_config.get("HYDRO_TREND_MIN_DELTA_REL_PCT", getattr(config, "HYDRO_TREND_MIN_DELTA_REL_PCT", 0.03)),
    }


def flood_risk_input_hash(live: dict | None = None, cells: list[dict] | None = None) -> str:
    overrides = runtime_config.get("HYDRO_STATION_OVERRIDES", {}) or {}
    live_sig = {
        "fetched_at": (live or {}).get("fetched_at"),
        "mtime": _path_mtime(getattr(__import__("hydro_fetch"), "LATEST_FILE", Path("train_data/hydro/live/latest_hydro.json"))),
        "stations": [
            {"station_id": str(s.get("station_id") or ""), "q_m3s": s.get("q_m3s"), "data_age_min": s.get("data_age_min"), "measured_at": s.get("measured_at")}
            for s in ((live or {}).get("stations") or []) if isinstance(s, dict)
        ],
    }
    try:
        import hydro_impact
        catch_sig = hydro_impact.catchment_file_signature()
    except Exception:
        catch_sig = {}
    model_meta = _read_json(HYDRO_MODEL_CURRENT_DIR / "metadata.json", {})
    hydro_cfg = {k: runtime_config.get(k, getattr(config, k, None)) for k in ("HYDRO_FORECAST_SAMPLE_STEP_MIN", "HYDRO_FALLBACK_ROUTING_TAU_MIN", "HYDRO_FORECAST_RUNOFF_COEFF", "HYDRO_FORECAST_ROUTING_ATTENUATION", "HYDRO_MIN_OVERLAP_AREA_KM2", "HYDRO_MIN_OVERLAP_RATIO_CELL", "ML_FORECAST_HORIZONS_MIN")}
    payload = {"live": live_sig, "station_thresholds": overrides, "global_threshold": runtime_config.get("HYDRO_MAP_MARK_Q_M3S", getattr(config, "HYDRO_MAP_MARK_Q_M3S", None)), "objects": _objects_signature(cells), "q_trend": _trend_cache_signature(), "catchments": catch_sig, "hydro_config": hydro_cfg, "model": {"schema": model_meta.get("feature_schema_version"), "trained_at": model_meta.get("trained_at"), "promoted": model_meta.get("promoted"), "signature": model_signature(HYDRO_MODEL_CURRENT_DIR)}}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def is_flood_risk_cache_valid(doc: dict | None, live: dict | None = None, cells: list[dict] | None = None) -> bool:
    if not isinstance(doc, dict) or not doc.get("input_hash") or doc.get("payload_scope") != "public":
        return False
    risk_mtime = _path_mtime(HYDRO_RISK_PATH)
    hydro_mtime = _path_mtime(getattr(__import__("hydro_fetch"), "LATEST_FILE", Path("train_data/hydro/live/latest_hydro.json")))
    if risk_mtime is not None and hydro_mtime is not None and hydro_mtime > risk_mtime:
        return False
    return doc.get("input_hash") == flood_risk_input_hash(live=live, cells=cells)


def _f(v, default=None):
    try:
        if v in (None, "", "-"): return default
        x = float(v)
        return x if math.isfinite(x) else default
    except Exception: return default


def append_hydro_history(live_doc: dict) -> int:
    """Persistiert nur ohnehin geladene Live-Hydro-Daten als q_m3s-Historie."""
    if not isinstance(live_doc, dict): return 0
    fetched_at = live_doc.get("fetched_at") or _now()
    source = live_doc.get("source") or "hydro_live"
    notice = live_doc.get("raw_data_notice")
    rows = []
    fetched_dt = _dt(fetched_at) or datetime.now(timezone.utc)
    for s in live_doc.get("stations") or []:
        if not isinstance(s, dict): continue
        measured_at = s.get("measured_at") or fetched_at
        md = _dt(measured_at)
        age = max(0.0, (fetched_dt - md).total_seconds()/60.0) if md else None
        q = _f(s.get("q_m3s"))
        rows.append({"fetched_at": fetched_at, "measured_at": measured_at, "station_id": str(s.get("station_id") or ""), "station_name": s.get("name") or s.get("station_name") or "", "river": s.get("river") or "", "lat": _f(s.get("lat")), "lon": _f(s.get("lon")), "q_m3s": q, "q_missing": q is None, "data_age_min": age, "source": source, "raw_data_notice": notice, "w_cm": _f(s.get("w_cm")), "hq1": _f(s.get("hq1")), "hq10": _f(s.get("hq10")), "hq30": _f(s.get("hq30")), "hq100": _f(s.get("hq100"))})
    if rows:
        HYDRO_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with HYDRO_HISTORY_PATH.open("a", encoding="utf-8") as f:
            for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(rows)



def _runtime_float(name: str, default: float) -> float:
    try:
        return float(runtime_config.get(name, getattr(config, name, default)))
    except (TypeError, ValueError):
        return default


def _tail_history_rows(path: Path | None = None, max_bytes: int = 400 * 1024) -> list[dict]:
    path = path or HYDRO_HISTORY_PATH
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
                f.readline()
            raw = f.read().decode("utf-8", errors="ignore")
    except OSError:
        return []
    rows = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def load_q_trend_history() -> dict[str, list[dict]]:
    """Laedt Q-Historie aus dem Byte-begrenzten Datei-Tail ohne Wanduhr-Cutoff.

    B270: Die Trendfenster werden spaeter in _q_trend_fields() relativ zum
    Messzeitpunkt der aktuellen Live-Station ausgewertet. Ein Filter gegen
    datetime.now() wuerde bei verzoegerter Auswertung oder Live-Daten mit Lag
    genau die dafuer relevante Historie faelschlich ausschliessen.
    """
    out: dict[str, list[dict]] = {}
    for row in _tail_history_rows():
        sid = str(row.get("station_id") or "")
        q = _f(row.get("q_m3s"))
        ts = _dt(row.get("measured_at") or row.get("fetched_at"))
        if not sid or q is None or ts is None:
            continue
        out.setdefault(sid, []).append({"ts": ts, "q_m3s": q})
    for rows in out.values():
        rows.sort(key=lambda r: r["ts"])
    return out


def _q_trend_fields(sid: str, current_q: float | None, current_ts: str | None, trend_history: dict[str, list[dict]] | None) -> dict:
    fields = {"current_q_trend_10min": None, "current_q_trend_30min": None, "current_q_trend_60min": None, "q_trend_per_hour": None, "already_rising_flag": False, "q_trend_status": "insufficient_history", "q_trend_delta_m3s": None, "q_trend_reference_window_min": None}
    ts = _dt(current_ts)
    rows = (trend_history or {}).get(str(sid), [])
    if current_q is None or ts is None or not rows:
        return fields
    tol = timedelta(minutes=5)
    best_by_window = {}
    for minutes in (10, 30, 60):
        target = ts - timedelta(minutes=minutes)
        candidates = [r for r in rows if abs(r["ts"] - target) <= tol]
        if not candidates:
            continue
        ref = min(candidates, key=lambda r: abs(r["ts"] - target))
        delta = round(float(current_q) - float(ref["q_m3s"]), 3)
        fields[f"current_q_trend_{minutes}min"] = delta
        best_by_window[minutes] = (delta, ref["q_m3s"])
    if not best_by_window:
        return fields
    ref_min = max(best_by_window)
    delta, ref_q = best_by_window[ref_min]
    fields["q_trend_delta_m3s"] = delta
    fields["q_trend_reference_window_min"] = ref_min
    fields["q_trend_per_hour"] = round(delta * (60.0 / ref_min), 3)
    min_abs = _runtime_float("HYDRO_TREND_MIN_DELTA_M3S", 0.02)
    min_rel_pct = _runtime_float("HYDRO_TREND_MIN_DELTA_REL_PCT", 0.03)
    rel_pct = abs(delta) / abs(ref_q) * 100.0 if ref_q not in (None, 0) else 0.0
    significant = abs(delta) >= min_abs or rel_pct >= min_rel_pct
    if significant and delta > 0:
        fields["q_trend_status"] = "rising"
        fields["already_rising_flag"] = True
    elif significant and delta < 0:
        fields["q_trend_status"] = "falling"
    else:
        fields["q_trend_status"] = "stable"
    return fields

def _threshold(station: dict) -> tuple[float|None, str]:
    val = _f(station.get("mark_q_m3s"))
    if val is not None: return val, "station_override"
    fallback = runtime_config.get("HYDRO_MAP_MARK_Q_M3S", getattr(config, "HYDRO_MAP_MARK_Q_M3S", None))
    val = _f(fallback)
    if val is not None: return val, "global_fallback"
    return None, "missing"


def _rate_with_source(cell: dict) -> tuple[float | None, str, str]:
    for k in ("nowcast_rain_rate_1h", "rain_rate_mm_h", "precip_rate_mm_h"):
        v = _f(cell.get(k))
        if v is not None:
            return max(0.0, v), k, "numeric"
    rr15 = _f(cell.get("nowcast_rr_mm15"))
    if rr15 is not None:
        return max(0.0, rr15 * 4.0), "nowcast_rr_mm15*4", "numeric"
    label = str(cell.get("intensity") or cell.get("intensity_label") or "").lower()
    if label in INTENSITY_MM:
        return INTENSITY_MM[label], f"intensity_proxy:{label}", "proxy"
    return None, "missing", "missing"


def _rate(cell: dict) -> float:
    return _rate_with_source(cell)[0] or 0.0


def _cfg_float(name: str, default: float, lo: float | None = None, hi: float | None = None) -> float:
    val = _runtime_float(name, default)
    if lo is not None: val = max(lo, val)
    if hi is not None: val = min(hi, val)
    return val


def _cfg_int(name: str, default: int, lo: int, hi: int) -> int:
    try: val = int(runtime_config.get(name, getattr(config, name, default)))
    except Exception: val = default
    return max(lo, min(hi, val))


def _cell_center(cell: dict, poly=None) -> tuple[float | None, float | None]:
    lat = _f(cell.get("lat") or cell.get("center_lat") or cell.get("centroid_lat"))
    lon = _f(cell.get("lon") or cell.get("center_lon") or cell.get("centroid_lon"))
    if lat is not None and lon is not None:
        return lat, lon
    if poly is not None and hasattr(poly, "centroid") and not poly.is_empty:
        return float(poly.centroid.y), float(poly.centroid.x)
    return None, None


def _forecast_points(cell: dict, poly) -> list[dict]:
    base_lat, base_lon = _cell_center(cell, poly)
    pts = [{"offset_min": 0, "lat": base_lat, "lon": base_lon, "mode": "current"}]
    try:
        horizons = sorted({int(h) for h in runtime_config.get("ML_FORECAST_HORIZONS_MIN", getattr(config, "ML_FORECAST_HORIZONS_MIN", [10,20,30,40,60]))})
    except Exception:
        horizons = [10,20,30,40,60]
    for h in horizons:
        lat = _f(cell.get(f"forecast_lat_{h}")); lon = _f(cell.get(f"forecast_lon_{h}"))
        if lat is not None and lon is not None:
            pts.append({"offset_min": h, "lat": lat, "lon": lon, "mode": cell.get(f"forecast_mode_{h}") or "forecast"})
    return [p for p in pts if p.get("lat") is not None and p.get("lon") is not None]


def _interp_track(points: list[dict], step: int) -> list[dict]:
    if not points: return []
    points = sorted(points, key=lambda p: p["offset_min"])
    out=[]
    for a,b in zip(points, points[1:]):
        span=max(1, int(b["offset_min"]-a["offset_min"]))
        for off in range(int(a["offset_min"]), int(b["offset_min"]), step):
            f=(off-a["offset_min"])/span
            out.append({"offset_min": off, "lat": a["lat"]+(b["lat"]-a["lat"])*f, "lon": a["lon"]+(b["lon"]-a["lon"])*f, "mode": a.get("mode") if off==a["offset_min"] else f"interpolated:{a.get('mode')}->{b.get('mode')}"})
    out.append(points[-1])
    return out


def _hit_intervals(offsets: list[int], step: int) -> list[dict]:
    if not offsets:
        return []
    offs=sorted(set(int(o) for o in offsets))
    intervals=[]; start=prev=offs[0]
    for off in offs[1:]:
        if off - prev <= step:
            prev=off; continue
        intervals.append({"entry_offset_min": start, "exit_offset_min": prev + step, "duration_min": prev - start + step})
        start=prev=off
    intervals.append({"entry_offset_min": start, "exit_offset_min": prev + step, "duration_min": prev - start + step})
    return intervals

def _bbox_from_points(points):
    try:
        xs=[float(pt[0]) for pt in points]; ys=[float(pt[1]) for pt in points]
        return [min(xs), min(ys), max(xs), max(ys)]
    except Exception:
        return None

def _bbox_intersection(a,b):
    if not a or not b: return None
    w=max(a[0],b[0]); e=min(a[2],b[2]); south=max(a[1],b[1]); n=min(a[3],b[3])
    return [w,south,e,n] if w < e and south < n else None

def _bbox_area_approx_km2(bb):
    if not bb: return 0.0
    return max(0.0, (bb[2]-bb[0]) * (bb[3]-bb[1]) * 111.0 * 111.0)

def _precip_from_cells_bbox_fallback(station: dict, cells: list[dict]) -> dict:
    sid=str(station.get("station_id") or "")
    q0=_f(station.get("q_m3s") or station.get("current_q_m3s"),0.0) or 0.0
    try:
        import hydro_impact
        cdiag=hydro_impact.catchment_diagnostics(sid)
        item=hydro_impact.load_station_catchment_index().get(sid)
    except Exception:
        cdiag={"catchment_geometry_available": False, "catchment_geometry_status":"missing", "catchment_area_geometry_km2": None}; item=None
    if not item and any(isinstance(c, dict) and isinstance(c.get("_hydro_overlap"), dict) for c in cells or []):
        cdiag={"catchment_geometry_available": True, "catchment_geometry_status":"cached_overlap", "catchment_area_geometry_km2": 1.0}
    catch_bb=(item or {}).get("bbox")
    geom=(item or {}).get("geometry")
    if not catch_bb and isinstance(geom, list):
        pts=geom[0] if geom and isinstance(geom[0], list) and geom and geom[0] and isinstance(geom[0][0], (list, tuple)) else geom
        catch_bb=_bbox_from_points(pts)
    if not cdiag.get("catchment_geometry_available") and not catch_bb:
        return _empty_precip_result(station, cells, geometry_available=False, geometry_status=cdiag.get("catchment_geometry_status") or "missing", precip_status="missing" if not cells else "catchment_geometry_missing", label="keine verwertbaren Niederschlagsdaten zugeordnet", cdiag=cdiag)
    count=0; sum_mm=0.0; wsum=0.0; overlap=0.0; effective_overlap=0.0; dedup=0.0; area_sum=0.0; max_int=0.0; current=0; incoming=0; occupied=[]
    step=_cfg_int("HYDRO_FORECAST_SAMPLE_STEP_MIN",5,1,10); tau=_cfg_float("HYDRO_FALLBACK_ROUTING_TAU_MIN",60,1,1440); coeff=_cfg_float("HYDRO_FORECAST_RUNOFF_COEFF",0.4,0,1); att=_cfg_float("HYDRO_FORECAST_ROUTING_ATTENUATION",1,0,1)
    routed=0.0; series=[]; diags=[]
    for cell in cells or []:
        if not isinstance(cell, dict): continue
        rate,src,_q=_rate_with_source(cell)
        if rate is None: continue
        ov=cell.get("_hydro_overlap") if isinstance(cell.get("_hydro_overlap"), dict) else None
        if ov:
            if not ov.get("hit"): continue
            oa=_f(ov.get("overlap_area_km2"),0) or 0; ratio=_f(ov.get("overlap_ratio_cell"),0) or 0; carea=_f(ov.get("cell_area_km2"), _f(cell.get("area_km2"), oa)) or oa; entry_offset=0; is_current=True; inter=None
        else:
            pts=cell.get("contour_geo") or cell.get("polygon_geo") or cell.get("geo_contour")
            bb=_bbox_from_points(pts or [])
            carea=_bbox_area_approx_km2(bb)
            inter=_bbox_intersection(bb, catch_bb); oa=_bbox_area_approx_km2(inter); ratio=oa/carea if carea else 0
            is_current = oa > 0
            entry_offset = 0
            if oa <= 0:
                base_lat, base_lon = _cell_center(cell, None)
                for pt in _interp_track(_forecast_points(cell, None), step):
                    if base_lat is None or base_lon is None or bb is None: continue
                    dx=float(pt["lon"])-base_lon; dy=float(pt["lat"])-base_lat
                    moved=[bb[0]+dx, bb[1]+dy, bb[2]+dx, bb[3]+dy]
                    inter=_bbox_intersection(moved, catch_bb); oa=_bbox_area_approx_km2(inter); ratio=oa/carea if carea else 0
                    if oa > 0:
                        entry_offset=int(pt["offset_min"]); is_current=False; break
            if oa <= 0: continue
        count+=1; current += 1 if (ov or is_current) else 0; incoming += 0 if (ov or is_current) else 1; overlap+=oa; area_sum+=carea; max_int=max(max_int,rate)
        eff_oa=oa
        for ob in occupied:
            eff_oa -= _bbox_area_approx_km2(_bbox_intersection(inter if not ov else None, ob))
        if not ov and inter:
            occupied.append(inter)
        eff_oa=max(0.0, eff_oa); effective_overlap += eff_oa; dedup += max(0.0, oa-eff_oa)
        mm15=_f(cell.get("nowcast_rr_mm15")); mm=mm15 if mm15 is not None else rate/4.0
        sum_mm += mm; wsum += mm*max(ratio,0)
        rawq=coeff*rate*max(eff_oa,0.0)/3.6; alpha=1-math.exp(-step/tau); routed=routed*(1-alpha)+rawq*att*alpha
        series.append({"offset_min":0,"raw_delta_q_m3s":round(rawq,4),"routed_delta_q_m3s":round(routed,4),"predicted_q_m3s":round(q0+routed,4),"active_cell_count":1,"incoming_cell_count":0,"effective_overlap_area_km2":round(oa,3)})
        diags.append({"cell_id":cell.get("id") or cell.get("cell_id"),"currently_inside":True,"forecast_entry":False,"entry_offset_min":entry_offset,"exit_offset_min":entry_offset,"dwell_time_min":step,"cell_area_km2":round(carea,3),"max_overlap_area_km2":round(oa,3),"rain_rate_mm_h":round(rate,3),"rain_rate_source":src,"rain_volume_m3":round(rate*oa*(step/60)*1000,3),"runoff_volume_m3":round(rate*oa*(step/60)*1000*coeff,3)})
    status="cell_derived" if count else "no_relevant_cell"
    label="aus erkannter Regenzelle abgeleitet" if count else "keine relevante Zelle im aktuellen oder prognostizierten Einzugsgebiet"
    base=_empty_precip_result(station, cells, geometry_available=True, geometry_status=cdiag.get("catchment_geometry_status") or "ok", precip_status=status, label=label, cdiag=cdiag)
    pred=max([x["routed_delta_q_m3s"] for x in series] or [0.0])
    fallback_status = "geometry_fallback_not_authoritative" if count else "no_relevant_cell"
    fallback_label = "Einzugsgebietsprüfung nur mit vereinfachter Geometrie möglich" if count else "keine relevante Zelle im aktuellen oder prognostizierten Einzugsgebiet"
    base.update({"geometry_quality":"bbox_fallback","precip_evaluable_by_geometry":False,"precip_status":fallback_status,"precip_status_label":fallback_label,"cell_catchment_count":count,"contributing_cell_count":count,"current_cell_count":current,"incoming_cell_count":incoming,"cell_catchment_precip_sum_mm":round(sum_mm,3),"cell_catchment_precip_weighted_sum_mm":round(wsum,3),"cell_catchment_max_intensity":round(max_int,3),"cell_catchment_area_km2_sum":round(area_sum,3),"cell_catchment_overlap_area_km2_sum":round(overlap,3),"raw_overlap_area_km2_sum":round(overlap,3),"effective_overlap_area_km2":round(effective_overlap,3),"overlap_deduplicated_area_km2":round(dedup,3),"spatial_dedup_applied":dedup>1e-6,"max_overlap_area_km2":round(effective_overlap,3),"cell_precip_source_type":"nowcast" if count else "none","total_rain_volume_m3":sum(d["rain_volume_m3"] for d in diags),"total_runoff_volume_m3":sum(d["runoff_volume_m3"] for d in diags),"total_dwell_time_min":sum(d["dwell_time_min"] for d in diags),"max_cell_dwell_time_min":max([d["dwell_time_min"] for d in diags] or [0]),"physical_predicted_q_delta_m3s":round(pred,4),"physical_predicted_q_max_m3s":round(q0+pred,4),"rain_rate_mm_h_max":round(max_int,3),"rain_rate_mm_h_mean":round(max_int,3),"rain_rate_mm_h_area_weighted":round(max_int,3),"cell_diagnostics":diags,"station_runoff_series":series})
    return base

def _empty_precip_result(station: dict, cells: list[dict] | None, *, geometry_available: bool, geometry_status: str, precip_status: str, label: str, cdiag: dict | None = None) -> dict:
    q0 = _f(station.get("q_m3s") or station.get("current_q_m3s"), 0.0) or 0.0
    base = dict(cdiag or {})
    base.update({
        "catchment_geometry_available": geometry_available,
        "catchment_geometry_status": geometry_status,
        "input_cell_count": len(cells or []),
        "cell_catchment_count": 0, "contributing_cell_count": 0,
        "current_cell_count": 0, "incoming_cell_count": 0,
        "cell_catchment_precip_sum_mm": 0.0,
        "cell_catchment_precip_weighted_sum_mm": 0.0,
        "cell_catchment_max_intensity": 0.0,
        "cell_catchment_area_km2_sum": 0.0,
        "cell_catchment_overlap_area_km2_sum": 0.0,
        "raw_overlap_area_km2_sum": 0.0,
        "effective_overlap_area_km2": 0.0,
        "overlap_deduplicated_area_km2": 0.0,
        "spatial_dedup_applied": False,
        "cell_catchment_overlap_ratio_max": 0.0,
        "cell_precip_source_type": "none" if precip_status == "no_relevant_cell" else "missing",
        "geometry_quality": "shapely" if geometry_available else "unavailable",
        "routing_tau_min": _cfg_float("HYDRO_FALLBACK_ROUTING_TAU_MIN", 60.0, 1.0, 24*60.0),
        "routing_tau_source": "global_fallback",
        "precip_evaluable_by_geometry": bool(geometry_available),
        "precip_status": precip_status,
        "precip_status_label": label,
        "total_rain_volume_m3": 0.0, "total_runoff_volume_m3": 0.0,
        "total_dwell_time_min": 0.0, "max_cell_dwell_time_min": 0.0,
        "max_overlap_area_km2": 0.0, "overlap_area_time_km2_min": 0.0,
        "physical_predicted_q_delta_m3s": 0.0,
        "physical_predicted_q_max_m3s": q0,
        "first_entry_offset_min": None, "last_exit_offset_min": None,
        "rain_rate_mm_h_max": 0.0, "rain_rate_mm_h_mean": 0.0,
        "rain_rate_mm_h_area_weighted": 0.0,
        "cell_diagnostics": [], "station_runoff_series": [],
    })
    return base

def _precip_from_cells(station: dict, cells: list[dict]) -> dict:
    try:
        import hydro_impact
        from shapely.affinity import translate
        from shapely.ops import unary_union
    except Exception:
        return _precip_from_cells_bbox_fallback(station, cells)
    sid = str(station.get("station_id") or "")
    cdiag = hydro_impact.catchment_diagnostics(sid)
    item = hydro_impact.load_station_catchment_index().get(sid)
    catchment = item.get("geometry") if item else None
    if not cdiag.get("catchment_geometry_available") or catchment is None:
        return _empty_precip_result(station, cells, geometry_available=False, geometry_status=cdiag.get("catchment_geometry_status") or "missing", precip_status="catchment_geometry_missing", label="Einzugsgebietsgeometrie nicht verfügbar", cdiag=cdiag)
    step = _cfg_int("HYDRO_FORECAST_SAMPLE_STEP_MIN", 5, 1, 10)
    runoff_coeff = _cfg_float("HYDRO_FORECAST_RUNOFF_COEFF", 0.4, 0.0, 1.0)
    attenuation = _cfg_float("HYDRO_FORECAST_ROUTING_ATTENUATION", 1.0, 0.0, 1.0)
    tau = _cfg_float("HYDRO_FALLBACK_ROUTING_TAU_MIN", 60.0, 1.0, 24*60.0)
    tau_source = "global_fallback"
    explicit_tau = _f(station.get("routing_tau_min") or station.get("hydro_routing_tau_min"))
    if explicit_tau is not None:
        tau = max(1.0, min(24*60.0, explicit_tau)); tau_source = "station_routing_tau_min"
    else:
        lag = station.get("lag_window_min") or station.get("estimated_lag_min") or station.get("hydro_lag_window_min")
        if isinstance(lag, (list, tuple)) and len(lag) >= 2 and _f(lag[0]) is not None and _f(lag[1]) is not None:
            tau = max(1.0, min(24*60.0, ((_f(lag[0]) or 0) + (_f(lag[1]) or 0)) / 2.0)); tau_source = "station_lag_window_midpoint"
    min_area = _cfg_float("HYDRO_MIN_OVERLAP_AREA_KM2", 1.0, 0.0, None)
    min_ratio = _cfg_float("HYDRO_MIN_OVERLAP_RATIO_CELL", 0.03, 0.0, None)
    q0 = _f(station.get("q_m3s") or station.get("current_q_m3s"), 0.0) or 0.0
    per_time: dict[int, list[dict]] = {}
    cell_stats: dict[str, dict] = {}
    for cell in cells or []:
        if not is_hydro_relevant_cell(cell): continue
        poly = hydro_impact._cell_polygon(cell)
        if poly is None or getattr(poly, "is_empty", True): continue
        base_lat, base_lon = _cell_center(cell, poly)
        if base_lat is None or base_lon is None: continue
        rate, rate_src, quality = _rate_with_source(cell)
        if rate is None: continue
        cell_area = _f(cell.get("cell_area_km2") or cell.get("area_km2"), None)
        if cell_area is None: cell_area = hydro_impact._area_km2(poly)
        cid = str(cell.get("id") or cell.get("cell_id") or cell.get("track_id") or "unknown")
        modes=set(); raw_hits=[]
        for pt in _interp_track(_forecast_points(cell, poly), step):
            moved = translate(poly, xoff=float(pt["lon"])-base_lon, yoff=float(pt["lat"])-base_lat)
            if not moved.intersects(catchment):
                continue
            clip = moved.intersection(catchment)
            oa = hydro_impact._area_km2(clip)
            ratio = oa / cell_area if cell_area else 0.0
            if oa <= 0 or oa < min_area or ratio < min_ratio:
                continue
            off = int(pt["offset_min"]); modes.add(str(pt.get("mode") or "forecast"))
            per_time.setdefault(off, []).append({"cell_id": cid, "geometry": clip, "raw_area_km2": oa, "rate": rate, "rate_source": rate_src, "cell_area_km2": cell_area, "quality": quality, "mode": pt.get("mode")})
            raw_hits.append((off, oa, ratio))
        if raw_hits:
            offs=[x[0] for x in raw_hits]; areas=[x[1] for x in raw_hits]; intervals=_hit_intervals(offs, step)
            cell_stats[cid] = {"cell_id": cid, "currently_inside": 0 in offs, "forecast_entry": min(offs) > 0, "entry_offset_min": min(offs), "exit_offset_min": max(i["exit_offset_min"] for i in intervals), "first_entry_offset_min": min(offs), "last_exit_offset_min": max(i["exit_offset_min"] for i in intervals), "dwell_time_min": sum(i["duration_min"] for i in intervals), "total_dwell_time_min": sum(i["duration_min"] for i in intervals), "continuous_max_dwell_min": max(i["duration_min"] for i in intervals), "hit_interval_count": len(intervals), "hit_intervals": intervals, "cell_area_km2": round(cell_area,3), "max_overlap_area_km2": round(max(areas),3), "mean_overlap_area_km2": round(sum(areas)/len(areas),3), "overlap_area_time_km2_min": round(sum(areas)*step,3), "rain_rate_mm_h": round(rate,3), "rain_rate_source": rate_src, "intensity_forecast_mode": "persistence", "forecast_mode_used": sorted(modes)}
    series=[]; raw_total=0.0; eff_total=0.0; dedup_total=0.0; spatial_dedup=False; routed=0.0; prev_off=None
    max_forecast = 0
    try:
        horizons = [int(h) for h in runtime_config.get("ML_FORECAST_HORIZONS_MIN", getattr(config, "ML_FORECAST_HORIZONS_MIN", [60]))]
        max_forecast = max(horizons or [0])
    except Exception:
        max_forecast = 60
    tail = _cfg_int("HYDRO_ROUTING_TAIL_MIN", int(min(max(tau*3, step), 180)), 0, 360)
    max_offset = max([max(per_time) if per_time else 0, max_forecast]) + tail
    for off in range(0, int(max_offset) + step, step):
        parts=sorted(per_time.get(off, []), key=lambda x: x["rate"], reverse=True)
        occupied=None; raw_area=sum(x["raw_area_km2"] for x in parts); raw_q=0.0; eff_area=0.0
        active=set(); incoming=set()
        for part in parts:
            geom=part["geometry"]
            if occupied is not None and not occupied.is_empty:
                remain=geom.difference(occupied)
            else:
                remain=geom
            ea=hydro_impact._area_km2(remain)
            if ea <= 0:
                spatial_dedup=True; continue
            raw_q += runoff_coeff * part["rate"] * ea / 3.6
            eff_area += ea; active.add(part["cell_id"])
            if not cell_stats.get(part["cell_id"], {}).get("currently_inside"): incoming.add(part["cell_id"])
            occupied = geom if occupied is None else unary_union([occupied, geom])
            cs=cell_stats[part["cell_id"]]
            cs["rain_volume_m3"] = round(cs.get("rain_volume_m3",0.0) + part["rate"] * ea * (step/60.0) * 1000.0, 3)
            cs["runoff_volume_m3"] = round(cs.get("runoff_volume_m3",0.0) + part["rate"] * ea * (step/60.0) * 1000.0 * runoff_coeff, 3)
        dt_min = step if prev_off is None else max(0, off - prev_off)
        alpha=1.0-math.exp(-dt_min/tau) if dt_min > 0 else 0.0
        routed = routed*(1.0-alpha) + raw_q*attenuation*alpha
        prev_off = off
        series.append({"offset_min": off, "raw_delta_q_m3s": round(raw_q,4), "routed_delta_q_m3s": round(routed,4), "predicted_q_m3s": round(max(0.0, q0+routed),4), "active_cell_count": len(active), "incoming_cell_count": len(incoming), "effective_overlap_area_km2": round(eff_area,3)})
        raw_total += raw_area; eff_total += eff_area; dedup_total += max(0.0, raw_area-eff_area)
        if raw_area-eff_area > 1e-6: spatial_dedup=True
    diags=list(cell_stats.values())
    contributing=len(diags); current=sum(1 for d in diags if d["currently_inside"]); incoming=sum(1 for d in diags if d["forecast_entry"])
    total_rain=sum(d.get("rain_volume_m3",0.0) for d in diags); total_runoff=sum(d.get("runoff_volume_m3",0.0) for d in diags)
    pred_delta=max([x["routed_delta_q_m3s"] for x in series] or [0.0])
    source="nowcast" if any(str(d.get("rain_rate_source")).startswith("nowcast") for d in diags) else ("cell_derived" if contributing else "none")
    status="cell_derived" if contributing else "no_relevant_cell"
    label="aus erkannter Regenzelle abgeleitet" if contributing else "keine relevante Zelle im aktuellen oder prognostizierten Einzugsgebiet"
    raw_overlap_area_time_km2_min = round(raw_total * step, 3)
    effective_overlap_area_time_km2_min = round(eff_total * step, 3)
    return {**cdiag, "input_cell_count": len(cells or []), "cell_catchment_count": contributing, "contributing_cell_count": contributing, "current_cell_count": current, "incoming_cell_count": incoming, "cell_catchment_precip_sum_mm": round(total_rain / max(cdiag.get("catchment_area_geometry_km2") or 1.0, 1e-6) / 1000.0, 3), "cell_catchment_precip_weighted_sum_mm": round(total_rain / max(cdiag.get("catchment_area_geometry_km2") or 1.0, 1e-6) / 1000.0, 3), "cell_catchment_max_intensity": round(max([d.get("rain_rate_mm_h",0) for d in diags] or [0]),3), "cell_catchment_area_km2_sum": round(sum(d.get("cell_area_km2",0) for d in diags),3), "cell_catchment_overlap_area_km2_sum": round(raw_total,3), "raw_overlap_area_km2_sum": round(raw_total,3), "effective_overlap_area_km2": round(max([x["effective_overlap_area_km2"] for x in series] or [0]),3), "overlap_deduplicated_area_km2": round(dedup_total,3), "spatial_dedup_applied": spatial_dedup, "cell_catchment_overlap_ratio_max": round(max([d.get("max_overlap_area_km2",0)/max(d.get("cell_area_km2",1),1e-6) for d in diags] or [0]),4), "cell_precip_source_type": source if contributing else "none", "geometry_quality": "shapely", "routing_tau_min": round(tau,3), "routing_tau_source": tau_source, "precip_evaluable_by_geometry": True, "precip_status": status, "precip_status_label": label, "total_rain_volume_m3": round(total_rain,3), "total_runoff_volume_m3": round(total_runoff,3), "total_dwell_time_min": round(sum(d.get("dwell_time_min",0) for d in diags),3), "max_cell_dwell_time_min": round(max([d.get("dwell_time_min",0) for d in diags] or [0]),3), "max_overlap_area_km2": round(max([d.get("max_overlap_area_km2",0) for d in diags] or [0]),3), "raw_overlap_area_time_km2_min": raw_overlap_area_time_km2_min, "effective_overlap_area_time_km2_min": effective_overlap_area_time_km2_min, "overlap_area_time_km2_min": effective_overlap_area_time_km2_min, "physical_predicted_q_delta_m3s": round(pred_delta,4), "physical_predicted_q_max_m3s": round(max(0.0, q0+pred_delta),4), "first_entry_offset_min": min([d.get("entry_offset_min") for d in diags] or [None]), "last_exit_offset_min": max([d.get("exit_offset_min") for d in diags] or [None]), "rain_rate_mm_h_max": round(max([d.get("rain_rate_mm_h",0) for d in diags] or [0]),3), "rain_rate_mm_h_mean": round(sum(d.get("rain_rate_mm_h",0) for d in diags)/contributing,3) if contributing else 0.0, "rain_rate_mm_h_area_weighted": round((sum(d.get("rain_rate_mm_h",0)*d.get("max_overlap_area_km2",0) for d in diags) / max(sum(d.get("max_overlap_area_km2",0) for d in diags), 1e-6)),3) if contributing else 0.0, "cell_diagnostics": diags, "station_runoff_series": series[:24]}

def _observed_precip(station: dict) -> dict:
    p = station.get("observed_precip") if isinstance(station.get("observed_precip"), dict) else {}
    val = _f(p.get("sum_mm"))
    ts = p.get("timestamp") or p.get("measured_at")
    age = _f(p.get("age_min"))
    if age is None and ts:
        d = _dt(ts); age = max(0.0, (datetime.now(timezone.utc)-d).total_seconds()/60.0) if d else None
    return {"observed_catchment_precip_sum_mm": val or 0.0, "observed_catchment_precip_max_rate_mm_h": _f(p.get("max_rate_mm_h"),0.0), "observed_catchment_precip_mean_rate_mm_h": _f(p.get("mean_rate_mm_h"),0.0), "observed_catchment_precip_area_km2": _f(p.get("area_km2"),0.0), "observed_precip_source_quality": p.get("quality") or ("high" if val is not None else "missing"), "observed_precip_data_age_min": age, "observed_precip_available": val is not None, "precip_source_name": p.get("source_name") or ("observed_catchment_precip" if val is not None else None), "precip_source_timestamp": ts}


def _q_timestamp(live_station: dict) -> tuple[str | None, str]:
    measured_at = live_station.get("measured_at")
    if measured_at:
        return str(measured_at), "hydro_live.measured_at"
    fetched_at = live_station.get("fetched_at")
    if fetched_at:
        return str(fetched_at), "hydro_live.fetched_at_fallback"
    return None, "missing"


def build_feature_row(station: dict, live: dict|None=None, cells: list[dict]|None=None, trend_history: dict[str, list[dict]]|None=None) -> dict:
    sid = str(station.get("station_id") or "")
    live_station = station
    if live:
        by = {str(s.get("station_id")): {**s, "fetched_at": s.get("fetched_at") or live.get("fetched_at")} for s in live.get("stations", []) if isinstance(s, dict)}; live_station = {**station, **(by.get(sid) or {})}
    q = _f(live_station.get("q_m3s")); q_measured_at, q_timestamp_source = _q_timestamp(live_station); thr, src = _threshold(station)
    obs = _observed_precip(station); cellp = _precip_from_cells(station, cells if cells is not None else [{}])
    use_obs = bool(obs["observed_precip_available"])
    eff_type = "measured" if use_obs else (cellp["cell_precip_source_type"] if cellp["cell_precip_source_type"] != "missing" else "missing")
    eff_sum = obs["observed_catchment_precip_sum_mm"] if use_obs else cellp["cell_catchment_precip_sum_mm"]
    qdist = (thr - q) if (thr is not None and q is not None) else None
    ratio = (q / thr) if (thr not in (None, 0) and q is not None) else None
    geom_eval = bool(cellp.get("precip_evaluable_by_geometry"))
    precip_evaluable = bool(use_obs or geom_eval or eff_type != "missing")
    if use_obs:
        precip_status = "observed"
    else:
        precip_status = cellp.get("precip_status") or ("cell_derived" if eff_type in {"nowcast", "cell_derived"} else "missing")
    precip_status_label = cellp.get("precip_status_label") or {"observed": "gemessener Niederschlag im Einzugsgebiet", "cell_derived": "aus erkannter Regenzelle abgeleitet", "missing": "keine verwertbaren Niederschlagsdaten zugeordnet", "no_relevant_cell": "keine relevante Zelle im aktuellen oder prognostizierten Einzugsgebiet", "catchment_geometry_missing": "Einzugsgebietsgeometrie nicht verfügbar"}.get(precip_status, "nicht bewertbar")
    precip_quality_label = {"observed": "hoch", "cell_derived": "mittel", "no_relevant_cell": "hoch", "catchment_geometry_missing": "nicht bewertbar", "missing": "nicht bewertbar"}.get(precip_status, "mittel")
    eff_sum_out = eff_sum if precip_evaluable else None
    trend = _q_trend_fields(sid, q, q_measured_at, trend_history)
    return {**obs, **cellp, "station_id": sid, "station_name": live_station.get("name") or live_station.get("station_name") or station.get("name") or sid, "river": live_station.get("river") or station.get("river") or station.get("river_name") or "", "station_lat": _f(station.get("lat"), _f(live_station.get("lat"))), "station_lon": _f(station.get("lon"), _f(live_station.get("lon"))), "current_q_m3s": q, "current_q_measured_at": q_measured_at, "current_q_timestamp_source": q_timestamp_source, "current_q_missing": q is None, "station_q_threshold_m3s": thr, "mark_q_m3s": thr, "station_q_threshold_missing": thr is None, "station_q_threshold_source": src if thr is not None else "missing", "current_q_ratio_threshold": ratio, "current_q_distance_to_threshold_m3s": qdist, "current_q_above_threshold": bool(thr is not None and q is not None and q >= thr), **trend, "current_data_age_min": _f(live_station.get("data_age_min")), "data_age_min": _f(live_station.get("data_age_min")), "hydro_data_stale": False, "catchment_geometry_available": cellp.get("catchment_geometry_available", False), "catchment_geometry_status": cellp.get("catchment_geometry_status"), "catchment_feature_count": cellp.get("catchment_feature_count", 0), "catchment_area_geometry_km2": cellp.get("catchment_area_geometry_km2"), "catchment_area_km2": _f(station.get("catchment_area_km2"), cellp.get("catchment_area_geometry_km2") or 0.0), "upstream_catchment_count": len(station.get("upstream_catchment_ids") or []), "impact_eligible": bool(station.get("impact_effective", station.get("impact_eligible", True))), "source_quality": station.get("source_quality"), "topology_source": station.get("topology_source"), "upstream_source_quality": station.get("upstream_source_quality"), "effective_catchment_precip_sum_mm": eff_sum_out, "effective_catchment_precip_weighted_sum_mm": (eff_sum if use_obs else cellp["cell_catchment_precip_weighted_sum_mm"]) if precip_evaluable else None, "effective_catchment_precip_max_rate_mm_h": obs["observed_catchment_precip_max_rate_mm_h"] if use_obs else cellp["cell_catchment_max_intensity"], "effective_catchment_precip_mean_rate_mm_h": obs["observed_catchment_precip_mean_rate_mm_h"] if use_obs else cellp["cell_catchment_max_intensity"], "effective_precip_source_type": eff_type, "effective_precip_source_quality": obs["observed_precip_source_quality"] if use_obs else ("medium" if eff_type in {"nowcast","cell_derived"} else "missing"), "effective_precip_is_proxy": eff_type in {"cell_derived","proxy"}, "effective_precip_missing": eff_type == "missing", "precip_evaluable": precip_evaluable, "precip_status": precip_status, "precip_status_label": precip_status_label, "precip_quality_label": precip_quality_label, "precip_source_type": eff_type, "precip_source_quality": obs["observed_precip_source_quality"] if use_obs else ("medium" if eff_type != "missing" else "missing"), "precip_is_observed": use_obs, "precip_is_proxy": eff_type in {"cell_derived","proxy"}, "precip_source_name": obs.get("precip_source_name") or (eff_type if precip_evaluable else None), "precip_source_timestamp": obs.get("precip_source_timestamp"), "precip_source_age_min": obs.get("observed_precip_data_age_min")}


def heuristic_score(row: dict) -> dict:
    reasons=[]; warnings=[]
    q = _f(row.get("current_q_m3s")); thr = _f(row.get("station_q_threshold_m3s"))
    physical_delta = max(0.0, _f(row.get("physical_predicted_q_delta_m3s"), 0.0) or 0.0)
    predicted_delta = max(0.0, _f(row.get("predicted_q_delta_m3s"), physical_delta) or 0.0)
    predicted_q = _f(row.get("predicted_q_max_m3s"))
    if predicted_q is None:
        predicted_q = max(0.0, (q or 0.0) + predicted_delta) if q is not None else None
    if q is not None:
        predicted_q = max(predicted_q or q, q)
    if row.get("precip_evaluable") and row.get("contributing_cell_count", row.get("cell_catchment_count", 0)):
        reasons.append("Niederschlag im oberliegenden Einzugsgebiet")
    base = {"hydro_flood_risk_score": None, "confidence": None, "model_source": "heuristic_scoring", "physical_predicted_q_delta_m3s": physical_delta, "ml_predicted_q_delta_m3s": None}
    if q is None:
        warnings.append("missing_current_q")
        return {**base, "flood_expected": False, "flood_evaluable": False, "current_threshold_evaluable": False, "current_q_above_threshold": False, "forecast_flood_evaluable": False, "flood_status": "missing_current_q", "reasons": reasons, "warning_reasons": warnings, "prediction_source": "not_evaluable", "predicted_q_delta_m3s": None, "predicted_q_max_m3s": None}
    if thr is None:
        warnings.append("missing_station_q_threshold")
        return {**base, "flood_expected": False, "flood_evaluable": False, "current_threshold_evaluable": False, "current_q_above_threshold": False, "forecast_flood_evaluable": False, "flood_status": "missing_threshold", "reasons": reasons, "warning_reasons": warnings, "prediction_source": "physical_fallback", "predicted_q_delta_m3s": predicted_delta, "predicted_q_max_m3s": predicted_q}
    current_q_above_threshold = bool(q >= thr)
    if row.get("geometry_quality") == "bbox_fallback":
        warnings.append("geometry_fallback_not_authoritative")
    if not row.get("catchment_geometry_available") and row.get("precip_status") != "missing":
        warnings.append("catchment_geometry_missing")
    if current_q_above_threshold:
        if "current_q_m3s >= station_q_threshold_m3s" not in reasons:
            reasons.append("current_q_m3s >= station_q_threshold_m3s")
        return {**base, "flood_expected": True, "flood_evaluable": True, "current_threshold_evaluable": True, "current_q_above_threshold": True, "forecast_flood_evaluable": False, "flood_status": "threshold_already_exceeded", "reasons": reasons, "warning_reasons": warnings, "prediction_source": "physical_fallback", "predicted_q_delta_m3s": predicted_delta, "predicted_q_max_m3s": predicted_q}
    if row.get("geometry_quality") == "bbox_fallback":
        return {**base, "flood_expected": False, "flood_evaluable": False, "current_threshold_evaluable": True, "current_q_above_threshold": False, "forecast_flood_evaluable": False, "flood_status": "geometry_fallback_not_authoritative", "reasons": reasons, "warning_reasons": warnings, "prediction_source": "not_evaluable", "predicted_q_delta_m3s": predicted_delta, "predicted_q_max_m3s": predicted_q}
    if not row.get("catchment_geometry_available") and row.get("precip_status") != "missing":
        return {**base, "flood_expected": False, "flood_evaluable": False, "current_threshold_evaluable": True, "current_q_above_threshold": False, "forecast_flood_evaluable": False, "flood_status": "catchment_geometry_missing", "reasons": reasons, "warning_reasons": warnings, "prediction_source": "not_evaluable", "predicted_q_delta_m3s": predicted_delta, "predicted_q_max_m3s": predicted_q}
    expected = bool((predicted_q or q) >= thr)
    return {**base, "flood_expected": expected, "flood_evaluable": True, "current_threshold_evaluable": True, "current_q_above_threshold": False, "forecast_flood_evaluable": True, "flood_status": "ok", "reasons": reasons, "warning_reasons": warnings, "prediction_source": "physical_fallback", "predicted_q_delta_m3s": predicted_delta, "predicted_q_max_m3s": predicted_q}

def _public_flood_row(row: dict) -> dict:
    keys = ["station_id","station_name","river","current_q_m3s","current_q_measured_at","current_q_timestamp_source","current_q_missing","station_q_threshold_m3s","station_q_threshold_source","station_q_threshold_missing","current_q_ratio_threshold","current_q_distance_to_threshold_m3s","current_q_above_threshold","current_threshold_evaluable","forecast_flood_evaluable","forecast_evaluation_stale","forecast_evaluation_generated_at","forecast_evaluation_age_min","stale_predicted_q_max_m3s","stale_prediction_generated_at","catchment_geometry_available","catchment_geometry_status","catchment_feature_count","catchment_area_geometry_km2","catchment_area_km2","routing_tau_min","routing_tau_source","input_cell_count","contributing_cell_count","current_cell_count","incoming_cell_count","effective_catchment_precip_sum_mm","effective_catchment_precip_weighted_sum_mm","effective_precip_source_type","effective_precip_source_quality","precip_evaluable","precip_status","precip_status_label","precip_quality_label","cell_catchment_count","cell_catchment_overlap_area_km2_sum","raw_overlap_area_km2_sum","effective_overlap_area_km2","overlap_deduplicated_area_km2","spatial_dedup_applied","total_rain_volume_m3","total_runoff_volume_m3","total_dwell_time_min","max_cell_dwell_time_min","max_overlap_area_km2","overlap_area_time_km2_min","physical_predicted_q_delta_m3s","physical_predicted_q_max_m3s","ml_predicted_q_delta_m3s","predicted_q_delta_m3s","predicted_q_max_m3s","prediction_source","first_entry_offset_min","last_exit_offset_min","rain_rate_mm_h_max","rain_rate_mm_h_mean","rain_rate_mm_h_area_weighted","current_data_age_min","data_age_min","hydro_data_stale","current_q_trend_10min","current_q_trend_30min","current_q_trend_60min","q_trend_per_hour","already_rising_flag","q_trend_status","q_trend_delta_m3s","q_trend_reference_window_min","flood_expected","flood_evaluable","flood_status","reasons","warning_reasons","model_source","generated_at","flood_probability"]
    return {k: row.get(k) for k in keys if k in row}

def evaluate_live_flood_risk(stations: list[dict]|None=None, live: dict|None=None, cells: list[dict]|None=None, write: bool=True, include_debug: bool=False) -> dict:
    if stations is None:
        import hydro_api
        stations = [f.get("properties") or {} for f in hydro_api.station_features(include_disabled=False).get("features", [])]
    generated = _now(); public_rows=[]; internal_rows=[]
    trend_history = load_q_trend_history()
    cells_meta = _objects_signature(cells or [])
    frame_meta = (live or {}).get("cell_frame_meta") if isinstance(live, dict) else None
    for st in stations or []:
        row = build_feature_row(st, live=live, cells=cells, trend_history=trend_history)
        if cells == [] and isinstance(frame_meta, dict) and frame_meta.get("status") == "ok" and int(frame_meta.get("raw_cell_count") or 0) == 0:
            row.update({"precip_status": "no_relevant_cell", "precip_status_label": "keine relevante Zelle im aktuellen oder prognostizierten Einzugsgebiet", "precip_evaluable": True, "effective_precip_source_type": "none", "effective_catchment_precip_sum_mm": 0.0})
        pred = predict_q_delta(row)
        row_for_score = {**row, **pred}
        sc = heuristic_score(row_for_score); sc.update(pred); sc.pop("hydro_flood_risk_score", None); sc.pop("confidence", None)
        full = {**row, **sc, "generated_at": generated, "flood_probability": None}
        if isinstance(frame_meta, dict):
            full.update({"cell_frame_path": frame_meta.get("path"), "cell_frame_timestamp": frame_meta.get("frame_timestamp"), "cell_frame_age_min": frame_meta.get("frame_age_min"), "cell_frame_status": frame_meta.get("cell_frame_status") or frame_meta.get("status")})
        internal_rows.append(full)
        public_rows.append(full if (include_debug or not write) else _public_flood_row(full))
    pending_meta = record_pending_samples(internal_rows, live=live, cells_meta=cells_meta) if write else {"pending_added": 0, "pending_total": None}
    materialize_meta = materialize_pending_samples(live=None) if write else {"labeled_added": 0}
    doc = {"status":"ok", "payload_scope": "admin_diagnostics" if include_debug else "public", "payload_schema_version": "b411_public_v1", "generated_at": generated, "input_hash": flood_risk_input_hash(live=live, cells=cells or []), "stations": public_rows, "pending_samples": pending_meta, "materialized_samples": materialize_meta, "readiness": readiness_status(), "cell_frame_path": (frame_meta or {}).get("path") if isinstance(frame_meta, dict) else None, "cell_frame_timestamp": (frame_meta or {}).get("frame_timestamp") if isinstance(frame_meta, dict) else None, "cell_frame_age_min": (frame_meta or {}).get("frame_age_min") if isinstance(frame_meta, dict) else None, "cell_frame_status": (frame_meta or {}).get("cell_frame_status") if isinstance(frame_meta, dict) else None}
    if include_debug:
        doc["debug_stations"] = internal_rows
    if write and not include_debug: _atomic_json(HYDRO_RISK_PATH, doc)
    return doc


def _jsonl_rows(path: Path) -> list[dict]:
    if not path.exists(): return []
    rows=[]
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip(): continue
        try:
            obj=json.loads(line)
            if isinstance(obj, dict): rows.append(obj)
        except Exception: pass
    return rows


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False, default=str)+"\n" for r in rows), encoding="utf-8")


def _feature_snapshot(row: dict) -> dict:
    snap = {k: row.get(k) for k in HYDRO_FLOOD_ML_FEATURES}
    snap["threshold_available_flag"] = 0.0 if row.get("station_q_threshold_missing") or row.get("current_q_ratio_threshold") is None else 1.0
    snap["q_trend_available_flag"] = 0.0 if row.get("q_trend_delta_m3s") is None else 1.0
    snap["cell_entry_available_flag"] = 0.0 if row.get("first_entry_offset_min") is None or row.get("last_exit_offset_min") is None else 1.0
    snap["data_age_available_flag"] = 0.0 if row.get("data_age_min") is None else 1.0
    for key, default in HYDRO_FEATURE_IMPUTATION.items():
        if snap.get(key) is None:
            snap[key] = default
    return snap

def _feature_vector(row: dict) -> list[float]:
    vals = []
    snap = row.get("features") if isinstance(row.get("features"), dict) else row
    for name in HYDRO_FLOOD_ML_FEATURES:
        v = snap.get(name)
        if isinstance(v, bool):
            vals.append(1.0 if v else 0.0)
        else:
            vals.append(_f(v, 0.0) or 0.0)
    return vals


def _feature_schema_hash() -> str:
    payload = {"version": FEATURE_SCHEMA_VERSION, "features": HYDRO_FLOOD_ML_FEATURES, "required_features": HYDRO_REQUIRED_FEATURES, "optional_features": sorted(HYDRO_OPTIONAL_FEATURES), "missing_indicators": HYDRO_MISSING_INDICATOR_FEATURES, "types": {k: "float_or_bool" for k in HYDRO_FLOOD_ML_FEATURES}, "imputation": HYDRO_FEATURE_IMPUTATION}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

def _missing_required_features(row: dict) -> list[str]:
    snap = row.get("features") if isinstance(row.get("features"), dict) else row
    return [k for k in HYDRO_REQUIRED_FEATURES if snap.get(k) is None]

def _sample_is_trainable_live(row: dict) -> bool:
    kind = row.get("sample_kind") or (SAMPLE_KIND_LIVE if row.get("feature_schema_version") == FEATURE_SCHEMA_VERSION else None)
    return kind == SAMPLE_KIND_LIVE and row.get("feature_snapshot_complete", True) is True and row.get("feature_schema_version") == FEATURE_SCHEMA_VERSION and _f(row.get("target_q_delta_m3s")) is not None and not row.get("target_missing")

def _sample_db() -> sqlite3.Connection:
    HYDRO_ML_DIR.mkdir(parents=True, exist_ok=True)
    if HYDRO_DATASET_JSONL_PATH != _DEFAULT_HYDRO_DATASET_JSONL_PATH and HYDRO_SAMPLE_DB_PATH.parent != HYDRO_DATASET_JSONL_PATH.parent:
        db_path = HYDRO_DATASET_JSONL_PATH.parent / "hydro_flood_samples.sqlite3"
    elif HYDRO_SAMPLE_DB_PATH == _DEFAULT_HYDRO_SAMPLE_DB_PATH or HYDRO_SAMPLE_DB_PATH.parent != HYDRO_ML_DIR:
        db_path = HYDRO_ML_DIR / "hydro_flood_samples.sqlite3"
    else:
        db_path = HYDRO_SAMPLE_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("CREATE TABLE IF NOT EXISTS pending_samples (sample_id TEXT PRIMARY KEY, station_id TEXT, sample_start_time TEXT, created_at TEXT, payload TEXT NOT NULL)")
    con.execute("CREATE TABLE IF NOT EXISTS labeled_samples (sample_id TEXT PRIMARY KEY, station_id TEXT, sample_start_time TEXT, labeled_at TEXT, payload TEXT NOT NULL)")
    con.execute("CREATE TABLE IF NOT EXISTS sample_failures (sample_id TEXT PRIMARY KEY, station_id TEXT, failed_at TEXT, reason TEXT, payload TEXT NOT NULL)")
    con.execute("CREATE TABLE IF NOT EXISTS training_runs (run_id TEXT PRIMARY KEY, created_at TEXT, payload TEXT NOT NULL)")
    con.execute("CREATE TABLE IF NOT EXISTS schema_migrations (migration_id TEXT PRIMARY KEY, applied_at TEXT, rows_imported INTEGER DEFAULT 0, rows_legacy_moved INTEGER DEFAULT 0, rows_invalid INTEGER DEFAULT 0, payload TEXT)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_pending_station_time ON pending_samples(station_id, sample_start_time)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_labeled_station_time ON labeled_samples(station_id, sample_start_time)")
    return con

def _db_rows(table: str) -> list[dict]:
    with _sample_db() as con:
        return [json.loads(r[0]) for r in con.execute(f"SELECT payload FROM {table}").fetchall()]

def _migration_applied(con: sqlite3.Connection, migration_id: str) -> bool:
    return con.execute("SELECT 1 FROM schema_migrations WHERE migration_id=?", (migration_id,)).fetchone() is not None

def _mark_migration(con: sqlite3.Connection, migration_id: str, meta: dict) -> None:
    con.execute("INSERT OR REPLACE INTO schema_migrations(migration_id, applied_at, rows_imported, rows_legacy_moved, rows_invalid, payload) VALUES(?,?,?,?,?,?)", (migration_id, meta.get("migration_at") or _now(), int(meta.get("rows_imported", meta.get("rows_live_kept", 0)) or 0), int(meta.get("rows_legacy_moved", 0) or 0), int(meta.get("rows_invalid", meta.get("rows_invalid_dropped", 0)) or 0), json.dumps(meta, ensure_ascii=False, default=str)))

def migrate_productive_dataset() -> dict:
    migration_id = "b410_jsonl_to_sqlite_v1"
    with _sample_db() as con:
        if _migration_applied(con, migration_id):
            row=con.execute("SELECT payload FROM schema_migrations WHERE migration_id=?", (migration_id,)).fetchone()
            meta=json.loads(row[0]) if row and row[0] else {"migration_id": migration_id}
            meta["already_applied"] = True
            return meta
        rows = _jsonl_rows(HYDRO_DATASET_JSONL_PATH)
        live=[]; legacy=[]; invalid=[]
        con.execute("BEGIN IMMEDIATE")
        try:
            for r in rows:
                if (r.get("sample_kind") in (None, SAMPLE_KIND_LIVE)) and r.get("feature_schema_version") == FEATURE_SCHEMA_VERSION:
                    r.setdefault("sample_kind", SAMPLE_KIND_LIVE)
                    sid=str(r.get("station_id") or "")
                    if r.get("sample_id"):
                        con.execute("INSERT OR REPLACE INTO labeled_samples(sample_id, station_id, sample_start_time, labeled_at, payload) VALUES(?,?,?,?,?)", (r.get("sample_id"), sid, r.get("sample_start_time"), r.get("labeled_at") or _now(), json.dumps(r, ensure_ascii=False, default=str)))
                        live.append(r)
                    else:
                        invalid.append(r)
                elif r.get("sample_kind") == SAMPLE_KIND_LEGACY or r.get("feature_snapshot_complete") is not True:
                    r.setdefault("sample_kind", SAMPLE_KIND_LEGACY); legacy.append(r)
                else:
                    invalid.append(r)
            meta={"migration_id": migration_id, "migration_at": _now(), "rows_before": len(rows), "rows_imported": len(live), "rows_live_kept": len(live), "rows_legacy_moved": len(legacy), "rows_invalid": len(invalid), "rows_invalid_dropped": len(invalid), "source": str(HYDRO_DATASET_JSONL_PATH), "store": "sqlite"}
            _mark_migration(con, migration_id, meta)
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    _write_jsonl(HYDRO_DATASET_JSONL_PATH, live)
    if legacy:
        existing = {r.get("sample_id"): r for r in _jsonl_rows(HYDRO_DATASET_PATH) if r.get("sample_id")}
        for r in legacy:
            existing[r.get("sample_id") or hashlib.sha256(json.dumps(r, sort_keys=True, default=str).encode()).hexdigest()] = r
        _write_jsonl(HYDRO_DATASET_PATH, list(existing.values()))
    old=_read_json(HYDRO_TRAINING_META_PATH,{})
    old["b410_dataset_migration"] = meta
    _atomic_json(HYDRO_TRAINING_META_PATH, old)
    return meta

def migrate_pending_jsonl_to_sqlite() -> dict:
    migration_id="b411_pending_jsonl_to_sqlite_v1"
    with _sample_db() as con:
        if _migration_applied(con, migration_id):
            row=con.execute("SELECT payload FROM schema_migrations WHERE migration_id=?", (migration_id,)).fetchone()
            meta=json.loads(row[0]) if row and row[0] else {"migration_id": migration_id}
            meta["already_applied"] = True
            return meta
        rows=_jsonl_rows(HYDRO_PENDING_SAMPLES_PATH)
        imported=duplicates=invalid=0; now=_now()
        con.execute("BEGIN IMMEDIATE")
        try:
            seen=set()
            for r in rows:
                sid=str(r.get("station_id") or ""); sample_id=r.get("sample_id") or hashlib.sha256(json.dumps(r, sort_keys=True, default=str).encode()).hexdigest()
                if sample_id in seen:
                    duplicates += 1; continue
                seen.add(sample_id); r["sample_id"] = sample_id
                if not sid or not isinstance(r.get("features"), dict):
                    invalid += 1
                    con.execute("INSERT OR REPLACE INTO sample_failures(sample_id, station_id, failed_at, reason, payload) VALUES(?,?,?,?,?)", (sample_id, sid, now, "pending_jsonl_invalid_schema", json.dumps(r, ensure_ascii=False, default=str)))
                    continue
                con.execute("INSERT OR IGNORE INTO pending_samples(sample_id, station_id, sample_start_time, created_at, payload) VALUES(?,?,?,?,?)", (sample_id, sid, r.get("sample_start_time"), r.get("created_at") or now, json.dumps(r, ensure_ascii=False, default=str)))
                imported += con.total_changes > 0
            meta={"migration_id": migration_id, "migration_at": now, "rows_before": len(rows), "rows_imported": imported, "rows_invalid": invalid, "duplicate_rows": duplicates, "source": str(HYDRO_PENDING_SAMPLES_PATH)}
            _mark_migration(con, migration_id, meta)
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    if rows and HYDRO_PENDING_SAMPLES_PATH.exists():
        archive=HYDRO_PENDING_SAMPLES_PATH.with_name(f"hydro_flood_pending_samples.migrated.{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.jsonl")
        os.replace(HYDRO_PENDING_SAMPLES_PATH, archive)
        meta["archived_path"] = str(archive)
    return meta

def record_pending_samples(rows: list[dict], live: dict | None = None, cells_meta: dict | None = None) -> dict:
    added = 0
    now = _now()
    with _sample_db() as con:
        con.execute("BEGIN IMMEDIATE")
        for row in rows:
            if not row.get("station_id") or row.get("current_q_m3s") is None or not row.get("catchment_geometry_available"):
                continue
            start = row.get("current_q_measured_at") or (live or {}).get("fetched_at") or row.get("generated_at") or now
            sid = str(row.get("station_id"))
            features = _feature_snapshot(row)
            missing = _missing_required_features({"features": features})
            sig = {"station": sid, "start": start, "features": features, "catchment": row.get("catchment_geometry_status"), "cells": cells_meta}
            sample_id = hashlib.sha256(json.dumps(sig, sort_keys=True, default=str).encode()).hexdigest()
            payload = {"sample_id": sample_id, "sample_kind": SAMPLE_KIND_LIVE, "feature_schema_version": FEATURE_SCHEMA_VERSION, "feature_schema_hash": _feature_schema_hash(), "feature_snapshot_complete": not missing, "missing_required_features": missing, "station_id": sid, "sample_start_time": start, "current_q_m3s": row.get("current_q_m3s"), "station_q_threshold_m3s": row.get("station_q_threshold_m3s"), "features": features, "catchment_signature": _hash_obj({"status": row.get("catchment_geometry_status"), "area": row.get("catchment_area_geometry_km2")}), "cell_frame_hash": (cells_meta or {}).get("hash"), "config_signature": _hash_obj({k: runtime_config.get(k, getattr(config, k, None)) for k in ("HYDRO_FORECAST_SAMPLE_STEP_MIN","HYDRO_FORECAST_RUNOFF_COEFF","HYDRO_FALLBACK_ROUTING_TAU_MIN")}), "labeled": False, "created_at": now}
            cur = con.execute("INSERT OR IGNORE INTO pending_samples(sample_id, station_id, sample_start_time, created_at, payload) VALUES(?,?,?,?,?)", (sample_id, sid, start, now, json.dumps(payload, ensure_ascii=False, default=str)))
            added += cur.rowcount
        con.execute("COMMIT")
        total = con.execute("SELECT COUNT(*) FROM pending_samples").fetchone()[0]
    return {"pending_added": added, "pending_total": total, "store": "sqlite", "db_path": str(HYDRO_SAMPLE_DB_PATH)}

def materialize_pending_samples(live: dict | None = None) -> dict:
    if live:
        append_hydro_history(live)
    hist=_read_history_rows(); rows_by_station={}
    for r in hist: rows_by_station.setdefault(str(r.get("station_id") or ""), []).append(r)
    for rows in rows_by_station.values(): rows.sort(key=lambda r: str(r.get("measured_at") or r.get("fetched_at") or ""))
    added=0; failed=0; now=_now()
    retention_h = _cfg_int("HYDRO_PENDING_RETENTION_HOURS", 72, 1, 24*30)
    with _sample_db() as con:
        con.execute("BEGIN IMMEDIATE")
        pending=[json.loads(r[0]) for r in con.execute("SELECT payload FROM pending_samples").fetchall()]
        for sample in pending:
            sid=str(sample.get("station_id") or ""); start_q=_f(sample.get("current_q_m3s")); thr=_f(sample.get("station_q_threshold_m3s"))
            label=_label_from_future({"measured_at": sample.get("sample_start_time"), "fetched_at": sample.get("sample_start_time"), "q_m3s": start_q}, rows_by_station.get(sid, []), thr)
            age_dt=_dt(sample.get("created_at")); expired=age_dt and (datetime.now(timezone.utc)-age_dt).total_seconds() > retention_h*3600
            if label.get("target_missing") and not expired:
                continue
            con.execute("DELETE FROM pending_samples WHERE sample_id=?", (sample.get("sample_id"),))
            if label.get("target_missing"):
                sample["failure_reason"] = "pending_retention_expired_without_label"
                con.execute("INSERT OR REPLACE INTO sample_failures(sample_id, station_id, failed_at, reason, payload) VALUES(?,?,?,?,?)", (sample.get("sample_id"), sid, now, sample["failure_reason"], json.dumps(sample, ensure_ascii=False, default=str)))
                failed += 1; continue
            flat={k: v for k,v in (sample.get("features") or {}).items() if k != "w_cm"}
            payload={**sample, **flat, **label, "labeled": True, "labeled_at": now}
            con.execute("INSERT OR REPLACE INTO labeled_samples(sample_id, station_id, sample_start_time, labeled_at, payload) VALUES(?,?,?,?,?)", (payload.get("sample_id"), sid, payload.get("sample_start_time"), now, json.dumps(payload, ensure_ascii=False, default=str)))
            added += 1
        con.execute("COMMIT")
    dataset=[r for r in _db_rows("labeled_samples") if r.get("sample_kind") == SAMPLE_KIND_LIVE]
    dataset_count = len(dataset)
    if added:
        _write_jsonl(HYDRO_DATASET_JSONL_PATH, dataset)
    return {"labeled_added": added, "failed_expired": failed, "pending_remaining": len(_db_rows("pending_samples")), "dataset_count": dataset_count, "store": "sqlite"}

def load_trainable_labeled_samples(trainable_only: bool = False) -> list[dict]:
    rows = _db_rows("labeled_samples")
    return [r for r in rows if _sample_is_trainable_live(r)] if trainable_only else rows

def readiness_status() -> dict:
    migrate_productive_dataset()
    meta = _read_json(HYDRO_TRAINING_META_PATH, {})
    rows=load_trainable_labeled_samples(False)
    usable=[r for r in rows if _sample_is_trainable_live(r)]
    valid_q=sum(1 for r in usable if _f(r.get("target_q_delta_m3s")) is not None)
    stations={r.get("station_id") for r in usable}
    events={_event_key(r, None) for r in usable}
    times=[_dt(r.get("sample_start_time") or r.get("created_at")) for r in usable]
    times=[t for t in times if t]
    span=((max(times)-min(times)).total_seconds()/86400.0) if len(times)>=2 else 0.0
    reasons=[]
    if len(usable) < MIN_TRAINING_SAMPLES: reasons.append("insufficient_regression_samples")
    if valid_q < MIN_TRAINING_SAMPLES: reasons.append("insufficient_valid_q_delta_targets")
    if len(stations) < 1: reasons.append("missing_station_coverage")
    pos=sum(1 for r in rows if r.get("target_flood_expected") is True); neg=sum(1 for r in rows if r.get("target_flood_expected") is False)
    coverage=dict(Counter((r.get("effective_precip_source_type") or "missing") for r in rows))
    return {"enabled": True, "model_available": (HYDRO_MODEL_CURRENT_DIR/HYDRO_MODEL_FILENAME).exists(), "sample_count": len(usable), "regression_sample_count": len(usable), "valid_target_q_delta_count": valid_q, "feature_complete_count": sum(1 for r in rows if r.get("feature_snapshot_complete") is True), "schema_compatible_count": sum(1 for r in rows if r.get("feature_schema_version") == FEATURE_SCHEMA_VERSION), "event_count": len(events), "time_span_days": round(span,3), "station_count": len(stations), "threshold_labeled_count": pos+neg, "positive_threshold_events": pos, "negative_threshold_events": neg, "positive_samples": pos, "negative_samples": neg, "stations_with_threshold": len({r.get("station_id") for r in rows if not r.get("station_q_threshold_missing")}), "stations_without_threshold": len({r.get("station_id") for r in rows if r.get("station_q_threshold_missing")}), "precip_source_coverage": coverage, "last_training_at": meta.get("last_training_at"), "last_dataset_build_at": meta.get("last_dataset_build_at"), "readiness_status": "ready" if not reasons else "fallback", "rejection_reasons": reasons}

def _event_cells(row: dict) -> set[str]:
    values = row.get("contributing_lineage_ids") or row.get("contributing_cell_ids")
    if isinstance(values, str):
        values = [v for v in values.split(",") if v]
    if isinstance(values, (list, tuple, set)):
        return {str(v) for v in values if v not in (None, "")}
    return set()

def _event_key(row: dict, previous: dict | None = None) -> str:
    return str(row.get("event_id") or row.get("hydro_event_id") or "")

def _assign_event_ids(rows: list[dict]) -> list[list[dict]]:
    gap = _cfg_int("HYDRO_EVENT_GAP_MIN", 180, 10, 1440)
    by_station = {}
    for row in sorted(rows, key=lambda r: (str(r.get("station_id") or ""), str(r.get("sample_start_time") or r.get("created_at") or ""))):
        by_station.setdefault(str(row.get("station_id") or ""), []).append(row)
    events=[]
    for sid, station_rows in by_station.items():
        cur=[]; cur_cells=set(); prev_dt=None; event_no=0
        for row in station_rows:
            dt=_dt(row.get("sample_start_time") or row.get("created_at"))
            cells=_event_cells(row)
            precip_active=bool(row.get("precip_event_active", (row.get("contributing_cell_count") or 0) > 0))
            prev_active=bool(cur[-1].get("precip_event_active", (cur[-1].get("contributing_cell_count") or 0) > 0)) if cur else False
            separated = False
            if cur and prev_dt and dt and (dt-prev_dt).total_seconds()/60.0 > gap:
                separated = True
            if cur and cells and cur_cells and cells.isdisjoint(cur_cells):
                separated = True
            if cur and precip_active and not prev_active and prev_dt and dt and (dt-prev_dt).total_seconds()/60.0 > gap:
                separated = True
            if cur and separated:
                events.append(cur); event_no += 1; cur=[]; cur_cells=set()
            eid=f"{sid}:event:{event_no}"
            row["event_id"] = eid
            cur.append(row); cur_cells |= cells; prev_dt = dt or prev_dt
        if cur: events.append(cur)
    return events



def _read_history_rows() -> list[dict]:
    if not HYDRO_HISTORY_PATH.exists():
        return []
    rows = []
    for line in HYDRO_HISTORY_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _lag_bounds_min() -> tuple[float, float]:
    raw = runtime_config.get("HYDRO_LAG_WINDOW_MIN", getattr(config, "HYDRO_LAG_WINDOW_MIN", [20, 180]))
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        lo = _f(raw[0], 20.0) or 20.0; hi = _f(raw[1], 180.0) or 180.0
    else:
        default_lag = runtime_config.get("HYDRO_DEFAULT_LAG_MIN", getattr(config, "HYDRO_DEFAULT_LAG_MIN", [20, 180]))
        if isinstance(default_lag, (list, tuple)) and len(default_lag) >= 2:
            lo = _f(default_lag[0], 20.0) or 20.0; hi = _f(default_lag[1], 180.0) or 180.0
        else:
            lo, hi = 20.0, _f(default_lag, 180.0) or 180.0
    return min(lo, hi), max(lo, hi)


def _label_from_future(start: dict, future_rows: list[dict], threshold: float | None) -> dict:
    if start.get("q_m3s") is None:
        return {"target_missing": True}
    start_dt = _dt(start.get("measured_at") or start.get("fetched_at"))
    if not start_dt:
        return {"target_missing": True}
    lo, hi = _lag_bounds_min()
    candidates = []
    for row in future_rows:
        if row.get("q_m3s") is None:
            continue
        dt = _dt(row.get("measured_at") or row.get("fetched_at"))
        if not dt:
            continue
        age = (dt - start_dt).total_seconds() / 60.0
        if lo <= age <= hi:
            candidates.append(row)
    if not candidates:
        return {"target_missing": True}
    future_q = max((_f(r.get("q_m3s"), start.get("q_m3s")) or start.get("q_m3s")) for r in candidates)
    delta = future_q - float(start.get("q_m3s"))
    exceeded = bool(future_q >= threshold) if threshold is not None else None
    min_delta = _f(runtime_config.get("HYDRO_VERIFY_MIN_DELTA_Q_M3S", getattr(config, "HYDRO_VERIFY_MIN_DELTA_Q_M3S", 0.2)), 0.2) or 0.2
    return {"target_missing": False, "target_q_delta_m3s": round(delta, 3), "target_q_max_m3s": round(future_q, 3), "target_q_threshold_exceeded": exceeded, "target_flood_expected": (bool(exceeded and delta >= -abs(min_delta)) if exceeded is not None else None), "target_q_distance_to_threshold_after_reaction_m3s": (round(threshold - future_q, 3) if threshold is not None else None)}


def build_dataset_scan() -> dict:
    HYDRO_ML_DIR.mkdir(parents=True, exist_ok=True)
    migrate_productive_dataset()
    history = sorted(_read_history_rows(), key=lambda r: (str(r.get("station_id")), str(r.get("measured_at") or r.get("fetched_at") or "")))
    by_station: dict[str, list[dict]] = {}
    for row in history:
        by_station.setdefault(str(row.get("station_id") or ""), []).append(row)
    samples = []
    for sid, rows in by_station.items():
        for i, row in enumerate(rows):
            station = {"station_id": sid, "name": row.get("station_name"), "river": row.get("river"), "lat": row.get("lat"), "lon": row.get("lon"), "q_m3s": row.get("q_m3s"), "data_age_min": row.get("data_age_min")}
            features = build_feature_row(station)
            label = _label_from_future(row, rows[i+1:], features.get("station_q_threshold_m3s"))
            sample_id = hashlib.sha256(json.dumps({"station_id": sid, "sample_start_time": row.get("measured_at") or row.get("fetched_at"), "kind": SAMPLE_KIND_LEGACY}, sort_keys=True, default=str).encode()).hexdigest()
            samples.append({**features, **label, "sample_id": sample_id, "sample_kind": SAMPLE_KIND_LEGACY, "feature_schema_version": FEATURE_SCHEMA_VERSION, "feature_snapshot_complete": False, "missing_required_features": _missing_required_features(features), "catchment_signature": None, "cell_frame_hash": None, "config_signature": None, "sample_start_time": row.get("measured_at") or row.get("fetched_at")})
    existing = {r.get("sample_id"): r for r in _jsonl_rows(HYDRO_DATASET_PATH) if r.get("sample_id")}
    for sample in samples:
        existing[sample["sample_id"]] = sample
    _write_jsonl(HYDRO_DATASET_PATH, list(existing.values()))
    meta=_read_json(HYDRO_TRAINING_META_PATH,{})
    meta.update({"last_dataset_build_at": _now(), "legacy_q_sample_count": len(existing), "productive_dataset_path": str(HYDRO_DATASET_JSONL_PATH), "legacy_dataset_path": str(HYDRO_DATASET_PATH), "note": "Legacy-Q-Scan bleibt getrennt und wird nicht in produktives Training gemergt."})
    _atomic_json(HYDRO_TRAINING_META_PATH, meta)
    return readiness_status() | {"status":"dataset_scanned", "dataset_path": str(HYDRO_DATASET_JSONL_PATH), "legacy_dataset_path": str(HYDRO_DATASET_PATH)}


def _file_sha256(path: Path) -> str | None:
    try:
        h=hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024*1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None

def model_signature(model_dir: Path | None = None) -> dict:
    model_dir = model_dir or HYDRO_MODEL_CURRENT_DIR
    mp=model_dir/HYDRO_MODEL_FILENAME; mt=model_dir/"metadata.json"
    out={"path": str(mp), "exists": mp.exists(), "metadata_path": str(mt), "metadata_exists": mt.exists()}
    for prefix,path in (("model",mp),("metadata",mt)):
        try:
            st=path.stat(); out[f"{prefix}_mtime_ns"]=st.st_mtime_ns; out[f"{prefix}_size"]=st.st_size; out[f"{prefix}_sha256"]=_file_sha256(path)
        except OSError:
            out[f"{prefix}_mtime_ns"]=None; out[f"{prefix}_size"]=None; out[f"{prefix}_sha256"]=None
    return out

def _dump_artifact(path: Path, artifact: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    try:
        import joblib
        joblib.dump(artifact, tmp)
        os.replace(tmp, path)
    except Exception:
        tmp.write_bytes(pickle.dumps(artifact)); os.replace(tmp, path)

def _load_artifact(path: Path) -> dict:
    try:
        import joblib
        return joblib.load(path)
    except Exception:
        return pickle.loads(path.read_bytes())

def _split_by_events(rows: list[dict]) -> tuple[list[dict], list[dict], dict]:
    events=_assign_event_ids(rows)
    min_train=_cfg_int("HYDRO_ML_MIN_TRAIN_EVENTS", 2, 1, 100000)
    min_val=_cfg_int("HYDRO_ML_MIN_VALIDATION_EVENTS", 1, 1, 100000)
    if len(events) < min_train + min_val:
        train_events=events; val_events=[]
    else:
        split=max(min_train, min(len(events)-min_val, int(len(events)*0.8)))
        train_events=events[:split]; val_events=events[split:]
    train=[r for ev in train_events for r in ev]; val=[r for ev in val_events for r in ev]
    train_ids={r.get("event_id") for r in train}; val_ids={r.get("event_id") for r in val}
    overlap=sorted(x for x in train_ids & val_ids if x)
    meta={"train_event_count": len(train_events), "validation_event_count": len(val_events), "event_count": len(events), "event_split_overlap": overlap, "independent_event_status": "ok" if not overlap and len(train_events)>=min_train and len(val_events)>=min_val else "insufficient_independent_events", "train_time_range": [train[0].get("sample_start_time") if train else None, train[-1].get("sample_start_time") if train else None], "validation_time_range": [val[0].get("sample_start_time") if val else None, val[-1].get("sample_start_time") if val else None]}
    return train, val, meta

def _active_model_mae(val: list[dict]) -> float | None:
    if not (HYDRO_MODEL_CURRENT_DIR/HYDRO_MODEL_FILENAME).exists(): return None
    errs=[]
    for r in val:
        pred=predict_q_delta(r)
        if pred.get("prediction_source") != "hydro_ml": return None
        y=_f(r.get("target_q_delta_m3s"))
        if y is not None and pred.get("predicted_q_delta_m3s") is not None:
            errs.append(abs(float(pred["predicted_q_delta_m3s"])-y))
    return sum(errs)/len(errs) if errs else None

def _promote_candidate(candidate_dir: Path, meta: dict) -> None:
    root=HYDRO_MODEL_ROOT_DIR; root.mkdir(parents=True, exist_ok=True)
    tmp=root/(".current_tmp_"+meta["new_active_version"])
    if tmp.exists(): shutil.rmtree(tmp)
    shutil.copytree(candidate_dir, tmp)
    backup=None
    if HYDRO_MODEL_CURRENT_DIR.exists():
        backup=HYDRO_MODEL_HISTORY_DIR/(meta.get("previous_active_version") or ("previous_"+meta["new_active_version"]))
        backup.parent.mkdir(parents=True, exist_ok=True)
        if backup.exists(): shutil.rmtree(backup)
        os.replace(HYDRO_MODEL_CURRENT_DIR, backup)
    try:
        os.replace(tmp, HYDRO_MODEL_CURRENT_DIR)
        art=_load_artifact(HYDRO_MODEL_CURRENT_DIR/HYDRO_MODEL_FILENAME)
        if art.get("feature_schema_version") != FEATURE_SCHEMA_VERSION: raise ValueError("post_promotion_schema_mismatch")
        _validate_model_integrity(HYDRO_MODEL_CURRENT_DIR)
        if HYDRO_MODEL_PREVIOUS_DIR.exists(): shutil.rmtree(HYDRO_MODEL_PREVIOUS_DIR)
        if backup: shutil.copytree(backup, HYDRO_MODEL_PREVIOUS_DIR)
    except Exception:
        if HYDRO_MODEL_CURRENT_DIR.exists(): shutil.rmtree(HYDRO_MODEL_CURRENT_DIR)
        if backup and backup.exists(): shutil.copytree(backup, HYDRO_MODEL_CURRENT_DIR)
        raise

def train_model() -> dict:
    materialize_pending_samples(); migration=migrate_productive_dataset()
    rows=load_trainable_labeled_samples(True)
    if len(rows) < MIN_TRAINING_SAMPLES:
        status = readiness_status(); status.update({"status": "insufficient_data", "fallback_reason": ",".join(status.get("rejection_reasons") or []), "dataset_migration": migration})
        return status
    rows.sort(key=lambda r: str(r.get("sample_start_time") or r.get("created_at") or ""))
    train,val,split_meta=_split_by_events(rows)
    if split_meta.get("independent_event_status") != "ok" or not val:
        return {"status": "insufficient_independent_events", "promoted": False, **split_meta}
    X_train=[_feature_vector(r) for r in train]
    y_train=[(_f(r.get("target_q_delta_m3s"),0.0) or 0.0) - (_f((r.get("features") or r).get("physical_predicted_q_delta_m3s"),0.0) or 0.0) for r in train]
    X_val=[_feature_vector(r) for r in val]
    model_type="hist_gradient_boosting_residual"
    try:
        from sklearn.ensemble import HistGradientBoostingRegressor
        model=HistGradientBoostingRegressor(max_iter=80, learning_rate=0.06, l2_regularization=0.01, random_state=42).fit(X_train,y_train)
        residual_pred=model.predict(X_val)
    except Exception:
        model_type="feature_linear_residual"; cols=list(zip(*X_train)) if X_train else []; y_mean=sum(y_train)/len(y_train) if y_train else 0.0; best=(0.0,0,0.0,y_mean)
        for idx,col in enumerate(cols):
            x_mean=sum(col)/len(col); var=sum((x-x_mean)**2 for x in col)
            if var<=0: continue
            cov=sum((x-x_mean)*(y-y_mean) for x,y in zip(col,y_train)); slope=cov/var; intercept=y_mean-slope*x_mean
            if abs(cov)>best[0]: best=(abs(cov),idx,slope,intercept)
        _,feat_idx,slope,intercept=best; model={"feature_idx":feat_idx,"slope":slope,"intercept":intercept}; residual_pred=[slope*x[feat_idx]+intercept for x in X_val]
    errs=[]; fb_errs=[]; preds=[]
    for r,residual in zip(val,residual_pred):
        y=_f(r.get("target_q_delta_m3s"),0.0) or 0.0; phys=_f((r.get("features") or r).get("physical_predicted_q_delta_m3s"),0.0) or 0.0
        pred=max(0.0, phys+float(residual)); preds.append(pred); errs.append(pred-y); fb_errs.append(phys-y)
    mae=sum(abs(e) for e in errs)/len(errs); rmse=math.sqrt(sum(e*e for e in errs)/len(errs)); fb_mae=sum(abs(e) for e in fb_errs)/len(fb_errs)
    active_mae=_active_model_mae(val); finite=all(math.isfinite(x) for x in preds+[mae,rmse,fb_mae])
    baseline=fb_mae if active_mae is None else min(fb_mae, active_mae)
    promoted=finite and split_meta.get("independent_event_status") == "ok" and split_meta["validation_event_count"] >= _cfg_int("HYDRO_ML_MIN_VALIDATION_EVENTS", 1, 1, 100000) and mae <= baseline*1.05
    run_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")+"_"+hashlib.sha256(os.urandom(8)).hexdigest()[:8]
    cand=HYDRO_MODEL_CANDIDATES_DIR/run_id; cand.mkdir(parents=True, exist_ok=True)
    artifact={"feature_schema_version": FEATURE_SCHEMA_VERSION, "feature_schema_hash": _feature_schema_hash(), "type": model_type, "model": model, "feature_names": HYDRO_FLOOD_ML_FEATURES}
    _dump_artifact(cand/HYDRO_MODEL_FILENAME, artifact)
    prev_meta=_read_json(HYDRO_MODEL_CURRENT_DIR/"metadata.json", {})
    meta={"status":"trained", "run_id": run_id, "model_type": model_type, "feature_schema_version": FEATURE_SCHEMA_VERSION, "feature_schema_hash": _feature_schema_hash(), "feature_names": HYDRO_FLOOD_ML_FEATURES, "imputation_rule": "Samples mit fehlenden Pflichtfeatures werden vom produktiven Training ausgeschlossen; Modellvektor erhält nur für kompatible vollständige Snapshots numerische Werte.", "trained_at": _now(), "last_training_at": _now(), "sample_count": len(rows), "station_count": len({r.get("station_id") for r in rows}), "event_count": len({_event_key(r) for r in rows}), "candidate_mae": round(mae,4), "mae": round(mae,4), "rmse": round(rmse,4), "physical_fallback_mae": round(fb_mae,4), "active_model_mae": round(active_mae,4) if active_mae is not None else None, "promotion_baseline": "active_model" if active_mae is not None and active_mae <= fb_mae else "physical_fallback", "promoted": promoted, "promotion_decision": "promoted" if promoted else "rejected", "promotion_reason": "candidate_beats_selected_baseline" if promoted else "validation_not_better_than_physical_or_active_baseline", "previous_active_version": prev_meta.get("new_active_version") or prev_meta.get("trained_at"), "new_active_version": run_id, "model_filename": HYDRO_MODEL_FILENAME, **split_meta}
    _atomic_json(cand/"metadata.json", meta); _atomic_json(cand/"validation.json", {"candidate_mae": mae, "physical_fallback_mae": fb_mae, "active_model_mae": active_mae, **split_meta})
    meta["model_signature"] = model_signature(cand); _atomic_json(cand/"metadata.json", meta); _write_model_manifest(cand, meta)
    if promoted:
        _promote_candidate(cand, meta)
        meta["active_model_signature"] = model_signature(HYDRO_MODEL_CURRENT_DIR)
    _atomic_json(HYDRO_TRAINING_META_PATH, meta)
    with _sample_db() as con:
        con.execute("INSERT OR REPLACE INTO training_runs(run_id, created_at, payload) VALUES(?,?,?)", (run_id, meta["trained_at"], json.dumps(meta, ensure_ascii=False, default=str)))
    return meta

def _write_model_manifest(model_dir: Path, meta: dict) -> dict:
    sig = model_signature(model_dir)
    manifest = {"manifest_schema_version": "b411_model_manifest_v1", "created_at": _now(), "model_filename": HYDRO_MODEL_FILENAME, "model_sha256": sig.get("model_sha256"), "metadata_payload_sha256": sig.get("metadata_sha256"), "artifact_schema_hash": meta.get("feature_schema_hash"), "feature_schema_version": meta.get("feature_schema_version"), "feature_names": meta.get("feature_names"), "promoted": bool(meta.get("promoted"))}
    _atomic_json(model_dir/"manifest.json", manifest)
    return manifest

def _validate_model_integrity(model_dir: Path = HYDRO_MODEL_CURRENT_DIR) -> dict:
    meta_path=model_dir/"metadata.json"; model_path=model_dir/HYDRO_MODEL_FILENAME; manifest_path=model_dir/"manifest.json"
    meta=_read_json(meta_path, {})
    if meta and (meta.get("feature_schema_version") != FEATURE_SCHEMA_VERSION or meta.get("feature_names") != HYDRO_FLOOD_ML_FEATURES):
        raise ValueError("feature_schema_mismatch")
    if not meta_path.exists() or not model_path.exists() or not manifest_path.exists():
        raise ValueError("model_integrity_error:missing_file")
    manifest=_read_json(manifest_path, {})
    sig=model_signature(model_dir)
    if sig.get("model_sha256") != manifest.get("model_sha256"):
        raise ValueError("model_integrity_error:hash_mismatch")
    if sig.get("metadata_sha256") != manifest.get("metadata_payload_sha256"):
        if meta.get("promoted") is True:
            manifest["metadata_payload_sha256"] = sig.get("metadata_sha256")
        else:
            raise ValueError("model_integrity_error:hash_mismatch")
    if meta.get("feature_schema_hash") != manifest.get("artifact_schema_hash") or meta.get("feature_schema_hash") != _feature_schema_hash():
        raise ValueError("model_integrity_error:schema_hash_mismatch")
    if meta.get("feature_schema_version") != FEATURE_SCHEMA_VERSION or meta.get("feature_names") != HYDRO_FLOOD_ML_FEATURES or not meta.get("promoted"):
        raise ValueError("model_integrity_error:metadata_mismatch")
    art=_load_artifact(model_path)
    if art.get("feature_schema_hash") != _feature_schema_hash() or art.get("feature_names") != HYDRO_FLOOD_ML_FEATURES:
        raise ValueError("model_integrity_error:artifact_schema_mismatch")
    return {"metadata": meta, "artifact": art, "signature": sig, "manifest": manifest}

def load_active_hydro_model(force_reload: bool = False) -> dict:
    sig=model_signature(HYDRO_MODEL_CURRENT_DIR)
    key=json.dumps({"path": sig.get("path"), "mtime_ns": sig.get("model_mtime_ns"), "size": sig.get("model_size"), "metadata_mtime_ns": sig.get("metadata_mtime_ns"), "schema": FEATURE_SCHEMA_VERSION}, sort_keys=True)
    with _MODEL_CACHE_LOCK:
        if not force_reload and _MODEL_CACHE.get("key") == key:
            return {**_MODEL_CACHE, "model_cache_status": "hit"}
        validated=_validate_model_integrity(HYDRO_MODEL_CURRENT_DIR)
        meta=validated["metadata"]
        art=validated["artifact"]
        loaded_at=_now()
        _MODEL_CACHE.clear(); _MODEL_CACHE.update({"key": key, "metadata": meta, "artifact": art, "signature": sig, "model_loaded_at": loaded_at, "model_version": meta.get("new_active_version") or meta.get("trained_at")})
        return {**_MODEL_CACHE, "model_cache_status": "miss"}

def predict_q_delta(row: dict) -> dict:
    q=_f(row.get("current_q_m3s")); phys=max(0.0, _f(row.get("physical_predicted_q_delta_m3s"), 0.0) or 0.0); phys_max=max(0.0, (q or 0.0)+phys) if q is not None else None
    base={"physical_predicted_q_delta_m3s": phys, "ml_predicted_q_delta_m3s": None, "predicted_q_delta_m3s": phys if q is not None else None, "predicted_q_max_m3s": phys_max, "prediction_source": "physical_fallback" if q is not None else "not_evaluable", "model_version": None, "model_rejection_reason": None, "model_cache_status": None, "model_loaded_at": None, "model_signature": model_signature(HYDRO_MODEL_CURRENT_DIR)}
    try:
        loaded=load_active_hydro_model(); meta=loaded["metadata"]; art=loaded["artifact"]
        base.update({"model_cache_status": loaded.get("model_cache_status"), "model_loaded_at": loaded.get("model_loaded_at"), "model_version": loaded.get("model_version"), "model_signature": loaded.get("signature")})
        if not meta.get("promoted"): base["model_rejection_reason"]="model_not_promoted"; return base
        if meta.get("feature_schema_version") != FEATURE_SCHEMA_VERSION or meta.get("feature_names") != HYDRO_FLOOD_ML_FEATURES: base["model_rejection_reason"]="feature_schema_mismatch"; return base
        vec=_feature_vector(row)
        if art.get("type") == "feature_linear_residual":
            m=art["model"]; residual=float(m["slope"]*vec[int(m["feature_idx"])] + m["intercept"])
        else: residual=float(art["model"].predict([vec])[0])
        if not math.isfinite(residual): raise ValueError("non_finite_prediction")
        if q is None: raise ValueError("missing_current_q")
        cap=max(phys*5.0+10.0, 10.0); delta=max(0.0, min(phys+residual, cap))
        return {**base, "ml_predicted_q_delta_m3s": round(delta,4), "predicted_q_delta_m3s": round(delta,4), "predicted_q_max_m3s": round(max(0.0, q+delta),4), "prediction_source": "hydro_ml", "model_rejection_reason": None}
    except Exception as exc:
        msg = f"{type(exc).__name__}: {exc}"
        base["model_rejection_reason"] = "feature_schema_mismatch" if "feature_schema_mismatch" in msg else ("model_integrity_error" if "model_integrity_error" in msg else msg)
        return base

def accuracy_status() -> dict:
    rows=[]
    if HYDRO_ACCURACY_HISTORY_PATH.exists():
        rows=[json.loads(l) for l in HYDRO_ACCURACY_HISTORY_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]
    latest = rows[-1] if rows else {}
    return {"status":"ok", "history": rows[-100:], "flood_precision": latest.get("flood_precision"), "flood_recall": latest.get("flood_recall"), "flood_false_alarm_rate": latest.get("flood_false_alarm_rate"), "flood_miss_rate": latest.get("flood_miss_rate")}



def _deferred_status_from_cell_meta(cell_frame_meta: dict | None) -> str:
    status = (cell_frame_meta or {}).get("cell_frame_status") or (cell_frame_meta or {}).get("status")
    return {
        "missing": "deferred_missing_cell_snapshot",
        "stale": "deferred_stale_cell_snapshot",
        "invalid": "deferred_invalid_cell_snapshot",
        "error": "deferred_cell_snapshot_error",
    }.get(status, "deferred_missing_cell_snapshot")


def _mark_row_forecast_deferred(row: dict, generated_at: str | None, status: str) -> None:
    q = _f(row.get("current_q_m3s")); thr = _f(row.get("station_q_threshold_m3s"))
    stale_predicted = row.get("predicted_q_max_m3s")
    if stale_predicted is not None:
        row["stale_predicted_q_max_m3s"] = stale_predicted
        row["stale_prediction_generated_at"] = generated_at
    row["predicted_q_max_m3s"] = None
    row["forecast_flood_evaluable"] = False
    row["forecast_evaluation_stale"] = True
    row["forecast_evaluation_generated_at"] = generated_at
    dt=_dt(generated_at)
    row["forecast_evaluation_age_min"] = round((datetime.now(timezone.utc)-dt).total_seconds()/60.0, 3) if dt else None
    if q is None:
        row.update({"flood_expected": False, "flood_evaluable": False, "current_threshold_evaluable": False, "current_q_above_threshold": False, "flood_status": "missing_current_q", "reasons": [], "warning_reasons": ["missing_current_q"]})
    elif thr is None:
        row.update({"flood_expected": False, "flood_evaluable": False, "current_threshold_evaluable": False, "current_q_above_threshold": False, "flood_status": "missing_threshold", "reasons": [], "warning_reasons": ["missing_station_q_threshold"]})
    elif q >= thr:
        row.update({"flood_expected": True, "flood_evaluable": True, "current_threshold_evaluable": True, "current_q_above_threshold": True, "flood_status": "threshold_already_exceeded", "reasons": ["current_q_m3s >= station_q_threshold_m3s"], "warning_reasons": []})
    else:
        row.update({"flood_expected": False, "flood_evaluable": False, "current_threshold_evaluable": True, "current_q_above_threshold": False, "flood_status": status, "reasons": [], "warning_reasons": []})


def refresh_hydro_fields_in_cached_risk(cached_doc: dict, live_doc: dict | None) -> dict:
    doc = dict(cached_doc or {})
    by_id = {str(s.get("station_id") or ""): s for s in ((live_doc or {}).get("stations") or []) if isinstance(s, dict)}
    generated_at = doc.get("generated_at")
    status = _deferred_status_from_cell_meta((live_doc or {}).get("cell_frame_meta") if isinstance(live_doc, dict) else None)
    trend_history = load_q_trend_history()
    for row in doc.get("stations") or []:
        if not isinstance(row, dict):
            continue
        live = by_id.get(str(row.get("station_id") or ""))
        if live:
            q = _f(live.get("q_m3s"))
            measured_at = live.get("measured_at") or live.get("fetched_at") or (live_doc or {}).get("fetched_at")
            row["current_q_m3s"] = q
            row["current_q_measured_at"] = measured_at
            row["current_q_timestamp_source"] = "hydro_live.measured_at" if live.get("measured_at") else "hydro_live.fetched_at_fallback"
            row["current_data_age_min"] = _f(live.get("data_age_min"))
            row["data_age_min"] = _f(live.get("data_age_min"))
            thr = _f(row.get("station_q_threshold_m3s"))
            row["current_q_distance_to_threshold_m3s"] = (thr - q) if (thr is not None and q is not None) else None
            row["current_q_ratio_threshold"] = (q / thr) if (thr not in (None, 0) and q is not None) else None
            trend = _q_trend_fields(str(row.get("station_id") or ""), q, measured_at, trend_history)
            for key in ("q_trend_status", "q_trend_delta_m3s", "q_trend_reference_window_min", "current_q_trend_10min", "current_q_trend_30min", "current_q_trend_60min", "q_trend_per_hour", "already_rising_flag"):
                if key in trend:
                    row[key] = trend[key]
        _mark_row_forecast_deferred(row, generated_at, status)
    doc["forecast_evaluation_stale"] = True
    doc["forecast_evaluation_generated_at"] = generated_at
    dt=_dt(generated_at)
    doc["forecast_evaluation_age_min"] = round((datetime.now(timezone.utc)-dt).total_seconds()/60.0, 3) if dt else None
    return doc


def build_deferred_public_risk(live_doc: dict, cell_frame_meta: dict, previous_doc: dict | None = None) -> dict:
    live = dict(live_doc or {})
    live["cell_frame_meta"] = cell_frame_meta or {}
    status = _deferred_status_from_cell_meta(cell_frame_meta)
    if isinstance(previous_doc, dict) and previous_doc.get("stations"):
        doc = refresh_hydro_fields_in_cached_risk(previous_doc, live)
    else:
        stations = [{**s, "mark_q_m3s": s.get("mark_q_m3s") or s.get("q_threshold")} for s in live.get("stations") or [] if isinstance(s, dict)]
        doc = evaluate_live_flood_risk(stations=stations, live=live, cells=[], write=False, include_debug=False)
        for row in doc.get("stations") or []:
            _mark_row_forecast_deferred(row, doc.get("generated_at"), status)
    doc.update({"status": status, "payload_scope": "public", "deferred_reason": status, "hydro_live_updated_at": live.get("fetched_at"), "cell_frame_path": (cell_frame_meta or {}).get("path"), "cell_frame_timestamp": (cell_frame_meta or {}).get("frame_timestamp"), "cell_frame_age_min": (cell_frame_meta or {}).get("frame_age_min"), "cell_frame_status": (cell_frame_meta or {}).get("status") or (cell_frame_meta or {}).get("cell_frame_status"), "warning": "Hydro-Flood-Risk-Cache wegen fehlendem, ungültigem oder veraltetem Zellframe nicht überschrieben."})
    doc["stations"] = [_public_flood_row(r) for r in doc.get("stations") or [] if isinstance(r, dict)]
    return doc

def export_labeled_samples_jsonl(path: Path = HYDRO_DATASET_JSONL_PATH) -> dict:
    rows = load_trainable_labeled_samples(False)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False, default=str)+"\n")
            fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        try:
            if os.path.exists(tmp): os.unlink(tmp)
        except Exception: pass
    return {"sqlite_row_count": len(rows), "jsonl_snapshot_row_count": len(rows), "snapshot_generated_at": _now(), "snapshot_source_db_sha": _file_sha256(HYDRO_SAMPLE_DB_PATH), "path": str(path)}

def hydro_ml_maintenance() -> dict:
    now_dt=datetime.now(timezone.utc); db_size_before=HYDRO_SAMPLE_DB_PATH.stat().st_size if HYDRO_SAMPLE_DB_PATH.exists() else 0
    fail_days=_cfg_int("HYDRO_FAILED_SAMPLE_RETENTION_DAYS", 30, 1, 3650)
    data_days=_cfg_int("HYDRO_DATASET_RETENTION_DAYS", 365, 1, 3650)
    report={"deleted_failure_rows":0,"deleted_dataset_rows":0,"deleted_training_runs":0,"deleted_candidates":0,"deleted_history_versions":0,"db_size_before":db_size_before}
    with _sample_db() as con:
        fail_cut=(now_dt-timedelta(days=fail_days)).isoformat().replace("+00:00","Z")
        data_cut=(now_dt-timedelta(days=data_days)).isoformat().replace("+00:00","Z")
        cur=con.execute("DELETE FROM sample_failures WHERE failed_at < ?", (fail_cut,)); report["deleted_failure_rows"]=cur.rowcount
        cur=con.execute("DELETE FROM labeled_samples WHERE sample_start_time < ?", (data_cut,)); report["deleted_dataset_rows"]=cur.rowcount
        old=[r[0] for r in con.execute("SELECT run_id FROM training_runs ORDER BY created_at DESC LIMIT -1 OFFSET 50").fetchall()]
        for run_id in old: con.execute("DELETE FROM training_runs WHERE run_id=?", (run_id,))
        report["deleted_training_runs"]=len(old)
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)"); con.execute("PRAGMA optimize")
    for directory,key,keep in ((HYDRO_MODEL_CANDIDATES_DIR,"deleted_candidates",20),(HYDRO_MODEL_HISTORY_DIR,"deleted_history_versions",10)):
        if directory.exists():
            entries=sorted([x for x in directory.iterdir() if x.is_dir()], key=lambda x: x.stat().st_mtime, reverse=True)
            for victim in entries[keep:]:
                shutil.rmtree(victim, ignore_errors=True); report[key]+=1
    report["db_size_after"] = HYDRO_SAMPLE_DB_PATH.stat().st_size if HYDRO_SAMPLE_DB_PATH.exists() else 0
    return report

def flood_risk_status() -> dict:
    risk = _read_json(HYDRO_RISK_PATH, {})
    ready = readiness_status(); acc = accuracy_status()
    return {**ready, "status":"ok", "model_source": "ml" if ready.get("model_available") and ready.get("readiness_status")=="ready" else "heuristic_scoring", "last_evaluation_at": risk.get("generated_at"), "fallback_reason": ",".join(ready.get("rejection_reasons") or []), "flood_precision": acc.get("flood_precision"), "flood_recall": acc.get("flood_recall"), "flood_false_alarm_rate": acc.get("flood_false_alarm_rate"), "flood_miss_rate": acc.get("flood_miss_rate")}


def diagnose_station(station_id: str) -> str:
    live = None
    try:
        import hydro_fetch
        live = hydro_fetch.load_latest_hydro_live(max_age_seconds=None)
    except Exception:
        live = None
    cells, meta = load_latest_cell_frame()
    doc = evaluate_live_flood_risk(live=live, cells=cells or [], write=False)
    row = next((s for s in doc.get("stations", []) if str(s.get("station_id")) == str(station_id)), None)
    if not row:
        return f"Station {station_id}: nicht gefunden\nverwendeter Zellframe: {meta}"
    lines = [
        f"Station: {row.get('station_name')} ({row.get('station_id')})",
        f"aktuelles Q: {row.get('current_q_m3s')} m³/s",
        f"Grenzwert: {row.get('station_q_threshold_m3s')} m³/s",
        f"Catchment verfügbar: {row.get('catchment_geometry_available')} ({row.get('catchment_geometry_status')})",
        f"verwendeter Zellframe: {meta.get('path')} ({meta.get('cell_count')} Zellen)",
        f"aktuelle Zelltreffer: {row.get('current_cell_count')}",
        f"einziehende Zellen: {row.get('incoming_cell_count')}",
    ]
    for c in row.get("cell_diagnostics") or []:
        lines.append(f"Zelle {c.get('cell_id')}: Fläche {c.get('cell_area_km2')} km², Intensität {c.get('rain_rate_mm_h')} mm/h ({c.get('rain_rate_source')}), Eintritt {c.get('entry_offset_min')} min, Austritt {c.get('exit_offset_min')} min, Aufenthalt {c.get('dwell_time_min')} min")
    lines += [
        f"physikalischer Q-Beitrag: {row.get('physical_predicted_q_delta_m3s')} m³/s",
        f"ML-/Fallback-Quelle: {row.get('prediction_source')}",
        f"maximal vorhergesagtes Q: {row.get('predicted_q_max_m3s')} m³/s",
        f"Hochwasserentscheidung: {row.get('flood_expected')} ({row.get('flood_status')})",
        f"Warnungen: {', '.join(row.get('warning_reasons') or []) or '—'}",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--diagnose-station")
    args = parser.parse_args()
    if args.diagnose_station:
        print(diagnose_station(args.diagnose_station))
