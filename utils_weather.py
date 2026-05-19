import numpy as np
import os
import json
from config import SAVE_PATHS

def find_n_nearest_stations(lat, lon, weather_data, n=3):
    stations = []
    for station in weather_data:
        slat, slon = station.get("lat"), station.get("lon")
        if slat is None or slon is None:
            continue
        dist = np.hypot(lat - slat, lon - slon)
        stations.append((dist, station))
    stations.sort(key=lambda x: x[0])
    return stations[:n]

def weighted_average_weather(station_list, lat, lon):
    weights = []
    values = []
    for dist, s in station_list:
        w = 1 / (dist + 1e-6)
        # P=0 ist Sensorausfall/fehlend → als None/NaN behandeln
        p_val = s.get("P")
        pressure = float(p_val) if p_val not in (None, 0, "0") else np.nan
        val = [
            s.get("RR", 0),
            s.get("DD", 0),
            s.get("FF", 0),
            s.get("FFX", 0),
            s.get("GLOW", 0),
            pressure,
            s.get("RF", 0),
            s.get("TL", 0),
            s.get("TP", 0),
        ]
        weights.append(w)
        values.append(val)
    weights = np.array(weights, dtype=float)
    values = np.array(values, dtype=float)
    avg = np.nanmean(values, axis=0)
    if len(weights) > 0:
        weighted = np.average(np.nan_to_num(values, nan=0.0), axis=0, weights=weights)
        nan_mask = np.isnan(avg)
        avg[~nan_mask] = weighted[~nan_mask]
    return avg.tolist()



def load_weather_data(timestamp):
    path = os.path.join(SAVE_PATHS["weather"].rstrip("/"), f"{timestamp}.json")
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return []
