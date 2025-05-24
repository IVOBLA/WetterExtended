import os
import json
import hashlib
import requests
from shapely.geometry import Point
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from debug_utils import debug_log

CAPE_URL = (
    "https://dataset.api.hub.geosphere.at/v1/grid/forecast/nwp-v1-1h-2500m?"
    "parameters=cape&bbox=46.4,12.7,47.2,14.8&forecast_offset=0&output_format=geojson"
)

SAVE_DIR = "train_data/cape"
LAST_HASH_FILE = os.path.join(SAVE_DIR, "last_hash_vector.txt")
_current_cache = {"geojson": None, "data": None}


def assign_cape(objects: list, timestamp: str) -> list:
    try:
        geojson_path = fetch_or_use_latest_geojson(timestamp)
        if not geojson_path:
            debug_log("[CAPE] Keine GeoJSON-Datei verfügbar.")
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
            debug_log(f"[CAPE] Kein Forecast für {target_time} in timestamps[] enthalten.")
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
            debug_log(f"[CAPE] Keine gültigen CAPE-Daten für {target_time} gefunden.")
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
    formats = (
        "%Y%m%d_%H%M%S",
        "%Y-%m-%d_%H-%M-%S",
        "%Y-%m-%d_%H:%M:%S",    # zusätzlicher Fall mit Doppelpunkten
        "%Y-%m-%dT%H:%M:%S%z",  # ISO mit Zeitzone (optional)
    )
    for fmt in formats:
        try:
            return datetime.strptime(timestamp_str, "%Y-%m-%d_%H-%M-%S").replace(tzinfo=ZoneInfo("Europe/Vienna"))
        except ValueError:
            continue
    raise ValueError(f"Ungültiges Timestamp-Format: {timestamp_str}")


def fetch_or_use_latest_geojson(filetimestamp: str) -> str | None:
    os.makedirs(SAVE_DIR, exist_ok=True)
    try:
        response = requests.get(CAPE_URL, timeout=30)
        response.raise_for_status()
        content = response.content

        new_hash = hashlib.md5(content).hexdigest()
        if os.path.exists(LAST_HASH_FILE):
            with open(LAST_HASH_FILE, "r") as f:
                old_hash = f.read().strip()
            if new_hash == old_hash:
                debug_log("[CAPE] Keine neuen Vektor-CAPE-Daten – verwende letzte gespeicherte Datei.")
                return get_latest_geojson()

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        save_path = os.path.join(SAVE_DIR, f"cape_vector_{filetimestamp}.geojson")
        with open(save_path, "wb") as f:
            f.write(content)
        with open(LAST_HASH_FILE, "w") as f:
            f.write(new_hash)

        debug_log(f"[CAPE] Neue CAPE-Vektor-Datei gespeichert: {save_path}")
        return save_path

    except Exception as e:
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
