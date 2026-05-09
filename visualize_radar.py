import cv2
import json
import glob
import numpy as np
import os
import debug_utils
from debug_utils import debug_log
from geo_utils import geo_to_pixel
from config import SAVE_PATHS


def create_visualized_radar():
    # Neuestes skaliertes Radarbild aus data/radar/ verwenden.
    # Diese Bilder sind zugeschnitten + hochskaliert (UPSCALE_FACTOR=3.0)
    # und stimmen mit den Objekt-Pixelkoordinaten überein.
    scaled_radar_files = sorted(glob.glob(os.path.join("data", "radar", "radar_*.png")))
    if not scaled_radar_files:
        debug_log("Kein skaliertes Radarbild in data/radar/ gefunden — Visualisierung übersprungen.")
        return
    radar_file = scaled_radar_files[-1]

    object_files = sorted(glob.glob(os.path.join(SAVE_PATHS["objects"], "*.json")))[-10:]

    if not object_files:
        debug_log("Keine Object-Dateien vorhanden — Visualisierung übersprungen.")
        return

    img = cv2.imread(radar_file)

    if img is None:
        debug_log(f"Radarbild konnte nicht geladen werden: {radar_file}")
        return

    # Historie sammeln
    history = {}

    from config import UPSCALE_FACTOR as _uf
    for obj_file in object_files:
        with open(obj_file) as f:
            objects = json.load(f)
        for obj in objects:
            obj_id = obj["id"]
            if obj_id not in history:
                history[obj_id] = []
            # x,y in Original-Pixeln → skalieren für skaliertes Bild
            history[obj_id].append((
                int(float(obj.get("x", 0)) * _uf),
                int(float(obj.get("y", 0)) * _uf),
            ))

    # Linien für Historie zeichnen
    for points in history.values():
        if len(points) > 1:
            for i in range(1, len(points)):
                cv2.line(img, points[i - 1], points[i], (150, 150, 150), 1)

    with open(object_files[-1]) as f:
        last_objects = json.load(f)

    from config import UPSCALE_FACTOR
    for obj in last_objects:
        # x,y sind Original-Pixelkoordinaten (vor Upscaling gespeichert).
        # Das Bild ist skaliert → mit UPSCALE_FACTOR multiplizieren.
        cx = int(float(obj.get("x", 0)) * UPSCALE_FACTOR)
        cy = int(float(obj.get("y", 0)) * UPSCALE_FACTOR)
        # vx,vy sind Original-Pixel/Frame → ebenfalls skalieren
        vx_scaled = float(obj.get("vx", 0)) * UPSCALE_FACTOR
        vy_scaled = float(obj.get("vy", 0)) * UPSCALE_FACTOR
        cv2.circle(img, (cx, cy), 15, (0, 0, 255), 2)
        cv2.putText(img, str(obj.get("id", "")), (cx + 5, cy - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        end_point = (int(cx + vx_scaled * 10), int(cy + vy_scaled * 10))
        cv2.arrowedLine(img, (cx, cy), end_point, (255, 0, 0), 2)

    output_path = "data/overlay.png"
    overlay = cv2.addWeighted(img, 0.7, np.full_like(img, 255), 0.3, 0)
    cv2.imwrite(output_path, overlay)
    debug_log(f"Overlay gespeichert: {output_path}")
