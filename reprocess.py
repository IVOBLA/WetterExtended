# reprocess.py

import os
import glob
import json
import matplotlib.pyplot as plt
from collections import Counter
from object_tracking import detect_and_track_objects
from model_training import retrain_all
from pathlib import Path

# Schalter: Nur wenn True, werden vorhandene Objektdateien überschrieben
RECREATE_OBJECTS = True

def reprocess_all_objects():
    radar_files = sorted(glob.glob("train_data/radar/*.png"))
    print(f"[INFO] {len(radar_files)} Radar-Bilder gefunden.")

    for radar_path in radar_files:
        filename = Path(radar_path).stem.replace("radar_", "")
        print(f"[INFO] Verarbeite: {filename}")

        weather_path = f"train_data/weather/{filename}.json"
        if os.path.exists(weather_path):
            with open(weather_path, "r") as f:
                weather_data = json.load(f)
        else:
            print(f"[WARNUNG] Keine Wetterdaten für {filename} gefunden.")
            continue

        json_path = f"train_data/objects/{filename}.json"
        if not RECREATE_OBJECTS and os.path.exists(json_path):
            print(f"[SKIP] Objektdatei existiert bereits: {json_path}")
            continue

        # Objekte erkennen und speichern
        objects, _ = detect_and_track_objects(radar_path, weather_data)
        if not objects:
            print(f"[INFO] Keine Objekte erkannt in {filename}")
            continue

        with open(json_path, "w") as f:
            json.dump(objects, f, indent=2)

    # 🔁 Trainingsdaten sammeln
    object_files = sorted(glob.glob("train_data/objects/*.json"))
    weather_files = sorted(glob.glob("train_data/weather/*.json"))

    # Objekt-IDs zählen
    id_counter = Counter()
    for path in object_files:
        with open(path) as f:
            try:
                data = json.load(f)
                ids = [obj["id"] for obj in data if "id" in obj]
                id_counter.update(ids)
            except Exception:
                continue

    sequence_length = 3
    valid_ids = {k for k, v in id_counter.items() if v >= sequence_length}
    print(f"[INFO] Gültige Objekt-IDs mit mindestens {sequence_length} Zeitpunkten: {len(valid_ids)}")

    all_objects = []
    timestamps = []
    weather_data = []

    for obj_path, wet_path in zip(object_files, weather_files):
        with open(obj_path) as f_obj, open(wet_path) as f_wet:
            objects = json.load(f_obj)
            weather = json.load(f_wet)

        filtered_objects = [obj for obj in objects if obj.get("id") in valid_ids]

        if filtered_objects and weather:
            all_objects.extend(filtered_objects)
            weather_data.append(weather)
            timestamp = os.path.basename(obj_path).replace(".json", "")
            timestamps.append(timestamp)

    print(f"[INFO] Starte Modell-Retraining auf Basis der aufbereiteten Daten...")
    retrain_all()
    print("[INFO] Training abgeschlossen.")

if __name__ == "__main__":
    reprocess_all_objects()
