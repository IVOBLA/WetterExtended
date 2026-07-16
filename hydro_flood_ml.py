"""Eigenständige Hydro-Flood-ML-/Fallback-Bewertung.

Der Modulpfad ist bewusst getrennt vom Zellbewegungs-ML: er liest keine
Bewegungsmodell-Artefakte und schreibt ausschließlich unter train_data/hydro
bzw. train_data/models/hydro_flood.
"""
from __future__ import annotations

import hashlib, json, math, os, pickle, tempfile
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
FEATURE_SCHEMA_VERSION = "b409_q_delta_v1"
HYDRO_MODEL_FILENAME = "model.joblib"
HYDRO_FLOOD_ML_FEATURES = [
    "current_q_m3s", "current_q_ratio_threshold", "current_q_distance_to_threshold_m3s",
    "q_trend_delta_m3s", "q_trend_reference_window_min", "already_rising_flag",
    "catchment_area_km2", "upstream_catchment_count", "routing_tau_min",
    "contributing_cell_count", "current_cell_count", "incoming_cell_count",
    "total_rain_volume_m3", "total_runoff_volume_m3", "total_dwell_time_min",
    "max_cell_dwell_time_min", "effective_overlap_area_km2", "overlap_area_time_km2_min",
    "cell_catchment_area_km2_sum", "rain_rate_mm_h_max", "rain_rate_mm_h_mean",
    "rain_rate_mm_h_area_weighted", "first_entry_offset_min", "last_exit_offset_min",
    "physical_predicted_q_delta_m3s", "physical_predicted_q_max_m3s", "data_age_min",
]

SOURCE_PRIORITY = {"measured": 0, "nowcast": 1, "radar_derived": 2, "cell_derived": 3, "proxy": 4, "missing": 9}
QUALITY_SCORE = {"high": 1.0, "medium": 0.7, "low": 0.4, "missing": 0.0}
INTENSITY_MM = {"heavy": 8.0, "strong": 12.0, "rot": 12.0, "red": 12.0, "severe": 20.0, "violett": 25.0, "purple": 25.0, "extreme": 35.0}


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

