"""Persistente Zell-Lineage-IDs für IR-Vorläuferzellen.

1L.1 vergibt stabile fachliche ``cell_id`` Werte für CB-IR-Tracks. Radar-
Übernahme und Score-Matching werden nur im State vorbereitet und noch nicht aktiv
umgesetzt.
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import runtime_config
except Exception:  # pragma: no cover - Fallback für frühe Importphasen
    runtime_config = None

try:
    from config import (
        CELL_ID_PREFIX,
        CELL_LINEAGE_EVENTS_FILE,
        CELL_LINEAGE_STATE_DIR,
        CELL_LINEAGE_STATE_FILE,
        IR_RADAR_MATCH_SCORE_MIN,
        IR_RADAR_MATCH_SCORE_WEAK_MIN,
        IR_RADAR_MATCH_MAX_KM,
        IR_RADAR_MATCH_STRONG_KM,
        IR_RADAR_MATCH_LOOKBACK_MIN,
        IR_RADAR_MATCH_MAX_IR_AGE_MIN,
        IR_RADAR_MATCH_USE_PREDICTED_POSITION,
        IR_RADAR_MATCH_USE_GROWTH_SIGNALS,
        IR_RADAR_MATCH_USE_METPOT,
        IR_PRECURSOR_HIDE_WHEN_RADAR_MATCHED,
    )
except Exception:  # pragma: no cover
    CELL_ID_PREFIX = "WX"
    CELL_LINEAGE_STATE_DIR = "train_data/cell_lineage"
    CELL_LINEAGE_STATE_FILE = "cell_lineage_state.json"
    CELL_LINEAGE_EVENTS_FILE = "cell_lineage_events.jsonl"
    IR_RADAR_MATCH_SCORE_MIN = 0.70
    IR_RADAR_MATCH_SCORE_WEAK_MIN = 0.55
    IR_RADAR_MATCH_MAX_KM = 40.0
    IR_RADAR_MATCH_STRONG_KM = 15.0
    IR_RADAR_MATCH_LOOKBACK_MIN = 45.0
    IR_RADAR_MATCH_MAX_IR_AGE_MIN = 20.0
    IR_RADAR_MATCH_USE_PREDICTED_POSITION = True
    IR_RADAR_MATCH_USE_GROWTH_SIGNALS = True
    IR_RADAR_MATCH_USE_METPOT = True
    IR_PRECURSOR_HIDE_WHEN_RADAR_MATCHED = True


def _debug(msg: str) -> None:
    try:
        from debug_utils import debug_log
        debug_log(msg)
    except Exception:
        pass


def _cfg(name: str, default: Any) -> Any:
    if runtime_config is not None:
        try:
            return runtime_config.get(name, default)
        except Exception:
            pass
    return default


def _state_dir() -> Path:
    return Path(str(_cfg("CELL_LINEAGE_STATE_DIR", CELL_LINEAGE_STATE_DIR)))


def _state_path() -> Path:
    return _state_dir() / str(_cfg("CELL_LINEAGE_STATE_FILE", CELL_LINEAGE_STATE_FILE))


def _events_path() -> Path:
    return _state_dir() / str(_cfg("CELL_LINEAGE_EVENTS_FILE", CELL_LINEAGE_EVENTS_FILE))


def _empty_state() -> dict:
    return {"version": 1, "date_counters": {}, "ir_to_cell": {}, "radar_to_cell": {}, "cells": {}}


def _normalize_state(state: dict | None) -> dict:
    if not isinstance(state, dict):
        return _empty_state()
    out = _empty_state()
    out.update(state)
    for key in ("date_counters", "ir_to_cell", "radar_to_cell", "cells"):
        if not isinstance(out.get(key), dict):
            out[key] = {}
    out["version"] = 1
    return out


def load_lineage_state() -> dict:
    path = _state_path()
    if not path.exists():
        return _empty_state()
    try:
        with path.open("r", encoding="utf-8") as f:
            return _normalize_state(json.load(f))
    except Exception as exc:
        _debug(f"[CELL-LINEAGE] State konnte nicht geladen werden ({path}): {exc}; nutze leeren State")
        return _empty_state()


def save_lineage_state(state: dict) -> None:
    path = _state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(_normalize_state(state), f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    except Exception as exc:
        _debug(f"[CELL-LINEAGE] State konnte nicht gespeichert werden ({path}): {exc}")


def append_lineage_event(event: dict) -> None:
    try:
        path = _events_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception as exc:
        _debug(f"[CELL-LINEAGE] Event konnte nicht geschrieben werden: {exc}")


def _timestamp_str(timestamp: str | None = None) -> str:
    if timestamp:
        return str(timestamp)
    return datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")


def _date_key(timestamp: str | None) -> str:
    raw = _timestamp_str(timestamp)
    for fmt in ("%Y-%m-%d_%H-%M-%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y%m%d_%H%M%S"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y%m%d")
        except ValueError:
            continue
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) >= 8:
        return digits[:8]
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def make_cell_id(timestamp: str, state: dict) -> str:
    state = _normalize_state(state)
    day = _date_key(timestamp)
    counters = state.setdefault("date_counters", {})
    counters[day] = int(counters.get(day, 0)) + 1
    prefix = str(_cfg("CELL_ID_PREFIX", CELL_ID_PREFIX) or "WX")
    return f"{prefix}-{day}-{counters[day]:04d}"


def _track_timestamp(track: dict, explicit: str | None) -> str:
    return _timestamp_str(explicit or track.get("source_timestamp") or track.get("first_seen_timestamp") or track.get("last_timestamp") or track.get("timestamp"))


def ensure_ir_track_cell_id(track: dict, *, timestamp: str | None = None, state: dict | None = None) -> tuple[dict, dict]:
    if not isinstance(track, dict):
        return track, _normalize_state(state) if state is not None else load_lineage_state()
    own_state = state is None
    state = load_lineage_state() if state is None else _normalize_state(state)
    ir_track_id = str(track.get("ir_track_id") or track.get("ir_id") or track.get("id") or "").strip()
    if ir_track_id:
        track["ir_track_id"] = ir_track_id
    ts = _track_timestamp(track, timestamp)

    existing_cell_id = track.get("cell_id") or (state.get("ir_to_cell", {}).get(ir_track_id) if ir_track_id else None)
    created = False
    if existing_cell_id:
        cell_id = str(existing_cell_id)
        track["cell_id"] = cell_id
    else:
        cell_id = make_cell_id(ts, state)
        track["cell_id"] = cell_id
        created = True

    if ir_track_id:
        state.setdefault("ir_to_cell", {})[ir_track_id] = cell_id
    cell = state.setdefault("cells", {}).setdefault(cell_id, {
        "cell_id": cell_id,
        "status": "ir_precursor",
        "first_seen_source": track.get("first_seen_source") or "ir108",
        "first_seen_timestamp": track.get("first_seen_timestamp") or ts,
        "last_seen_timestamp": ts,
        "ir_track_id": ir_track_id or None,
        "radar_track_id": track.get("radar_track_id"),
        "radar_confirmed": False,
        "ended": False,
        "aliases": [],
    })
    cell["last_seen_timestamp"] = ts
    cell["ir_track_id"] = cell.get("ir_track_id") or ir_track_id or None
    cell["radar_track_id"] = cell.get("radar_track_id") or track.get("radar_track_id")
    if track.get("radar_confirmed") is True:
        cell["radar_confirmed"] = True
        cell["status"] = "radar_confirmed"
    track.setdefault("first_seen_source", cell.get("first_seen_source") or "ir108")
    track.setdefault("first_seen_timestamp", cell.get("first_seen_timestamp") or ts)

    if created:
        append_lineage_event({
            "event_type": "ir_cell_id_created",
            "cell_id": cell_id,
            "ir_track_id": ir_track_id,
            "timestamp": ts,
            "source": track.get("first_seen_source") or track.get("source_type") or "ir108",
        })
    if own_state:
        save_lineage_state(state)
    return track, state


def ensure_ir_tracks_cell_ids(tracks: list[dict], *, timestamp: str | None = None) -> list[dict]:
    state = load_lineage_state()
    changed = False
    out = []
    for track in tracks or []:
        before = track.get("cell_id") if isinstance(track, dict) else None
        new_track, state = ensure_ir_track_cell_id(track, timestamp=timestamp, state=state)
        changed = changed or (isinstance(track, dict) and track.get("cell_id") != before)
        out.append(new_track)
    if changed:
        save_lineage_state(state)
    return out


def get_cell_id_for_ir_track(ir_track_id: str) -> str | None:
    state = load_lineage_state()
    return state.get("ir_to_cell", {}).get(str(ir_track_id))


# ─────────────────────────────────────────────────────────────────────────────
# 1L.2: deterministisches Score-Matching IR↔Radar
# ─────────────────────────────────────────────────────────────────────────────

def _float_or_none(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        val = float(value)
        return val if math.isfinite(val) else None
    except Exception:
        return None


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip()
    if raw.endswith("Z"):
        raw2 = raw[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(raw2).astimezone(timezone.utc).replace(tzinfo=None)
        except Exception:
            pass
    for fmt in ("%Y-%m-%d_%H-%M-%S", "%Y-%m-%dT%H:%M:%S", "%Y%m%d_%H%M%S"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw).replace(tzinfo=None)
    except Exception:
        return None


def _track_time(track: dict) -> str | None:
    return track.get("last_seen_timestamp") or track.get("last_timestamp") or track.get("timestamp") or track.get("source_timestamp") or track.get("first_seen_timestamp")


def _age_min(track: dict, timestamp: str | None) -> float:
    explicit = _float_or_none(track.get("cloud_age_min") if track.get("cloud_age_min") is not None else track.get("age_min"))
    target = _parse_dt(timestamp)
    src = _parse_dt(_track_time(track))
    if target and src:
        return max(0.0, (target - src).total_seconds() / 60.0)
    return max(0.0, explicit or 0.0)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dp = math.radians(float(lat2) - float(lat1))
    dl = math.radians(float(lon2) - float(lon1))
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1 - a)))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dl = math.radians(float(lon2) - float(lon1))
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def angle_diff_deg(a: float, b: float) -> float:
    return abs((float(a) - float(b) + 180.0) % 360.0 - 180.0)


def predict_ir_position(ir_track: dict, target_timestamp: str | None = None, dt_min: float | None = None) -> tuple[float, float]:
    lat = _float_or_none(ir_track.get("lat"))
    lon = _float_or_none(ir_track.get("lon"))
    if lat is None or lon is None:
        raise ValueError("missing IR coordinates")
    vx = _float_or_none(ir_track.get("vx_deg_min"))
    vy = _float_or_none(ir_track.get("vy_deg_min"))
    if vx is None or vy is None:
        return lat, lon
    if dt_min is None:
        target = _parse_dt(target_timestamp)
        src = _parse_dt(_track_time(ir_track))
        dt_min = (target - src).total_seconds() / 60.0 if target and src else 0.0
    return lat + vy * float(dt_min), lon + vx * float(dt_min)


def _proximity_points(distance: float | None, max_points: float) -> float:
    if distance is None:
        return 0.0
    max_km = float(_cfg("IR_RADAR_MATCH_MAX_KM", IR_RADAR_MATCH_MAX_KM))
    strong = float(_cfg("IR_RADAR_MATCH_STRONG_KM", IR_RADAR_MATCH_STRONG_KM))
    if distance <= strong:
        return max_points
    if distance >= max_km:
        return 0.0
    return max_points * (max_km - distance) / max(0.001, max_km - strong)


def _vector_bearing(obj: dict) -> float | None:
    vx = _float_or_none(obj.get("vx_deg_min") or obj.get("vx"))
    vy = _float_or_none(obj.get("vy_deg_min") or obj.get("vy"))
    if vx is None or vy is None or (abs(vx) + abs(vy) == 0):
        return None
    return (math.degrees(math.atan2(vx, vy)) + 360.0) % 360.0


def _growth_score(ir_track: dict) -> float:
    signals = 0
    total = 4
    if (_float_or_none(ir_track.get("bt_trend_k_per_min")) or 0.0) < 0: signals += 1
    if (_float_or_none(ir_track.get("cloud_height_trend_m_per_min")) or 0.0) > 0: signals += 1
    if (_float_or_none(ir_track.get("area_growth_km2_per_min")) or 0.0) > 0: signals += 1
    if bool(ir_track.get("overshooting_top")): signals += 1
    return signals / total


def _metpot_score(radar_obj: dict, ir_track: dict, weather_context: dict | None) -> float:
    vals = {}
    for src in (weather_context or {}, ir_track or {}, radar_obj or {}):
        if isinstance(src, dict):
            vals.update({k: src.get(k) for k in ("cape", "li", "arome_li", "cin", "lapse_700_500", "ship_index", "lightning_count") if src.get(k) is not None})
    score = 0.0; n = 0
    for key, val in vals.items():
        v = _float_or_none(val)
        if v is None: continue
        n += 1
        if key == "cape": score += min(1.0, max(0.0, v / 2000.0))
        elif key in ("li", "arome_li"): score += min(1.0, max(0.0, (-v + 2.0) / 8.0))
        elif key == "cin": score += min(1.0, max(0.0, 1.0 - abs(v) / 200.0))
        elif key == "lapse_700_500": score += min(1.0, max(0.0, (v - 5.0) / 3.0))
        elif key == "ship_index": score += min(1.0, max(0.0, v / 2.0))
        elif key == "lightning_count": score += min(1.0, max(0.0, v / 10.0))
    return min(1.0, score / n) if n else 0.0


def compute_ir_radar_match_score(radar_obj: dict, ir_track: dict, *, timestamp: str | None = None, weather_context: dict | None = None) -> dict:
    rid = str(radar_obj.get("id") or radar_obj.get("track_id") or "")
    iid = str(ir_track.get("ir_track_id") or ir_track.get("ir_id") or ir_track.get("id") or "")
    base = {"matched": False, "score": 0.0, "decision": "rejected", "reason": "rejected", "ir_id": ir_track.get("ir_id"), "ir_track_id": iid, "radar_track_id": rid, "cell_id": ir_track.get("cell_id"), "centroid_distance_km": None, "predicted_centroid_distance_km": None, "ir_age_min": None, "direction_error_deg": None, "growth_score": 0.0, "metpot_score": 0.0, "score_components": {"distance": 0.0, "predicted_position": 0.0, "time": 0.0, "direction": 0.0, "growth": 0.0, "metpot": 0.0}}
    rlat, rlon = _float_or_none(radar_obj.get("lat")), _float_or_none(radar_obj.get("lon"))
    ilat, ilon = _float_or_none(ir_track.get("lat")), _float_or_none(ir_track.get("lon"))
    if None in (rlat, rlon, ilat, ilon):
        base["reason"] = "missing_coords"; return base
    if ir_track.get("radar_confirmed") is True and str(ir_track.get("radar_track_id") or rid) != rid:
        base["reason"] = "already_radar_confirmed"; return base
    max_km = float(_cfg("IR_RADAR_MATCH_MAX_KM", IR_RADAR_MATCH_MAX_KM))
    dist = haversine_km(rlat, rlon, ilat, ilon); base["centroid_distance_km"] = round(dist, 3)
    if dist > max_km:
        base["reason"] = "distance_too_far"; return base
    age = _age_min(ir_track, timestamp); base["ir_age_min"] = round(age, 3)
    if age > float(_cfg("IR_RADAR_MATCH_LOOKBACK_MIN", IR_RADAR_MATCH_LOOKBACK_MIN)):
        base["reason"] = "ir_too_old"; return base
    comps = base["score_components"]
    comps["distance"] = _proximity_points(dist, 0.30)
    if bool(_cfg("IR_RADAR_MATCH_USE_PREDICTED_POSITION", IR_RADAR_MATCH_USE_PREDICTED_POSITION)):
        plat, plon = predict_ir_position(ir_track, target_timestamp=timestamp)
        pdist = haversine_km(rlat, rlon, plat, plon); base["predicted_centroid_distance_km"] = round(pdist, 3)
        if any(_float_or_none(ir_track.get(k)) is not None for k in ("vx_deg_min", "vy_deg_min")):
            comps["predicted_position"] = _proximity_points(pdist, 0.25)
    full_age = float(_cfg("IR_RADAR_MATCH_MAX_IR_AGE_MIN", IR_RADAR_MATCH_MAX_IR_AGE_MIN))
    lookback = float(_cfg("IR_RADAR_MATCH_LOOKBACK_MIN", IR_RADAR_MATCH_LOOKBACK_MIN))
    comps["time"] = 0.15 if age <= full_age else 0.15 * max(0.0, (lookback - age) / max(0.001, lookback - full_age))
    ib, rb = _vector_bearing(ir_track), _vector_bearing(radar_obj)
    if ib is not None and rb is not None:
        err = angle_diff_deg(ib, rb); base["direction_error_deg"] = round(err, 3); comps["direction"] = 0.10 * max(0.0, 1.0 - err / 180.0)
    if bool(_cfg("IR_RADAR_MATCH_USE_GROWTH_SIGNALS", IR_RADAR_MATCH_USE_GROWTH_SIGNALS)):
        gs = _growth_score(ir_track); base["growth_score"] = round(gs, 3); comps["growth"] = 0.10 * gs
    if bool(_cfg("IR_RADAR_MATCH_USE_METPOT", IR_RADAR_MATCH_USE_METPOT)):
        ms = _metpot_score(radar_obj, ir_track, weather_context); base["metpot_score"] = round(ms, 3); comps["metpot"] = 0.10 * ms
    score = sum(comps.values()); base["score"] = round(score, 4)
    strong_min = float(_cfg("IR_RADAR_MATCH_SCORE_MIN", IR_RADAR_MATCH_SCORE_MIN))
    weak_min = float(_cfg("IR_RADAR_MATCH_SCORE_WEAK_MIN", IR_RADAR_MATCH_SCORE_WEAK_MIN))
    if score >= strong_min:
        base.update({"matched": True, "decision": "strong", "reason": "score_ge_min"})
    elif score >= weak_min:
        base.update({"matched": True, "decision": "weak", "reason": "score_ge_weak_unique"})
    else:
        base["reason"] = "score_below_min"
    for k, v in list(comps.items()): comps[k] = round(v, 4)
    return base


def _real_cell_id(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(str(_cfg("CELL_ID_PREFIX", CELL_ID_PREFIX) or "WX") + "-")


def select_ir_radar_matches(radar_objects: list[dict], ir_tracks: list[dict], *, timestamp: str | None = None, weather_context: dict | None = None) -> tuple[list[dict], dict]:
    candidates = []
    for ri, robj in enumerate(radar_objects or []):
        if _real_cell_id(robj.get("cell_id")):
            continue
        for ii, itrack in enumerate(ir_tracks or []):
            m = compute_ir_radar_match_score(robj, itrack, timestamp=timestamp, weather_context=weather_context)
            if m.get("centroid_distance_km") is not None:
                m["radar_index"] = ri; m["ir_index"] = ii; candidates.append(m)
    candidates.sort(key=lambda m: (bool(m.get("matched")), float(m.get("score") or 0), -float(m.get("ir_age_min") or 9999), -float((ir_tracks[m["ir_index"]] or {}).get("bt_min_k") or 9999), float((ir_tracks[m["ir_index"]] or {}).get("cloud_height_m") or 0)), reverse=True)
    by_ir: dict[int, list[dict]] = {}
    for m in candidates:
        if m.get("matched"):
            by_ir.setdefault(m["ir_index"], []).append(m)
    allowed_ir_radar = set()
    for ii, ms in by_ir.items():
        ms.sort(key=lambda m: (float((radar_objects[m["radar_index"]] or {}).get("core_ratio") or 0), float((radar_objects[m["radar_index"]] or {}).get("area") or (radar_objects[m["radar_index"]] or {}).get("area_km2") or 0), float(m.get("score") or 0)), reverse=True)
        allowed_ir_radar.add((ii, ms[0]["radar_index"]))
    used_radar, used_ir, selected = set(), set(), []
    for m in candidates:
        ri, ii = m["radar_index"], m["ir_index"]
        if not m.get("matched") or ri in used_radar or ii in used_ir or (ii, ri) not in allowed_ir_radar:
            continue
        selected.append(m); used_radar.add(ri); used_ir.add(ii)
    return selected, {"candidates": candidates, "selected_count": len(selected)}


def apply_ir_radar_lineage_match(radar_obj: dict, ir_track: dict, match: dict, state: dict | None = None, *, timestamp: str | None = None) -> tuple[dict, dict, dict]:
    state = load_lineage_state() if state is None else _normalize_state(state)
    if not ir_track.get("cell_id"):
        ir_track, state = ensure_ir_track_cell_id(ir_track, timestamp=timestamp, state=state)
    cell_id = ir_track.get("cell_id")
    ir_track_id = str(ir_track.get("ir_track_id") or ir_track.get("ir_id") or ir_track.get("id") or "")
    radar_track_id = str(radar_obj.get("id") or radar_obj.get("track_id") or "")
    radar_obj.update({"cell_id": cell_id, "ir_match_id": ir_track.get("ir_id"), "ir_track_id": ir_track_id or ir_track.get("ir_id"), "ir_status": "radar_confirmed", "ir_radar_confirmed": True, "ir_is_potential_new_cell": False, "ir_display_as_precursor": False, "ir_only_precursor": 0.0, "lineage_status": "radar_confirmed", "lineage_event": "ir_to_radar_confirmation", "lineage_match_score": match.get("score"), "lineage_match_decision": match.get("decision"), "lineage_match_reason": match.get("reason"), "lineage_match_distance_km": match.get("centroid_distance_km"), "lineage_match_predicted_distance_km": match.get("predicted_centroid_distance_km")})
    for key in ("area_growth_km2_per_min", "cloud_height_trend_m_per_min", "bt_min_k", "bt_mean_k", "bt_trend_k_per_min", "cloud_age_min", "anvil_extension_km", "overshooting_top"):
        if key in ir_track: radar_obj.setdefault("ir_" + key if key.startswith(("area", "cloud_height")) else key, ir_track.get(key))
    ir_track.update({"radar_track_id": radar_obj.get("id"), "status": "radar_confirmed", "radar_confirmed": True, "is_potential_new_cell": False, "display_as_precursor": False, "ir_only_precursor": 0.0})
    state.setdefault("radar_to_cell", {})[radar_track_id] = cell_id
    state.setdefault("ir_to_cell", {})[ir_track_id] = cell_id
    cell = state.setdefault("cells", {}).setdefault(cell_id, {"cell_id": cell_id})
    cell.update({"status": "radar_confirmed", "radar_confirmed": True, "radar_track_id": radar_track_id, "ir_track_id": ir_track_id, "last_seen_timestamp": _timestamp_str(timestamp)})
    event = {"event_type": "ir_to_radar_confirmation", "cell_id": cell_id, "ir_track_id": ir_track_id, "radar_track_id": radar_track_id, "timestamp": _timestamp_str(timestamp), "score": match.get("score"), "decision": match.get("decision"), "centroid_distance_km": match.get("centroid_distance_km"), "predicted_centroid_distance_km": match.get("predicted_centroid_distance_km")}
    append_lineage_event(event)
    match["event"] = event
    return radar_obj, ir_track, state


def update_cell_lineage(radar_objects: list[dict], ir_tracks: list[dict], *, timestamp: str | None = None, weather_context: dict | None = None) -> tuple[list[dict], list[dict], list[dict]]:
    state = load_lineage_state()
    for t in ir_tracks or []:
        ensure_ir_track_cell_id(t, timestamp=timestamp, state=state)
    matches, _info = select_ir_radar_matches(radar_objects or [], ir_tracks or [], timestamp=timestamp, weather_context=weather_context)
    events = []
    for m in matches:
        r, ir = radar_objects[m["radar_index"]], ir_tracks[m["ir_index"]]
        apply_ir_radar_lineage_match(r, ir, m, state=state, timestamp=timestamp)
        events.append(m.get("event"))
    for ir in ir_tracks or []:
        if ir.get("radar_confirmed") is not True:
            ir.setdefault("status", "ir_precursor")
            ir.setdefault("radar_confirmed", False)
            ir.setdefault("is_potential_new_cell", True)
            ir.setdefault("display_as_precursor", True)
            ir.setdefault("ir_only_precursor", 1.0)
    save_lineage_state(state)
    return radar_objects or [], ir_tracks or [], [e for e in events if e]
