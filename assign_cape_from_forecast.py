import os
import json
import hashlib
import re
import requests
from shapely.geometry import Point
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from debug_utils import debug_log, log_http_response
from config import BBOX_KAERNTEN_EXTENDED, SAVE_PATHS
from api_cache import cache_key, cache_get, cache_set, get_ttl
import runtime_config


# ─── CAPE Timestamp Normalisierung (Fix B54) ──────────────────────────────────
def _parse_cape_ts(ts_str: str) -> datetime | None:
    """
    Parst einen ISO-8601-Timestamp aus dem CAPE-GeoJSON in ein UTC-datetime.
    Unterstützt Formate mit oder ohne Sekunden, Z-Suffix, Offset und Leerzeichen.
    """
    if not ts_str:
        return None
    normalized = str(ts_str).strip().replace(" ", "T")
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    normalized = re.sub(r"T(\d{2}):(\d{2})([+-])", r"T\1:\2:00\3", normalized)
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _find_nearest_cape_ts(
    target_dt: datetime,
    available_dts: list[datetime],
    max_tolerance_h: float = 2.0,
) -> datetime | None:
    """
    Gibt den nächstgelegenen verfügbaren Timestamp zurück, wenn er innerhalb
    max_tolerance_h Stunden liegt. Sonst None.
    """
    if not available_dts:
        return None
    target_dt = target_dt.astimezone(timezone.utc)
    best = min(available_dts, key=lambda dt: abs((dt - target_dt).total_seconds()))
    diff_h = abs((best - target_dt).total_seconds()) / 3600.0
    if diff_h <= max_tolerance_h:
        return best
    return None
# ─────────────────────────────────────────────────────────────────────────────

def _build_cape_url(bbox: dict) -> str:
    # GeoSphere API v1 grid/forecast — verifizierte Parameter:
    #   bbox:          south,west,north,east (Reihenfolge korrekt laut API-Spec)
    #   output_format: geojson — gültig für v1, liefert FeatureCollection mit
    #                  "timestamps" und "features[].properties.parameters.cape.data"
    #   forecast_offset: 0 = nächster verfügbarer Forecast-Step
    # Bestätigt funktionierend: Cache-HITs in api_call_counts.jsonl sichtbar.
    b = bbox
    bbox_str = f"{b['south']},{b['west']},{b['north']},{b['east']}"
    return (
        "https://dataset.api.hub.geosphere.at/v1/grid/forecast/nwp-v1-1h-2500m?"
        f"parameters=cape&bbox={bbox_str}&forecast_offset=0&output_format=geojson"
    )


SAVE_DIR = SAVE_PATHS["cape"].rstrip("/")
LAST_HASH_FILE = os.path.join(SAVE_DIR, "last_hash_vector.txt")
_current_cache = {"geojson": None, "data": None}


def assign_cape(objects: list, timestamp: str) -> list:
    try:
        bbox = runtime_config.get("BBOX_KAERNTEN_EXTENDED", BBOX_KAERNTEN_EXTENDED)
        cape_url = _build_cape_url(bbox)
        geojson_path = fetch_or_use_latest_geojson(timestamp, cape_url)
        if not geojson_path:
            from debug_utils import log_api_failure
            log_api_failure("GeoSphere-CAPE", cape_url,
                            "geojson-fetch-failed", fallback_used=True)
            return objects

        forecast_data = load_geojson_data(geojson_path)
        if not forecast_data:
            debug_log("[CAPE] Forecast-Datei konnte nicht geladen werden.")
            return objects

        dt_local = parse_timestamp(timestamp)
        dt_utc = dt_local.astimezone(timezone.utc)
        rounded_dt = dt_utc.replace(minute=0, second=0, microsecond=0)

        debug_log(f"[CAPE] Verwende Datei: {geojson_path}")
        debug_log(f"[CAPE] Suche CAPE für Zeitstempel: {rounded_dt.isoformat()}")

        timestamps = forecast_data.get("timestamps", [])
        parsed_timestamps = []
        timestamp_index_by_dt = {}
        for i, ts_raw in enumerate(timestamps):
            ts_dt = _parse_cape_ts(ts_raw)
            if ts_dt is None:
                continue
            parsed_timestamps.append(ts_dt)
            timestamp_index_by_dt.setdefault(ts_dt, i)

        best_dt = rounded_dt if rounded_dt in timestamp_index_by_dt else _find_nearest_cape_ts(
            rounded_dt,
            parsed_timestamps,
            max_tolerance_h=2.0,
        )
        if best_dt is None:
            diff_info = f"{len(parsed_timestamps)} verfügbare Schritte" if parsed_timestamps else "keine Daten"
            debug_log(
                f"[CAPE] Kein Match für {rounded_dt.isoformat()} "
                f"({diff_info}, Toleranz ±2h)"
            )
            if not parsed_timestamps:
                from debug_utils import log_api_failure
                log_api_failure("GeoSphere-CAPE", cape_url,
                                "no-data", fallback_used=True)
            return objects

        index = timestamp_index_by_dt[best_dt]
        diff_min = int(abs((best_dt - rounded_dt).total_seconds()) / 60)
        target_time = best_dt.isoformat()
        if diff_min > 0:
            debug_log(
                f"[CAPE] Nearest-Match: {best_dt.isoformat()} "
                f"(Δ={diff_min} min von Ziel {rounded_dt.isoformat()})"
            )

        # Vorbereitung: alle Forecast-Punkte mit Position und CAPE-Wert
        features = forecast_data.get("features", [])
        data_points = []
        for f in features:
            coords = f.get("geometry", {}).get("coordinates")
            props = f.get("properties", {})
            try:
                cape_values = props["parameters"]["cape"]["data"]
                cape_value = cape_values[index]
                if cape_value is not None:
                    data_points.append((Point(coords), cape_value))
            except Exception:
                continue

        if not data_points:
            from debug_utils import log_api_failure
            log_api_failure("GeoSphere-CAPE", cape_url,
                            f"no-valid-data-for-{target_time}", fallback_used=True)
            return objects

        # Zuordnung: jedes Objekt bekommt den nächstgelegenen CAPE-Wert
        for obj in objects:
            lat, lon = obj.get("lat"), obj.get("lon")
            if lat is None or lon is None:
                obj["cape"] = None
                continue

            p = Point(lon, lat)
            min_dist = float("inf")
            best_value = None
            for point, cape in data_points:
                dist = p.distance(point)
                if dist < min_dist:
                    min_dist = dist
                    best_value = cape
            obj["cape"] = best_value

        debug_log(f"[CAPE] {len(objects)} Objekte wurden mit CAPE-Werten ergänzt.")
        return objects

    except Exception as e:
        debug_log(f"[CAPE] Fehler bei Vektor-Zuordnung: {e}")
        return objects


