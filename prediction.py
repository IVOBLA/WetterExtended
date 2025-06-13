# prediction.py

import os
import json
import glob
import numpy as np
from math import sin, cos, pi, atan2
from datetime import datetime

from geo_utils import pixel_to_geo
from debug_utils import debug_log
from utils import find_nearest_station, calculate_velocity

sequence_length = 3
num_features = 22

def predict_positions(objects, model, timestamp, stations):
    from math import sin, cos, pi, atan2
    import numpy as np
    import glob
    import json
    from datetime import datetime
    from geo_utils import pixel_to_geo
    from debug_utils import debug_log
    from utils import find_nearest_station, calculate_velocity

    sequence_length = 3
    num_features = 22

    forecast_10, forecast_20, forecast_30 = [], [], []

    object_files = sorted(glob.glob("train_data/objects/*.json"))

    for obj in objects:
        sequence = []

        lat, lon = pixel_to_geo(obj["x"], obj["y"])
        nearest = find_nearest_station(lat, lon, stations)

        clock = datetime.strptime(timestamp, "%Y-%m-%d_%H-%M-%S")
        hour_angle = 2 * pi * (clock.hour * 60 + clock.minute) / (24 * 60)

        for j in range(-sequence_length, 0):
            idx = j + len(object_files)
            if idx < 0:
                continue

            with open(object_files[idx]) as f_hist:
                hist_objs = json.load(f_hist)

            hist_match = next((h for h in hist_objs if h["id"] == obj["id"]), None)
            if not hist_match:
                break

            vx_hist, vy_hist = calculate_velocity(obj["id"], object_files)
            delta_hist = atan2(vy_hist, vx_hist)
            weather_vals = [nearest.get(k, 0) for k in ["RR", "DD", "FF", "FFX", "GLOW", "P", "RF", "TL", "TP"]] if nearest else [0] * 9

            inp = [
                hist_match["x"], hist_match["y"],
                vx_hist, vy_hist,
                hist_match["size"], hist_match["area"], hist_match["eccentricity"],
                hist_match.get("core_ratio", 0), hist_match.get("intensity_trend", 0)
            ] + weather_vals + [
                sin(hour_angle), cos(hour_angle),
                cos(delta_hist), sin(delta_hist)
            ]

            if len(inp) == num_features:
                sequence.append(inp)

        if len(sequence) != sequence_length:
            debug_log(f"[SKIP] Zu wenig Historie für Objekt {obj['id']}")
            continue

        sequence = np.array(sequence).reshape(1, sequence_length, num_features)
        prediction = model.predict(sequence, verbose=0)[0]

        for idx, t in enumerate([10, 20, 30]):
            x_pred = prediction[idx * 2]
            y_pred = prediction[idx * 2 + 1]
            obj[f"forecast_x_{t}"] = float(x_pred)
            obj[f"forecast_y_{t}"] = float(y_pred)

            forecast_lat, forecast_lon = pixel_to_geo(x_pred, y_pred)
            obj[f"forecast_lat_{t}"] = forecast_lat
            obj[f"forecast_lon_{t}"] = forecast_lon

        for t, forecast_list in zip([10, 20, 30], [forecast_10, forecast_20, forecast_30]):
            forecast_list.append({
                "x": obj[f"forecast_x_{t}"],
                "y": obj[f"forecast_y_{t}"],
                "lat": obj[f"forecast_lat_{t}"],
                "lon": obj[f"forecast_lon_{t}"],
                "size": obj["size"],
                "id": obj["id"]
            })            

    with open(f"train_data/objects/{timestamp}.json", "w") as f:
        json.dump(objects, f, indent=2)

    return forecast_10, forecast_20, forecast_30

