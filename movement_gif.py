import os
import cv2
import numpy as np
import glob
import json
from PIL import Image
from collections import defaultdict
from datetime import datetime

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

def create_movement_gif(output_path):
    radar_files = sorted(glob.glob("train_data/radar/*.png"))[-10:]
    object_files = sorted(glob.glob("train_data/objects/*.json"))[-10:]

    if len(radar_files) < 2 or len(object_files) < 2:
        img = np.ones((512, 512, 3), dtype=np.uint8) * 255
        text = "Keine Regenzelle gefunden"
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 1
        color = (0, 0, 0)
        thickness = 2
        text_size = cv2.getTextSize(text, font, font_scale, thickness)[0]
        text_x = (img.shape[1] - text_size[0]) // 2
        text_y = (img.shape[0] + text_size[1]) // 2
        cv2.putText(img, text, (text_x, text_y), font, font_scale, color, thickness, cv2.LINE_AA)
        img_pil = Image.fromarray(img)
        img_pil.save(output_path, format='GIF', save_all=True, append_images=[img_pil]*2, duration=2000, loop=0)
        return

    frames = []
    object_trails = defaultdict(list)
    arrow_length = 30

    for i in range(1, len(radar_files)):
        img = cv2.imread(radar_files[i])
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        objs1 = safe_load_json(object_files[i - 1])
        frame_number = f"{i}/{len(radar_files)-1}"
        filename = os.path.basename(radar_files[i])
        try:
            dt = datetime.strptime(filename.split(".")[0], "%Y-%m-%d_%H-%M-%S")
            timestamp = dt.strftime("%d.%m.%Y %H:%M")
        except Exception:
            timestamp = "?"

        for obj1 in objs1:
            if obj1.get("missing", 0) != 0:
                continue

            obj_id = obj1["id"]
            cx1, cy1 = int(obj1["x"]), int(obj1["y"])

            # Kontur zeichnen (weiß)
            if "contour" in obj1 and isinstance(obj1["contour"], list) and len(obj1["contour"]) >= 3:
                try:
                    contour = np.array(obj1["contour"], dtype=np.int32).reshape(-1, 1, 2)
                    cv2.drawContours(img, [contour], -1, (255, 255, 255), 1)
                except Exception as e:
                    print(f"[WARNUNG] Konturfehler (Objekt {obj_id}): {e}")

            # Objektverlauf (grau)
            object_trails[obj_id].append((cx1, cy1))
            if len(object_trails[obj_id]) > 10:
                object_trails[obj_id] = object_trails[obj_id][-10:]
            for j in range(1, len(object_trails[obj_id])):
                pt1 = object_trails[obj_id][j - 1]
                pt2 = object_trails[obj_id][j]
                cv2.line(img, pt1, pt2, (200, 200, 200), 1)

            # Objekt-ID
            cv2.putText(img, obj_id, (cx1 + 4, cy1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1, cv2.LINE_AA)

            # Bewegungspfeil (ROT)
            vx = obj1.get("vx", 0)
            vy = obj1.get("vy", 0)
            if vx != 0 or vy != 0:
                norm = np.hypot(vx, vy)
                if norm != 0:
                    dx, dy = vx / norm, vy / norm
                    cv2.arrowedLine(img, (cx1, cy1),
                                    (int(cx1 + dx * arrow_length), int(cy1 + dy * arrow_length)),
                                    (255, 0, 0), 2, tipLength=0.3)

            # Kalman-Vorhersage (WEISS)
            # gleiche vx/vy wie oben → optional redundant, falls separiert
            # Kann entfallen oder separat verwendet werden, wenn explizit unterschieden

            # LSTM-Vorhersage (GRÜN)
            lvx, lvy = obj1.get("lstm_vx", 0), obj1.get("lstm_vy", 0)
            if lvx != 0 or lvy != 0:
                norm = np.hypot(lvx, lvy)
                if norm != 0:
                    dx, dy = lvx / norm, lvy / norm
                    cv2.arrowedLine(img, (cx1, cy1),
                                    (int(cx1 + dx * arrow_length), int(cy1 + dy * arrow_length)),
                                    (0, 255, 0), 2, tipLength=0.3)

        # Legende & Zeitstempel
        text = f"Frame {frame_number}   {timestamp}"
        cv2.rectangle(img, (0, img.shape[0] - 45), (img.shape[1], img.shape[0]), (255, 255, 255), -1)
        cv2.putText(img, text, (10, img.shape[0] - 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2, cv2.LINE_AA)
        cv2.putText(img, "ROT = Bewegung, GRUEN = LSTM", (10, img.shape[0] - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)

        frames.append(Image.fromarray(img))

    frames[0].save(output_path, format='GIF', append_images=frames[1:], save_all=True, duration=2000, loop=0)
    print(f"GIF gespeichert: {output_path}")
