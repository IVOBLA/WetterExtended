"""Skywarn export snapshot for the 24h debug export only.

This module intentionally only stores a sanitized daily snapshot under
``train_data/external_responses``. It must not be used by tracking, forecast,
ML, dashboard, API-live or map logic.
"""

from __future__ import annotations

import json
import logging
import re
import socket
import urllib.error
import urllib.request
from datetime import datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from config import (
    BBOX_KAERNTEN_EXTENDED,
    SKYWARN_EXPORT_DIR,
    SKYWARN_EXPORT_TIMEOUT_SECONDS,
    SKYWARN_EXPORT_URL,
)

LOGGER = logging.getLogger(__name__)
VIENNA_TZ = ZoneInfo("Europe/Vienna")
SNAPSHOT_FILENAME = "skywarn_export.json"
USER_AGENT = "WetterExtended/1.0 (+skywarn export snapshot)"


class _PlainTextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data:
            self.parts.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"br", "p", "div", "li", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def get_text(self) -> str:
        return " ".join("".join(self.parts).split())


def _now_vienna() -> datetime:
    return datetime.now(VIENNA_TZ)


def _snapshot_path() -> Path:
    return Path(SKYWARN_EXPORT_DIR) / SNAPSHOT_FILENAME


def _html_to_plaintext(value: Any) -> str:
    parser = _PlainTextHTMLParser()
    parser.feed(str(value or ""))
    text = unescape(parser.get_text())
    return re.sub(r"\s+", " ", text).strip()


def _coerce_coordinate_pair(point: Any) -> list[float] | None:
    if not isinstance(point, (list, tuple)) or len(point) < 2:
        return None
    try:
        lon = float(point[0])
        lat = float(point[1])
    except (TypeError, ValueError):
        return None
    return [lon, lat]


def _normalize_polygon_ring(ring: Any) -> list[list[float]] | None:
    if not isinstance(ring, (list, tuple)):
        return None
    normalized: list[list[float]] = []
    for point in ring:
        pair = _coerce_coordinate_pair(point)
        if pair is not None:
            normalized.append(pair)
    if not normalized:
        return None
    if normalized[0] != normalized[-1]:
        normalized.append(normalized[0].copy())
    return normalized if len(normalized) >= 4 else None


def _looks_like_coordinate_pair(value: Any) -> bool:
    return _coerce_coordinate_pair(value) is not None


def _normalize_polygon_coordinates(coordinates: Any) -> list[list[list[float]]] | None:
    if not isinstance(coordinates, (list, tuple)) or not coordinates:
        return None

    rings_source = [coordinates] if _looks_like_coordinate_pair(coordinates[0]) else coordinates
    rings: list[list[list[float]]] = []
    for ring in rings_source:
        normalized_ring = _normalize_polygon_ring(ring)
        if normalized_ring is not None:
            rings.append(normalized_ring)
    return rings or None


def normalize_skywarn_geometry(geometry: dict) -> dict | None:
    """Normalize defensive Skywarn-only polygon GeoJSON before Shapely parsing."""
    if not isinstance(geometry, dict):
        return None

    geom_type = geometry.get("type")
    if geom_type == "Polygon":
        rings = _normalize_polygon_coordinates(geometry.get("coordinates"))
        if not rings:
            return None
        return {"type": "Polygon", "coordinates": rings}

    if geom_type == "MultiPolygon":
        coordinates = geometry.get("coordinates")
        if not isinstance(coordinates, (list, tuple)):
            return None
        polygons: list[list[list[list[float]]]] = []
        for polygon in coordinates:
            rings = _normalize_polygon_coordinates(polygon)
            if rings:
                polygons.append(rings)
        if not polygons:
            return None
        return {"type": "MultiPolygon", "coordinates": polygons}

    if geom_type == "GeometryCollection":
        geometries = geometry.get("geometries")
        if not isinstance(geometries, (list, tuple)):
            return None
        normalized_geometries = []
        for child in geometries:
            normalized_child = normalize_skywarn_geometry(child)
            if normalized_child is not None:
                normalized_geometries.append(normalized_child)
        if not normalized_geometries:
            return None
        return {"type": "GeometryCollection", "geometries": normalized_geometries}

    return None


