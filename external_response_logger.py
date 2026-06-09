"""Persistiert externe API-Requests/Responses für Debug-Dauerläufe."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from export_security import redact_obj, redact_text, redact_url

_MAX_RESPONSE_CHARS = int(os.getenv("WE_EXTERNAL_RESPONSE_MAX_CHARS", "5000000"))
_SOURCE_RE = re.compile(r"[^a-zA-Z0-9_.-]+")


def normalize_source(source: str | None) -> str:
    raw = (source or "other").strip().lower()
    raw = raw.replace("geosphere-tawes", "geosphere_tawes")
    raw = raw.replace("geosphere-nowcast", "geosphere_nowcast")
    raw = raw.replace("open-meteo", "open_meteo")
    raw = raw.replace("eumetview-wms", "eumetview")
    raw = raw.replace("eumetview_wms", "eumetview")
    raw = raw.replace("blitzortung", "blitz")
    clean = _SOURCE_RE.sub("_", raw).strip("_")
    if "tawes" in clean:
        return "geosphere_tawes"
    if "nowcast" in clean:
        return "geosphere_nowcast"
    if "eumet" in clean:
        return "eumetview"
    if "open_meteo" in clean or "openmeteo" in clean:
        return "open_meteo"
    if "blitz" in clean or "lightning" in clean:
        return "blitz"
    if "hydro" in clean:
        return "hydro"
    return clean or "other"


def _coerce_body(body):
    if body is None:
        return None, False
    if isinstance(body, (dict, list)):
        text = json.dumps(redact_obj(body), ensure_ascii=False)
    elif isinstance(body, bytes):
        text = body.decode("utf-8", errors="replace")
    else:
        text = str(body)
    text = redact_text(text)
    truncated = False
    if _MAX_RESPONSE_CHARS > 0 and len(text) > _MAX_RESPONSE_CHARS:
        text = text[:_MAX_RESPONSE_CHARS]
        truncated = True
    return text, truncated


def persist_external_response(
    source: str,
    *,
    url: str = "",
    method: str = "GET",
    status_code: int | None = None,
    duration_ms: float | None = None,
    request_headers=None,
    response_headers=None,
    response_body=None,
    fallback: bool = False,
    error: str | None = None,
    base_dir: str | Path = ".",
) -> Path | None:
    try:
        source_name = normalize_source(source)
        timestamp = datetime.now(timezone.utc)
        body_text, truncated = _coerce_body(response_body)
        record = {
            "timestamp": timestamp.isoformat(timespec="seconds"),
            "source": source_name,
            "url": redact_url(url or ""),
            "method": (method or "GET").upper(),
            "status_code": status_code,
            "duration_ms": duration_ms,
            "request_headers": redact_obj(dict(request_headers or {})) if request_headers else {},
            "response_headers": redact_obj(dict(response_headers or {})) if response_headers else {},
            "response_body": body_text,
            "fallback": bool(fallback),
            "error": redact_text(error) if error else None,
            "truncated": truncated,
        }
        digest = hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]
        status = status_code if status_code is not None else 0
        filename = f"{source_name}_{timestamp.strftime('%Y-%m-%d_%H-%M-%S')}_{status}_{digest}.json"
        target_dir = Path(base_dir) / "train_data" / "external_responses" / source_name
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / filename
        target.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        return target
    except Exception:
        return None


def persist_requests_response(service: str, method: str, response, duration_ms: float | None = None, request_headers=None, fallback: bool = False, error: str | None = None):
    try:
        body = None
        ctype = (response.headers.get("content-type", "") or "").lower()
        if any(x in ctype for x in ("image/", "application/octet-stream", "application/zip", "application/vnd.google-earth.kmz", "image/tiff", "application/geotiff")):
            body = f"<binary response: content_type={ctype}, bytes={len(response.content or b'')}>"
        else:
            body = response.text
        return persist_external_response(
            service,
            url=str(response.url),
            method=method,
            status_code=response.status_code,
            duration_ms=duration_ms,
            request_headers=request_headers or getattr(response.request, "headers", None),
            response_headers=response.headers,
            response_body=body,
            fallback=fallback,
            error=error,
        )
    except Exception:
        return None
