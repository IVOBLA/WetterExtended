"""Erzeugt den statischen Hydro-Pegel-zu-Einzugsgebiet-Index."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import config
from hydro_geography import geometry_centroid, geometry_contains_point, haversine_m, point_to_linestring_distance_m, polygon_area_km2


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


def build_station_index(stations_geojson: str, basins_geojson: str | None, flowlines_geojson: str | None, output_dir: str | None = None) -> dict:
    output_dir = output_dir or os.path.join(getattr(config, "HYDRO_STATIC_DIR", "train_data/hydro/static"), "generated")
    default_lag = getattr(config, "HYDRO_DEFAULT_LAG_MIN", [20, 180])
    stations = _read_geojson(stations_geojson)
    basins = _read_geojson(basins_geojson).get("features", []) if basins_geojson and os.path.exists(basins_geojson) else []
    flowlines = _read_geojson(flowlines_geojson).get("features", []) if flowlines_geojson and os.path.exists(flowlines_geojson) else []

    index = []
    station_features = []
    catchment_features = []
    for st in stations.get("features", []):
        pt = _station_point(st)
        sid = str(_prop(st, ["station_id", "id", "number", "pegel_id"], len(index) + 1))
        name = str(_prop(st, ["station_name", "name", "bez", "Bezeichnung"], sid))
        river = str(_prop(st, ["river_name", "river", "gewaesser", "Gewässer"], ""))
        if not pt:
            index.append({"station_id": sid, "station_name": name, "river_name": river, "enabled": False, "quality": "unresolved", "default_lag_min": default_lag})
            continue
        lon, lat = pt
        containing = [b for b in basins if geometry_contains_point(b.get("geometry") or {}, lon, lat)]
        quality = "exact" if containing else "unresolved"
        basin = containing[0] if containing else None
        nearest_basin_hint = None
        if basin is None and basins:
            def basin_dist(b: dict) -> float:
                c = geometry_centroid(b.get("geometry") or {})
                return haversine_m(lon, lat, c[0], c[1]) if c else float("inf")
            nearest = min(basins, key=basin_dist)
            nearest_basin_hint = {
                "catchment_id": str(_prop(nearest, ["catchment_id", "basin_id", "id", "name"], "")),
                "distance_m": round(float(basin_dist(nearest)), 2),
                "note": "unverbindlicher Hinweis; nicht impact_eligible",
            }
        flowline = None
        snap_distance = None
        if flowlines:
            candidates = []
            for fl in flowlines:
                geom = fl.get("geometry") or {}
                if geom.get("type") == "LineString":
                    candidates.append((point_to_linestring_distance_m(lon, lat, geom.get("coordinates") or []), fl))
            if candidates:
                snap_distance, flowline = min(candidates, key=lambda x: x[0])
                if quality == "exact" and snap_distance is not None and snap_distance > 0:
                    quality = "snapped"
        basin_id = str(_prop(basin, ["catchment_id", "basin_id", "id", "name"], "")) if basin else None
        upstream = _prop(basin, ["upstream_catchment_ids", "upstream_ids"], None) if basin else None
        if upstream is None and basin_id:
            upstream = [basin_id]
        area = float(_prop(basin, ["catchment_area_km2", "area_km2"], polygon_area_km2(basin.get("geometry") or {}))) if basin else 0.0
        item = {
            "station_id": sid, "station_name": name, "river_name": river, "lon": lon, "lat": lat,
            "snapped_flowline_id": str(_prop(flowline, ["flowline_id", "id"], "")) if flowline else None,
            "snap_distance_m": round(float(snap_distance), 2) if snap_distance is not None else None,
            "station_basin": basin_id, "catchment_id": basin_id, "upstream_catchment_ids": upstream or [], "catchment_area_km2": round(area, 3),
            "default_lag_min": default_lag, "estimated_lag_min": default_lag, "enabled": quality != "unresolved", "impact_eligible": quality != "unresolved", "quality": quality,
            "reason": ["cell_intersects_upstream_catchment", "not_station_radius_based", "time_lag_window_applied"] if quality != "unresolved" else ["no_hydrological_upstream_catchment_match"],
            "nearest_basin_hint": nearest_basin_hint,
        }
        index.append(item)
        station_features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": item})
        if basin:
            catchment_features.append({"type": "Feature", "geometry": basin.get("geometry"), "properties": item})

    status = {"status": "ok" if index and any(i.get("enabled") for i in index) else "hydro_static_missing", "generated_at": datetime.now(timezone.utc).isoformat(), "station_count": len(index), "enabled_station_count": sum(1 for i in index if i.get("enabled"))}
    _write_json(os.path.join(output_dir, "station_network_index.json"), {"stations": index, "by_station_id": {str(i.get("station_id")): i for i in index}})
    _write_json(os.path.join(output_dir, "hydro_stations.geojson"), {"type": "FeatureCollection", "features": station_features})
    _write_json(os.path.join(output_dir, "station_catchments.geojson"), {"type": "FeatureCollection", "features": catchment_features})
    _write_json(os.path.join(output_dir, "hydro_static_status.json"), status)
    return status
