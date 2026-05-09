import os
import json
import time
import requests
from math import radians, sin, cos
from datetime import datetime
from zoneinfo import ZoneInfo
from config import SAVE_PATHS

def fetch_and_assign_700hpa_wind(objects, timestamp):
    """
    Holt 700hPa-Winddaten über Open-Meteo API für alle gegebenen Objekte,
    speichert die Daten in SAVE_PATHS["wind"]/wind_<timestamp>.json,
    und fügt sie zur Laufzeit den Objekten (dicts) anhand ihrer ID hinzu.
    """
    output_folder = SAVE_PATHS["wind"].rstrip("/")
    os.makedirs(output_folder, exist_ok=True)
    wind_data = {}

    for obj in objects:
        lat = obj.get("lat")
        lon = obj.get("lon")
        obj_id = obj.get("id")
        if lat is None or lon is None or obj_id is None:
            continue

        speed, dir_cos, dir_sin = get_700hpa_wind(lat, lon)
        if speed is not None:
            wind_data[obj_id] = {
                "id": obj_id,
                "wind_speed_700hPa": speed,
                "wind_dir_cos": dir_cos,
                "wind_dir_sin": dir_sin
            }
        time.sleep(0.3)  # API Rate-Limiting beachten

    # Speichern als JSON-Datei
    output_file = os.path.join(output_folder, f"wind_{timestamp}.json")
    with open(output_file, "w") as f:
        json.dump(list(wind_data.values()), f, indent=2)
    print(f"[INFO] Winddaten gespeichert: {output_file}")

    # Winddaten zur Laufzeit in die Objekte einfügen
    for obj in objects:
        wid = obj.get("id")
        wind = wind_data.get(wid, {})
        obj["wind_speed_700hPa"] = wind.get("wind_speed_700hPa", 0)
        obj["wind_dir_cos"] = wind.get("wind_dir_cos", 0)
        obj["wind_dir_sin"] = wind.get("wind_dir_sin", 0)

    return objects

def get_700hpa_wind(lat, lon):
    """
    Fragt die Open-Meteo API nach Winddaten auf 700 hPa an einem Punkt (lat, lon).
    Rückgabe: (Geschwindigkeit, cos(Richtung), sin(Richtung))
    """
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "wind_speed_700hPa,wind_direction_700hPa",
        "timezone": "Europe/Vienna"
    }
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        now = datetime.now(ZoneInfo("Europe/Vienna")).strftime("%Y-%m-%dT%H:00")
        idx = data["hourly"]["time"].index(now)
        speed = data["hourly"]["wind_speed_700hPa"][idx]
        direction = data["hourly"]["wind_direction_700hPa"][idx]
        dir_rad = radians(direction)
        return round(speed, 2), round(cos(dir_rad), 4), round(sin(dir_rad), 4)
    except Exception as e:
        print(f"[WARNUNG] Fehler bei {lat}, {lon}: {e}")
        return None, None, None
