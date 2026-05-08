# main.py

import time
import os
import cv2
import json
import debug_utils

from radar_download import download_kmz
from object_tracking import detect_and_track_objects
from weather_api import get_weather_data
from prediction import predict_positions
from kmz_export import save_forecast_as_kmz
from visualize_radar import create_visualized_radar
from movement_gif import create_movement_gif
from upload_utilities import upload_file_ftp
from debug_utils import debug_log
from fetch_700hpa_wind_per_object_slim import fetch_and_assign_700hpa_wind
from assign_cape_from_forecast import assign_cape
from geo_utils import get_roi_from_bbox, kml_bounds
from config import BBOX_KAERNTEN_EXTENDED
from cloud_height_from_eumetview import assign_cloud_top_height
from optical_flow_features import assign_optical_flow_to_objects
from fetch_arome_openmeteo import assign_arome_to_objects
import runtime_config
from locations_check import annotate_locations

ROI = get_roi_from_bbox(BBOX_KAERNTEN_EXTENDED)

def _count_lightning_near(lat: float, lon: float,
                          lightning_data: list, radius_km: float = 10.0) -> int:
    """Zählt Blitze im radius_km-Umkreis. Nutzt einfache Grad-Näherung."""
    if not lightning_data:
        return 0
    count = 0
    lat_deg = radius_km / 111.0
    lon_deg = radius_km / (111.0 * abs(__import__('math').cos(__import__('math').radians(lat))) + 1e-9)
    for bolt in lightning_data:
        blat = bolt.get("lat") or bolt.get("y")
        blon = bolt.get("lon") or bolt.get("x")
        if blat is None or blon is None:
            continue
        if abs(float(blat) - lat) <= lat_deg and abs(float(blon) - lon) <= lon_deg:
            count += 1
    return count


def main_loop():
    image_path = "data/latest.png"
    sleep_time = 120

    _prev_radar_path = None

    while True:
        runtime_config.reload_overrides()
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
            objects = assign_cloud_top_height(objects, weather_data=weather_data, timestamp=timestamp)
            curr_scaled_path = os.path.join("data/radar", f"radar_{timestamp}.png")
            objects = assign_optical_flow_to_objects(
                objects,
                prev_radar_path=_prev_radar_path,
                curr_radar_path=curr_scaled_path,
            )
            _prev_radar_path = curr_scaled_path
            objects = assign_arome_to_objects(objects, timestamp)

            # Blitzdaten für aktuelle Zellen auswerten
            lightning_data = []
            lightning_file = f"train_data/lightning/{timestamp}.json"
            if os.path.exists(lightning_file):
                try:
                    with open(lightning_file, encoding="utf-8") as _f:
                        lightning_data = json.load(_f)
                except Exception:
                    pass
            for obj in objects:
                if obj.get("lat") is not None and obj.get("lon") is not None:
                    obj["lightning_count_10km"] = _count_lightning_near(
                        float(obj["lat"]), float(obj["lon"]), lightning_data
                    )

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

            # Kein Training im Live-Loop — übernimmt scheduler.py.
            forecasts_per_horizon = predict_positions(objects, timestamp, weather_data)
            from config import ML_FORECAST_HORIZONS_MIN as _DEFAULT_HORIZONS
            from config import FORECAST_ARROW_COLORS as _DEFAULT_COLORS
            horizons = runtime_config.get("ML_FORECAST_HORIZONS_MIN", _DEFAULT_HORIZONS)
            colors = runtime_config.get("FORECAST_ARROW_COLORS", _DEFAULT_COLORS)
            save_forecast_as_kmz(dict(zip(horizons, forecasts_per_horizon)), colors)

            # Orte-Markierung bei Pfad-Durchquerung
            locations = runtime_config.get("LOCATIONS_WATCHLIST", [])
            location_hits = annotate_locations(objects, locations, horizons, colors)
            os.makedirs("train_data/evaluation", exist_ok=True)
            with open(f"train_data/evaluation/locations_{timestamp}.json", "w", encoding="utf-8") as f:
                json.dump(location_hits, f, indent=2, ensure_ascii=False)
            debug_log(f"Ort-Hits: {len(location_hits)} betroffene Orte")

        else:
            debug_log("Keine vollständigen Daten → Keine Speicherung")
            save_forecast_as_kmz({}, {})
            create_movement_gif("movement.gif")

        create_visualized_radar()

        # Uploads
        upload_file_ftp("data/overlay.png", "overlay.png")
        upload_file_ftp("forecast.kmz", "forecast.kmz")
        upload_file_ftp("movement.gif", "movement.gif")

        try:
            latest_object = sorted(os.listdir("train_data/objects"))[-1]
            upload_file_ftp(f"train_data/objects/{latest_object}", "latest_objects.json")
        except:
            debug_log("Kein Object-File vorhanden — überspringe Upload von latest_objects.json")

        debug_log("Warte auf nächstes Radarbild...")
        time.sleep(sleep_time)

if __name__ == "__main__":
    main_loop()