def load_latest_cell_frame() -> tuple[list[dict] | None, dict]:
    obj_dir = Path(config.SAVE_PATHS.get("objects", "train_data/objects"))
    try:
        files = sorted(obj_dir.glob("*.json"))
        if not files:
            return None, {"status": "missing", "path": None}
        path = files[-1]
        data = json.loads(path.read_text(encoding="utf-8"))
        cells = data.get("objects") if isinstance(data, dict) else data
        if not isinstance(cells, list):
            return None, {"status": "invalid", "path": str(path)}
        st = path.stat()
        active = [c for c in cells if is_hydro_relevant_cell(c)]
        return active, {"status": "ok", "path": str(path), "mtime_ns": st.st_mtime_ns, "size": st.st_size, "frame_time": path.stem, "cell_count": len(active), "raw_cell_count": len(cells)}
    except Exception as exc:
        return None, {"status": "error", "error": f"{type(exc).__name__}: {exc}"}


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
    payload = {"live": live_sig, "station_thresholds": overrides, "global_threshold": runtime_config.get("HYDRO_MAP_MARK_Q_M3S", getattr(config, "HYDRO_MAP_MARK_Q_M3S", None)), "objects": _objects_signature(cells), "q_trend": _trend_cache_signature(), "catchments": catch_sig, "hydro_config": hydro_cfg, "model": {"schema": model_meta.get("feature_schema_version"), "trained_at": model_meta.get("trained_at"), "promoted": model_meta.get("promoted")}}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def is_flood_risk_cache_valid(doc: dict | None, live: dict | None = None, cells: list[dict] | None = None) -> bool:
    if not isinstance(doc, dict) or not doc.get("input_hash"):
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
    base.update({"geometry_quality":"bbox_fallback","cell_catchment_count":count,"contributing_cell_count":count,"current_cell_count":current,"incoming_cell_count":incoming,"cell_catchment_precip_sum_mm":round(sum_mm,3),"cell_catchment_precip_weighted_sum_mm":round(wsum,3),"cell_catchment_max_intensity":round(max_int,3),"cell_catchment_area_km2_sum":round(area_sum,3),"cell_catchment_overlap_area_km2_sum":round(overlap,3),"raw_overlap_area_km2_sum":round(overlap,3),"effective_overlap_area_km2":round(effective_overlap,3),"overlap_deduplicated_area_km2":round(dedup,3),"spatial_dedup_applied":dedup>1e-6,"max_overlap_area_km2":round(effective_overlap,3),"cell_precip_source_type":"nowcast" if count else "none","total_rain_volume_m3":sum(d["rain_volume_m3"] for d in diags),"total_runoff_volume_m3":sum(d["runoff_volume_m3"] for d in diags),"total_dwell_time_min":sum(d["dwell_time_min"] for d in diags),"max_cell_dwell_time_min":max([d["dwell_time_min"] for d in diags] or [0]),"physical_predicted_q_delta_m3s":round(pred,4),"physical_predicted_q_max_m3s":round(q0+pred,4),"rain_rate_mm_h_max":round(max_int,3),"rain_rate_mm_h_mean":round(max_int,3),"rain_rate_mm_h_area_weighted":round(max_int,3),"cell_diagnostics":diags,"station_runoff_series":series})
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
            offs=[x[0] for x in raw_hits]; areas=[x[1] for x in raw_hits]
            cell_stats[cid] = {"cell_id": cid, "currently_inside": 0 in offs, "forecast_entry": min(offs) > 0, "entry_offset_min": min(offs), "exit_offset_min": max(offs), "dwell_time_min": max(step, (max(offs)-min(offs))+step), "cell_area_km2": round(cell_area,3), "max_overlap_area_km2": round(max(areas),3), "mean_overlap_area_km2": round(sum(areas)/len(areas),3), "overlap_area_time_km2_min": round(sum(areas)*step,3), "rain_rate_mm_h": round(rate,3), "rain_rate_source": rate_src, "intensity_forecast_mode": "persistence", "forecast_mode_used": sorted(modes)}
    series=[]; raw_total=0.0; eff_total=0.0; dedup_total=0.0; spatial_dedup=False; routed=0.0
    for off in sorted(per_time):
        parts=sorted(per_time[off], key=lambda x: x["rate"], reverse=True)
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
        alpha=1.0-math.exp(-step/tau)
        routed = routed*(1.0-alpha) + raw_q*attenuation*alpha
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
    return {**cdiag, "input_cell_count": len(cells or []), "cell_catchment_count": contributing, "contributing_cell_count": contributing, "current_cell_count": current, "incoming_cell_count": incoming, "cell_catchment_precip_sum_mm": round(total_rain / max(cdiag.get("catchment_area_geometry_km2") or 1.0, 1e-6) / 1000.0, 3), "cell_catchment_precip_weighted_sum_mm": round(total_rain / max(cdiag.get("catchment_area_geometry_km2") or 1.0, 1e-6) / 1000.0, 3), "cell_catchment_max_intensity": round(max([d.get("rain_rate_mm_h",0) for d in diags] or [0]),3), "cell_catchment_area_km2_sum": round(sum(d.get("cell_area_km2",0) for d in diags),3), "cell_catchment_overlap_area_km2_sum": round(raw_total,3), "raw_overlap_area_km2_sum": round(raw_total,3), "effective_overlap_area_km2": round(max([x["effective_overlap_area_km2"] for x in series] or [0]),3), "overlap_deduplicated_area_km2": round(dedup_total,3), "spatial_dedup_applied": spatial_dedup, "cell_catchment_overlap_ratio_max": round(max([d.get("max_overlap_area_km2",0)/max(d.get("cell_area_km2",1),1e-6) for d in diags] or [0]),4), "cell_precip_source_type": source if contributing else "none", "geometry_quality": "shapely", "routing_tau_min": round(tau,3), "routing_tau_source": tau_source, "precip_evaluable_by_geometry": True, "precip_status": status, "precip_status_label": label, "total_rain_volume_m3": round(total_rain,3), "total_runoff_volume_m3": round(total_runoff,3), "total_dwell_time_min": round(sum(d.get("dwell_time_min",0) for d in diags),3), "max_cell_dwell_time_min": round(max([d.get("dwell_time_min",0) for d in diags] or [0]),3), "max_overlap_area_km2": round(max([d.get("max_overlap_area_km2",0) for d in diags] or [0]),3), "overlap_area_time_km2_min": round(sum(d.get("overlap_area_time_km2_min",0) for d in diags),3), "physical_predicted_q_delta_m3s": round(pred_delta,4), "physical_predicted_q_max_m3s": round(max(0.0, q0+pred_delta),4), "first_entry_offset_min": min([d.get("entry_offset_min") for d in diags] or [None]), "last_exit_offset_min": max([d.get("exit_offset_min") for d in diags] or [None]), "rain_rate_mm_h_max": round(max([d.get("rain_rate_mm_h",0) for d in diags] or [0]),3), "rain_rate_mm_h_mean": round(sum(d.get("rain_rate_mm_h",0) for d in diags)/contributing,3) if contributing else 0.0, "rain_rate_mm_h_area_weighted": round((sum(d.get("rain_rate_mm_h",0)*d.get("max_overlap_area_km2",0) for d in diags) / max(sum(d.get("max_overlap_area_km2",0) for d in diags), 1e-6)),3) if contributing else 0.0, "cell_diagnostics": diags, "station_runoff_series": series[:24]}

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
    obs = _observed_precip(station); cellp = _precip_from_cells(station, cells or [])
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
    if q is None:
        warnings.append("missing_current_q")
        return {"hydro_flood_risk_score": None, "flood_expected": False, "flood_evaluable": False, "flood_status": "missing_current_q", "confidence": None, "reasons": reasons, "warning_reasons": warnings, "model_source": "heuristic_scoring", "prediction_source": "not_evaluable", "physical_predicted_q_delta_m3s": physical_delta, "ml_predicted_q_delta_m3s": None, "predicted_q_delta_m3s": None, "predicted_q_max_m3s": None}
    if thr is None:
        warnings.append("missing_station_q_threshold")
        return {"hydro_flood_risk_score": None, "flood_expected": False, "flood_evaluable": False, "flood_status": "missing_threshold", "confidence": None, "reasons": reasons, "warning_reasons": warnings, "model_source": "heuristic_scoring", "prediction_source": "physical_fallback", "physical_predicted_q_delta_m3s": physical_delta, "ml_predicted_q_delta_m3s": None, "predicted_q_delta_m3s": predicted_delta, "predicted_q_max_m3s": predicted_q}
    if not row.get("catchment_geometry_available") and row.get("precip_status") != "missing":
        warnings.append("catchment_geometry_missing")
        return {"hydro_flood_risk_score": None, "flood_expected": False, "flood_evaluable": False, "flood_status": "catchment_geometry_missing", "confidence": None, "reasons": reasons, "warning_reasons": warnings, "model_source": "heuristic_scoring", "prediction_source": "not_evaluable", "physical_predicted_q_delta_m3s": physical_delta, "ml_predicted_q_delta_m3s": None, "predicted_q_delta_m3s": predicted_delta, "predicted_q_max_m3s": predicted_q}
    status = "threshold_already_exceeded" if q >= thr else "ok"
    expected = bool((predicted_q or q) >= thr)
    if q >= thr: reasons.append("current_q_m3s >= station_q_threshold_m3s")
    return {"hydro_flood_risk_score": None, "flood_expected": expected, "flood_evaluable": True, "flood_status": status, "confidence": None, "reasons": reasons, "warning_reasons": warnings, "model_source": "heuristic_scoring", "prediction_source": "physical_fallback", "physical_predicted_q_delta_m3s": physical_delta, "ml_predicted_q_delta_m3s": None, "predicted_q_delta_m3s": predicted_delta, "predicted_q_max_m3s": predicted_q}

