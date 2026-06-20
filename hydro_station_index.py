"""Erzeugt den statischen Hydro-Pegel-zu-Einzugsgebiet-Index."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import config
from hydro_geography import geometry_centroid, geometry_contains_point, haversine_m, point_to_linestring_distance_m, polygon_area_km2

try:
    from shapely.geometry import mapping, shape
    from shapely.ops import unary_union
    from shapely.validation import make_valid
    SHAPELY_AVAILABLE = True
except Exception:
    mapping = shape = unary_union = make_valid = None
    SHAPELY_AVAILABLE = False


def _read_geojson(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _prop(feature: dict, names: list[str], default: Any = None) -> Any:
    props = feature.get("properties") or {}
    for name in names:
        if name in props and props[name] not in (None, ""):
            return props[name]
    return default


def _station_point(feature: dict) -> tuple[float, float] | None:
    geom = feature.get("geometry") or {}
    if geom.get("type") == "Point" and len(geom.get("coordinates") or []) >= 2:
        return float(geom["coordinates"][0]), float(geom["coordinates"][1])
    lon = _prop(feature, ["lon", "longitude", "x"])
    lat = _prop(feature, ["lat", "latitude", "y"])
    if lon is not None and lat is not None:
        return float(lon), float(lat)
    return None



def _as_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value if v not in (None, "")]
    if isinstance(value, str):
        return [v.strip() for v in value.replace(";", ",").split(",") if v.strip()]
    return [str(value)]


def _basin_id(feature: dict) -> str:
    return str(_prop(feature, ["catchment_id", "basin_id", "id", "name"], ""))


def _union_basins(features: list[dict]) -> dict | None:
    if not features:
        return None
    if not SHAPELY_AVAILABLE:
        # Ohne Shapely wird bewusst keine produktive Catchment-Union erzeugt.
        # Ein Bounding-Box-/Koordinaten-Fallback duerfte fachlich keine Attribution tragen.
        return None
    shapes = []
    for feature in features:
        try:
            geom = shape(feature.get("geometry") or {})
            shapes.append(make_valid(geom) if not geom.is_valid else geom)
        except Exception:
            continue
    if not shapes:
        return None
    return mapping(unary_union(shapes))

def build_station_index(stations_geojson: str, basins_geojson: str | None, flowlines_geojson: str | None, output_dir: str | None = None) -> dict:
    output_dir = output_dir or os.path.join(getattr(config, "HYDRO_STATIC_DIR", "train_data/hydro/static"), "generated")
    default_lag = getattr(config, "HYDRO_DEFAULT_LAG_MIN", [20, 180])
    try:
        stations = _read_geojson(stations_geojson)
        basins = _read_geojson(basins_geojson).get("features", []) if basins_geojson and os.path.exists(basins_geojson) else []
        flowlines = _read_geojson(flowlines_geojson).get("features", []) if flowlines_geojson and os.path.exists(flowlines_geojson) else []
    except Exception as exc:
        status = {"status": "invalid_static_json", "ok": False, "error": f"{type(exc).__name__}: {exc}", "generated_at": datetime.now(timezone.utc).isoformat(), "station_count": 0, "enabled_station_count": 0}
        _write_json(os.path.join(output_dir, "station_network_index.json"), {"stations": [], "by_station_id": {}})
        _write_json(os.path.join(output_dir, "hydro_stations.geojson"), {"type": "FeatureCollection", "features": []})
        _write_json(os.path.join(output_dir, "station_catchments.geojson"), {"type": "FeatureCollection", "features": []})
        _write_json(os.path.join(output_dir, "hydro_static_status.json"), status)
        return status

    basin_by_id = {_basin_id(b): b for b in basins if _basin_id(b)}
    index = []
    station_features = []
    catchment_features = []
    for st in stations.get("features", []):
        pt = _station_point(st)
        sid = str(_prop(st, ["station_id", "id", "number", "pegel_id"], len(index) + 1))
        name = str(_prop(st, ["station_name", "name", "bez", "Bezeichnung"], sid))
        river = str(_prop(st, ["river_name", "river", "gewaesser", "Gewässer"], ""))
        if not pt:
            index.append({
                "station_id": sid, "station_name": name, "river_name": river,
                "enabled": False, "impact_eligible": False, "quality": "unresolved",
                "source_quality": "station_point_missing",
                "topology_source": "none",
                "upstream_source_quality": "station_point_missing",
                "flow_distance_available": False, "flow_distance_km": None,
                "reason": ["station_catchment_unavailable"], "default_lag_min": default_lag,
            })
            continue
        lon, lat = pt
        containing = [b for b in basins if geometry_contains_point(b.get("geometry") or {}, lon, lat)]
        basin = containing[0] if containing else None
        basin_id = _basin_id(basin) if basin else None
        # Aktuell wird keine automatische Fließtopologie aus dem Gewässernetz berechnet.
        # Produktive Attribution nutzt konservativ nur explizit gelieferte upstream_catchment_ids;
        # Flowline-Snapping unten ist ausschließlich Diagnose und liefert keine Fließwegdistanz.
        declared_upstream = _as_list(_prop(st, ["upstream_catchment_ids", "upstream_ids"], None)) or _as_list(_prop(basin or {}, ["upstream_catchment_ids", "upstream_ids"], None))
        upstream_ids = [uid for uid in declared_upstream if uid in basin_by_id]
        topology_source = "conservative_declared_upstream_catchments" if upstream_ids else "none"
        if upstream_ids:
            upstream_source_quality = "declared_upstream_catchment_ids_valid"
        elif declared_upstream:
            upstream_source_quality = "declared_upstream_catchment_ids_unresolved"
        else:
            upstream_source_quality = "missing"
        eligible_basins = [basin_by_id[uid] for uid in upstream_ids]
        union_geom = _union_basins(eligible_basins) if upstream_ids else None
        impact_eligible = bool(union_geom and upstream_ids and SHAPELY_AVAILABLE)
        if impact_eligible:
            source_quality = "upstream_union"
            reason = ["upstream_catchment_union_available", "not_station_radius_based"]
        elif not SHAPELY_AVAILABLE:
            source_quality = "hydro_geometry_unavailable"
            reason = ["hydro_geometry_unavailable", "station_catchment_unavailable", "no_hydrological_upstream_catchment_match"]
        else:
            source_quality = "upstream_topology_missing" if basin else "hydro_static_missing"
            reason = [source_quality, "station_catchment_unavailable", "no_hydrological_upstream_catchment_match"]

        nearest_basin_hint = None
        if basin is None and basins:
            def basin_dist(b: dict) -> float:
                c = geometry_centroid(b.get("geometry") or {})
                return haversine_m(lon, lat, c[0], c[1]) if c else float("inf")
            nearest = min(basins, key=basin_dist)
            nearest_basin_hint = {"catchment_id": _basin_id(nearest), "distance_m": round(float(basin_dist(nearest)), 2), "note": "unverbindlicher Hinweis; nicht impact_eligible"}

        flowline = None; snap_distance = None
        # Diagnose-Snapping: identifiziert die nächstgelegene Flowline, begründet aber weder
        # impact_eligible noch flow_distance_km. Eine echte Fließwegdistanz darf erst nach
        # Einführung einer belastbaren gerichteten Fließtopologie gesetzt werden.
        if flowlines:
            candidates = []
            for fl in flowlines:
                geom = fl.get("geometry") or {}
                if geom.get("type") == "LineString":
                    candidates.append((point_to_linestring_distance_m(lon, lat, geom.get("coordinates") or []), fl))
            if candidates:
                snap_distance, flowline = min(candidates, key=lambda x: x[0])
        quality = "exact" if impact_eligible else "unresolved"
        area = polygon_area_km2(union_geom or {}) if union_geom else 0.0
        item = {
            "station_id": sid, "station_name": name, "river_name": river, "lon": lon, "lat": lat,
            "snapped_flowline_id": str(_prop(flowline, ["flowline_id", "id"], "")) if flowline else None,
            "snap_distance_m": round(float(snap_distance), 2) if snap_distance is not None else None,
            "flow_distance_available": False, "flow_distance_km": None,
            "topology_source": topology_source, "upstream_source_quality": upstream_source_quality,
            "station_basin": basin_id, "catchment_id": basin_id if impact_eligible else None, "upstream_catchment_ids": upstream_ids, "catchment_area_km2": round(area, 3),
            "default_lag_min": default_lag, "estimated_lag_min": default_lag, "enabled": impact_eligible, "impact_eligible": impact_eligible,
            "quality": quality, "source_quality": source_quality, "reason": reason, "nearest_basin_hint": nearest_basin_hint,
        }
        index.append(item)
        station_features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": item})
        if impact_eligible:
            catchment_features.append({"type": "Feature", "geometry": union_geom, "properties": item})
    enabled = sum(1 for i in index if i.get("impact_eligible"))
    status = {"ok": bool(enabled), "status": "ok" if enabled else "hydro_static_missing", "generated_at": datetime.now(timezone.utc).isoformat(), "station_count": len(index), "enabled_station_count": enabled}
    _write_json(os.path.join(output_dir, "station_network_index.json"), {"stations": index, "by_station_id": {str(i.get("station_id")): i for i in index}})
    _write_json(os.path.join(output_dir, "hydro_stations.geojson"), {"type": "FeatureCollection", "features": station_features})
    _write_json(os.path.join(output_dir, "station_catchments.geojson"), {"type": "FeatureCollection", "features": catchment_features})
    _write_json(os.path.join(output_dir, "hydro_static_status.json"), status)
    return status
