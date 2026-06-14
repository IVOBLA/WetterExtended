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
    features = []
    polygon = payload.get("polygon") if isinstance(payload, dict) else None
    for feature in (polygon or {}).get("features", []) if isinstance(polygon, dict) else []:
        if isinstance(feature, dict):
            features.extend(clip_feature_to_bbox(feature))
    severity_values = _sort_severities(list({f["properties"].get("severity") for f in features}))
    return {
        "source": "skywarn.at",
        "source_url": SKYWARN_EXPORT_URL,
        "fetched_at": fetched_at.isoformat(timespec="seconds"),
        "status": "ok",
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


def _write_snapshot(snapshot: dict) -> None:
    path = _snapshot_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")


def _snapshot_is_from_today(path: Path, now: datetime) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        fetched = datetime.fromisoformat(str(data.get("fetched_at")))
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=VIENNA_TZ)
        return fetched.astimezone(VIENNA_TZ).date() == now.date()
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
    if not force and path.exists() and _snapshot_is_from_today(path, now):
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
            http_status = int(getattr(response, "status", response.getcode()))
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

    _write_snapshot(snapshot)
    _log_snapshot(snapshot)
    return snapshot