def evaluate_live_flood_risk(stations: list[dict]|None=None, live: dict|None=None, cells: list[dict]|None=None, write: bool=True) -> dict:
    if stations is None:
        import hydro_api
        stations = [f.get("properties") or {} for f in hydro_api.station_features(include_disabled=False).get("features", [])]
    generated = _now(); out=[]
    trend_history = load_q_trend_history()
    for st in stations or []:
        row = build_feature_row(st, live=live, cells=cells or [], trend_history=trend_history)
        pred = predict_q_delta(row)
        row_for_score = {**row, **pred}
        sc = heuristic_score(row_for_score)
        sc.update(pred)
        public = {k: row.get(k) for k in ["station_id","station_name","river","current_q_m3s","current_q_measured_at","current_q_timestamp_source","current_q_missing","station_q_threshold_m3s","station_q_threshold_source","station_q_threshold_missing","current_q_ratio_threshold","current_q_distance_to_threshold_m3s","catchment_geometry_available","catchment_geometry_status","catchment_feature_count","catchment_area_geometry_km2","catchment_area_km2","routing_tau_min","routing_tau_source","input_cell_count","contributing_cell_count","current_cell_count","incoming_cell_count","effective_catchment_precip_sum_mm","effective_catchment_precip_weighted_sum_mm","effective_precip_source_type","effective_precip_source_quality","precip_evaluable","precip_status","precip_status_label","precip_quality_label","cell_catchment_count","cell_catchment_overlap_area_km2_sum","raw_overlap_area_km2_sum","effective_overlap_area_km2","overlap_deduplicated_area_km2","spatial_dedup_applied","total_rain_volume_m3","total_runoff_volume_m3","total_dwell_time_min","max_cell_dwell_time_min","max_overlap_area_km2","overlap_area_time_km2_min","physical_predicted_q_delta_m3s","physical_predicted_q_max_m3s","first_entry_offset_min","last_exit_offset_min","rain_rate_mm_h_max","rain_rate_mm_h_mean","rain_rate_mm_h_area_weighted","cell_diagnostics","station_runoff_series","current_data_age_min","data_age_min","hydro_data_stale","current_q_trend_10min","current_q_trend_30min","current_q_trend_60min","q_trend_per_hour","already_rising_flag","q_trend_status","q_trend_delta_m3s","q_trend_reference_window_min"]}
        sc.pop("hydro_flood_risk_score", None); sc.pop("confidence", None)
        out.append(public | {"generated_at": generated, "flood_probability": None, **sc})
    cells_meta = _objects_signature(cells or [])
    pending_meta = record_pending_samples(out, live=live, cells_meta=cells_meta) if write else {"pending_added": 0, "pending_total": None}
    materialize_meta = materialize_pending_samples(live=None) if write else {"labeled_added": 0}
    doc = {"status":"ok", "generated_at": generated, "input_hash": flood_risk_input_hash(live=live, cells=cells or []), "stations": out, "pending_samples": pending_meta, "materialized_samples": materialize_meta, "readiness": readiness_status()}
    if write: _atomic_json(HYDRO_RISK_PATH, doc)
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
    return {k: row.get(k) for k in HYDRO_FLOOD_ML_FEATURES}

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


