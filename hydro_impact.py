"""Hydrologische Impact-Bewertung auf Basis oberliegender Einzugsgebiete.

Diese erste Version erzeugt nur dann Hydro-Impact-Kandidaten, wenn das
Geo-Polygon einer aktiven Regen-/Gewitterzelle ein Stations-Einzugsgebiet
schneidet. Eine spätere Pegelreaktion wird bewusst nicht hier verifiziert.
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import SAVE_PATHS

try:
    SHAPELY_AVAILABLE = importlib.util.find_spec("shapely") is not None
except (ImportError, ValueError):
    SHAPELY_AVAILABLE = False
if SHAPELY_AVAILABLE:
    from shapely.geometry import Polygon, shape
    from shapely.ops import transform
    from shapely.validation import make_valid
else:  # pragma: no cover - schlanker Fallback für Minimalumgebungen
    Polygon = shape = transform = make_valid = None

HYDRO_ENABLED_ENV = "HYDRO_ENABLED"
MIN_OVERLAP_AREA_KM2 = float(os.environ.get("HYDRO_MIN_OVERLAP_AREA_KM2", "1.0"))
MIN_OVERLAP_RATIO_CELL = float(os.environ.get("HYDRO_MIN_OVERLAP_RATIO_CELL", "0.03"))
MIN_DURATION_MIN = float(os.environ.get("HYDRO_MIN_DURATION_MIN", "5"))
RELEVANT_INTENSITIES = {"strong", "severe", "extreme", "rot", "violett", "red", "purple", "heavy"}

_HYDRO_BASE = Path(SAVE_PATHS.get("hydro", "train_data/hydro/live/"))
HYDRO_STATIC_DIR = Path(os.environ.get("HYDRO_STATIC_DIR", str(_HYDRO_BASE.parent / "static" / "generated")))
CATCHMENTS_PATH = Path(os.environ.get("HYDRO_CATCHMENTS_PATH", str(HYDRO_STATIC_DIR / "station_catchments.geojson")))
NETWORK_INDEX_PATH = Path(os.environ.get("HYDRO_NETWORK_INDEX_PATH", str(HYDRO_STATIC_DIR / "station_network_index.json")))
LATEST_HYDRO_PATH = Path(os.environ.get("HYDRO_LATEST_PATH", str(_HYDRO_BASE / "latest_hydro.json")))
IMPACT_DIR = Path(os.environ.get("HYDRO_IMPACT_DIR", str(_HYDRO_BASE.parent / "impact")))
LATEST_IMPACTS_PATH = Path(os.environ.get("HYDRO_LATEST_IMPACTS_PATH", str(IMPACT_DIR / "latest_hydro_impacts.json")))
HYDRO_IMPACT_STATE_PATH = Path(os.environ.get("HYDRO_IMPACT_STATE_PATH", str(IMPACT_DIR / "hydro_impact_state.json")))


def _runtime_get(name: str, default: Any) -> Any:
    try:
        import runtime_config
        return runtime_config.get(name, default)
    except Exception:
        return default

def _runtime_bool(name: str, default: bool) -> bool:
    value = _runtime_get(name, default)
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)

def _runtime_float(name: str, default: float) -> float:
    try:
        return float(_runtime_get(name, default))
    except Exception:
        return float(default)

def hydro_enabled() -> bool:
    if HYDRO_ENABLED_ENV in os.environ:
        return str(os.environ.get(HYDRO_ENABLED_ENV, "true")).strip().lower() not in {"0", "false", "no", "off"}
    return _runtime_bool("HYDRO_ENABLED", True)


def static_data_available() -> bool:
    return CATCHMENTS_PATH.exists() and NETWORK_INDEX_PATH.exists()


def _load_json(path: Path, default: Any) -> Any:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _parse_time(timestamp: str | None) -> datetime:
    if not timestamp:
        return datetime.now(timezone.utc)
    for fmt in ("%Y-%m-%d_%H-%M-%S", "%Y%m%d_%H%M%S"):
        try:
            return datetime.strptime(timestamp, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return datetime.now(timezone.utc)


def _station_id(props: dict[str, Any]) -> str:
    return str(props.get("station_id") or props.get("id") or props.get("peg_id") or props.get("number") or "")


def _cell_id(cell: dict[str, Any]) -> Any:
    return cell.get("id", cell.get("cell_id", cell.get("track_id", "unknown")))


def _to_polygon_from_coords(coords: Any):
    if not isinstance(coords, list) or len(coords) < 3:
        return None
    pts = []
    for p in coords:
        if isinstance(p, (list, tuple)) and len(p) >= 2:
            try:
                pts.append((float(p[0]), float(p[1])))
            except (TypeError, ValueError):
                return None
    if len(pts) < 3:
        return None
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    if not SHAPELY_AVAILABLE:
        return pts
    poly = Polygon(pts)
    return make_valid(poly) if not poly.is_valid else poly


def _cell_polygon(cell: dict[str, Any]):
    for key in ("contour_geo", "polygon_geo", "geo_contour"):
        poly = _to_polygon_from_coords(cell.get(key))
        if poly and (not SHAPELY_AVAILABLE or not poly.is_empty):
            return poly
    geom = cell.get("geometry") or cell.get("polygon")
    if isinstance(geom, dict):
        if not SHAPELY_AVAILABLE:
            g = geom.get("geometry", geom) if geom.get("type") == "Feature" else geom
            if g.get("type") == "Polygon":
                return _to_polygon_from_coords((g.get("coordinates") or [[]])[0])
            return None
        try:
            poly = shape(geom.get("geometry", geom)) if geom.get("type") == "Feature" else shape(geom)
            return make_valid(poly) if not poly.is_valid else poly
        except Exception:
            return None
    return None


def _ring_area_km2(ring) -> float:
    if not ring or len(ring) < 3:
        return 0.0
    lat0 = math.radians(sum(p[1] for p in ring) / len(ring))
    sx = 111.320 * math.cos(lat0)
    sy = 110.574
    pts = [(x * sx, y * sy) for x, y in ring]
    area = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def _area_km2(geom) -> float:
    if geom is None:
        return 0.0
    if not SHAPELY_AVAILABLE:
        return _ring_area_km2(geom)
    if geom.is_empty:
        return 0.0
    c = geom.representative_point()
    lat0 = math.radians(c.y)
    km_per_deg_lat = 110.574
    km_per_deg_lon = 111.320 * math.cos(lat0)
    projected = transform(lambda x, y, z=None: (x * km_per_deg_lon, y * km_per_deg_lat), geom)
    return float(abs(projected.area))


def _bbox(ring):
    xs = [p[0] for p in ring]; ys = [p[1] for p in ring]
    return min(xs), min(ys), max(xs), max(ys)


def _bbox_intersection_ring(a, b):
    aw, as_, ae, an = _bbox(a); bw, bs, be, bn = _bbox(b)
    w, s, e, n = max(aw, bw), max(as_, bs), min(ae, be), min(an, bn)
    if w >= e or s >= n:
        return []
    return [(w, s), (e, s), (e, n), (w, n), (w, s)]


def compute_cell_catchment_overlap(cell, catchment) -> dict:
    """Berechnet Schnittfläche zwischen Zellpolygon und Stations-Einzugsgebiet.

    Ohne Shapely wird bewusst keine produktive Bounding-Box-Attribution erzeugt.
    """
    empty = {"hit": False, "status": "hydro_geometry_unavailable" if not SHAPELY_AVAILABLE else "no_intersection", "overlap_area_km2": 0.0, "overlap_ratio_cell": 0.0, "overlap_ratio_catchment": 0.0, "cell_area_km2": 0.0, "catchment_area_km2": 0.0}
    if not SHAPELY_AVAILABLE:
        return empty
    cell_poly = _cell_polygon(cell)
    try:
        catch_poly = catchment if hasattr(catchment, "intersection") else shape(catchment.get("geometry", catchment))
    except Exception:
        return empty | {"status": "invalid_catchment_geometry"}
    if catch_poly is not None and not catch_poly.is_valid:
        catch_poly = make_valid(catch_poly)
    if cell_poly is None or catch_poly is None or cell_poly.is_empty or catch_poly.is_empty:
        return empty | {"status": "missing_geometry"}
    cell_area = _area_km2(cell_poly)
    catch_area = _area_km2(catch_poly)
    if not cell_poly.intersects(catch_poly):
        return empty | {"cell_area_km2": round(cell_area, 3), "catchment_area_km2": round(catch_area, 3)}
    inter = cell_poly.intersection(catch_poly)
    overlap_area = _area_km2(inter)
    return {
        "hit": overlap_area > 0,
        "status": "ok" if overlap_area > 0 else "no_intersection",
        "overlap_area_km2": round(overlap_area, 3),
        "overlap_ratio_cell": round(overlap_area / cell_area, 4) if cell_area else 0.0,
        "overlap_ratio_catchment": round(overlap_area / catch_area, 4) if catch_area else 0.0,
        "cell_area_km2": round(cell_area, 3),
        "catchment_area_km2": round(catch_area, 3),
    }

def _intensity(cell: dict[str, Any]) -> str:
    return str(cell.get("intensity") or cell.get("intensity_label") or cell.get("max_intensity") or "unknown").lower()


def _duration(cell: dict[str, Any]) -> float:
    for key in ("duration_min", "age_min", "cell_age_min", "lifetime_min"):
        if cell.get(key) is not None:
            try:
                return float(cell[key])
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def score_hydro_impact(cell, station, overlap, context) -> dict:
    reason: list[str] = ["cell_intersects_upstream_catchment", "not_station_radius_based", "time_lag_window_applied", "plausibler Zusammenhang"]
    score = 0.0
    area = float(overlap.get("overlap_area_km2", 0.0))
    ratio_cell = float(overlap.get("overlap_ratio_cell", 0.0))
    duration = _duration(cell)
    intensity = _intensity(cell)

    min_area = _runtime_float("HYDRO_MIN_OVERLAP_AREA_KM2", MIN_OVERLAP_AREA_KM2)
    min_ratio = _runtime_float("HYDRO_MIN_OVERLAP_RATIO_CELL", MIN_OVERLAP_RATIO_CELL)
    if area >= min_area:
        score += min(area / 20.0, 0.25); reason.append("Schnittfläche über Mindestwert")
    else:
        reason.append("Schnittfläche unter Mindestwert")
    if ratio_cell >= min_ratio:
        score += min(ratio_cell, 0.25); reason.append("Relevanter Zellanteil im Einzugsgebiet")
    if intensity in RELEVANT_INTENSITIES:
        score += 0.25; reason.append("Intensität relevant")
    else:
        reason.append("Intensität nicht relevant")
    min_duration = _runtime_float("HYDRO_MIN_DURATION_MIN", MIN_DURATION_MIN)
    if duration >= min_duration:
        score += min(duration / 60.0, 0.15); reason.append("Dauer relevant")
    else:
        reason.append("Dauer zu kurz")
    if station.get("main_river_distance_km") is not None and float(station["main_river_distance_km"]) <= 5:
        score += 0.05; reason.append("Nähe zum Hauptgewässer plausibel")
    if cell.get("motion_direction_deg") is not None and station.get("valley_direction_deg") is not None:
        diff = abs((float(cell["motion_direction_deg"]) - float(station["valley_direction_deg"]) + 180) % 360 - 180)
        if diff <= 45:
            score += 0.05; reason.append("Bewegungsrichtung entlang Tal/Einzugsgebiet plausibel")

    score = round(max(0.0, min(score, 1.0)), 3)
    confidence = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
    return {"impact_score": score, "confidence": confidence, "reason": reason}


def _load_catchments() -> list[dict[str, Any]]:
    data = _load_json(CATCHMENTS_PATH, {})
    return data.get("features", []) if isinstance(data, dict) else []


def evaluate_hydro_impact(objects: list, timestamp: str | None = None, include_rejections: bool = False) -> list[dict]:
    if not hydro_enabled() or not static_data_available() or not SHAPELY_AVAILABLE:
        return []
    network_raw = _load_json(NETWORK_INDEX_PATH, {})
    if isinstance(network_raw, dict) and isinstance(network_raw.get("by_station_id"), dict):
        network = network_raw["by_station_id"]
    elif isinstance(network_raw, dict) and isinstance(network_raw.get("stations"), list):
        network = {str(s.get("station_id")): s for s in network_raw.get("stations", []) if isinstance(s, dict)}
    elif isinstance(network_raw, list):
        network = {str(s.get("station_id")): s for s in network_raw if isinstance(s, dict)}
    else:
        network = network_raw if isinstance(network_raw, dict) else {}
    overrides = _runtime_get("HYDRO_STATION_OVERRIDES", {}) or {}
    latest_hydro = _load_json(LATEST_HYDRO_PATH, {})
    created = _parse_time(timestamp)
    events = []
    for cell in objects or []:
        if str(cell.get("status", cell.get("state", "active"))).lower().startswith("inactive"):
            continue
        for feature in _load_catchments():
            props = dict(feature.get("properties") or {})
            sid = _station_id(props)
            overlap = compute_cell_catchment_overlap(cell, feature)
            if not overlap.get("hit"):
                continue
            if overlap["overlap_area_km2"] < _runtime_float("HYDRO_MIN_OVERLAP_AREA_KM2", MIN_OVERLAP_AREA_KM2) or overlap["overlap_ratio_cell"] < _runtime_float("HYDRO_MIN_OVERLAP_RATIO_CELL", MIN_OVERLAP_RATIO_CELL):
                continue
            station_ctx = {**props, **(network.get(sid, {}) if isinstance(network, dict) else {})}
            if isinstance(overrides, dict):
                station_ctx.update(overrides.get(sid, {}) or {})
            catchment_id = props.get("catchment_id") or station_ctx.get("catchment_id")
            upstream_ids = station_ctx.get("upstream_catchment_ids") or props.get("upstream_catchment_ids") or []
            upstream_id_set = {str(x) for x in upstream_ids if x is not None} if isinstance(upstream_ids, (list, tuple, set)) else {str(upstream_ids)}
            if upstream_id_set and str(catchment_id) not in upstream_id_set:
                if include_rejections:
                    events.append({
                        "cell_id": _cell_id(cell),
                        "station_id": sid,
                        "catchment_id": catchment_id,
                        "upstream_catchment_ids": sorted(upstream_id_set),
                        "relation": "no_hydro_impact",
                        "status": "rejected",
                        "reason": ["outside_upstream_catchment", "not_station_radius_based", "not_nearest_station_based"],
                    })
                continue
            quality = station_ctx.get("quality")
            if not station_ctx.get("enabled", True) or station_ctx.get("ignored") or station_ctx.get("impact_eligible") is not True or quality in {"unresolved", "fallback_nearest_basin", "upstream_topology_missing"}:
                continue
            scored = score_hydro_impact(cell, station_ctx, overlap, {"latest_hydro": latest_hydro})
            relevant = _runtime_get("HYDRO_RELEVANT_INTENSITIES", list(RELEVANT_INTENSITIES))
            relevant_set = {str(x).lower() for x in (relevant if isinstance(relevant, (list, tuple, set)) else str(relevant).split(","))}
            if _intensity(cell) not in relevant_set or _duration(cell) < _runtime_float("HYDRO_MIN_DURATION_MIN", MIN_DURATION_MIN):
                continue
            lag = station_ctx.get("estimated_lag_min") or station_ctx.get("lag_min") or station_ctx.get("default_lag_min") or [20, 180]
            cid = _cell_id(cell)
            events.append({
                "event_id": f"hydro_{created.strftime('%Y%m%d_%H%M%S')}_cell{cid}_station{sid}",
                "created_at": created.isoformat().replace("+00:00", "Z"),
                "cell_id": cid,
                "station_id": sid,
                "station_name": props.get("station_name") or props.get("name"),
                "river": props.get("river") or props.get("waterbody"),
                "relation": "upstream_catchment_hit",
                "overlap_area_km2": overlap["overlap_area_km2"],
                "overlap_ratio_cell": overlap["overlap_ratio_cell"],
                "overlap_ratio_catchment": overlap["overlap_ratio_catchment"],
                "duration_in_catchment_min": int(round(_duration(cell))),
                "cell_duration_in_catchment_min": int(round(_duration(cell))),
                "cell_intensity": _intensity(cell),
                "cell_area_km2": overlap["cell_area_km2"],
                "movement_direction": cell.get("motion_direction_deg") or cell.get("movement_direction"),
                "cell_motion_direction_deg": cell.get("motion_direction_deg"),
                "cell_type": cell.get("type") or cell.get("cell_type"),
                "cell_lat": cell.get("lat") or cell.get("cell_lat") or cell.get("center_lat"),
                "cell_lon": cell.get("lon") or cell.get("cell_lon") or cell.get("center_lon"),
                "station_lat": station_ctx.get("lat") or props.get("lat"),
                "station_lon": station_ctx.get("lon") or props.get("lon"),
                "catchment_id": station_ctx.get("catchment_id") or props.get("catchment_id"),
                "upstream_catchment_ids": station_ctx.get("upstream_catchment_ids") or props.get("upstream_catchment_ids") or [],
                "source_quality": station_ctx.get("source_quality") or station_ctx.get("quality"),
                "flow_distance_km": station_ctx.get("flow_distance_km") if station_ctx.get("flow_distance_available") else None,
                "expected_lag_min": lag[0] if isinstance(lag, (list, tuple)) else lag,
                "expected_lag_window_min": lag,
                "precipitation_proxy": {"intensity": _intensity(cell), "duration_min": _duration(cell), "overlap_area_km2": overlap["overlap_area_km2"]},
                "estimated_lag_min": lag,
                **scored,
                "status": "pending",
                "verification": None,
            })
    return events


def save_hydro_impact_events(events, timestamp) -> Path:
    IMPACT_DIR.mkdir(parents=True, exist_ok=True)
    dt = _parse_time(timestamp)
    path = IMPACT_DIR / f"hydro_impact_{dt.strftime('%Y-%m-%d')}.jsonl"
    with path.open("a", encoding="utf-8") as f:
        for event in events or []:
            f.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    with LATEST_IMPACTS_PATH.open("w", encoding="utf-8") as f:
        json.dump(list(events or []), f, ensure_ascii=False, indent=2)
    return path


def _load_hydro_impact_state() -> dict[str, Any]:
    data = _load_json(HYDRO_IMPACT_STATE_PATH, {})
    return data if isinstance(data, dict) else {}


def save_hydro_impact_state(event_id: str, state: dict[str, Any]) -> None:
    if not event_id:
        return
    current = _load_hydro_impact_state()
    events = current.get("events") if isinstance(current.get("events"), dict) else {}
    events[str(event_id)] = {**(events.get(str(event_id), {}) if isinstance(events.get(str(event_id)), dict) else {}), **state}
    current.update({"updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "events": events})
    HYDRO_IMPACT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    HYDRO_IMPACT_STATE_PATH.write_text(json.dumps(current, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def load_pending_hydro_impacts() -> list[dict]:
    state_events = (_load_hydro_impact_state().get("events") or {})
    by_id: dict[str, dict[str, Any]] = {}
    for path in sorted(IMPACT_DIR.glob("hydro_impact_*.jsonl")):
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                event_id = str(event.get("event_id") or "")
                if not event_id:
                    continue
                merged = {**event, **(state_events.get(event_id) if isinstance(state_events.get(event_id), dict) else {})}
                by_id[event_id] = merged
    return [event for event in by_id.values() if event.get("status") == "pending"]
