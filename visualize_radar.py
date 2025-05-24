import cv2
import json
import glob
import numpy as np
import os
import debug_utils
from debug_utils import debug_log # Log-Funktion nutzen
from geo_utils import geo_to_pixel

def create_visualized_radar():
    radar_file = "data/latest.png"

    if not os.path.exists(radar_file):
        debug_log("Kein Radarbild gefunden — Visualisierung übersprungen.")
        return

    object_files = sorted(glob.glob("train_data/objects/*.json"))[-10:]

    if not object_files:
        debug_log("Keine Object-Dateien vorhanden — Visualisierung übersprungen.")
        return

    img = cv2.imread(radar_file)

    if img is None:
        debug_log("Radarbild konnte nicht geladen werden.")
        return

    # Historie sammeln
    history = {}

    for obj_file in object_files:
        with open(obj_file) as f:
            objects = json.load(f)
        for obj in objects:
            obj_id = obj["id"]
            if obj_id not in history:
                history[obj_id] = []
            history[obj_id].append((int(obj["x"]), int(obj["y"])))

    # Linien für Historie zeichnen
    for points in history.values():
        if len(points) > 1:
            for i in range(1, len(points)):
                cv2.line(img, points[i - 1], points[i], (150, 150, 150), 1)

    with open(object_files[-1]) as f:
        last_objects = json.load(f)

    for obj in last_objects:
        cx, cy = geo_to_pixel(obj["lat"], obj["lon"])
        cv2.circle(img, (cx, cy), 15, (0, 0, 255), 2)
        cv2.putText(img, obj["id"], (cx + 5, cy - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        end_point = (int(cx + obj["vx"] * 10), int(cy + obj["vy"] * 10))
        cv2.arrowedLine(img, (cx, cy), end_point, (255, 0, 0), 2)

    output_path = "data/overlay.png"
    overlay = cv2.addWeighted(img, 0.7, np.full_like(img, 255), 0.3, 0)
    cv2.imwrite(output_path, overlay)
    debug_log(f"Overlay gespeichert: {output_path}")
