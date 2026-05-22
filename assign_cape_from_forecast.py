import os
import json
import hashlib
import requests
from shapely.geometry import Point
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from debug_utils import debug_log
from config import BBOX_KAERNTEN_EXTENDED, SAVE_PATHS
from api_cache import cache_key, cache_get, cache_set, get_ttl
import runtime_config

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
        target_time = rounded_dt.strftime("%Y-%m-%dT%H:%M+00:00")

        debug_log(f"[CAPE] Verwende Datei: {geojson_path}")
        debug_log(f"[CAPE] Suche CAPE für Zeitstempel: {target_time}")

        timestamps = forecast_data.get("timestamps", [])
        try:
            index = timestamps.index(target_time)
        except ValueError:
            from debug_utils import log_api_failure
            log_api_failure("GeoSphere-CAPE", cape_url,
                            f"no-forecast-for-{target_time}", fallback_used=True)
            return objects

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
        response = requests.get(cape_url, timeout=30)
        from debug_utils import log_api_call
        log_api_call("geosphere_cape", url=cape_url, status_code=response.status_code,
                     method="GET", content_type=response.headers.get("content-type"))
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
