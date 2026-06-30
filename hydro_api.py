"""API-Helfer fuer Hydro-Impact-Status, Stationen und Events."""
from __future__ import annotations

import json, os, logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import config
import runtime_config
import hydro_station_overrides
from config import SAVE_PATHS

log = logging.getLogger(__name__)

BASE = Path(SAVE_PATHS.get("hydro", "train_data/hydro/live"))
STATIC_GENERATED = Path(getattr(config, "HYDRO_STATIC_DIR", "train_data/hydro/static")) / "generated"
LIVE_LATEST = BASE / "latest_hydro.json" if BASE.name == "live" else BASE / "live" / "latest_hydro.json"
LIVE_STATUS = LIVE_LATEST.parent / "hydro_status.json"
IMPACT_DIR = Path("train_data/hydro/impact")
LATEST_IMPACTS = IMPACT_DIR / "latest_hydro_impacts.json"
VERIFICATIONS = IMPACT_DIR / "hydro_verifications.jsonl"
HYDRO_FLOOD_RISK = IMPACT_DIR / "latest_hydro_flood_risk.json"


def _json(path: Path, default: Any):
    try:
        with path.open(encoding="utf-8") as f: return json.load(f)
    except Exception: return default


def _read_json_strict(path: Path) -> tuple[Any | None, str | None]:
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f), None
    except FileNotFoundError:
        return None, "missing"
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _dt(v):
    if not v: return None
    try: return datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception: return None


def enabled() -> bool:
    try:
        from hydro_fetch import hydro_enabled
        return hydro_enabled(getattr(config, "HYDRO_ENABLED", True))
    except Exception:
        value = runtime_config.get("HYDRO_ENABLED", getattr(config, "HYDRO_ENABLED", True))
        if isinstance(value, str):
            return value.strip().lower() not in {"0", "false", "no", "off"}
        return bool(value)


def _static_index():
    data = _json(STATIC_GENERATED / "station_network_index.json", {})
    rows = data.get("stations", data if isinstance(data, list) else []) if isinstance(data, (dict, list)) else []
    if not rows:
        fc = _json(STATIC_GENERATED / "hydro_stations.geojson", {})
        if isinstance(fc, dict):
            rows = [{**(f.get("properties") or {}), "lon": ((f.get("geometry") or {}).get("coordinates") or [None, None])[0], "lat": ((f.get("geometry") or {}).get("coordinates") or [None, None])[1]} for f in fc.get("features", []) if isinstance(f, dict)]
    return {str(r.get("station_id")): r for r in rows if isinstance(r, dict) and r.get("station_id") not in (None, "")}



def _station_rows() -> list[dict]:
    return list(_static_index().values())


def _has_display_coordinates(station: dict) -> bool:
    try:
        lat = float(station.get("lat"))
        lon = float(station.get("lon"))
    except Exception:
        return False
    return -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0


def _impact_eligible_station_count() -> int:
    return sum(1 for station in _station_rows() if (station.get("impact_eligible_auto", station.get("impact_eligible")) is True))

def _overrides() -> dict:
    legacy = runtime_config.get("HYDRO_STATION_OVERRIDES", {}) or {}
    legacy = legacy if isinstance(legacy, dict) else {}

    # In Tests wird runtime_config.get haeufig gezielt monkeypatched, um den
    # kompletten Override-Zustand zu simulieren. In diesem Fall duerfen echte
    # lokale Datei-Overrides aus data/config/hydro_station_overrides.json nicht
    # in die Testdaten hineinleaken. Im regulaeren Betrieb bleibt die Datei der
    # dauerhafte Fallback-Speicher und wird von Runtime-Overrides uebersteuert.
    runtime_get_is_original = (
        getattr(runtime_config.get, "__module__", None)
        == getattr(runtime_config, "__name__", "runtime_config")
    )
    if not runtime_get_is_original:
        return dict(legacy)

    file_overrides = hydro_station_overrides.load()
    if not isinstance(file_overrides, dict):
        file_overrides = {}
    merged = dict(file_overrides)
    merged.update(legacy)
    return merged

