# impact_evaluation.py

import os
import json
import math
import glob
from datetime import datetime
from geo_utils import haversine_distance

# Verzeichnisse mit Zusatzdaten
LIGHTNING_DIR = "train_data/lightning"
HYDRO_DIR = "train_data/hydro"
IR_CELL_DIR = "train_data/ir_cells"


def find_latest_ir_before(ts):
    ts_dt = datetime.strptime(ts, "%Y-%m-%d_%H-%M-%S")
    ir_files = sorted(glob.glob(os.path.join(IR_CELL_DIR, "*.json")), reverse=True)
    for path in ir_files:
        fname = os.path.basename(path).replace(".json", "")
        try:
            ir_time = datetime.strptime(fname, "%Y-%m-%d_%H-%M-%S")
            if ir_time <= ts_dt:
                return fname
        except:
            continue
    return None


def evaluate_impact(objects, timestamp):
    """
    Bewertet jede Zelle anhand von Blitz-, IR- und Hydro-Daten.
    Ergänzt das Objekt um ein "impact"-Feld.
    """
    lightning = load_json_if_exists(os.path.join(LIGHTNING_DIR, f"{timestamp}.json"))
    hydro = load_json_if_exists(os.path.join(HYDRO_DIR, f"{timestamp}.json"))

    # Neuestes IR-Bild ≤ Radarzeit verwenden
    ir_ts = find_latest_ir_before(timestamp)
    ir_cells = load_json_if_exists(os.path.join(IR_CELL_DIR, f"{ir_ts}.json")) if ir_ts else None

    for obj in objects:
        lat = obj.get("lat")
        lon = obj.get("lon")
        impact = {"score": 0}

        # Blitzprüfung: Blitz < 10km?
        if lightning:
            nearest = min((haversine_distance(lat, lon, l["lat"], l["lon"]) for l in lightning), default=999)
            if nearest <= 10:
                impact["blitz"] = True
                impact["blitz_distance"] = round(nearest, 2)
                impact["score"] += 1

        # IR-Zelle deckt sich (Abstand < 5km)
        if ir_cells:
            for cell in ir_cells:
                d = haversine_distance(lat, lon, cell["lat"], cell["lon"])
                if d <= 5:
                    impact["ir"] = True
                    impact["score"] += 1
                    break

        # Hydro: Durchflussmenge direkt bewerten (nicht HQ-Schwellen)
        if hydro:
            for station in hydro:
                s_lat = station.get("werte", {}).get("lat")
                s_lon = station.get("werte", {}).get("lon")
                q = station.get("werte", {}).get("q")
                if not s_lat or not s_lon or q is None:
                    continue
                dist = haversine_distance(lat, lon, s_lat, s_lon)
                if dist <= 10:
                    impact["hydro_q_m3s"] = q
                    if q >= 100:
                        impact["score"] += 3
                    elif q >= 50:
                        impact["score"] += 2
                    elif q >= 20:
                        impact["score"] += 1
                    break

        obj["impact"] = impact


def load_json_if_exists(path):
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return None
