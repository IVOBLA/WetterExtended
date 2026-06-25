"""Eigenständige Hydro-Flood-ML-/Fallback-Bewertung.

Der Modulpfad ist bewusst getrennt vom Zellbewegungs-ML: er liest keine
Bewegungsmodell-Artefakte und schreibt ausschließlich unter train_data/hydro
bzw. train_data/models/hydro_flood.
"""
from __future__ import annotations

import hashlib, json, math, os, tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config
import runtime_config

HYDRO_HISTORY_PATH = Path("train_data/hydro/live/hydro_history.jsonl")
HYDRO_ML_DIR = Path("train_data/hydro/ml")
HYDRO_DATASET_PATH = HYDRO_ML_DIR / "hydro_flood_dataset.parquet"
HYDRO_DATASET_JSONL_PATH = HYDRO_ML_DIR / "hydro_flood_dataset.jsonl"
HYDRO_TRAINING_META_PATH = HYDRO_ML_DIR / "hydro_flood_training_meta.json"
HYDRO_ACCURACY_HISTORY_PATH = HYDRO_ML_DIR / "hydro_flood_accuracy_history.jsonl"
HYDRO_RISK_PATH = Path("train_data/hydro/impact/latest_hydro_flood_risk.json")
HYDRO_MODEL_CURRENT_DIR = Path("train_data/models/hydro_flood/current")
MIN_TRAINING_SAMPLES = int(os.getenv("HYDRO_FLOOD_ML_MIN_SAMPLES", "20"))

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


def _objects_signature(cells: list[dict] | None) -> dict:
    items = []
    for c in cells or []:
        if not isinstance(c, dict):
            continue
        items.append({
            "id": c.get("id") or c.get("cell_id"),
            "ts": c.get("timestamp") or c.get("source_timestamp") or c.get("last_seen"),
            "rr15": c.get("nowcast_rr_mm15"),
            "rate": c.get("nowcast_rain_rate_1h") or c.get("rain_rate_mm_h") or c.get("precip_rate_mm_h"),
            "overlap": c.get("_hydro_overlap"),
        })
    return {"count": len(items), "items": items}


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
    payload = {
        "live": live_sig,
        "station_thresholds": overrides,
        "global_threshold": runtime_config.get("HYDRO_MAP_MARK_Q_M3S", getattr(config, "HYDRO_MAP_MARK_Q_M3S", None)),
        "objects": _objects_signature(cells),
    }
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


def _threshold(station: dict) -> tuple[float|None, str]:
    val = _f(station.get("mark_q_m3s"))
    if val is not None: return val, "station_override"
    fallback = runtime_config.get("HYDRO_MAP_MARK_Q_M3S", getattr(config, "HYDRO_MAP_MARK_Q_M3S", None))
    val = _f(fallback)
    if val is not None: return val, "global_fallback"
    return None, "missing"


def _rate(cell: dict) -> float:
    for k in ("nowcast_rain_rate_1h", "rain_rate_mm_h", "precip_rate_mm_h"):
        v = _f(cell.get(k))
        if v is not None: return v
    rr15 = _f(cell.get("nowcast_rr_mm15"))
    if rr15 is not None: return rr15 * 4.0
    return INTENSITY_MM.get(str(cell.get("intensity") or "").lower(), 2.0)


def _precip_from_cells(station: dict, cells: list[dict]) -> dict:
    try:
        import hydro_impact
    except Exception:
        hydro_impact = None
    catchment = station.get("_catchment_feature")
    count=0; sum_mm=0.0; wsum=0.0; area=0.0; oarea=0.0; max_ratio=0.0; max_core=0.0; max_int=0.0
    src_type = "missing"
    for c in cells or []:
        ov = c.get("_hydro_overlap") if isinstance(c.get("_hydro_overlap"), dict) else None
        if ov is None and hydro_impact and catchment:
            ov = hydro_impact.compute_cell_catchment_overlap(c, catchment)
        ov = ov or {}
        if not ov.get("hit"): continue
        if _f(ov.get("overlap_area_km2"), 0.0) < float(runtime_config.get("HYDRO_MIN_OVERLAP_AREA_KM2", getattr(config, "HYDRO_MIN_OVERLAP_AREA_KM2", 1.0))): continue
        count += 1
        rate = _rate(c); mm15 = _f(c.get("nowcast_rr_mm15")); mm = mm15 if mm15 is not None else rate/4.0
        ratio = _f(ov.get("overlap_ratio_cell"), 0.0) or 0.0
        oa = _f(ov.get("overlap_area_km2"), 0.0) or 0.0
        sum_mm += mm; wsum += mm * max(ratio, 0.0); area += _f(ov.get("cell_area_km2"), _f(c.get("area_km2"), 0.0)) or 0.0; oarea += oa
        max_ratio=max(max_ratio, ratio); max_core=max(max_core, _f(c.get("core_ratio"),0.0) or 0.0); max_int=max(max_int, rate)
        src_type = "nowcast" if (c.get("nowcast_rr_mm15") is not None or c.get("nowcast_rain_rate_1h") is not None) else "cell_derived"
    return {"cell_catchment_precip_sum_mm": round(sum_mm,3), "cell_catchment_precip_weighted_sum_mm": round(wsum,3), "cell_catchment_count": count, "cell_catchment_max_intensity": round(max_int,3), "cell_catchment_max_core_ratio": round(max_core,3), "cell_catchment_area_km2_sum": round(area,3), "cell_catchment_overlap_area_km2_sum": round(oarea,3), "cell_catchment_overlap_ratio_max": round(max_ratio,4), "cell_catchment_overlap_ratio_weighted": round((oarea/area),4) if area else 0.0, "cell_precip_source_type": src_type}


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


