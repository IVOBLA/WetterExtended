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

SHAPELY_AVAILABLE = importlib.util.find_spec("shapely") is not None
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


def hydro_enabled() -> bool:
    return os.environ.get(HYDRO_ENABLED_ENV, "true").strip().lower() not in {"0", "false", "no", "off"}


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
    """Berechnet Schnittfläche zwischen Zellpolygon und Stations-Einzugsgebiet."""
    cell_poly = _cell_polygon(cell)
    if not SHAPELY_AVAILABLE:
        geom = catchment.get("geometry", catchment) if isinstance(catchment, dict) else None
        coords = (geom.get("coordinates") or [[]])[0] if isinstance(geom, dict) and geom.get("type") == "Polygon" else None
        catch_poly = _to_polygon_from_coords(coords)
        if cell_poly is None or catch_poly is None:
            return {"hit": False, "overlap_area_km2": 0.0, "overlap_ratio_cell": 0.0, "overlap_ratio_catchment": 0.0, "cell_area_km2": 0.0, "catchment_area_km2": 0.0}
        inter = _bbox_intersection_ring(cell_poly, catch_poly)
        cell_area = _area_km2(cell_poly); catch_area = _area_km2(catch_poly); overlap_area = _area_km2(inter)
        return {"hit": overlap_area > 0, "overlap_area_km2": round(overlap_area, 3), "overlap_ratio_cell": round(overlap_area / cell_area, 4) if cell_area else 0.0, "overlap_ratio_catchment": round(overlap_area / catch_area, 4) if catch_area else 0.0, "cell_area_km2": round(cell_area, 3), "catchment_area_km2": round(catch_area, 3)}
    catch_poly = catchment if hasattr(catchment, "intersection") else shape(catchment.get("geometry", catchment))
    if catch_poly is not None and not catch_poly.is_valid:
        catch_poly = make_valid(catch_poly)
    if cell_poly is None or catch_poly is None or cell_poly.is_empty or catch_poly.is_empty:
        return {"hit": False, "overlap_area_km2": 0.0, "overlap_ratio_cell": 0.0, "overlap_ratio_catchment": 0.0, "cell_area_km2": 0.0, "catchment_area_km2": 0.0}
    if not cell_poly.intersects(catch_poly):
        cell_area = _area_km2(cell_poly)
        return {"hit": False, "overlap_area_km2": 0.0, "overlap_ratio_cell": 0.0, "overlap_ratio_catchment": 0.0, "cell_area_km2": round(cell_area, 3), "catchment_area_km2": round(_area_km2(catch_poly), 3)}
    inter = cell_poly.intersection(catch_poly)
    cell_area = _area_km2(cell_poly)
    catch_area = _area_km2(catch_poly)
    overlap_area = _area_km2(inter)
    return {
        "hit": overlap_area > 0,
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
    reason: list[str] = ["Zelle schneidet oberliegendes Einzugsgebiet"]
    score = 0.0
    area = float(overlap.get("overlap_area_km2", 0.0))
    ratio_cell = float(overlap.get("overlap_ratio_cell", 0.0))
    duration = _duration(cell)
    intensity = _intensity(cell)

    if area >= MIN_OVERLAP_AREA_KM2:
        score += min(area / 20.0, 0.25); reason.append("Schnittfläche über Mindestwert")
    else:
        reason.append("Schnittfläche unter Mindestwert")
    if ratio_cell >= MIN_OVERLAP_RATIO_CELL:
        score += min(ratio_cell, 0.25); reason.append("Relevanter Zellanteil im Einzugsgebiet")
    if intensity in RELEVANT_INTENSITIES:
        score += 0.25; reason.append("Intensität relevant")
    else:
        reason.append("Intensität nicht relevant")
    if duration >= MIN_DURATION_MIN:
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


def evaluate_hydro_impact(objects: list, timestamp: str | None = None) -> list[dict]:
    if not hydro_enabled() or not static_data_available():
        return []
    network = _load_json(NETWORK_INDEX_PATH, {})
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
            if overlap["overlap_area_km2"] < MIN_OVERLAP_AREA_KM2 or overlap["overlap_ratio_cell"] < MIN_OVERLAP_RATIO_CELL:
                continue
            station_ctx = {**props, **(network.get(sid, {}) if isinstance(network, dict) else {})}
            scored = score_hydro_impact(cell, station_ctx, overlap, {"latest_hydro": latest_hydro})
            if _intensity(cell) not in RELEVANT_INTENSITIES or _duration(cell) < MIN_DURATION_MIN:
                continue
            lag = station_ctx.get("estimated_lag_min") or station_ctx.get("lag_min") or [20, 180]
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
                "cell_duration_in_catchment_min": int(round(_duration(cell))),
                "cell_intensity": _intensity(cell),
                "cell_area_km2": overlap["cell_area_km2"],
                "cell_motion_direction_deg": cell.get("motion_direction_deg"),
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


def load_pending_hydro_impacts() -> list[dict]:
    pending = []
    if LATEST_IMPACTS_PATH.exists():
        data = _load_json(LATEST_IMPACTS_PATH, [])
        return [e for e in data if isinstance(e, dict) and e.get("status") == "pending"]
    for path in sorted(IMPACT_DIR.glob("hydro_impact_*.jsonl")):
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("status") == "pending":
                    pending.append(event)
    return pending
