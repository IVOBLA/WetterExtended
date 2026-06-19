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


def _dt(v):
    if not v: return None
    try: return datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception: return None


def enabled() -> bool:
    return bool(runtime_config.get("HYDRO_ENABLED", getattr(config, "HYDRO_ENABLED", True)))


def _static_index():
    data = _json(STATIC_GENERATED / "station_network_index.json", {})
    rows = data.get("stations", data if isinstance(data, list) else []) if isinstance(data, (dict, list)) else []
    return {str(r.get("station_id")): r for r in rows if isinstance(r, dict)}


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
    live = _json(LIVE_STATUS, {})
    impacts = normalized_impacts(False)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    last_error = live.get("last_error") or live.get("error")
    live_ok = bool(live.get("ok")) and not last_error
    static_ready = bool(_static_index())
    return {"enabled": enabled(), "hydro_enabled": enabled(), "static_ready": static_ready, "static_status": "ok" if static_ready else "hydro_static_missing", "hydro_static_missing": not static_ready, "live_ready": LIVE_LATEST.exists(), "live_ok": live_ok, "from_cache": bool(live.get("from_cache")), "cache_used": bool(live.get("from_cache")), "status": "ok" if live_ok else "error", "last_fetch": live.get("updated_at") or _json(LIVE_LATEST, {}).get("fetched_at"), "last_error": last_error, "station_count": len(station_features()["features"]), "impact_pending": sum(e.get("status") == "pending" for e in impacts), "impact_confirmed_24h": sum(e.get("status") == "confirmed" and ((_dt(e.get("verified_at") or e.get("created_at")) or cutoff) >= cutoff) for e in impacts)}


def catchment(station_id):
    fc = _json(STATIC_GENERATED / "station_catchments.geojson", {"type":"FeatureCollection","features":[]})
    feats = [f for f in fc.get("features", []) if str((f.get("properties") or {}).get("station_id")) == str(station_id)]
    return {"type":"FeatureCollection", "features": feats}
