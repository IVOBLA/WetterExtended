"""Erzeugt den statischen Hydro-Pegel-zu-Einzugsgebiet-Index."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import config
import runtime_config
from hydro_geography import geometry_centroid, geometry_contains_point, haversine_m, point_to_linestring_distance_m, polygon_area_km2
from hydro_upstream_graph import build_upstream_basin_graph, get_upstream_basin_ids, build_upstream_union_geometry, write_upstream_diagnostics

try:
    from shapely.geometry import Point, mapping, shape
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
    if not feature:
        return ""
    value = _prop(feature, ["catchment_id", "basin_id", "HYDROID", "ID", "IDENTIFIER", "INSPIREID_IDENTIFIER_LOCALID", "id", "name"], None)
    if value not in (None, ""):
        return str(value)
    object_id = _prop(feature, ["OBJECTID"], None)
    if object_id not in (None, ""):
        return f"generated_basin_{object_id}"
    return ""



def _first_prop(feature: dict, needles: list[str]) -> Any:
    props = feature.get("properties") or {}
    low = {str(k).lower(): v for k, v in props.items()}
    for needle in needles:
        for key, value in low.items():
            if needle.lower() in key and value not in (None, ""):
                return value
    return None

def _downstream_id(feature: dict) -> str | None:
    value = _prop(feature, ["downstream_basin_id", "outlet_id", "OUTLET", "RELATEDHYDROOBJECT", "nextdownstream", "next_downstream", "downstream_id", "downstream_catchment_id", "unterlieger", "unterlieger_id", "toid", "to_id"], None)
    if value in (None, ""):
        value = _first_prop(feature, ["nextdownstream", "downstream", "unterlieger"])
    vals = _as_list(value)
    return vals[0] if vals else None

def _feature_id(feature: dict, default: str = "") -> str:
    return _basin_id(feature) or str(_prop(feature, ["hydro_id", "hybas_id", "gml_id", "identifier"], default))

def _normalize_basin_feature(feature: dict) -> dict:
    props = feature.setdefault("properties", {})
    basin_id = _basin_id(feature)
    original = _prop(feature, ["HYDROID", "ID", "IDENTIFIER", "INSPIREID_IDENTIFIER_LOCALID"], basin_id)
    downstream = _downstream_id(feature)
    contains = _as_list(_prop(feature, ["CONTAINSBASIN"], None))
    props["catchment_id"] = basin_id
    props["basin_id"] = basin_id
    props["id"] = basin_id
    props["hydro_id_original"] = str(original) if original not in (None, "") else basin_id
    props["source_schema"] = "GGN_DRAINAGEBASIN"
    if downstream:
        props["downstream_basin_id"] = str(downstream)
        props["outlet_id"] = str(downstream)
    if contains:
        props["contains_basin_ids"] = contains
    return feature

def _build_basin_graph(basin_by_id: dict[str, dict]) -> tuple[dict[str, dict[str, Any]], int, str]:
    graph = {bid: {"basin_id": bid, "downstream_basin_id": None, "upstream_basin_ids": set()} for bid in basin_by_id}
    edge_count = 0
    for bid, basin in basin_by_id.items():
        ds = _downstream_id(basin)
        if ds and ds in basin_by_id and ds != bid:
            graph[bid]["downstream_basin_id"] = ds
            graph[ds]["upstream_basin_ids"].add(bid)
            edge_count += 1
        for up in _as_list(_prop(basin, ["CONTAINSBASIN", "contains_basin_ids"], None)):
            if up in basin_by_id and up != bid:
                graph[bid]["upstream_basin_ids"].add(up)
                graph[up]["downstream_basin_id"] = bid
                edge_count += 1
    for node in graph.values():
        node["upstream_basin_ids"] = sorted(node["upstream_basin_ids"])
    return graph, edge_count, "ggn_basin_attributes" if edge_count else "none"

def _derive_upstream_ids_from_basins(basin_id: str | None, basin_graph: dict[str, dict[str, Any]], edge_count: int) -> tuple[list[str], str, str]:
    if not basin_id or basin_id not in basin_graph:
        return [], "none", "missing"
    if edge_count == 0:
        return [], "none", "missing"
    seen = {basin_id}
    stack = [basin_id]
    while stack:
        cur = stack.pop()
        for up in basin_graph.get(cur, {}).get("upstream_basin_ids", []):
            if up not in seen:
                seen.add(up); stack.append(up)
    return sorted(seen), "ggn_basin_downstream_topology", "derived_from_downstream_attributes"

def _locate_basin(basins: list[dict], lon: float, lat: float) -> tuple[dict | None, str]:
    containing = [b for b in basins if geometry_contains_point(b.get("geometry") or {}, lon, lat)]
    if containing:
        return containing[0], "exact"
    if SHAPELY_AVAILABLE:
        point = Point(lon, lat)
        candidates = []
        for basin in basins:
            try:
                geom = shape(basin.get("geometry") or {})
                geom = make_valid(geom) if not geom.is_valid else geom
                if geom.covers(point):
                    return basin, "exact"
                distance = geom.distance(point)
                if distance <= 1e-6:
                    candidates.append((distance, basin))
            except Exception:
                continue
        if candidates:
            return min(candidates, key=lambda x: x[0])[1], "nearby_unresolved"
    return None, "unresolved"

def _infer_basin_from_flowline(flowline: dict, basin_by_id: dict[str, dict]) -> str | None:
    for names in (["catchment_id", "basin_id", "drainagebasin", "drainage_basin_id"],):
        val = _prop(flowline, list(names), None)
        if val and str(val) in basin_by_id:
            return str(val)
    val = _first_prop(flowline, ["catchment", "basin", "drainagebasin"])
    return str(val) if val and str(val) in basin_by_id else None

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


def _station_admin_enabled(station_id: str) -> bool:
    overrides = runtime_config.get("HYDRO_STATION_OVERRIDES", getattr(config, "HYDRO_STATION_OVERRIDES", {})) or {}
    if not isinstance(overrides, dict):
        return True
    override = overrides.get(str(station_id))
    return not (isinstance(override, dict) and override.get("enabled") is False)

def build_station_index(stations_geojson: str, basins_geojson: str | None, flowlines_geojson: str | None, output_dir: str | None = None) -> dict:
    output_dir = output_dir or os.path.join(getattr(config, "HYDRO_STATIC_DIR", "train_data/hydro/static"), "generated")
    default_lag = getattr(config, "HYDRO_DEFAULT_LAG_MIN", [20, 180])
    try:
        stations = _read_geojson(stations_geojson)
        basins = [_normalize_basin_feature(b) for b in (_read_geojson(basins_geojson).get("features", []) if basins_geojson and os.path.exists(basins_geojson) else [])]
        flowlines = _read_geojson(flowlines_geojson).get("features", []) if flowlines_geojson and os.path.exists(flowlines_geojson) else []
    except Exception as exc:
        status = {"status": "invalid_static_json", "ok": False, "error": f"{type(exc).__name__}: {exc}", "generated_at": datetime.now(timezone.utc).isoformat(), "station_count": 0, "enabled_station_count": 0}
        _write_json(os.path.join(output_dir, "station_network_index.json"), {"stations": [], "by_station_id": {}})
        _write_json(os.path.join(output_dir, "hydro_stations.geojson"), {"type": "FeatureCollection", "features": []})
        _write_json(os.path.join(output_dir, "station_catchments.geojson"), {"type": "FeatureCollection", "features": []})
        _write_json(os.path.join(output_dir, "hydro_static_status.json"), status)
        return status

    basin_by_id = {_feature_id(b): b for b in basins if _feature_id(b)}
    basin_graph, basin_edge_count, topology_source_overall = _build_basin_graph(basin_by_id)
    upstream_graph = build_upstream_basin_graph(basins, flowlines) if basins and flowlines else {"nodes": list(basin_by_id), "edges": [], "confident_edge_count": 0, "cycle_count": 0, "topology_quality": "flowlines_missing" if basins and not flowlines else "upstream_topology_missing", "diagnostics": []}
    if flowlines:
        write_upstream_diagnostics(upstream_graph, output_dir, basins)
    if upstream_graph.get("confident_edge_count", 0) > 0:
        topology_source_overall = "ggn_watercourselink_flowdirection"
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
                "enabled": _station_admin_enabled(sid), "visible": False, "impact_eligible": False, "quality": "unresolved",
                "source_quality": "station_point_missing",
                "topology_source": "none",
                "upstream_source_quality": "station_point_missing",
                "flow_distance_available": False, "flow_distance_km": None,
                "reason": ["upstream_catchment_unavailable"], "default_lag_min": default_lag,
            })
            continue
        lon, lat = pt
        basin, basin_match_quality = _locate_basin(basins, lon, lat)
        basin_id = _basin_id(basin) if basin else None
        declared_upstream = _as_list(_prop(st, ["upstream_catchment_ids", "upstream_ids"], None)) or _as_list(_prop(basin or {}, ["upstream_catchment_ids", "upstream_ids"], None))
        upstream_ids = [uid for uid in declared_upstream if uid in basin_by_id] if basin_match_quality != "nearby_unresolved" else []
        topology_source = "conservative_declared_upstream_catchments" if upstream_ids else "none"
        if upstream_ids:
            upstream_source_quality = "declared_upstream_catchment_ids_valid"
        elif declared_upstream:
            upstream_source_quality = "declared_upstream_catchment_ids_unresolved"
        else:
            graph_ids = get_upstream_basin_ids(basin_id, upstream_graph) if basin_match_quality != "nearby_unresolved" else []
            if graph_ids:
                upstream_ids = graph_ids
                topology_source = "ggn_watercourselink_flowdirection"
                upstream_source_quality = "upstream_graph_confident"
            else:
                derived, topology_source, upstream_source_quality = _derive_upstream_ids_from_basins(basin_id, basin_graph, basin_edge_count)
                upstream_ids = derived if basin_match_quality != "nearby_unresolved" and not flowlines else []
            if basin_match_quality == "nearby_unresolved":
                topology_source = "none"
                upstream_source_quality = "nearby_basin_not_hydrologically_resolved"
        eligible_basins = [basin_by_id[uid] for uid in upstream_ids]
        union_geom = build_upstream_union_geometry(upstream_ids, basin_by_id) if topology_source == "ggn_watercourselink_flowdirection" else (_union_basins(eligible_basins) if upstream_ids else None)
        impact_eligible = bool(union_geom and upstream_ids and SHAPELY_AVAILABLE and basin_match_quality != "nearby_unresolved" and (topology_source != "ggn_watercourselink_flowdirection" or str(basin_id) not in set(upstream_graph.get("cycle_nodes") or [])))
        if impact_eligible:
            source_quality = "upstream_union"
            reason = ["upstream_catchment_union_available", "not_station_radius_based"]
        elif basin_match_quality == "nearby_unresolved":
            source_quality = "nearby_unresolved"
            reason = ["nearby_basin_not_hydrologically_resolved", "upstream_catchment_unavailable", "no_hydrological_upstream_catchment_match"]
        elif not SHAPELY_AVAILABLE:
            source_quality = "hydro_geometry_unavailable"
            reason = ["hydro_geometry_unavailable", "upstream_catchment_unavailable", "no_hydrological_upstream_catchment_match"]
        else:
            source_quality = "upstream_topology_missing" if basin else "hydro_static_missing"
            reason = [source_quality, "upstream_catchment_unavailable", "no_hydrological_upstream_catchment_match"]

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
        quality = "exact" if impact_eligible else basin_match_quality
        area = polygon_area_km2(union_geom or {}) if union_geom else 0.0
        station_enabled = _station_admin_enabled(sid)
        item = {
            "station_id": sid, "station_name": name, "river_name": river, "lon": lon, "lat": lat,
            "snapped_flowline_id": str(_prop(flowline, ["flowline_id", "id"], "")) if flowline else None,
            "snap_distance_m": round(float(snap_distance), 2) if snap_distance is not None else None,
            "flow_distance_available": False, "flow_distance_km": None,
            "topology_source": topology_source, "upstream_source_quality": upstream_source_quality,
            "station_basin": basin_id, "catchment_id": basin_id if impact_eligible else basin_id, "upstream_catchment_ids": upstream_ids, "catchment_area_km2": round(area, 3),
            "hydro_id_original": _prop(basin or {}, ["hydro_id_original"], None),
            "downstream_basin_id": _prop(basin or {}, ["downstream_basin_id"], None),
            "outlet_id": _prop(basin or {}, ["outlet_id"], None),
            "source_schema": _prop(basin or {}, ["source_schema"], None),
            "default_lag_min": default_lag, "estimated_lag_min": default_lag, "enabled": station_enabled, "visible": station_enabled, "impact_eligible": impact_eligible,
            "quality": quality, "source_quality": source_quality, "reason": reason, "nearest_basin_hint": nearest_basin_hint,
        }
        index.append(item)
        station_features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": item})
        if impact_eligible:
            catchment_features.append({"type": "Feature", "geometry": union_geom, "properties": item})
    impact_enabled = sum(1 for i in index if i.get("impact_eligible"))
    visible_enabled = sum(1 for i in index if i.get("enabled") is not False and i.get("visible") is not False)
    matched = sum(1 for i in index if i.get("station_basin"))
    missing = []
    if not basins:
        missing.append("basins")
    if not stations.get("features", []):
        missing.append("stations")
    if impact_enabled == len(index) and impact_enabled:
        status_value = "hydro_static_ready"
    elif impact_enabled:
        status_value = "upstream_topology_partial"
    elif basins and matched and not flowlines:
        status_value = "flowlines_missing"
    elif basins and matched:
        status_value = "upstream_topology_missing"
    else:
        status_value = "station_basin_unavailable" if basins else "hydro_static_missing"
    reason_summary = {
        "station_basin_available": matched,
        "upstream_topology_missing": bool(basins and matched and not impact_enabled),
        "impact_eligible_available": bool(impact_enabled),
    }
    status = {"ok": bool(impact_enabled), "status": status_value, "message": "Hydro-Static bereit." if impact_enabled else "Hydro-Static vorbereitet, aber keine belastbare Upstream-Topologie verfügbar.", "generated_at": datetime.now(timezone.utc).isoformat(), "station_count": len(index), "static_station_count": len(index), "station_basin_count": matched, "basin_count": len(basins), "flowline_count": len(flowlines), "station_basin_match_count": matched, "impact_eligible_station_count": impact_enabled, "enabled_station_count": visible_enabled, "visible_station_count": visible_enabled, "topology_source": topology_source_overall, "topology_quality": upstream_graph.get("topology_quality"), "upstream_graph_node_count": len(upstream_graph.get("nodes", [])), "upstream_graph_edge_count": len(upstream_graph.get("edges", [])), "upstream_graph_confident_edge_count": upstream_graph.get("confident_edge_count", 0), "upstream_graph_cycle_count": upstream_graph.get("cycle_count", 0), "topology_errors": (["upstream_graph_cycle"] if upstream_graph.get("cycle_count", 0) else []), "topology_warnings": upstream_graph.get("diagnostics", [])[:20], "missing": missing, "reason_summary": reason_summary, "errors": [], "warnings": (["flowlines_missing"] if basins and matched and not flowlines else (["upstream_topology_missing"] if matched and not impact_enabled else []))}
    _write_json(os.path.join(output_dir, "station_network_index.json"), {"stations": index, "by_station_id": {str(i.get("station_id")): i for i in index}})
    _write_json(os.path.join(output_dir, "hydro_stations.geojson"), {"type": "FeatureCollection", "features": station_features})
    _write_json(os.path.join(output_dir, "station_catchments.geojson"), {"type": "FeatureCollection", "features": catchment_features})
    _write_json(os.path.join(output_dir, "hydro_static_status.json"), status)
    return status