def parse_timestamp(timestamp_str: str) -> datetime:
    """
    Erkennt alle bekannten Timestamp-Formate.
    Timezone-aware Formate (ISO mit %z) werden direkt zurückgegeben.
    Naive Formate erhalten Europe/Vienna als Zeitzone.
    """
    formats = (
        "%Y%m%d_%H%M%S",
        "%Y-%m-%d_%H-%M-%S",
        "%Y-%m-%d_%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
    )
    for fmt in formats:
        try:
            dt = datetime.strptime(timestamp_str, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo("Europe/Vienna"))
            return dt
        except ValueError:
            continue
    raise ValueError(f"Ungültiges Timestamp-Format: {timestamp_str!r}")


def fetch_or_use_latest_geojson(filetimestamp: str, cape_url: str) -> str | None:
    """
    Holt CAPE-Vektor-Daten von GeoSphere — mit TTL-Cache (30 Min).
    GeoSphere AROME wird alle 3 h neu gerechnet → 30 Min Cache ist sicher.
    """
    os.makedirs(SAVE_DIR, exist_ok=True)

    # --- Cache-Lookup ---
    ck = cache_key("geosphere:cape", cape_url)
    cached_path = cache_get(ck, ttl_seconds=get_ttl("geosphere_cape", 1800))
    if cached_path is not None and isinstance(cached_path, str) and os.path.exists(cached_path):
        debug_log(f"[CAPE] Cache-HIT — kein HTTP-Request (Pfad: {cached_path}).")
        return cached_path

    try:
        import time as _t_cape
        _t0_cape = _t_cape.monotonic()
        response = requests.get(cape_url, timeout=30)
        _dur_cape = (_t_cape.monotonic() - _t0_cape) * 1000
        log_http_response(
            service="geosphere_cape",
            method="GET",
            response=response,
            duration_ms=_dur_cape,
        )
        response.raise_for_status()
        content = response.content

        new_hash = hashlib.md5(content).hexdigest()
        if os.path.exists(LAST_HASH_FILE):
            with open(LAST_HASH_FILE, "r") as f:
                old_hash = f.read().strip()
            if new_hash == old_hash:
                debug_log("[CAPE] Keine neuen Vektor-CAPE-Daten – verwende letzte gespeicherte Datei.")
                latest = get_latest_geojson()
                if latest:
                    cache_set(ck, latest)
                return latest

        save_path = os.path.join(SAVE_DIR, f"cape_vector_{filetimestamp}.geojson")
        with open(save_path, "wb") as f:
            f.write(content)
        with open(LAST_HASH_FILE, "w") as f:
            f.write(new_hash)

        cache_set(ck, save_path)
        debug_log(f"[CAPE] Neue CAPE-Vektor-Datei gespeichert: {save_path}")
        return save_path

    except Exception as e:
        from debug_utils import log_api_failure
        log_api_failure("GeoSphere-CAPE", cape_url,
                        f"{type(e).__name__}: {e}", fallback_used=True)
        debug_log(f"[CAPE] Fehler beim Abrufen der CAPE-Vektor-Daten: {e}")
        return get_latest_geojson()


def get_latest_geojson() -> str | None:
    files = [f for f in os.listdir(SAVE_DIR) if f.endswith(".geojson")]
    if not files:
        debug_log("[CAPE] Keine gespeicherten CAPE-Vektor-Dateien gefunden.")
        return None
    return os.path.join(SAVE_DIR, sorted(files)[-1])


def load_geojson_data(path: str) -> dict | None:
    global _current_cache
    if _current_cache["geojson"] == path:
        return _current_cache["data"]
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        _current_cache = {"geojson": path, "data": data}
        return data
    except Exception as e:
        debug_log(f"[CAPE] Fehler beim Laden von {path}: {e}")
        return None