def build_feature_row(station: dict, live: dict|None=None, cells: list[dict]|None=None) -> dict:
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
    precip_evaluable = eff_type != "missing"
    precip_status = "observed" if use_obs else ("cell_derived" if eff_type in {"nowcast", "cell_derived"} else "missing")
    precip_status_label = {"observed": "gemessener Niederschlag im Einzugsgebiet", "cell_derived": "aus erkannter Regenzelle abgeleitet", "missing": "keine verwertbaren Niederschlagsdaten zugeordnet"}[precip_status]
    precip_quality_label = {"observed": "hoch", "cell_derived": "mittel", "missing": "nicht bewertbar"}[precip_status]
    eff_sum_out = eff_sum if precip_evaluable else None
    return {**obs, **cellp, "station_id": sid, "station_name": live_station.get("name") or live_station.get("station_name") or station.get("name") or sid, "river": live_station.get("river") or station.get("river") or station.get("river_name") or "", "station_lat": _f(station.get("lat"), _f(live_station.get("lat"))), "station_lon": _f(station.get("lon"), _f(live_station.get("lon"))), "current_q_m3s": q, "current_q_measured_at": q_measured_at, "current_q_timestamp_source": q_timestamp_source, "current_q_missing": q is None, "station_q_threshold_m3s": thr, "mark_q_m3s": thr, "station_q_threshold_missing": thr is None, "station_q_threshold_source": src if thr is not None else "missing", "current_q_ratio_threshold": ratio, "current_q_distance_to_threshold_m3s": qdist, "current_q_above_threshold": bool(thr is not None and q is not None and q >= thr), "current_q_trend_10min": 0.0, "current_q_trend_30min": 0.0, "current_q_trend_60min": 0.0, "q_trend_per_hour": 0.0, "already_rising_flag": False, "current_data_age_min": _f(live_station.get("data_age_min")), "data_age_min": _f(live_station.get("data_age_min")), "hydro_data_stale": False, "catchment_area_km2": _f(station.get("catchment_area_km2"),0.0), "upstream_catchment_count": len(station.get("upstream_catchment_ids") or []), "impact_eligible": bool(station.get("impact_effective", station.get("impact_eligible", True))), "source_quality": station.get("source_quality"), "topology_source": station.get("topology_source"), "upstream_source_quality": station.get("upstream_source_quality"), "effective_catchment_precip_sum_mm": eff_sum_out, "effective_catchment_precip_weighted_sum_mm": (eff_sum if use_obs else cellp["cell_catchment_precip_weighted_sum_mm"]) if precip_evaluable else None, "effective_catchment_precip_max_rate_mm_h": obs["observed_catchment_precip_max_rate_mm_h"] if use_obs else cellp["cell_catchment_max_intensity"], "effective_catchment_precip_mean_rate_mm_h": obs["observed_catchment_precip_mean_rate_mm_h"] if use_obs else cellp["cell_catchment_max_intensity"], "effective_precip_source_type": eff_type, "effective_precip_source_quality": obs["observed_precip_source_quality"] if use_obs else ("medium" if eff_type in {"nowcast","cell_derived"} else "missing"), "effective_precip_is_proxy": eff_type in {"cell_derived","proxy"}, "effective_precip_missing": eff_type == "missing", "precip_evaluable": precip_evaluable, "precip_status": precip_status, "precip_status_label": precip_status_label, "precip_quality_label": precip_quality_label, "precip_source_type": eff_type, "precip_source_quality": obs["observed_precip_source_quality"] if use_obs else ("medium" if eff_type != "missing" else "missing"), "precip_is_observed": use_obs, "precip_is_proxy": eff_type in {"cell_derived","proxy"}, "precip_source_name": obs.get("precip_source_name") or (eff_type if precip_evaluable else None), "precip_source_timestamp": obs.get("precip_source_timestamp"), "precip_source_age_min": obs.get("observed_precip_data_age_min")}


