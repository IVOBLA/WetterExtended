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
from config import (BBOX_KAERNTEN_EXTENDED, SAVE_PATHS, LIVE_LOOP_INTERVAL_S,
                    LOOP_INTERVAL_CELLS_S, LOOP_INTERVAL_NO_CELLS_S)
from cloud_height_from_eumetview import assign_cloud_top_height
from optical_flow_features import assign_optical_flow_to_objects
from fetch_arome_openmeteo import assign_arome_to_objects
from fetch_synoptic_features import assign_synoptic_features
from orographic_module import assign_orographic_scores
from fetch_openmeteo_extended import assign_extended_openmeteo
from fetch_geosphere_nowcast import assign_nowcast_to_objects
from fetch_tawes_gust import fetch_tawes_stations, max_gust_near
import math as _math_main
import runtime_config
from locations_check import annotate_locations
from config import (HAIL_WARN_THRESHOLD, STATIONARY_RISK_MARKER_THRESHOLD,
                    GUST_WARN_KMH, HEAVY_RAIN_WARN_MM_PER_H)

_ROI_CACHE = None

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


def _compute_hail_prob(obj: dict) -> float:
    """
    Hagelwahrscheinlichkeit 0.0–1.0 aus vorhandenen Features (F06/F43).

    Formel: hail_prob = core_factor * cape_factor * height_factor
      core_factor  : core_ratio (0-1) — kompakter Kern = Hagelindiz
      cape_factor  : CAPE / 1500 J/kg, max 1.0 — viel Energie = Hagelmöglich
      height_factor: 1.0 wenn Gefriergrenze < 3000 m MSL,
                     linear 0.0 bei 4500 m (hohe Gefriergrenze = kein Hagel)
    """
    core_ratio = float(obj.get("core_ratio", 0.0))
    cape       = float(obj.get("cape", 0.0))
    fl_height  = float(obj.get("arome_fl_height", 4000.0))  # m MSL

    core_factor  = min(core_ratio, 1.0)
    cape_factor  = min(cape / 1500.0, 1.0) if cape > 0 else 0.0
    height_factor = 1.0 if fl_height <= 3000 else max(0.0, (4500.0 - fl_height) / 1500.0)

    return round(core_factor * cape_factor * height_factor, 3)


def _compute_wind_shear(obj: dict) -> tuple:
    """
    Windscherung zwischen Boden (10m) und 700 hPa (ca. 3000m) (F16).
    Rückgabe: (wind_shear_speed_kmh, wind_shear_dir_cos, wind_shear_dir_sin)
    """
    speed_700 = float(obj.get("wind_speed_700hPa", 0.0))
    dir_cos_700 = float(obj.get("wind_dir_cos", 0.0))
    dir_sin_700 = float(obj.get("wind_dir_sin", 0.0))
    speed_10m = float(obj.get("arome_ff10m", 0.0))
    dir_cos_10m = float(obj.get("arome_dd_cos", 0.0))
    dir_sin_10m = float(obj.get("arome_dd_sin", 0.0))

    vx_700 = speed_700 * dir_cos_700
    vy_700 = speed_700 * dir_sin_700
    vx_10m = speed_10m * dir_cos_10m
    vy_10m = speed_10m * dir_sin_10m

    dvx = vx_700 - vx_10m
    dvy = vy_700 - vy_10m
    shear_speed = _math_main.hypot(dvx, dvy)
    angle = _math_main.atan2(dvy, dvx) if shear_speed > 0 else 0.0
    return (
        round(shear_speed, 2),
        round(_math_main.cos(angle), 4),
        round(_math_main.sin(angle), 4),
    )


