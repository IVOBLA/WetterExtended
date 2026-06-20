"""API-Helfer fuer Hydro-Impact-Status, Stationen und Events."""
from __future__ import annotations

import json, os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import config
import runtime_config
from config import SAVE_PATHS

BASE = Path(SAVE_PATHS.get("hydro", "train_data/hydro/live"))
STATIC_GENERATED = Path(getattr(config, "HYDRO_STATIC_DIR", "train_data/hydro/static")) / "generated"
LIVE_LATEST = BASE / "latest_hydro.json" if BASE.name == "live" else BASE / "live" / "latest_hydro.json"
LIVE_STATUS = LIVE_LATEST.parent / "hydro_status.json"
IMPACT_DIR = Path("train_data/hydro/impact")
LATEST_IMPACTS = IMPACT_DIR / "latest_hydro_impacts.json"
VERIFICATIONS = IMPACT_DIR / "hydro_verifications.jsonl"


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
    return {str(r.get("station_id")): r for r in rows if isinstance(r, dict)}



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
    return sum(1 for station in _station_rows() if station.get("impact_eligible") is True)


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
    if raw_status == "invalid_static_json":
        return {"ready": False, "status": "invalid_static_json", "error": (status_doc or {}).get("error"), "status_file": str(status_path)}
    if raw_status == "hydro_geometry_unavailable":
        return {"ready": False, "status": "hydro_geometry_unavailable", "error": (status_doc or {}).get("error"), "status_file": str(status_path)}

    idx = _static_index()
    if not idx:
        return {"ready": False, "status": raw_status or "hydro_static_missing", "error": None, "status_file": str(status_path)}

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
        return {"ready": True, "status": "hydro_ready", "error": None, "status_file": str(status_path)}
    if "hydro_geometry_unavailable" in reasons:
        concrete = "hydro_geometry_unavailable"
    elif "upstream_topology_missing" in reasons:
        concrete = "upstream_topology_missing"
    elif "station_catchment_unavailable" in reasons:
        concrete = "station_catchment_unavailable"
    else:
        concrete = raw_status or "hydro_static_missing"
    return {"ready": False, "status": concrete, "error": None, "status_file": str(status_path)}

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
    overrides = runtime_config.get("HYDRO_STATION_OVERRIDES", {}) or {}
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


def station_features(include_disabled=False):
    idx = _static_index(); live = _json(LIVE_LATEST, {})
    overrides = runtime_config.get("HYDRO_STATION_OVERRIDES", {}) or {}
    by_id = {str(s.get("station_id")): s for s in live.get("stations", []) if isinstance(s, dict)} if isinstance(live, dict) else {}
    active = {str(e.get("station_id")): e for e in normalized_impacts(True, include_disabled=include_disabled) if e.get("status") in {"pending","confirmed","ambiguous"}}
    feats = []
    for sid, st in idx.items():
        st = {**st, **(overrides.get(sid, {}) if isinstance(overrides, dict) else {})}
        l = by_id.get(sid, {})
        lon = st.get("lon", l.get("lon")); lat = st.get("lat", l.get("lat"))
        if lon is None or lat is None: continue
        station_enabled = bool(st.get("enabled", True))
        if not station_enabled and not include_disabled:
            continue
        ev = None if not station_enabled else active.get(sid)
        status_value = "disabled" if not station_enabled else (ev.get("status") if ev else ("ok" if enabled() else "disabled"))
        props = {"station_id": sid, "name": l.get("name") or st.get("station_name") or sid, "river": l.get("river") or st.get("river_name") or "", "q_m3s": l.get("q_m3s"), "w_cm": l.get("w_cm"), "measured_at": l.get("measured_at"), "status": status_value, "enabled": station_enabled, "active": station_enabled and not bool(st.get("ignored", False)), "ignored": bool(st.get("ignored", False)), "impact_active": bool(ev) if station_enabled else False, "last_hydro_impact": ev if station_enabled else None, "reason": "station_disabled_by_admin" if not station_enabled else None}
        feats.append({"type":"Feature", "geometry":{"type":"Point", "coordinates":[float(lon), float(lat)]}, "properties":props})
    return {"type":"FeatureCollection", "features": feats}


def status():
    hydro_on = enabled()
    static = _static_health()
    station_rows = _station_rows()
    station_count = len(station_rows)
    visible_station_count = sum(1 for station in station_rows if _has_display_coordinates(station))
    impact_eligible_station_count = _impact_eligible_station_count()
    if not hydro_on:
        return {"enabled": False, "hydro_enabled": False, "static_ready": static["ready"], "static_status": "hydro_disabled", "hydro_static_missing": False, "static_error": static.get("error"), "live_ready": False, "live_ok": False, "from_cache": False, "cache_used": False, "status": "hydro_disabled", "last_fetch": None, "last_error": None, "station_count": station_count, "visible_station_count": visible_station_count, "impact_eligible_station_count": impact_eligible_station_count, "impact_pending": 0, "impact_confirmed_24h": 0}
    live = _json(LIVE_STATUS, {})
    live = live if isinstance(live, dict) else {}
    impacts = normalized_impacts(False)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    last_error = live.get("last_error") or live.get("error") or static.get("error")
    live_ok = bool(live.get("ok")) and not (live.get("last_error") or live.get("error"))
    overall_status = "error" if (LIVE_LATEST.exists() and (live.get("last_error") or live.get("error"))) else (static["status"] if not static["ready"] else ("hydro_ready" if live_ok or LIVE_LATEST.exists() else "error"))
    return {"enabled": hydro_on, "hydro_enabled": hydro_on, "static_ready": static["ready"], "static_status": static["status"], "hydro_static_missing": static["status"] == "hydro_static_missing", "static_error": static.get("error"), "live_ready": LIVE_LATEST.exists(), "live_ok": live_ok, "from_cache": bool(live.get("from_cache")), "cache_used": bool(live.get("from_cache")), "status": overall_status, "last_fetch": live.get("updated_at") or _json(LIVE_LATEST, {}).get("fetched_at"), "last_error": last_error, "station_count": station_count, "visible_station_count": visible_station_count, "impact_eligible_station_count": impact_eligible_station_count, "impact_pending": sum(e.get("status") == "pending" for e in impacts), "impact_confirmed_24h": sum(e.get("status") == "confirmed" and ((_dt(e.get("verified_at") or e.get("created_at")) or cutoff) >= cutoff) for e in impacts)}


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