def record_pending_samples(rows: list[dict], live: dict | None = None, cells_meta: dict | None = None) -> dict:
    existing = {r.get("sample_id"): r for r in _jsonl_rows(HYDRO_PENDING_SAMPLES_PATH) if r.get("sample_id")}
    added=0
    for row in rows:
        if not row.get("station_id") or row.get("current_q_m3s") is None or not row.get("catchment_geometry_available"):
            continue
        start = row.get("current_q_measured_at") or (live or {}).get("fetched_at") or row.get("generated_at") or _now()
        sid=str(row.get("station_id"))
        sig={"station": sid, "start": start, "features": _feature_snapshot(row), "catchment": row.get("catchment_geometry_status"), "cells": cells_meta}
        sample_id=hashlib.sha256(json.dumps(sig, sort_keys=True, default=str).encode()).hexdigest()
        if sample_id in existing: continue
        existing[sample_id] = {"sample_id": sample_id, "feature_schema_version": FEATURE_SCHEMA_VERSION, "station_id": sid, "sample_start_time": start, "current_q_m3s": row.get("current_q_m3s"), "station_q_threshold_m3s": row.get("station_q_threshold_m3s"), "features": _feature_snapshot(row), "catchment_signature": row.get("catchment_geometry_status"), "cell_frame_hash": (cells_meta or {}).get("hash"), "config_signature": flood_risk_input_hash(cells=[]), "labeled": False, "created_at": _now()}
        added += 1
    _write_jsonl(HYDRO_PENDING_SAMPLES_PATH, list(existing.values()))
    return {"pending_added": added, "pending_total": len(existing)}


