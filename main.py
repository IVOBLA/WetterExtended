# main.py

import time
import os
import cv2
import json
import debug_utils

from radar_download import download_kmz
from object_tracking import detect_and_track_objects
from weather_api import get_weather_data
from model_training import train_or_load_model, train_with_historical_and_live_data
from prediction import predict_positions
from kmz_export import save_forecast_as_kmz
from evaluation import evaluate_prediction, plot_forecast_vs_reality, plot_error_over_time
from visualize_radar import create_visualized_radar
from movement_gif import create_movement_gif
from upload_utilities import upload_file_ftp
from debug_utils import debug_log
from fetch_700hpa_wind_per_object_slim import fetch_and_assign_700hpa_wind
from assign_cape_from_forecast import assign_cape
from geo_utils import get_roi_from_bbox, kml_bounds
from config import BBOX_KAERNTEN_EXTENDED
from cloud_height_from_eumetview import assign_cloud_top_height

ROI = get_roi_from_bbox(BBOX_KAERNTEN_EXTENDED)

def main_loop():
    image_path = "data/latest.png"
    model = train_or_load_model()
    sleep_time = 120
    forecast_queue = []

    while True:
        debug_log("Neuer Zyklus gestartet...")
        radar_ok = download_kmz()

        if not radar_ok:
            debug_log("[SKIP] Radarbild ungültig oder nicht neu → nächster Zyklus.")
            time.sleep(sleep_time)
            continue

        image = cv2.imread(image_path) if os.path.exists(image_path) else None
        objects, timestamp = ([], None)

        weather_data = get_weather_data(include_all_stations=True)

        if image is not None:
            objects,  timestamp = detect_and_track_objects(image_path, weather_data)
            objects = fetch_and_assign_700hpa_wind(objects, timestamp)
            objects = assign_cape(objects, timestamp)
            objects = assign_cloud_top_height(objects)
        
        if radar_ok and image is not None and objects and weather_data:
            debug_log("Radarbild, Objekte und Wetterdaten vorhanden → Speichern & Verarbeiten")

            # Radarbild speichern
            radar_file = f"train_data/radar/{timestamp}.png"
            cv2.imwrite(radar_file, image)
            debug_log(f"Radarbild gespeichert als {radar_file}")

            # Objekte speichern (ohne Kalman)
            object_file = f"train_data/objects/{timestamp}.json"
            json.dump([{k: v for k, v in o.items() if k != "kf"} for o in objects], open(object_file, "w"))
            debug_log(f"Object-File gespeichert mit {len(objects)} Objekten")

            # Wetter speichern
            weather_file = f"train_data/weather/{timestamp}.json"
            json.dump(weather_data, open(weather_file, "w"))
            debug_log(f"Wetterdaten gespeichert als {weather_file}")

            # Training
            train_with_historical_and_live_data(model, objects, timestamp, weather_data)

            # Forecast
            forecast_10, forecast_20, forecast_30 = predict_positions(objects, model, timestamp, weather_data)
            save_forecast_as_kmz(forecast_10, forecast_20, forecast_30)

            # Merken für spätere Evaluation
            forecast_queue.append((forecast_10, timestamp))
            if len(forecast_queue) > 2:
                forecast_queue.pop(0)

        else:
            debug_log("Keine vollständigen Daten → Keine Speicherung")
            save_forecast_as_kmz([], [], [])
            create_movement_gif("movement.gif")

        create_visualized_radar()

        # Evaluation
        if len(forecast_queue) == 2 and objects:
            forecast_old, forecast_ts = forecast_queue[0]
            evaluate_prediction(forecast_old, objects, forecast_ts)
            plot_forecast_vs_reality(forecast_old, objects, forecast_ts)
            plot_error_over_time()
            create_movement_gif("movement.gif")

        # Uploads
        upload_file_ftp("data/overlay.png", "overlay.png")
        upload_file_ftp("forecast.kmz", "forecast.kmz")
        upload_file_ftp("movement.gif", "movement.gif")

        try:
            latest_object = sorted(os.listdir("train_data/objects"))[-1]
            upload_file_ftp(f"train_data/objects/{latest_object}", "latest_objects.json")
        except:
            debug_log("Kein Object-File vorhanden — überspringe Upload von latest_objects.json")

        upload_file_ftp("templates/index.html", "index.html")
        upload_file_ftp("templates/map.html", "map.html")

        debug_log("Warte auf nächstes Radarbild...")
        time.sleep(sleep_time)

if __name__ == "__main__":
    main_loop()
