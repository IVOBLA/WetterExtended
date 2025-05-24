# eumetsat_ir.py

import os
import requests
from datetime import datetime
from PIL import Image
from io import BytesIO
import numpy as np
import json
import cv2
from geo_utils import pixel_to_geo

# Speichern
SAVE_IMAGE_DIR = "train_data/ir"
SAVE_CELL_DIR = "train_data/ir_cells"
os.makedirs(SAVE_IMAGE_DIR, exist_ok=True)
os.makedirs(SAVE_CELL_DIR, exist_ok=True)

# WCS-Endpoint & Layer
WCS_BASE = "https://view.eumetsat.int/geoserver/eumetsat/wcs"
COVERAGE_ID = "MSG15_IR_108"
FORMAT = "image/png"

def fetch_ir_image_and_analyze(timestamp: str, cold_percent=5):
    """
    Holt IR-Bild für Kärnten, speichert es und analysiert kalte Zellkerne.
    """
    # LatLonBox für Kärnten
    lat_min, lat_max = 46.4, 47.1
    lon_min, lon_max = 12.5, 15.0

    wcs_url = (
        f"{WCS_BASE}?service=WCS&version=2.0.1&request=GetCoverage"
        f"&coverageId={COVERAGE_ID}&format={FORMAT}"
        f"&subset=Lat({lat_min},{lat_max})&subset=Long({lon_min},{lon_max})"
    )

    try:
        response = requests.get(wcs_url, timeout=20)
        response.raise_for_status()

        # Bild speichern
        img = Image.open(BytesIO(response.content)).convert("L")
        image_path = os.path.join(SAVE_IMAGE_DIR, f"{timestamp}.png")
        img.save(image_path)
        print(f"[INFO] IR-Bild gespeichert: {image_path}")

        # Analyse starten
        np_img = np.array(img)
        threshold = np.percentile(np_img, cold_percent)
        cold_mask = (np_img <= threshold).astype(np.uint8) * 255
        contours, _ = cv2.findContours(cold_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        cells = []
        for i, contour in enumerate(contours):
            if cv2.contourArea(contour) < 20:
                continue

            M = cv2.moments(contour)
            if M["m00"] == 0:
                continue

            cx = int(M["m10"] / M["m00"])
            cy = int(M["m01"] / M["m00"])
            lat, lon = pixel_to_geo(cx, cy)

            cell = {
                "id": f"ir_{i}_{timestamp}",
                "x": cx,
                "y": cy,
                "lat": lat,
                "lon": lon,
                "area": float(cv2.contourArea(contour)),
                "gray_threshold": float(threshold)
            }
            cells.append(cell)

        # Zell-JSON speichern
        cell_path = os.path.join(SAVE_CELL_DIR, f"{timestamp}.json")
        with open(cell_path, "w") as f:
            json.dump(cells, f, indent=2)

        print(f"[INFO] {len(cells)} IR-Zellen gespeichert in {cell_path}")
        return image_path, cell_path

    except Exception as e:
        print(f"[FEHLER] IR-Download oder Analyse fehlgeschlagen: {e}")
        return None, None


# Testlauf
if __name__ == "__main__":
    ts = datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
    fetch_ir_image_and_analyze(ts)
