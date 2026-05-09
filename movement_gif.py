import os
import cv2
import numpy as np
import glob
import json
from PIL import Image
from collections import defaultdict
from datetime import datetime
from config import UPSCALE_FACTOR, SAVE_PATHS  # Wichtig!

def safe_load_json(path):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r") as f:
            content = f.read()
            if not content.strip():
                return []
            return json.loads(content)
    except json.JSONDecodeError:
        return []

def create_movement_gif(output_path="movement.gif", timestamps=None):
    radar_dir = "data/radar"  # 📷 Skaliertes Bild (wie in debug_overlay)
    object_dir = SAVE_PATHS["objects"].rstrip("/")

    if timestamps:
        radar_files = [os.path.join(radar_dir, f"radar_{ts}.png") for ts in timestamps]
        object_files = [os.path.join(object_dir, f"{ts}.json") for ts in timestamps]
    else:
        radar_files = sorted(glob.glob(f"{radar_dir}/radar_*.png"))[-10:]
        object_files = [
            os.path.join(object_dir, os.path.basename(f).replace("radar_", "").replace(".png", ".json"))
            for f in radar_files
        ]

    if len(radar_files) < 2 or len(object_files) < 2:
        img = np.ones((512, 512, 3), dtype=np.uint8) * 255
        text = "Keine Regenzelle gefunden"
        font = cv2.FONT_HERSHEY_SIMPLEX
        text_size = cv2.getTextSize(text, font, 1, 2)[0]
        text_x = (img.shape[1] - text_size[0]) // 2
        text_y = (img.shape[0] + text_size[1]) // 2
        cv2.putText(img, text, (text_x, text_y), font, 1, (0, 0, 0), 2, cv2.LINE_AA)
        img_pil = Image.fromarray(img)
        img_pil.save(output_path, format='GIF', save_all=True, append_images=[img_pil]*2, duration=2000, loop=0)
        return

    frames = []
    object_trails = defaultdict(list)

    for i in range(len(radar_files)):
        img = cv2.imread(radar_files[i])
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        objs = safe_load_json(object_files[i])
        timestamp = os.path.basename(radar_files[i])[6:-4]
        frame_number = f"{i+1}/{len(radar_files)}"

        for obj in objs:
            if obj.get("missing", 0) != 0:
                continue

            obj_id = obj["id"]
            cx = int(obj["x"] * UPSCALE_FACTOR)
            cy = int(obj["y"] * UPSCALE_FACTOR)

            # Kontur (bereits skaliert)
            if "contour" in obj and isinstance(obj["contour"], list):
                try:
                    contour = np.array(obj["contour"], dtype=np.int32).reshape(-1, 1, 2)
                    cv2.drawContours(img, [contour], -1, (255, 255, 255), 1)
                except Exception:
                    pass

            # Verlauf (grau)
            object_trails[obj_id].append((cx, cy))
            if len(object_trails[obj_id]) > 10:
                object_trails[obj_id] = object_trails[obj_id][-10:]
            for j in range(1, len(object_trails[obj_id])):
                pt1, pt2 = object_trails[obj_id][j-1], object_trails[obj_id][j]
                cv2.line(img, pt1, pt2, (200, 200, 200), 1)

            # ID
            cv2.putText(img, obj_id, (cx + 4, cy - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)

            # Bewegungspfeil (ROT)
            vx, vy = obj.get("vx", 0), obj.get("vy", 0)
            if vx or vy:
                norm = np.hypot(vx, vy)
                if norm:
                    dx, dy = vx / norm, vy / norm
                    cv2.arrowedLine(img, (cx, cy), (int(cx + dx * 30), int(cy + dy * 30)), (255, 0, 0), 2, tipLength=0.3)

            # LSTM-Vorhersage (GRÜN)
            lvx, lvy = obj.get("lstm_vx", 0), obj.get("lstm_vy", 0)
            if lvx or lvy:
                norm = np.hypot(lvx, lvy)
                if norm:
                    dx, dy = lvx / norm, lvy / norm
                    cv2.arrowedLine(img, (cx, cy), (int(cx + dx * 30), int(cy + dy * 30)), (0, 255, 0), 2, tipLength=0.3)

        # Legende
        cv2.rectangle(img, (0, img.shape[0] - 45), (img.shape[1], img.shape[0]), (255, 255, 255), -1)
        cv2.putText(img, f"Frame {frame_number}   {timestamp}", (10, img.shape[0] - 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
        cv2.putText(img, "ROT = Bewegung, GRUEN = LSTM", (10, img.shape[0] - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

        frames.append(Image.fromarray(img))

    frames[0].save(output_path, format='GIF', append_images=frames[1:], save_all=True, duration=2000, loop=0)
    print(f"✅ movement.gif gespeichert: {output_path}")