def materialize_pending_samples(live: dict | None = None) -> dict:
    pending=_jsonl_rows(HYDRO_PENDING_SAMPLES_PATH); dataset=_jsonl_rows(HYDRO_DATASET_JSONL_PATH)
    done={r.get("sample_id") for r in dataset}; rows_by_station={}
    hist=_read_history_rows()
    if live:
        append_hydro_history(live); hist=_read_history_rows()
    for r in hist: rows_by_station.setdefault(str(r.get("station_id") or ""), []).append(r)
    for rows in rows_by_station.values(): rows.sort(key=lambda r: str(r.get("measured_at") or r.get("fetched_at") or ""))
    added=0; remaining=[]
    for sample in pending:
        if sample.get("sample_id") in done or sample.get("labeled"):
            continue
        sid=str(sample.get("station_id") or ""); start_q=_f(sample.get("current_q_m3s")); thr=_f(sample.get("station_q_threshold_m3s"))
        label=_label_from_future({"measured_at": sample.get("sample_start_time"), "fetched_at": sample.get("sample_start_time"), "q_m3s": start_q}, rows_by_station.get(sid, []), thr)
        if label.get("target_missing"):
            remaining.append(sample); continue
        flat={k: v for k,v in (sample.get("features") or {}).items() if k != "w_cm"}
        dataset.append({**sample, **flat, **label, "labeled_at": _now()}); done.add(sample.get("sample_id")); added+=1
    _write_jsonl(HYDRO_DATASET_JSONL_PATH, dataset); _write_jsonl(HYDRO_PENDING_SAMPLES_PATH, remaining)
    return {"labeled_added": added, "pending_remaining": len(remaining), "dataset_count": len(dataset)}

def readiness_status() -> dict:
    meta = _read_json(HYDRO_TRAINING_META_PATH, {})
    rows=[]
    if HYDRO_DATASET_JSONL_PATH.exists():
        rows=[json.loads(l) for l in HYDRO_DATASET_JSONL_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]
    usable=[r for r in rows if not r.get("target_missing")]
    pos=sum(1 for r in usable if r.get("target_flood_expected") is True); neg=sum(1 for r in usable if r.get("target_flood_expected") is False)
    reasons=[]
    if len(usable) < MIN_TRAINING_SAMPLES: reasons.append("insufficient_samples")
    if pos == 0 or neg == 0: reasons.append("missing_class_diversity")
    coverage=dict(Counter((r.get("effective_precip_source_type") or "missing") for r in rows))
    return {"enabled": True, "model_available": (HYDRO_MODEL_CURRENT_DIR/"model.joblib").exists(), "sample_count": len(usable), "positive_samples": pos, "negative_samples": neg, "station_count": len({r.get("station_id") for r in rows}), "stations_with_threshold": len({r.get("station_id") for r in rows if not r.get("station_q_threshold_missing")}), "stations_without_threshold": len({r.get("station_id") for r in rows if r.get("station_q_threshold_missing")}), "precip_source_coverage": coverage, "last_training_at": meta.get("last_training_at"), "last_dataset_build_at": meta.get("last_dataset_build_at"), "readiness_status": "ready" if not reasons else "fallback", "rejection_reasons": reasons}


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
    # Historie wird nur aus bereits geladenen Hydro-Daten aufgebaut; ohne spätere
    # q_m3s-Beobachtung wird ein Sample nicht falsch gelabelt.
    HYDRO_ML_DIR.mkdir(parents=True, exist_ok=True)
    history = sorted(_read_history_rows(), key=lambda r: (str(r.get("station_id")), str(r.get("measured_at") or r.get("fetched_at") or "")))
    by_station: dict[str, list[dict]] = {}
    for row in history:
        by_station.setdefault(str(row.get("station_id") or ""), []).append(row)
    samples = []
    for sid, rows in by_station.items():
        for i, row in enumerate(rows):
            station = {"station_id": sid, "name": row.get("station_name"), "river": row.get("river"), "lat": row.get("lat"), "lon": row.get("lon"), "q_m3s": row.get("q_m3s"), "data_age_min": row.get("data_age_min")}
            # mark_q_m3s kommt zur Laufzeit aus Overrides/globalem Fallback, nicht aus einem neuen ML-Grenzwert.
            features = build_feature_row(station)
            label = _label_from_future(row, rows[i+1:], features.get("station_q_threshold_m3s"))
            samples.append({**features, **label, "sample_start_time": row.get("measured_at") or row.get("fetched_at")})
    existing = _jsonl_rows(HYDRO_DATASET_JSONL_PATH)
    by_id = {r.get("sample_id") or hashlib.sha256(json.dumps({"station_id": r.get("station_id"), "sample_start_time": r.get("sample_start_time")}, sort_keys=True, default=str).encode()).hexdigest(): r for r in existing}
    for sample in samples:
        sid = sample.get("station_id"); start = sample.get("sample_start_time")
        sample_id = sample.get("sample_id") or hashlib.sha256(json.dumps({"station_id": sid, "sample_start_time": start}, sort_keys=True, default=str).encode()).hexdigest()
        sample["sample_id"] = sample_id
        by_id.setdefault(sample_id, sample)
    _write_jsonl(HYDRO_DATASET_JSONL_PATH, list(by_id.values()))
    _write_jsonl(HYDRO_DATASET_PATH, samples)
    _atomic_json(HYDRO_TRAINING_META_PATH, {"last_dataset_build_at": _now(), "sample_count_total": len(by_id), "legacy_q_sample_count": len(samples), "note": "Legacy-Q-Scan wird gemergt; vollständige Zell-/Catchment-Samples bleiben erhalten."})
    return readiness_status() | {"status":"dataset_scanned", "dataset_path": str(HYDRO_DATASET_JSONL_PATH)}