def heuristic_score(row: dict) -> dict:
    reasons=[]; warnings=[]
    if row.get("station_q_threshold_missing"):
        warnings.append("missing_station_q_threshold")
        return {"hydro_flood_risk_score": 0.0, "flood_expected": False, "flood_evaluable": False, "flood_status": "missing_threshold", "confidence": 0.2, "reasons": reasons, "warning_reasons": warnings, "model_source": "heuristic_scoring"}
    q = _f(row.get("current_q_m3s")); thr = _f(row.get("station_q_threshold_m3s")); precip = _f(row.get("effective_catchment_precip_sum_mm"),0.0) or 0.0
    ratio = q/thr if q is not None and thr else 0.0
    score = min(1.0, max(0.0, ratio*0.55 + min(precip/30.0,1.0)*0.25 + min((_f(row.get("cell_catchment_overlap_area_km2_sum"),0.0) or 0.0)/20.0,1.0)*0.1 + min((_f(row.get("cell_catchment_max_core_ratio"),0.0) or 0.0),1.0)*0.1))
    if q is not None and thr is not None and q >= thr: score=1.0; reasons.append("current_q_m3s >= station_q_threshold_m3s")
    if precip > 0: reasons.append("Niederschlag im oberliegenden Einzugsgebiet")
    if ratio >= 0.8: reasons.append("current_q_m3s nahe am Q-Grenzwert")
    if row.get("effective_precip_is_proxy"): warnings.append("precipitation_proxy_used")
    return {"hydro_flood_risk_score": round(score,3), "flood_expected": bool(score >= 0.75), "flood_evaluable": True, "flood_status": "ok", "confidence": round(0.45 + score*0.4,3), "reasons": reasons, "warning_reasons": warnings, "model_source": "heuristic_scoring"}


def evaluate_live_flood_risk(stations: list[dict]|None=None, live: dict|None=None, cells: list[dict]|None=None, write: bool=True) -> dict:
    if stations is None:
        import hydro_api
        stations = [f.get("properties") or {} for f in hydro_api.station_features(include_disabled=False).get("features", [])]
    generated = _now(); out=[]
    for st in stations or []:
        row = build_feature_row(st, live=live, cells=cells or [])
        sc = heuristic_score(row)
        out.append({k: row.get(k) for k in ["station_id","station_name","river","current_q_m3s","current_q_measured_at","current_q_timestamp_source","current_q_missing","station_q_threshold_m3s","station_q_threshold_source","station_q_threshold_missing","current_q_ratio_threshold","current_q_distance_to_threshold_m3s","effective_catchment_precip_sum_mm","effective_catchment_precip_weighted_sum_mm","effective_precip_source_type","effective_precip_source_quality","precip_evaluable","precip_status","precip_status_label","precip_quality_label","cell_catchment_count","cell_catchment_overlap_area_km2_sum","current_data_age_min","data_age_min","hydro_data_stale"]} | {"generated_at": generated, "flood_probability": None, "predicted_q_delta_m3s": None, **sc})
    doc = {"status":"ok", "generated_at": generated, "input_hash": flood_risk_input_hash(live=live, cells=cells or []), "stations": out, "readiness": readiness_status()}
    if write: _atomic_json(HYDRO_RISK_PATH, doc)
    return doc


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
    if threshold is None or start.get("q_m3s") is None:
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
    exceeded = bool(future_q >= threshold)
    min_delta = _f(runtime_config.get("HYDRO_VERIFY_MIN_DELTA_Q_M3S", getattr(config, "HYDRO_VERIFY_MIN_DELTA_Q_M3S", 0.2)), 0.2) or 0.2
    return {"target_missing": False, "target_q_delta_m3s": round(delta, 3), "target_q_threshold_exceeded": exceeded, "target_flood_expected": bool(exceeded and delta >= -abs(min_delta)), "target_q_distance_to_threshold_after_reaction_m3s": round(threshold - future_q, 3)}


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
    HYDRO_DATASET_JSONL_PATH.write_text("".join(json.dumps(s, ensure_ascii=False) + "\n" for s in samples), encoding="utf-8")
    _atomic_json(HYDRO_TRAINING_META_PATH, {"last_dataset_build_at": _now(), "sample_count_total": len(samples), "note": "Samples ohne spätere q_m3s-Beobachtung bleiben target_missing=true."})
    return readiness_status() | {"status":"dataset_scanned", "dataset_path": str(HYDRO_DATASET_JSONL_PATH)}


def train_model() -> dict:
    status = build_dataset_scan()
    status["status"] = "insufficient_data" if status["readiness_status"] != "ready" else "training_skipped_no_backend"
    status["fallback_reason"] = ",".join(status.get("rejection_reasons") or [])
    return status


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
