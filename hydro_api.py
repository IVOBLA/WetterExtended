# hydro_api.py

import os
import json
import requests
from datetime import datetime

# Speicherort vorbereiten
SAVE_DIR = "train_data/hydro"
os.makedirs(SAVE_DIR, exist_ok=True)

# Tiebel-Stationen
STATION_IDS = [
    "2900020_l",  # Tiebel bei Feldkirchen
    "2900018_l",  # Tiebel bei Himmelberg
]

# API-Basis
BASE_URL = "https://info.ktn.gv.at/asp/hydro/daten/json/station/"

def calculate_impact(q, hq10, hq30, hq100):
    """Berechnet Impact-Stufe basierend auf Abfluss Q."""
    try:
        if q is None or any(x is None for x in [hq10, hq30, hq100]):
            return None
        if q < hq10:
            return 0  # normal
        elif q < hq30:
            return 1  # erhöht
        elif q < hq100:
            return 2  # kritisch
        else:
            return 3  # extrem
    except:
        return None

def fetch_hydro_data(timestamp: str):
    all_data = []

    for station_id in STATION_IDS:
        url = f"{BASE_URL}{station_id}.json"
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()

            q = data.get("letzter_wert_q")
            hq10 = data.get("hq10")
            hq30 = data.get("hq30")
            hq100 = data.get("hq100")
            impact = calculate_impact(q, hq10, hq30, hq100)

            station_data = {
                "id": station_id,
                "name": data.get("name"),
                "fluss": data.get("fluss"),
                "werte": {
                    "q": q,
                    "q_time": data.get("letzter_wert_q_date"),
                    "hq10": hq10,
                    "hq30": hq30,
                    "hq100": hq100
                },
                "impact": impact
            }
            all_data.append(station_data)
        except Exception as e:
            print(f"[FEHLER] {station_id}: {e}")

    # Speichern
    save_path = os.path.join(SAVE_DIR, f"{timestamp}.json")
    with open(save_path, "w") as f:
        json.dump(all_data, f, indent=2)

    print(f"[INFO] {len(all_data)} Hydrostationen gespeichert in {save_path}")

# Testlauf
if __name__ == "__main__":
    now = datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
    fetch_hydro_data(now)
