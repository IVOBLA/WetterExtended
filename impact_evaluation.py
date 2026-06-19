# impact_evaluation.py

import os
import json
import math
import glob
from datetime import datetime
from geo_utils import haversine_distance

# Verzeichnisse mit Zusatzdaten
from config import SAVE_PATHS as _SP
LIGHTNING_DIR = _SP["lightning"].rstrip("/")
IR_CELL_DIR = _SP["ir_cells"].rstrip("/")


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


        obj["impact"] = impact

    _integrate_hydro_impact(objects, timestamp)


def load_json_if_exists(path):
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return None


def _integrate_hydro_impact(objects, timestamp):
    """Optionale Hydro-Impact-Integration ohne harte Laufzeit-Abhängigkeit."""
    from hydro_impact import (
        evaluate_hydro_impact,
        hydro_enabled,
        save_hydro_impact_events,
        static_data_available,
    )

    if not hydro_enabled():
        for obj in objects:
            obj.setdefault("impact", {})["hydro"] = False
            obj["impact"]["hydro_status"] = "disabled"
        return

    if not static_data_available():
        for obj in objects:
            obj.setdefault("impact", {})["hydro"] = False
            obj["impact"]["hydro_status"] = "missing_static_data"
        return

    try:
        events = evaluate_hydro_impact(objects, timestamp)
        if events:
            save_hydro_impact_events(events, timestamp)
        by_cell = {}
        for event in events:
            by_cell.setdefault(str(event.get("cell_id")), []).append(event)
        for obj in objects:
            cell_events = by_cell.get(str(obj.get("id", obj.get("cell_id", obj.get("track_id", "unknown")))), [])
            obj.setdefault("impact", {})["hydro"] = bool(cell_events)
            if cell_events:
                obj["impact"]["hydro_events"] = cell_events
                obj["impact"]["score"] = obj["impact"].get("score", 0) + max(e.get("impact_score", 0) for e in cell_events)
            else:
                obj["impact"]["hydro_status"] = "no_upstream_catchment_hit"
    except Exception:
        for obj in objects:
            obj.setdefault("impact", {})["hydro"] = False
            obj["impact"]["hydro_status"] = "error"
