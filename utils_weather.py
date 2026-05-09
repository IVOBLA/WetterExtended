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
        val = [s.get(k, 0) for k in ["RR", "DD", "FF", "FFX", "GLOW", "P", "RF", "TL", "TP"]]
        weights.append(w)
        values.append(val)
    weights = np.array(weights)
    values = np.array(values)
    avg = np.average(values, axis=0, weights=weights)
    return avg.tolist()



def load_weather_data(timestamp):
    path = os.path.join(SAVE_PATHS["weather"].rstrip("/"), f"{timestamp}.json")
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return []