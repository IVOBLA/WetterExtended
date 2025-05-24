# pws_api.py

import os
import json
import requests
from datetime import datetime

# Weather.com API-Zugang (ersetzen!)
PWS_API_KEY = "DUMMY"
STATION_ID = "IFELDK130"

# Speicherort
SAVE_DIR = "train_data/pws"
os.makedirs(SAVE_DIR, exist_ok=True)

def fetch_pws_data(timestamp: str):
    url = (
        f"https://api.weather.com/v2/pws/observations/current"
        f"?stationId={STATION_ID}&format=json&units=m&apiKey={PWS_API_KEY}"
    )

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        # Extraktion der wichtigsten Messwerte
        obs = data.get("observations", [{}])[0]
        pws_data = {
            "station_id": STATION_ID,
            "obs_time": obs.get("obsTimeUtc"),
            "temp_c": obs.get("metric", {}).get("temp"),
            "humidity": obs.get("humidity"),
            "wind_speed_kph": obs.get("metric", {}).get("windSpeed"),
            "wind_gust_kph": obs.get("metric", {}).get("windGust"),
            "wind_dir_deg": obs.get("winddir"),
            "pressure_hpa": obs.get("metric", {}).get("pressure"),
            "precip_mm": obs.get("metric", {}).get("precipTotal")
        }

        save_path = os.path.join(SAVE_DIR, f"{timestamp}.json")
        with open(save_path, "w") as f:
            json.dump(pws_data, f, indent=2)

        print(f"[INFO] Wetterdaten von {STATION_ID} gespeichert in {save_path}")

    except Exception as e:
        print(f"[FEHLER] Weather.com API: {e}")

# Test
if __name__ == "__main__":
    now = datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
    fetch_pws_data(now)