def apply_station_override(station: dict, overrides: dict | None = None) -> dict:
    sid = str(station.get("station_id"))
    merged = dict(station)
    ov = (overrides or _overrides()).get(sid, {})
    override_has_enabled = isinstance(ov, dict) and "enabled" in ov
    if isinstance(ov, dict):
        merged.update(ov)
    auto_known = "impact_eligible_auto" in merged or "impact_eligible" in merged
    auto = bool(merged.get("impact_eligible_auto", merged.get("impact_eligible") is True))
    if override_has_enabled:
        requested_enabled = bool(ov.get("enabled"))
    elif not auto_known and merged.get("impact_eligible") is False:
        requested_enabled = True
    else:
        requested_enabled = bool(merged.get("impact_enabled", merged.get("enabled", True)))
    if auto_known and not auto and requested_enabled:
        log.warning("Ignoriere Hydro-Station-Override enabled=true fuer nicht impact_eligible_auto Station %s", sid)
    admin_enabled = bool(requested_enabled and (auto or not auto_known))
    effective = bool(auto and admin_enabled) if auto_known else admin_enabled
    merged["_impact_auto_known"] = auto_known
    merged["_override_has_enabled"] = override_has_enabled
    merged["impact_eligible_auto"] = auto
    merged["impact_enabled"] = admin_enabled
    merged["impact_effective"] = effective
    merged["enabled"] = effective if auto_known else admin_enabled
    merged["impact_eligible"] = auto
    return merged

def _static_health() -> dict[str, Any]:
    status_path = STATIC_GENERATED / "hydro_static_status.json"
    status_doc, status_error = _read_json_strict(status_path)
    if status_error and status_error != "missing":
        return {"ready": False, "status": "invalid_static_json", "error": status_error, "status_file": str(status_path)}

    index_path = STATIC_GENERATED / "station_network_index.json"
    index_doc, index_error = _read_json_strict(index_path)
    if index_error and index_error != "missing":
        return {"ready": False, "status": "invalid_static_json", "error": index_error, "status_file": str(status_path)}

    raw_status = status_doc.get("status") if isinstance(status_doc, dict) else None
    doc = status_doc if isinstance(status_doc, dict) else {}
    basin_count = int(doc.get("basin_count") or 0)
    flowline_count = int(doc.get("flowline_count") or 0)
    if raw_status == "invalid_static_json":
        return {"ready": False, "status": "invalid_static_json", "error": (status_doc or {}).get("error"), "status_file": str(status_path)}
    if raw_status == "hydro_geometry_unavailable":
        return {"ready": False, "status": "hydro_geometry_unavailable", "error": (status_doc or {}).get("error"), "status_file": str(status_path)}

    idx = _static_index()
    if not idx:
        concrete = raw_status or ("flowlines_missing" if basin_count > 0 and flowline_count <= 0 else "hydro_static_missing")
        return {"ready": False, "status": concrete, "error": None, "status_file": str(status_path), "doc": doc}

    reasons = set()
    eligible = 0
    for station in idx.values():
        if station.get("impact_eligible") is True:
            eligible += 1
        for reason in station.get("reason") or []:
            reasons.add(str(reason))
        if station.get("source_quality"):
            reasons.add(str(station.get("source_quality")))

    if eligible > 0:
        return {"ready": True, "status": "hydro_static_ready", "error": None, "status_file": str(status_path), "doc": doc}
    if basin_count > 0 and flowline_count <= 0:
        concrete = "flowlines_missing"
    elif "hydro_geometry_unavailable" in reasons:
        concrete = "hydro_geometry_unavailable"
    elif "upstream_topology_missing" in reasons:
        concrete = "upstream_topology_missing"
    elif "upstream_catchment_unavailable" in reasons:
        concrete = "upstream_topology_missing"
    elif "station_catchment_unavailable" in reasons:
        concrete = "station_catchment_unavailable"
    else:
        concrete = raw_status or ("flowlines_missing" if basin_count > 0 and flowline_count <= 0 else "hydro_static_missing")
    return {"ready": False, "status": concrete, "error": None, "status_file": str(status_path), "doc": doc}

def latest_impacts() -> list[dict]:
    rows = _json(LATEST_IMPACTS, [])
    return rows if isinstance(rows, list) else []


