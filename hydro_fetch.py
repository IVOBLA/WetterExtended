"""Live-Abruf, Cache und Normalisierung der Kärntner Hydro-Abflussdaten."""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from config import SAVE_PATHS
except Exception:  # pragma: no cover
    SAVE_PATHS = {}

HYDRO_SOURCE_URL = "https://info.ktn.gv.at/asp/hydro/daten/json/hdkaernten_abfluss_lite.json"
SERVICE_NAME = "hydro_kaernten"
SOURCE_NAME = "hydro_kaernten"
RAW_DATA_NOTICE = "ungeprüfte Rohdaten / Live-Indikator"
DEFAULT_TTL_SECONDS = int(os.getenv("HYDRO_LIVE_TTL_SECONDS", "600"))
REQUEST_TIMEOUT_SECONDS = float(os.getenv("HYDRO_LIVE_TIMEOUT_SECONDS", "15"))

_BASE_DIR = Path(SAVE_PATHS.get("hydro", "train_data/hydro/live"))
if _BASE_DIR.name != "live":
    _LIVE_DIR = _BASE_DIR / "live"
else:
    _LIVE_DIR = _BASE_DIR
LATEST_FILE = _LIVE_DIR / "latest_hydro.json"
STATUS_FILE = _LIVE_DIR / "hydro_status.json"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_z(dt: datetime | None = None) -> str:
    dt = dt or _utc_now()
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except Exception:
            pass


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _file_age_seconds(path: Path) -> float | None:
    try:
        return max(0.0, time.time() - path.stat().st_mtime)
    except OSError:
        return None


def _to_float(value: Any) -> float | None:
    if value in (None, "", "-", "--"):
        return None
    if isinstance(value, str):
        value = value.strip().replace(",", ".")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pick(d: dict, keys: tuple[str, ...]) -> Any:
    low = {str(k).lower(): v for k, v in d.items()}
    for key in keys:
        if key in d:
            return d[key]
        val = low.get(key.lower())
        if val is not None:
            return val
    return None


def _station_items(raw: Any) -> list[dict]:
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if not isinstance(raw, dict):
        return []
    for key in ("stations", "pegel", "data", "features", "items"):
        val = _pick(raw, (key,))
        if isinstance(val, list):
            if key == "features":
                out = []
                for feat in val:
                    if not isinstance(feat, dict):
                        continue
                    props = feat.get("properties") if isinstance(feat.get("properties"), dict) else {}
                    geom = feat.get("geometry") if isinstance(feat.get("geometry"), dict) else {}
                    coords = geom.get("coordinates") if isinstance(geom.get("coordinates"), list) else []
                    merged = {**props, "raw_feature": feat}
                    if len(coords) >= 2:
                        merged.setdefault("lon", coords[0]); merged.setdefault("lat", coords[1])
                    out.append(merged)
                return out
            return [x for x in val if isinstance(x, dict)]
    if any(k.lower() in {"station_id", "id", "name", "station", "kennzahl"} for k in raw):
        return [raw]
    return []


def normalize_hydro_payload(raw: dict) -> dict:
    fetched_at = _iso_z()
    stations = []
    for item in _station_items(raw):
        station_id = _pick(item, ("station_id", "id", "kennzahl", "hzbnr", "nummer", "station"))
        name = _pick(item, ("name", "station_name", "pegelname", "messstelle", "bezeichnung"))
        river = _pick(item, ("river", "gewaesser", "gewässer", "fluss", "waterbody"))
        measured_at = _pick(item, ("measured_at", "timestamp", "zeit", "datum", "datetime", "messzeit"))
        stations.append({
            "station_id": str(station_id) if station_id is not None else "",
            "name": str(name) if name is not None else "",
            "river": str(river) if river is not None else "",
            "lon": _to_float(_pick(item, ("lon", "lng", "longitude", "x"))),
            "lat": _to_float(_pick(item, ("lat", "latitude", "y"))),
            "q_m3s": _to_float(_pick(item, ("q_m3s", "q", "abfluss", "durchfluss"))),
            "w_cm": _to_float(_pick(item, ("w_cm", "w", "wasserstand", "pegelstand"))),
            "measured_at": str(measured_at) if measured_at is not None else None,
            "hq1": _to_float(_pick(item, ("hq1", "hq_1"))),
            "hq10": _to_float(_pick(item, ("hq10", "hq_10"))),
            "hq30": _to_float(_pick(item, ("hq30", "hq_30"))),
            "hq100": _to_float(_pick(item, ("hq100", "hq_100"))),
            "raw": item,
        })
    return {
        "fetched_at": fetched_at,
        "source": SOURCE_NAME,
        "raw_data_notice": RAW_DATA_NOTICE,
        "stations": stations,
        "status": {"ok": True, "from_cache": False, "station_count": len(stations), "error": None},
    }