def train_model() -> dict:
    materialize_pending_samples()
    rows=[r for r in _jsonl_rows(HYDRO_DATASET_JSONL_PATH) if not r.get("target_missing") and _f(r.get("target_q_delta_m3s")) is not None]
    if len(rows) < MIN_TRAINING_SAMPLES:
        status = readiness_status(); status.update({"status": "insufficient_data", "fallback_reason": ",".join(status.get("rejection_reasons") or [])})
        return status
    rows.sort(key=lambda r: str(r.get("sample_start_time") or r.get("created_at") or ""))
    split=max(1, int(len(rows)*0.8)); train=rows[:split]; val=rows[split:] or rows[-max(1, len(rows)//5):]
    X_train=[_feature_vector(r) for r in train]
    y_train=[(_f(r.get("target_q_delta_m3s"),0.0) or 0.0) - (_f((r.get("features") or r).get("physical_predicted_q_delta_m3s"),0.0) or 0.0) for r in train]
    X_val=[_feature_vector(r) for r in val]
    model_type = "hist_gradient_boosting_residual"
    try:
        from sklearn.ensemble import HistGradientBoostingRegressor
        model = HistGradientBoostingRegressor(max_iter=80, learning_rate=0.06, l2_regularization=0.01, random_state=42)
        model.fit(X_train, y_train)
        residual_pred = model.predict(X_val)
    except Exception:
        model_type = "feature_linear_residual"
        # Dependency-freier, feature-abhaengiger Regressor als Minimalfallback:
        # univariate Projektion auf das Feature mit der besten Korrelation.
        cols = list(zip(*X_train)) if X_train else []
        best = (0.0, 0, 0.0, sum(y_train)/len(y_train) if y_train else 0.0)
        y_mean = sum(y_train)/len(y_train) if y_train else 0.0
        for idx, col in enumerate(cols):
            x_mean = sum(col)/len(col); var = sum((x-x_mean)**2 for x in col)
            if var <= 0: continue
            cov = sum((x-x_mean)*(y-y_mean) for x,y in zip(col, y_train))
            slope = cov/var; intercept = y_mean - slope*x_mean
            score = abs(cov)
            if score > best[0]: best = (score, idx, slope, intercept)
        _, feat_idx, slope, intercept = best
        model = {"feature_idx": feat_idx, "slope": slope, "intercept": intercept}
        residual_pred = [slope*x[feat_idx]+intercept for x in X_val]
    errs=[]; fb_errs=[]; preds=[]
    for r, residual in zip(val, residual_pred):
        y=_f(r.get("target_q_delta_m3s"),0.0) or 0.0; phys=_f((r.get("features") or r).get("physical_predicted_q_delta_m3s"),0.0) or 0.0
        pred=max(0.0, phys+float(residual)); preds.append(pred)
        errs.append(pred-y); fb_errs.append(phys-y)
    mae=sum(abs(e) for e in errs)/len(errs); rmse=math.sqrt(sum(e*e for e in errs)/len(errs)); fb_mae=sum(abs(e) for e in fb_errs)/len(fb_errs)
    station_count=len({r.get("station_id") for r in rows})
    event_count=len({str(r.get("station_id"))+":"+str(r.get("sample_start_time"))[:10] for r in rows})
    finite=all(math.isfinite(x) for x in preds+[mae, rmse, fb_mae])
    promoted = finite and event_count >= 2 and mae <= fb_mae * 1.05
    HYDRO_MODEL_CURRENT_DIR.mkdir(parents=True, exist_ok=True)
    model_path = HYDRO_MODEL_CURRENT_DIR / HYDRO_MODEL_FILENAME
    artifact={"feature_schema_version": FEATURE_SCHEMA_VERSION, "type": model_type, "model": model, "feature_names": HYDRO_FLOOD_ML_FEATURES}
    try:
        import joblib
        joblib.dump(artifact, model_path)
    except Exception:
        model_path.write_bytes(pickle.dumps(artifact))
    meta={"status":"trained", "model_type": model_type, "feature_schema_version": FEATURE_SCHEMA_VERSION, "feature_names": HYDRO_FLOOD_ML_FEATURES, "trained_at": _now(), "last_training_at": _now(), "sample_count": len(rows), "station_count": station_count, "event_count": event_count, "mae": round(mae,4), "rmse": round(rmse,4), "physical_fallback_mae": round(fb_mae,4), "promoted": promoted, "promotion_decision": "promoted" if promoted else "fallback_kept", "rejection_reason": None if promoted else "validation_not_better_than_physical_fallback_or_insufficient_events", "model_filename": HYDRO_MODEL_FILENAME}
    _atomic_json(HYDRO_MODEL_CURRENT_DIR/"metadata.json", meta); _atomic_json(HYDRO_TRAINING_META_PATH, meta)
    return meta

def predict_q_delta(row: dict) -> dict:
    q=_f(row.get("current_q_m3s"))
    phys=max(0.0, _f(row.get("physical_predicted_q_delta_m3s"), 0.0) or 0.0)
    phys_max=max(0.0, (q or 0.0)+phys) if q is not None else None
    base={"physical_predicted_q_delta_m3s": phys, "ml_predicted_q_delta_m3s": None, "predicted_q_delta_m3s": phys if q is not None else None, "predicted_q_max_m3s": phys_max, "prediction_source": "physical_fallback" if q is not None else "not_evaluable", "model_version": None, "model_rejection_reason": None}
    meta=_read_json(HYDRO_MODEL_CURRENT_DIR/"metadata.json", {})
    if not meta.get("promoted"):
        base["model_rejection_reason"]="model_not_promoted"; return base
    if meta.get("feature_schema_version") != FEATURE_SCHEMA_VERSION or meta.get("feature_names") != HYDRO_FLOOD_ML_FEATURES:
        base["model_rejection_reason"]="feature_schema_mismatch"; return base
    model_path=HYDRO_MODEL_CURRENT_DIR/HYDRO_MODEL_FILENAME
    if not model_path.exists():
        base["model_rejection_reason"]="model_missing"; return base
    try:
        try:
            import joblib
            art=joblib.load(model_path)
        except Exception:
            art=pickle.loads(model_path.read_bytes())
        vec=_feature_vector(row)
        if art.get("type") == "feature_linear_residual":
            m=art["model"]; residual=float(m["slope"]*vec[int(m["feature_idx"])] + m["intercept"])
        else:
            residual=float(art["model"].predict([vec])[0])
        if not math.isfinite(residual): raise ValueError("non_finite_prediction")
        cap=max(phys*5.0+10.0, 10.0)
        delta=max(0.0, min(phys+residual, cap))
        if q is None: raise ValueError("missing_current_q")
        return {**base, "ml_predicted_q_delta_m3s": round(delta,4), "predicted_q_delta_m3s": round(delta,4), "predicted_q_max_m3s": round(max(0.0, q+delta),4), "prediction_source": "hydro_ml", "model_version": meta.get("trained_at"), "model_rejection_reason": None}
    except Exception as exc:
        base["model_rejection_reason"] = f"{type(exc).__name__}: {exc}"
        return base

def accuracy_status() -> dict:
    rows=[]
    if HYDRO_ACCURACY_HISTORY_PATH.exists():
        rows=[json.loads(l) for l in HYDRO_ACCURACY_HISTORY_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]
    latest = rows[-1] if rows else {}
    return {"status":"ok", "history": rows[-100:], "flood_precision": latest.get("flood_precision"), "flood_recall": latest.get("flood_recall"), "flood_false_alarm_rate": latest.get("flood_false_alarm_rate"), "flood_miss_rate": latest.get("flood_miss_rate")}


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
