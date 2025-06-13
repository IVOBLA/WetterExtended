# run_tracking_test.py

import os
import glob
from datetime import datetime
from object_tracking import detect_and_track_objects
from movement_gif import create_movement_gif

# 📌 Startbild (ohne radar_-Präfix im Dateinamen)
start_image = "train_data/radar/2025-06-01_17-43-41.png"
base_dir = os.path.dirname(start_image)

# 🕒 Timestamp extrahieren aus Dateinamen
def extract_timestamp(path):
    name = os.path.basename(path).replace(".png", "")
    return datetime.strptime(name, "%Y-%m-%d_%H-%M-%S")

start_ts = extract_timestamp(start_image)

# 📂 Nur Bilder ohne radar_-Präfix verwenden
all_images = [f for f in glob.glob(os.path.join(base_dir, "*.png")) if not os.path.basename(f).startswith("radar_")]
all_images_sorted = sorted(all_images, key=extract_timestamp)

# 📍 Startindex suchen
start_index = next((i for i, path in enumerate(all_images_sorted) if extract_timestamp(path) == start_ts), None)
if start_index is None:
    raise RuntimeError("Startbild nicht gefunden!")

# 🖼️ 10 weitere Bilder ab Start laden
selected_images = all_images_sorted[start_index:start_index + 11]

print(f"\n📂 Verarbeite {len(selected_images)} Bilder:")
timestamps = []

for img_path in selected_images:
    print(f"  • {img_path}")
    objects, timestamp = detect_and_track_objects(img_path)
    timestamps.append(timestamp)

# 🎞️ GIF erzeugen
print("\n🎞️ Erzeuge movement.gif ...")
create_movement_gif("movement.gif")
print("✅ movement.gif gespeichert.")