def load_latest_hydro_live(max_age_seconds: int | None = None) -> dict | None:
    data = _read_json(LATEST_FILE)
    if data is None:
        return None
    if max_age_seconds is not None:
        age = _file_age_seconds(LATEST_FILE)
        if age is None or age > max_age_seconds:
            return None
    return data



def _log_external_response(response, duration_ms: float, error: str | None = None) -> None:
    try:
        from external_response_logger import persist_requests_response
        persist_requests_response(SERVICE_NAME, "GET", response, duration_ms=duration_ms, fallback=bool(error), error=error)
    except Exception:
        pass


def _log_api_call_safe(response, raw: dict | None, duration_ms: float, error: str | None = None) -> None:
    try:
        from debug_utils import log_api_call
        log_api_call(
            SERVICE_NAME,
            HYDRO_SOURCE_URL,
            getattr(response, "status_code", 0),
            duration_ms=duration_ms,
            method="GET",
            response_payload=raw,
            response_text=None if raw is not None else getattr(response, "text", None),
            content_type=getattr(response, "headers", {}).get("content-type") if getattr(response, "headers", None) else None,
            error=error,
        )
    except Exception:
        pass

def _write_status(status: dict) -> None:
    current = dict(status)
    current.setdefault("updated_at", _iso_z())
    _atomic_write_json(STATUS_FILE, current)


def _mark_cache(data: dict, error: str | None = None) -> dict:
    out = dict(data)
    status = dict(out.get("status") or {})
    status.update({"ok": error is None, "from_cache": True, "station_count": len(out.get("stations") or []), "error": error})
    if error:
        status["last_error"] = error
    out["status"] = status
    return out


def fetch_hydro_live(force: bool = False) -> dict:
    if not force:
        cached = load_latest_hydro_live(max_age_seconds=DEFAULT_TTL_SECONDS)
        if cached is not None:
            result = _mark_cache(cached)
            _write_status(result["status"])
            return result

    started = time.monotonic()
    try:
        from http_retry import retry_get
        response = retry_get(
            HYDRO_SOURCE_URL,
            service=SERVICE_NAME,
            breaker_service=SERVICE_NAME,
            timeout=REQUEST_TIMEOUT_SECONDS,
            max_retries=1,
            headers={"Accept": "application/json"},
        )
        duration_ms = (time.monotonic() - started) * 1000
        _log_external_response(response, duration_ms)
        try:
            raw = response.json()
        except Exception as json_exc:
            _log_api_call_safe(response, None, duration_ms, error=f"{type(json_exc).__name__}: {json_exc}")
            raise
        if not isinstance(raw, dict):
            raise ValueError("Hydro-JSON ist kein Objekt")
        result = normalize_hydro_payload(raw)
        result["status"].update({"ok": True, "from_cache": False, "station_count": len(result["stations"]), "error": None})
        stamp = _utc_now().strftime("%Y-%m-%d_%H-%M-%S")
        _atomic_write_json(_LIVE_DIR / f"hydro_{stamp}.json", result)
        _atomic_write_json(LATEST_FILE, result)
        _write_status(result["status"])
        _log_api_call_safe(response, raw, duration_ms)
        return result
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        try:
            from debug_utils import log_api_failure
            log_api_failure(SERVICE_NAME, HYDRO_SOURCE_URL, error, fallback_used=LATEST_FILE.exists())
        except Exception:
            pass
        cached = load_latest_hydro_live(max_age_seconds=None)
        if cached is not None:
            result = _mark_cache(cached, error)
            _write_status(result["status"])
            return result
        status = {"ok": False, "from_cache": False, "station_count": 0, "error": error, "last_error": error}
        _write_status(status)
        return {"fetched_at": _iso_z(), "source": SOURCE_NAME, "raw_data_notice": RAW_DATA_NOTICE, "stations": [], "status": status}


def get_hydro_status() -> dict:
    status = _read_json(STATUS_FILE) or {}
    status.setdefault("ok", False)
    status.setdefault("from_cache", False)
    status.setdefault("station_count", 0)
    status.setdefault("error", None)
    status["latest_exists"] = LATEST_FILE.exists()
    status["latest_age_seconds"] = _file_age_seconds(LATEST_FILE)
    return status