def main_loop():
    image_path = "data/latest.png"

    _prev_radar_path = None
    _prev_location_hit_names: set = set()  # F47: Auto-Entwarnung

    while True:
        runtime_config.reload_overrides()
        global _ROI_CACHE
        _bbox = runtime_config.get("BBOX_KAERNTEN_EXTENDED", BBOX_KAERNTEN_EXTENDED)
        _ROI_CACHE = get_roi_from_bbox(_bbox)
        debug_log("Neuer Zyklus gestartet...")
        radar_ok = download_kmz()

        if not radar_ok:
            debug_log("[SKIP] Radarbild ungültig oder nicht neu → nächster Zyklus.")
            time.sleep(runtime_config.get("LOOP_INTERVAL_NO_CELLS_S", LOOP_INTERVAL_NO_CELLS_S))
            continue

        image = cv2.imread(image_path) if os.path.exists(image_path) else None
        objects, timestamp = ([], None)

        weather_data = get_weather_data(include_all_stations=True)

        if image is not None:
            objects,  timestamp = detect_and_track_objects(image_path, weather_data)
            objects = fetch_and_assign_700hpa_wind(objects, timestamp)
            objects = assign_cape(objects, timestamp)
            # Orographische Scores nach CAPE berechnen (brauchen cape-Wert)
            objects = assign_orographic_scores(objects)
            objects = assign_cloud_top_height(objects, weather_data=weather_data, timestamp=timestamp)
            curr_scaled_path = os.path.join("data", "radar", f"radar_{timestamp}.png")
            objects = assign_optical_flow_to_objects(
                objects,
                prev_radar_path=_prev_radar_path,
                curr_radar_path=curr_scaled_path,
            )
            _prev_radar_path = curr_scaled_path
            objects = assign_arome_to_objects(objects, timestamp)
            objects = assign_synoptic_features(objects, timestamp)
            objects = assign_extended_openmeteo(objects, timestamp)
            objects = assign_nowcast_to_objects(objects, timestamp)
            _tawes_stations = fetch_tawes_stations()
            for _obj in objects:
                if _obj.get("lat") is not None and _obj.get("lon") is not None:
                    _measured_gust = max_gust_near(_obj["lat"], _obj["lon"], _tawes_stations, 30.0)
                    _obj["tawes_max_gust_kmh"] = _measured_gust
                    _obj["gust_warning"] = float(_obj.get("nowcast_ffx_kmh",0.0)) >= GUST_WARN_KMH or _measured_gust >= GUST_WARN_KMH
                    _obj["heavy_rain_warning"] = float(_obj.get("nowcast_rain_rate_1h",0.0)) >= HEAVY_RAIN_WARN_MM_PER_H
            debug_log(f"Gefundene Objekte: {len(objects)}")
            # ── Strukturiertes Cell-Log (JSONL) ──────────────────────────
            _cell_log_path = os.path.join(
                SAVE_PATHS.get("evaluation", "train_data/evaluation"),
                "cells_log.jsonl"
            )
            os.makedirs(os.path.dirname(_cell_log_path), exist_ok=True)
            _cell_entry = {
                "ts":    timestamp,
                "count": len(objects),
                "cells": [
                    {
                        "id":         o.get("id"),
                        "lat":        o.get("lat"),
                        "lon":        o.get("lon"),
                        "size":       o.get("size"),
                        "core_ratio": round(float(o.get("core_ratio") or 0), 3),
                        "missing":    o.get("missing", 0),
                        "lineage":    o.get("lineage"),
                        "vx":         round(float(o.get("vx") or 0), 2),
                        "vy":         round(float(o.get("vy") or 0), 2),
                    }
                    for o in objects
                ],
            }
            try:
                with open(_cell_log_path, "a", encoding="utf-8") as _clf:
                    json.dump(_cell_entry, _clf, ensure_ascii=False)
                    _clf.write("\n")
            except Exception as _cl_exc:
                debug_log(f"[CELLS-LOG] Schreibfehler: {_cl_exc}")

            # Blitzdaten: erst fetchen, dann einlesen
            lightning_data = []
            if timestamp:
                try:
                    from blitz_api import fetch_and_save_lightning
                    fetch_and_save_lightning(timestamp)
                except Exception as _le:
                    debug_log(f"[LIGHTNING] Fetch fehlgeschlagen: {_le}")
                lightning_file = os.path.join(SAVE_PATHS["lightning"], f"{timestamp}.json")
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

        if radar_ok and image is not None and objects:
            if not weather_data:
                debug_log("[WARN] Keine Wetterdaten — Forecast läuft mit Defaults.")

            # F1-FIX: predict_positions() VOR dem Speichern — schreibt forecast_lat_X
            # in-place in die Objekte, danach erst JSON-Dump damit /api/forecast Pfeile hat.
            forecasts_per_horizon = predict_positions(objects, timestamp, weather_data)

            # Radarbild speichern
            radar_file = os.path.join(SAVE_PATHS["radar"], f"{timestamp}.png")
            cv2.imwrite(radar_file, image)
            debug_log(f"Radarbild gespeichert als {radar_file}")

            # Objekte NACH predict_positions() speichern (forecast_lat_X enthalten)
            object_file = os.path.join(SAVE_PATHS["objects"], f"{timestamp}.json")
            with open(object_file, "w", encoding="utf-8") as _of:
                json.dump(
                    [{k: v for k, v in o.items() if k != "kf"} for o in objects],
                    _of, ensure_ascii=False,
                )
            debug_log(f"Object-File gespeichert: {len(objects)} Objekte (inkl. Forecasts)")

            # Wetter speichern (falls vorhanden)
            if weather_data:
                weather_file = os.path.join(SAVE_PATHS["weather"], f"{timestamp}.json")
                with open(weather_file, "w", encoding="utf-8") as _wf:
                    json.dump(weather_data, _wf, ensure_ascii=False)
                debug_log(f"Wetterdaten gespeichert als {weather_file}")
            from config import ML_FORECAST_HORIZONS_MIN as _DEFAULT_HORIZONS
            from config import FORECAST_ARROW_COLORS as _DEFAULT_COLORS
            horizons = runtime_config.get("ML_FORECAST_HORIZONS_MIN", _DEFAULT_HORIZONS)
            colors = runtime_config.get("FORECAST_ARROW_COLORS", _DEFAULT_COLORS)
            save_forecast_as_kmz(dict(zip(horizons, forecasts_per_horizon)), colors)

            # ── Windscherung und Hagelwahrscheinlichkeit (F16, F06/F43) ──────────
            for _obj in objects:
                _shear_speed, _shear_cos, _shear_sin = _compute_wind_shear(_obj)
                _obj["wind_shear_speed"]   = _shear_speed
                _obj["wind_shear_dir_cos"] = _shear_cos
                _obj["wind_shear_dir_sin"] = _shear_sin

                _hp = _compute_hail_prob(_obj)
                _obj["hail_prob"]    = _hp
                _obj["hail_warning"] = bool(_hp >= HAIL_WARN_THRESHOLD)

                _sr = float(_obj.get("stationary_risk", 0.0))
                _obj["stationary_marker"] = bool(_sr >= STATIONARY_RISK_MARKER_THRESHOLD)

            # Orte-Markierung bei Pfad-Durchquerung
            locations = runtime_config.get("LOCATIONS_WATCHLIST", [])
            from config import (
                MIN_MOVEMENT_FOR_ARROW_KMH as _MIN_ARROW_KMH,
                SLOW_CELL_MAX_KMH as _SLOW_MAX_KMH,
                SLOW_CELL_RADIUS_FACTOR as _SLOW_FACTOR,
            )
            _min_speed   = runtime_config.get("MIN_MOVEMENT_FOR_ARROW_KMH", _MIN_ARROW_KMH)
            _slow_max    = runtime_config.get("SLOW_CELL_MAX_KMH",          _SLOW_MAX_KMH)
            _slow_factor = runtime_config.get("SLOW_CELL_RADIUS_FACTOR",    _SLOW_FACTOR)
            location_hits = annotate_locations(
                objects, locations, horizons, colors,
                min_speed_kmh=_min_speed,
                slow_cell_max_kmh=_slow_max,
                slow_radius_factor=_slow_factor,
            )
            os.makedirs(SAVE_PATHS["evaluation"], exist_ok=True)
            with open(os.path.join(SAVE_PATHS["evaluation"], f"locations_{timestamp}.json"), "w", encoding="utf-8") as f:
                json.dump(location_hits, f, indent=2, ensure_ascii=False)
            debug_log(f"Ort-Hits: {len(location_hits)} betroffene Orte")
            _gust_cells  = [o["id"] for o in objects if o.get("gust_warning")]
            _rain_cells  = [o["id"] for o in objects if o.get("heavy_rain_warning")]
            _hail_cells  = [o["id"] for o in objects if o.get("hail_warning")]
            if _gust_cells: debug_log(f"[WARN] Böen >= {GUST_WARN_KMH} km/h: {_gust_cells}")
            if _rain_cells: debug_log(f"[WARN] Starkregen >= {HEAVY_RAIN_WARN_MM_PER_H} mm/h: {_rain_cells}")
            if _hail_cells: debug_log(f"[WARN] Hagelwarnung: {_hail_cells}")

            # ── Auto-Entwarnung (F47) ─────────────────────────────────────────
            _current_hit_names = {h["name"] for h in location_hits}
            _cleared = _prev_location_hit_names - _current_hit_names
            if _cleared:
                try:
                    from sms_notifier import send_sms
                    for _loc_name in sorted(_cleared):
                        _msg = f"ENTWARNUNG: Kein Gewitter mehr in Richtung {_loc_name}."
                        send_sms(_msg)
                        debug_log(f"[SMS] Entwarnung gesendet: {_loc_name}")
                except Exception as _e:
                    debug_log(f"[SMS] Entwarnung fehlgeschlagen: {_e}")
            _prev_location_hit_names = _current_hit_names

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
            latest_object = sorted(os.listdir(SAVE_PATHS["objects"]))[-1]
            upload_file_ftp(os.path.join(SAVE_PATHS["objects"], latest_object), "latest_objects.json")
        except Exception:
            debug_log("Kein Object-File vorhanden — überspringe Upload von latest_objects.json")

        # Adaptiver Intervall: kurz bei aktiven Zellen, lang bei Ruhe
        _cells_now = bool(objects and any(o.get("missing", 0) == 0 for o in objects))
        if _cells_now:
            _sleep = runtime_config.get("LOOP_INTERVAL_CELLS_S", LOOP_INTERVAL_CELLS_S)
            debug_log(f"[LOOP] Zellen aktiv → kurzer Intervall ({_sleep}s)")
        else:
            _sleep = runtime_config.get("LOOP_INTERVAL_NO_CELLS_S", LOOP_INTERVAL_NO_CELLS_S)
            debug_log(f"[LOOP] Keine Zellen → langer Intervall ({_sleep}s)")
        time.sleep(_sleep)

if __name__ == "__main__":
    main_loop()
