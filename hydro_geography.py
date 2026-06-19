"""Kleine GeoJSON-/Geometrie-Helfer für die statische Hydrologie.

Bewusst ohne schwere GIS-Abhängigkeiten, damit WetterExtended auch auf kleinen
Systemen und in Tests ohne Shapely/GeoPandas lauffähig bleibt.
"""
from __future__ import annotations

import math
from typing import Any, Iterable

EARTH_RADIUS_M = 6_371_000.0


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _point_segment_distance_planar_m(lon: float, lat: float, a: list, b: list) -> float:
    ref_lat = math.radians(lat)
    scale_x = 111_320.0 * max(math.cos(ref_lat), 0.01)
    scale_y = 110_540.0
    px, py = lon * scale_x, lat * scale_y
    ax, ay = float(a[0]) * scale_x, float(a[1]) * scale_y
    bx, by = float(b[0]) * scale_x, float(b[1]) * scale_y
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    qx, qy = ax + t * dx, ay + t * dy
    return math.hypot(px - qx, py - qy)


def point_to_linestring_distance_m(lon: float, lat: float, coords: list) -> float:
    if len(coords) < 2:
        return float("inf")
    return min(_point_segment_distance_planar_m(lon, lat, coords[i], coords[i + 1]) for i in range(len(coords) - 1))


def point_in_ring(lon: float, lat: float, ring: list) -> bool:
    inside = False
    if not ring:
        return False
    j = len(ring) - 1
    for i, p in enumerate(ring):
        xi, yi = float(p[0]), float(p[1])
        xj, yj = float(ring[j][0]), float(ring[j][1])
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def point_in_polygon(lon: float, lat: float, polygon_coords: list) -> bool:
    if not polygon_coords or not point_in_ring(lon, lat, polygon_coords[0]):
        return False
    return not any(point_in_ring(lon, lat, hole) for hole in polygon_coords[1:])


def geometry_contains_point(geometry: dict, lon: float, lat: float) -> bool:
    gtype = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if gtype == "Polygon":
        return point_in_polygon(lon, lat, coords)
    if gtype == "MultiPolygon":
        return any(point_in_polygon(lon, lat, poly) for poly in coords)
    return False


def geometry_centroid(geometry: dict) -> tuple[float, float] | None:
    coords: list[tuple[float, float]] = []
    def collect(obj: Any) -> None:
        if isinstance(obj, list) and obj and isinstance(obj[0], (int, float)) and len(obj) >= 2:
            coords.append((float(obj[0]), float(obj[1])))
        elif isinstance(obj, list):
            for item in obj:
                collect(item)
    collect(geometry.get("coordinates") or [])
    if not coords:
        return None
    return (sum(x for x, _ in coords) / len(coords), sum(y for _, y in coords) / len(coords))


def polygon_area_km2(geometry: dict) -> float:
    # Equirectangular Shoelace, für kleine Basins ausreichend reproduzierbar.
    def ring_area(ring: list) -> float:
        if len(ring) < 3:
            return 0.0
        lat0 = math.radians(sum(float(p[1]) for p in ring) / len(ring))
        pts = [(float(p[0]) * 111_320.0 * math.cos(lat0), float(p[1]) * 110_540.0) for p in ring]
        return abs(sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts))) / 2)
    if geometry.get("type") == "Polygon":
        rings = geometry.get("coordinates") or []
        if not rings: return 0.0
        return max(0.0, ring_area(rings[0]) - sum(ring_area(r) for r in rings[1:])) / 1_000_000.0
    if geometry.get("type") == "MultiPolygon":
        return sum(polygon_area_km2({"type": "Polygon", "coordinates": p}) for p in geometry.get("coordinates") or [])
    return 0.0
