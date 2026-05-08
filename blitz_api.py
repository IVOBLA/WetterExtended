# blitz_api.py

import os
import requests
from datetime import datetime
import json

# Blitzortung.org Zugang (ersetze ggf. durch sichere Konfiguration)
USERNAME = os.getenv("BLITZ_USERNAME", "")
PASSWORD = os.getenv("BLITZ_PASSWORD", "")

# Kärnten-Bounding Box
WEST = 12.5
EAST = 15.0
SOUTH = 46.4
NORTH = 47.1

# Anzahl Blitzdaten, die geholt werden sollen
NUM_STRIKES = 100

# Zielverzeichnis
SAVE_DIR = "train_data/lightning"
os.makedirs(SAVE_DIR, exist_ok=True)

def fetch_and_save_lightning(timestamp: str):
    url = (
        f"https://{USERNAME}:{PASSWORD}@data.blitzortung.org/Data/Protected/last_strikes.php"
        f"?number={NUM_STRIKES}&west={WEST}&east={EAST}&north={NORTH}&south={SOUTH}&sig=0"
    )

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"[FEHLER] Blitzdaten konnten nicht geladen werden: {e}")
        return

    lines = response.text.strip().splitlines()
    strikes = []

    for line in lines:
        parts = line.strip().split(",")
        if len(parts) >= 4:
            try:
                time_str, lat, lon, strength = parts[0], float(parts[1]), float(parts[2]), float(parts[3])
                strikes.append({
                    "timestamp": time_str,
                    "lat": lat,
                    "lon": lon,
                    "strength": strength
                })
            except ValueError:
                continue

    # Datei speichern (z. B. 2025-05-10_20-15-00.json)
    save_path = os.path.join(SAVE_DIR, f"{timestamp}.json")
    with open(save_path, "w") as f:
        json.dump(strikes, f, indent=2)

    print(f"[INFO] {len(strikes)} Blitzereignisse gespeichert in {save_path}")


# Beispiel-Aufruf für aktuelle Zeit (wenn du es testweise laufen willst)
if __name__ == "__main__":
    now = datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
    fetch_and_save_lightning(now)