def all_impacts() -> list[dict]:
    rows = []
    for p in sorted(IMPACT_DIR.glob("hydro_impact_*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            try: rows.append(json.loads(line))
            except Exception: pass
    return rows or latest_impacts()


def _latest_status_by_event() -> dict[str, dict]:
    out = {}
    if not VERIFICATIONS.exists(): return out
    for line in VERIFICATIONS.read_text(encoding="utf-8").splitlines():
        try: row = json.loads(line)
        except Exception: continue
        key = str(row.get("event_id") or f"{row.get('cell_id')}:{row.get('station_id')}")
        out[key] = row
    return out


def _disabled_station_ids() -> set[str]:
    overrides = _overrides()
    if not isinstance(overrides, dict):
        return set()
    return {str(sid) for sid, ov in overrides.items() if isinstance(ov, dict) and ov.get("enabled") is False}


def normalized_impacts(latest_only=False, include_disabled=False):
    ver = _latest_status_by_event()
    src = latest_impacts() if latest_only else all_impacts()
    disabled = _disabled_station_ids()
    out = []
    for e in src:
        if str(e.get("station_id")) in disabled and not include_disabled:
            continue
        key = str(e.get("event_id") or f"{e.get('cell_id')}:{e.get('station_id')}")
        v = ver.get(key)
        disabled_station = str(e.get("station_id")) in disabled
        status = "disabled" if disabled_station else (v or e).get("status", "pending")
        row = {**e, "score": e.get("score", e.get("impact_score")), "status": status, "verification": v or e.get("verification")}
        if disabled_station:
            row["impact_active"] = False
            row["reason"] = "station_disabled_by_admin"
        out.append(row)
    return out


def station_features(include_disabled=False, map_view=False):
    idx = _static_index(); live = _json(LIVE_LATEST, {})
    overrides = _overrides()
    _global_mark_q = runtime_config.get("HYDRO_MAP_MARK_Q_M3S", None)
    try:
        from hydro_impact import load_latest_hydro_forecast as _llf
        _fc_events = _llf() or []
    except Exception:
        _fc_events = []
    _forecast_q_by_sid = {}
    for _e in _fc_events:
        if not isinstance(_e, dict):
            continue
        _fsid = str(_e.get("station_id"))
        _qf = _e.get("q_forecast_m3s")
        if _qf is None:
            continue
        try:
            _qf = float(_qf)
        except (TypeError, ValueError):
            continue
        if _fsid not in _forecast_q_by_sid or _qf > _forecast_q_by_sid[_fsid]:
            _forecast_q_by_sid[_fsid] = _qf
    map_min_q = 0.0; map_mark_q = None
    if map_view:
        try: map_min_q = float(runtime_config.get("HYDRO_MAP_MIN_Q_M3S", 0.0) or 0.0)
        except (TypeError, ValueError): map_min_q = 0.0
        _mm = runtime_config.get("HYDRO_MAP_MARK_Q_M3S", None)
        try: map_mark_q = float(_mm) if _mm is not None else None
        except (TypeError, ValueError): map_mark_q = None
    by_id = {str(s.get("station_id")): s for s in live.get("stations", []) if isinstance(s, dict)} if isinstance(live, dict) else {}
    active = {str(e.get("station_id")): e for e in normalized_impacts(True, include_disabled=include_disabled) if e.get("status") in {"pending","confirmed","ambiguous"}}
    risk_doc = _json(HYDRO_FLOOD_RISK, {})
    risk_by_sid = {str(r.get("station_id")): r for r in risk_doc.get("stations", []) if isinstance(r, dict)} if isinstance(risk_doc, dict) else {}
    feats = []
    for sid, st in idx.items():
        if "station_id" not in st:
            st = {**st, "station_id": sid}
        st = apply_station_override(st, overrides)
        l = by_id.get(sid, {})
        lon = st.get("lon", l.get("lon")); lat = st.get("lat", l.get("lat"))
        if lon is None or lat is None: continue
        station_enabled = bool(st.get("impact_effective"))
        # Public callers must only see stations whose Hydro impact is actually
        # effective. Admin/debug callers pass include_disabled=1 and need the
        # full list, including ineligible stations for diagnosis and editing.
        if not station_enabled and not include_disabled:
            continue
        ev = None if not station_enabled else active.get(sid)
        status_value = "disabled" if not station_enabled else (ev.get("status") if ev else ("ok" if enabled() else "disabled"))
        props = {"station_id": sid, "name": l.get("name") or st.get("station_name") or sid, "river": l.get("river") or st.get("river_name") or "", "q_m3s": l.get("q_m3s"), "w_cm": l.get("w_cm"), "measured_at": l.get("measured_at"), "status": status_value, "enabled": station_enabled, "impact_eligible_auto": st.get("impact_eligible_auto"), "impact_enabled": st.get("impact_enabled"), "impact_effective": st.get("impact_effective"), "active": station_enabled and not bool(st.get("ignored", False)), "ignored": bool(st.get("ignored", False)), "impact_active": bool(ev) if station_enabled else False, "last_hydro_impact": ev if station_enabled else None, "station_basin": st.get("station_basin"), "upstream_catchment_ids": st.get("upstream_catchment_ids", []), "impact_eligible": st.get("impact_eligible"), "topology_source": st.get("topology_source"), "upstream_source_quality": st.get("upstream_source_quality"), "source_quality": st.get("source_quality"), "catchment_area_km2": st.get("catchment_area_km2"), "mark_q_m3s": st.get("mark_q_m3s"), "exclusion_reason": st.get("exclusion_reason") or ((st.get("reason") or [None])[0] if isinstance(st.get("reason"), list) else st.get("reason")), "reason": "station_disabled_by_admin" if not station_enabled and st.get("impact_eligible_auto") else st.get("reason"), "flood_expected": None}
        # P61: Warngrenzen-Ueberschreitung (gemessen oder prognostiziert) + Quelle.
        try: _qcur = float(props.get("q_m3s"))
        except (TypeError, ValueError): _qcur = None
        _p61_smk = st.get("mark_q_m3s")
        try: _p61_thr = float(_p61_smk) if _p61_smk is not None else (float(_global_mark_q) if _global_mark_q is not None else None)
        except (TypeError, ValueError): _p61_thr = None
        _qfc = _forecast_q_by_sid.get(sid)
        _p61_meas = bool(_p61_thr is not None and _qcur is not None and _qcur >= _p61_thr)
        _p61_fore = bool(_p61_thr is not None and _qfc is not None and _qfc >= _p61_thr)
        props["q_current"] = _qcur
        props["q_forecast"] = _qfc
        props["q_threshold"] = _p61_thr
        props["q_threshold_exceeded"] = bool(station_enabled and (_p61_meas or _p61_fore))
        props["impact_source"] = ("both" if (_p61_meas and _p61_fore) else ("measured" if _p61_meas else ("forecast" if _p61_fore else None)))
        _risk = risk_by_sid.get(sid) or {}
        for _k in ("flood_expected", "q_trend_status", "q_trend_delta_m3s", "q_trend_reference_window_min"):
            if _k in _risk:
                props[_k] = _risk.get(_k)
        if map_view:
            try: _qn = float(props.get("q_m3s"))
            except (TypeError, ValueError): _qn = None
            if map_min_q and _qn is not None and _qn < map_min_q:
                continue
            _smk = st.get("mark_q_m3s")
            try: _eff_mark = float(_smk) if _smk is not None else map_mark_q
            except (TypeError, ValueError): _eff_mark = map_mark_q
            props["marked"] = bool(_eff_mark is not None and _qn is not None and _qn >= _eff_mark)
        feats.append({"type":"Feature", "geometry":{"type":"Point", "coordinates":[float(lon), float(lat)]}, "properties":props})
    return {"type":"FeatureCollection", "features": feats}


def status():
    hydro_on = enabled()
    static = _static_health()
    station_rows = _station_rows()
    station_count = len(station_rows)
    station_rows = [apply_station_override(s) for s in station_rows]
    visible_station_count = sum(1 for station in station_rows if _has_display_coordinates(station))
    impact_eligible_station_count = sum(1 for station in station_rows if station.get("impact_eligible_auto") is True)
    enabled_station_count = sum(1 for station in station_rows if station.get("impact_effective") is True)
    if not hydro_on:
        return {"enabled": False, "hydro_enabled": False, "static_ready": static["ready"], "static_status": "hydro_disabled", "hydro_static_missing": False, "static_error": static.get("error"), "live_ready": False, "live_ok": False, "from_cache": False, "cache_used": False, "status": "hydro_disabled", "last_fetch": None, "last_error": None, "station_count": station_count, "visible_station_count": visible_station_count, "impact_eligible_station_count": impact_eligible_station_count, "impact_not_eligible_station_count": max(0, station_count-impact_eligible_station_count), "enabled_station_count": enabled_station_count, "disabled_station_count": max(0, impact_eligible_station_count-enabled_station_count), "impact_pending": 0, "impact_confirmed_24h": 0}
    live = _json(LIVE_STATUS, {})
    live = live if isinstance(live, dict) else {}
    impacts = normalized_impacts(False)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    last_error = live.get("last_error") or live.get("error") or static.get("error")
    live_ok = bool(live.get("ok")) and not (live.get("last_error") or live.get("error"))
    overall_status = "error" if (LIVE_LATEST.exists() and (live.get("last_error") or live.get("error"))) else (static["status"] if not static["ready"] else ("hydro_ready" if live_ok or LIVE_LATEST.exists() else "error"))
    doc = static.get("doc") if isinstance(static.get("doc"), dict) else {}
    latest_doc = _json(LIVE_LATEST, {}) if LIVE_LATEST.exists() else {}
    live_station_count = len(latest_doc.get("stations", [])) if isinstance(latest_doc, dict) else 0
    coverage = doc.get("feldkirchen_coverage") or _json(STATIC_GENERATED / "hydro_static_coverage.json", {})
    coverage = coverage if isinstance(coverage, dict) else {}
    sample_eligible = [s for s in station_rows if s.get("impact_eligible") is True][:5]
    return {"enabled": hydro_on, "hydro_enabled": hydro_on, "hydro_global_mark_q_m3s": runtime_config.get("HYDRO_MAP_MARK_Q_M3S", None), "static_ready": static["ready"], "static_status": static["status"], "hydro_static_missing": static["status"] == "hydro_static_missing", "static_error": static.get("error"), "basins_available": doc.get("basin_count", 0) > 0, "flowlines_available": doc.get("flowline_count", 0) > 0, "feldkirchen_coverage_ok": bool(coverage.get("coverage_ok")), "basin_features_feldkirchen": int(coverage.get("basin_features_feldkirchen") or 0), "flowline_features_feldkirchen": int(coverage.get("flowline_features_feldkirchen") or 0), "impact_not_eligible_reason": static["status"] if impact_eligible_station_count <= 0 else None, "live_status": "ok" if live_ok or LIVE_LATEST.exists() else "missing", "live_station_count": live_station_count, "static_station_count": doc.get("static_station_count", doc.get("station_count", station_count)), "basin_count": doc.get("basin_count", 0), "flowline_count": doc.get("flowline_count", 0), "upstream_graph_node_count": doc.get("upstream_graph_node_count", 0), "upstream_graph_edge_count": doc.get("upstream_graph_edge_count", 0), "upstream_graph_confident_edge_count": doc.get("upstream_graph_confident_edge_count", 0), "topology_quality": doc.get("topology_quality"), "topology_warnings": doc.get("topology_warnings", []), "topology_errors": doc.get("topology_errors", []), "sample_impact_eligible_stations": sample_eligible, "downloads": doc.get("downloads", {}), "missing": doc.get("missing", []), "errors": doc.get("errors", []), "warnings": doc.get("warnings", []), "live_ready": LIVE_LATEST.exists(), "live_ok": live_ok, "from_cache": bool(live.get("from_cache")), "cache_used": bool(live.get("from_cache")), "status": overall_status, "last_fetch": live.get("updated_at") or latest_doc.get("fetched_at") if isinstance(latest_doc, dict) else live.get("updated_at"), "last_error": last_error, "station_count": station_count, "visible_station_count": visible_station_count, "impact_eligible_station_count": impact_eligible_station_count, "impact_not_eligible_station_count": max(0, station_count-impact_eligible_station_count), "enabled_station_count": enabled_station_count, "disabled_station_count": max(0, impact_eligible_station_count-enabled_station_count), "impact_pending": sum(e.get("status") == "pending" for e in impacts), "impact_confirmed_24h": sum(e.get("status") == "confirmed" and ((_dt(e.get("verified_at") or e.get("created_at")) or cutoff) >= cutoff) for e in impacts)}


def catchment(station_id):
    fc = _json(STATIC_GENERATED / "station_catchments.geojson", {"type":"FeatureCollection","features":[]})
    feats = [f for f in fc.get("features", []) if str((f.get("properties") or {}).get("station_id")) == str(station_id)]
    return {"type":"FeatureCollection", "features": feats}


def catchments_all():
    fc = _json(STATIC_GENERATED / "station_catchments.geojson", {"type": "FeatureCollection", "features": []})
    if not isinstance(fc, dict):
        return {"type": "FeatureCollection", "features": []}
    fc.setdefault("type", "FeatureCollection")
    fc.setdefault("features", [])
    return fc


def _segment_linestrings(geom):
    if not isinstance(geom, dict):
        return []
    t = geom.get("type"); c = geom.get("coordinates")
    if t == "LineString" and isinstance(c, list):
        return [c]
    if t == "MultiLineString" and isinstance(c, list):
        return list(c)
    return []


def _active_segment_features():
    """Aktive Flussabschnitte (Warngrenze ueberschritten) mit q-Kontext; ohne affected_places.
    Liefert zusaetzlich die Stationskoordinaten je station_id."""
    fc = _json(STATIC_GENERATED / "station_river_segments.geojson", {"type": "FeatureCollection", "features": []})
    if not isinstance(fc, dict):
        return [], {}
    seg_by_sid = {str((f.get("properties") or {}).get("station_id")): f for f in fc.get("features", []) if isinstance(f, dict)}
    live = _json(LIVE_LATEST, {})
    updated_at = live.get("fetched_at") if isinstance(live, dict) else None
    out = []; station_coords = {}
    for feat in station_features(include_disabled=False).get("features", []):
        p = feat.get("properties") or {}
        if not p.get("q_threshold_exceeded"):
            continue
        sid = str(p.get("station_id"))
        seg = seg_by_sid.get(sid)
        if not seg:
            continue
        coords = (feat.get("geometry") or {}).get("coordinates") or [None, None]
        station_coords[sid] = (coords[0], coords[1])
        props = dict(seg.get("properties") or {})
        props.update({
            "impact_source": p.get("impact_source"),
            "q_current": p.get("q_current"),
            "q_forecast": p.get("q_forecast"),
            "q_threshold": p.get("q_threshold"),
            "updated_at": updated_at,
        })
        out.append({"type": "Feature", "geometry": seg.get("geometry"), "properties": props})
    return out, station_coords


def _place_buffer_km() -> float:
    try:
        return float(runtime_config.get("HYDRO_IMPACT_PLACE_BUFFER_KM", getattr(config, "HYDRO_IMPACT_PLACE_BUFFER_KM", 1.0)) or 1.0)
    except (TypeError, ValueError):
        return 1.0


def _affected_place_rows(seg_features, station_coords):
    from hydro_geography import point_to_linestring_distance_m, haversine_m
    buffer_km = _place_buffer_km()
    places = runtime_config.get("LOCATIONS_WATCHLIST", getattr(config, "LOCATIONS_WATCHLIST", [])) or []
    rows = []
    for seg in seg_features:
        sp = seg.get("properties") or {}
        sid = str(sp.get("station_id"))
        lines = _segment_linestrings(seg.get("geometry") or {})
        if not lines:
            continue
        scoord = station_coords.get(sid)
        for place in places:
            try:
                plat = float(place.get("lat")); plon = float(place.get("lon"))
            except (TypeError, ValueError):
                continue
            d_river = min((point_to_linestring_distance_m(plon, plat, ls) for ls in lines), default=float("inf"))
            if d_river / 1000.0 > buffer_km:
                continue
            d_station = haversine_m(plon, plat, scoord[0], scoord[1]) if scoord and scoord[0] is not None else None
            rows.append({
                "place_name": place.get("name"), "lon": plon, "lat": plat,
                "station_id": sid, "station_name": sp.get("station_name"), "river": sp.get("river"),
                "impact_source": sp.get("impact_source"),
                "distance_to_river_km": round(d_river / 1000.0, 3),
                "distance_to_station_km": round(d_station / 1000.0, 3) if d_station is not None else None,
                "q_current": sp.get("q_current"), "q_forecast": sp.get("q_forecast"), "q_threshold": sp.get("q_threshold"),
            })
    return rows


def impact_segments():
    """GeoJSON der betroffenen Flussabschnitte (nur ueberschrittene Warngrenze), inkl. betroffener Orte."""
    seg_features, station_coords = _active_segment_features()
    rows = _affected_place_rows(seg_features, station_coords)
    names_by_sid = {}
    for r in rows:
        names_by_sid.setdefault(str(r["station_id"]), []).append(r["place_name"])
    for seg in seg_features:
        sid = str((seg.get("properties") or {}).get("station_id"))
        seg["properties"]["affected_places"] = names_by_sid.get(sid, [])
    return {"type": "FeatureCollection", "features": seg_features}


def affected_places():
    """GeoJSON der betroffenen Orte (Watchlist-Orte im Puffer um aktive Flussabschnitte)."""
    seg_features, station_coords = _active_segment_features()
    rows = _affected_place_rows(seg_features, station_coords)
    feats = []
    for r in rows:
        props = {k: v for k, v in r.items() if k not in ("lon", "lat")}
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]}, "properties": props})
    return {"type": "FeatureCollection", "features": feats}