def load_skywarn_clip_bbox():
    """Return a Shapely bbox for BBOX_KAERNTEN_EXTENDED without modifying it."""
    from shapely.geometry import box

    bbox = BBOX_KAERNTEN_EXTENDED
    return box(float(bbox["west"]), float(bbox["south"]), float(bbox["east"]), float(bbox["north"]))


def extract_severity(feature: dict) -> int | float | str | None:
    props = feature.get("properties") if isinstance(feature, dict) else None
    if not isinstance(props, dict):
        return None
    return props.get("severity")


def _safe_geometry(feature: dict):
    from shapely.geometry import shape
    from shapely.validation import make_valid

    geom_data = feature.get("geometry") if isinstance(feature, dict) else None
    geom_data = normalize_skywarn_geometry(geom_data)
    if not geom_data:
        return None
    geom = shape(geom_data)
    if geom.is_empty:
        return None
    if not geom.is_valid:
        try:
            geom = make_valid(geom)
        except Exception:
            geom = geom.buffer(0)
    return geom if not geom.is_empty else None


def _polygonal_parts(geom):
    from shapely.geometry import GeometryCollection, MultiPolygon, Polygon

    if geom.is_empty:
        return []
    if isinstance(geom, (Polygon, MultiPolygon)):
        return [geom]
    if isinstance(geom, GeometryCollection):
        parts = []
        for part in geom.geoms:
            parts.extend(_polygonal_parts(part))
        return parts
    return []


def clip_feature_to_bbox(feature: dict) -> list[dict]:
    """Clip one GeoJSON feature to BBOX_KAERNTEN_EXTENDED and keep only severity."""
    geom = _safe_geometry(feature)
    if geom is None:
        return []
    bbox = load_skywarn_clip_bbox()
    if not geom.intersects(bbox):
        return []
    clipped = geom.intersection(bbox)
    if clipped.is_empty:
        return []
    from shapely.geometry import mapping

    severity = extract_severity(feature)
    result: list[dict] = []
    for part in _polygonal_parts(clipped):
        if part.is_empty:
            continue
        result.append({
            "type": "Feature",
            "properties": {"severity": severity},
            "geometry": mapping(part),
        })
    return result


def _sort_severities(values: list[Any]) -> list[Any]:
    def key(value: Any):
        try:
            return (0, float(value))
        except (TypeError, ValueError):
            return (1, str(value))
    return sorted(values, key=key)


def _max_severity(values: list[Any]) -> Any:
    numeric = []
    for value in values:
        try:
            numeric.append((float(value), value))
        except (TypeError, ValueError):
            pass
    if numeric:
        return max(numeric, key=lambda item: item[0])[1]
    return max(values, key=str) if values else None


