# utils.py

import time
import json
import random
import string
import math
from datetime import datetime, timezone

try:
    from geopy.distance import geodesic
except Exception:
    geodesic = None

def log(msg):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}")

def generate_id(length=8):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=4)

def find_nearest_station(lat, lon, stations):
    if not stations:
        return None
    if lat is None or lon is None:
        return None
    if isinstance(lat, float) and math.isnan(lat):
        return None
    if isinstance(lon, float) and math.isnan(lon):
        return None

    nearest = None
    min_dist = float('inf')

    for station in stations:
        try:
            if not isinstance(station, dict):
                continue
            station_coord = (station.get("lat"), station.get("lon"))
            if None in station_coord:
                continue
            if geodesic is not None:
                dist = geodesic((lat, lon), station_coord).kilometers
            else:
                # Lightweight fallback for test/install environments without
                # geopy. Accuracy is sufficient for nearest-station ordering.
                lat1, lon1, lat2, lon2 = map(math.radians, (lat, lon, station_coord[0], station_coord[1]))
                dlat = lat2 - lat1
                dlon = lon2 - lon1
                a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
                dist = 6371.0 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            if dist < min_dist:
                min_dist = dist
                nearest = station
        except Exception as e:
            log(f"[DEBUG] Fehler bei Station {station.get('station_id', 'unknown')}: {e}")

    return nearest

def calculate_velocity(obj_id, object_files):
    positions = []

    for idx in range(-3, 0):
        real_idx = idx + len(object_files)
        if real_idx < 0:
            continue

        with open(object_files[real_idx]) as f:
            objs = json.load(f)

        match = next((o for o in objs if o["id"] == obj_id), None)
        if match:
            positions.append((match["x"], match["y"]))

    if len(positions) >= 2:
        vx = (positions[-1][0] - positions[0][0]) / (5 * (len(positions) - 1))
        vy = (positions[-1][1] - positions[0][1]) / (5 * (len(positions) - 1))
    else:
        vx, vy = 0, 0

    return vx, vy



def utc_iso_z(dt=None):
    """Zentraler UTC-ISO-Formatter mit 'Z'-Suffix OHNE doppelte Zeitzone.

    - dt=None  -> aktuelle UTC-Zeit
    - aware    -> nach UTC konvertiert
    - naive    -> als UTC interpretiert
    Rueckgabe immer: 'YYYY-MM-DDTHH:MM:SSZ'  (nie '+00:00Z').
    """
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