def build_success_snapshot(payload: dict, fetched_at: datetime | None = None) -> dict:
    fetched_at = fetched_at or _now_vienna()
    # B175/B326: skywarn.at liefert bei leerer Lage JSON `null` / eine
    # Nicht-Dict-Struktur. Das ist kein API-Fehler, sondern der regulaere
    # Zustand "keine Warnlage"; siehe _no_active_warning_snapshot().
    if not isinstance(payload, dict):
        return _no_active_warning_snapshot(fetched_at)
    features = []
    polygon = payload.get("polygon") if isinstance(payload, dict) else None
    malformed_count = 0
    for idx, feature in enumerate((polygon or {}).get("features", []) if isinstance(polygon, dict) else []):
        if not isinstance(feature, dict):
            malformed_count += 1
            LOGGER.warning("Skywarn export: skipping non-dict feature index=%s", idx)
            continue
        try:
            features.extend(clip_feature_to_bbox(feature))
        except Exception as exc:
            malformed_count += 1
            LOGGER.warning(
                "Skywarn export: skipping malformed feature index=%s error=%s",
                idx,
                exc,
            )
            continue
    if malformed_count:
        LOGGER.warning("Skywarn export: skipped malformed_features=%s", malformed_count)
    severity_values = _sort_severities(list({f["properties"].get("severity") for f in features}))
    return {
        "source": "skywarn.at",
        "source_url": SKYWARN_EXPORT_URL,
        "fetched_at": fetched_at.isoformat(timespec="seconds"),
        "status": "ok",
        "data_available": True,
        "valid_from": payload.get("start"),
        "valid_to": payload.get("end"),
        "text": _html_to_plaintext(payload.get("text")),
        "features_inside_kaernten_bbox": {"type": "FeatureCollection", "features": features},
        "severity_values_inside_kaernten_bbox": severity_values,
        "max_severity_inside_kaernten_bbox": _max_severity(severity_values),
        "kaernten_bbox_relevant": bool(features),
        "clip_reference": "BBOX_KAERNTEN_EXTENDED",
        "error": None,
    }


def _error_snapshot(error_type: str, message: str, http_status: int | None = None, fetched_at: datetime | None = None) -> dict:
    error = {"type": error_type, "http_status": http_status, "message": str(message)[:500]}
    return {
        "source": "skywarn.at",
        "source_url": SKYWARN_EXPORT_URL,
        "fetched_at": (fetched_at or _now_vienna()).isoformat(timespec="seconds"),
        "status": "error",
        "valid_from": None,
        "valid_to": None,
        "text": None,
        "features_inside_kaernten_bbox": {"type": "FeatureCollection", "features": []},
        "severity_values_inside_kaernten_bbox": [],
        "max_severity_inside_kaernten_bbox": None,
        "kaernten_bbox_relevant": False,
        "clip_reference": "BBOX_KAERNTEN_EXTENDED",
        "error": error,
    }


def _no_active_warning_snapshot(fetched_at: datetime | None = None) -> dict:
    """B326: Leere Skywarn-Lage als erfolgreichen Abruf ohne Warnlage abbilden."""
    return {
        "source": "skywarn.at",
        "source_url": SKYWARN_EXPORT_URL,
        "fetched_at": (fetched_at or _now_vienna()).isoformat(timespec="seconds"),
        "status": "ok",
        "data_available": False,
        "valid_from": None,
        "valid_to": None,
        "text": None,
        "features_inside_kaernten_bbox": {"type": "FeatureCollection", "features": []},
        "severity_values_inside_kaernten_bbox": [],
        "max_severity_inside_kaernten_bbox": None,
        "kaernten_bbox_relevant": False,
        "clip_reference": "BBOX_KAERNTEN_EXTENDED",
        "error": None,
    }


def _write_snapshot(snapshot: dict) -> None:
    path = _snapshot_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")


def _todays_snapshot_status(path: Path, now: datetime) -> str | None:
    """B297: Liefert den status-Wert ('ok'/'error') des heutigen Snapshots,
    sonst None (kein Snapshot von heute / Datei fehlt / nicht lesbar).
    Ersetzt _snapshot_is_from_today(), damit zwischen gueltigem und
    fehlerhaftem Snapshot unterschieden werden kann — ein Fehlerstatus darf
    weitere Versuche am selben Tag nicht blockieren."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        fetched = datetime.fromisoformat(str(data.get("fetched_at")))
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=VIENNA_TZ)
        if fetched.astimezone(VIENNA_TZ).date() != now.date():
            return None
        return data.get("status")
    except Exception:
        return None


def _todays_snapshot_had_real_data(path: Path, now: datetime) -> bool:
    """B326: True fuer heutigen ok-Snapshot mit echten/Legacy-Warndaten."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        fetched = datetime.fromisoformat(str(data.get("fetched_at")))
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=VIENNA_TZ)
        if fetched.astimezone(VIENNA_TZ).date() != now.date():
            return False
        return data.get("status") == "ok" and data.get("data_available", True) is not False
    except Exception:
        return False


def _log_snapshot(snapshot: dict) -> None:
    if snapshot.get("status") == "ok":
        LOGGER.info(
            "Skywarn export snapshot fetched_at=%s status=%s valid_from=%s valid_to=%s features=%s max_severity=%s",
            snapshot.get("fetched_at"), snapshot.get("status"), snapshot.get("valid_from"), snapshot.get("valid_to"),
            len(snapshot.get("features_inside_kaernten_bbox", {}).get("features", [])),
            snapshot.get("max_severity_inside_kaernten_bbox"),
        )
    elif snapshot.get("status") == "error":
        err = snapshot.get("error") or {}
        LOGGER.warning(
            "Skywarn export snapshot error fetched_at=%s type=%s http_status=%s message=%s",
            snapshot.get("fetched_at"), err.get("type"), err.get("http_status"), err.get("message"),
        )


def fetch_and_store_skywarn_export_snapshot(force: bool = False) -> dict:
    now = _now_vienna()
    path = _snapshot_path()
    # B297: Nur ueberspringen, wenn der heutige Snapshot tatsaechlich gueltig
    # ('ok') ist. Ein Fehlerstatus (z.B. empty_payload) blockierte zuvor jeden
    # weiteren Versuch fuer den Rest des Tages.
    if not force and path.exists() and _todays_snapshot_status(path, now) == "ok":
        return {
            "source": "skywarn.at",
            "source_url": SKYWARN_EXPORT_URL,
            "fetched_at": now.isoformat(timespec="seconds"),
            "status": "skipped_fresh",
            "message": "Skywarn export snapshot for this local date already exists",
            "error": None,
        }

    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    try:
        request = urllib.request.Request(SKYWARN_EXPORT_URL, headers=headers, method="GET")
        with urllib.request.urlopen(request, timeout=SKYWARN_EXPORT_TIMEOUT_SECONDS) as response:
            http_status = int(getattr(response, "status", None) or response.getcode())
            body = response.read()
        if http_status >= 400:
            snapshot = _error_snapshot("http_error", f"HTTP {http_status}", http_status, now)
        else:
            try:
                payload = json.loads(body.decode("utf-8"))
            except ValueError as exc:
                snapshot = _error_snapshot("json_parse_error", exc, http_status, now)
            else:
                snapshot = build_success_snapshot(payload, now)
    except urllib.error.HTTPError as exc:
        snapshot = _error_snapshot("http_error", f"HTTP {exc.code}", int(exc.code), now)
    except (TimeoutError, socket.timeout) as exc:
        snapshot = _error_snapshot("timeout", exc, None, now)
    except Exception as exc:
        snapshot = _error_snapshot("unexpected_error", exc, None, now)

    # B297/B326: Ein bereits heute gespeicherter Snapshot MIT echten Warndaten
    # darf nicht durch einen neuen Snapshot OHNE echte Daten ueberschrieben werden.
    new_has_data = snapshot.get("status") == "ok" and snapshot.get("data_available", True) is not False
    if not new_has_data and _todays_snapshot_had_real_data(path, now):
        _log_snapshot(snapshot)
        return snapshot

    _write_snapshot(snapshot)
    _log_snapshot(snapshot)
    return snapshot


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Fetch Skywarn export snapshot")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Erzwingt einen manuellen Abruf auch wenn heute bereits ein Snapshot existiert",
    )
    args = parser.parse_args()

    try:
        result = fetch_and_store_skywarn_export_snapshot(force=args.force)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(f"[SKYWARN-EXPORT] FEHLER: {exc}", file=sys.stderr)
        raise
