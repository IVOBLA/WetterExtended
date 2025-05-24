import os
import cv2
import numpy as np
from datetime import datetime
from filterpy.kalman import KalmanFilter
from shapely.geometry import Polygon
from shapely.ops import unary_union
from config import UPSCALE_FACTOR, FILTER_CONFIG, CORE_HSV_RANGES, BBOX_KAERNTEN_EXTENDED as BBOX
from geo_utils import pixel_to_geo
from utils import generate_id
from utils_weather import find_n_nearest_stations, weighted_average_weather
from debug_utils import save_debug_image, debug_log
from geo_utils import crop_and_upscale_to_bbox
from config import MIN_CONTOUR_OVERLAP
from config import MIN_CONTOUR_TOUCH

tracking_memory = {}

def are_contours_connected(cnt1, cnt2, shape, min_overlap=10):
    mask1 = np.zeros(shape, dtype=np.uint8)
    mask2 = np.zeros(shape, dtype=np.uint8)

    cv2.drawContours(mask1, [cnt1], -1, 255, thickness=cv2.FILLED)
    cv2.drawContours(mask2, [cnt2], -1, 255, thickness=cv2.FILLED)

    # Vergrößere die Konturen leicht, um realen Kontakt zu simulieren
    kernel = np.ones((3, 3), np.uint8)
    mask1 = cv2.dilate(mask1, kernel, iterations=1)
    mask2 = cv2.dilate(mask2, kernel, iterations=1)

    # Überlappung der vergrößerten Masken prüfen
    overlap = cv2.bitwise_and(mask1, mask2)
    return cv2.countNonZero(overlap) >= min_overlap
    
def are_contours_touching_edges(cnt1, cnt2, shape, min_touch=3):
    mask1 = np.zeros(shape, dtype=np.uint8)
    mask2 = np.zeros(shape, dtype=np.uint8)

    # Nur Ränder zeichnen (keine Fläche)
    cv2.drawContours(mask1, [cnt1], -1, 255, thickness=1)
    cv2.drawContours(mask2, [cnt2], -1, 255, thickness=1)

    # Überlappung der Ränder prüfen
    overlap = cv2.bitwise_and(mask1, mask2)
    return cv2.countNonZero(overlap) >= min_touch
    

def calculate_shape_features(contour):
    area = cv2.contourArea(contour)
    perimeter = cv2.arcLength(contour, True)
    if area == 0:
        eccentricity = 0
    else:
        (x, y), (MA, ma), angle = cv2.fitEllipse(contour) if len(contour) >= 5 else ((0, 0), (0, 0), 0)
        eccentricity = ma / MA if MA > 0 else 0
    return area, eccentricity

def merge_close_contours(contours, image_shape, min_touch=3):
    merged = []
    used = [False] * len(contours)

    for i, cnt1 in enumerate(contours):
        if used[i]:
            continue

        group = [cnt1]
        used[i] = True

        for j, cnt2 in enumerate(contours):
            if used[j] or i == j:
                continue

            if are_contours_touching_edges(cnt1, cnt2, image_shape, min_touch=min_touch):
                group.append(cnt2)
                used[j] = True

        merged_poly = unary_union([Polygon(c[:, 0, :]) for c in group])
        if merged_poly.geom_type == 'MultiPolygon':
            for part in merged_poly.geoms:
                merged.append(np.array(part.exterior.coords, dtype=np.int32).reshape(-1, 1, 2))
        else:
            merged.append(np.array(merged_poly.exterior.coords, dtype=np.int32).reshape(-1, 1, 2))

    return merged

def preprocess_image(image_path):
    # Bild mit geo-zuschnitt & hochskalierung laden
    from config import BBOX_KAERNTEN_EXTENDED

    processed_img = crop_and_upscale_to_bbox(image_path, BBOX_KAERNTEN_EXTENDED, UPSCALE_FACTOR)
    hsv = cv2.cvtColor(processed_img, cv2.COLOR_BGR2HSV)

    mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
    for lower, upper in FILTER_CONFIG["allowed_hsv_ranges"]:
        mask |= cv2.inRange(hsv, np.array(lower), np.array(upper))

    kernel = np.ones((7, 7), np.uint8)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    merged = merge_close_contours(contours, hsv.shape[:2], min_touch=MIN_CONTOUR_TOUCH)
    return hsv, merged, mask
    
def calculate_core_ratio(hsv, contour):
    mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
    cv2.drawContours(mask, [contour], -1, 255, -1)
    core_mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
    for lower, upper in CORE_HSV_RANGES:
        range_mask = cv2.inRange(hsv, np.array(lower), np.array(upper))
        core_mask |= cv2.bitwise_and(range_mask, range_mask, mask=mask)
    core_pixels = cv2.countNonZero(core_mask)
    total_pixels = cv2.countNonZero(mask)
    return core_pixels / total_pixels if total_pixels > 0 else 0

def update_tracking_memory(hsv, contours, weather_data, timestamp):
    global tracking_memory
    objects = []
    new_memory = {}
    used_ids = set()

    for contour in contours:
        M = cv2.moments(contour)
        if M["m00"] == 0:
            continue  # kontur zu klein/fehlerhaft

        cx = int(M["m10"] / M["m00"])
        cy = int(M["m01"] / M["m00"])
        original_cx = int(cx / UPSCALE_FACTOR)
        original_cy = int(cy / UPSCALE_FACTOR)

        area, eccentricity = calculate_shape_features(contour)
        core_ratio = calculate_core_ratio(hsv, contour)

        # Bedingung: Nur große oder "rote" Zellen
        if area < FILTER_CONFIG["min_object_area"] and core_ratio < 0.05:
            continue

        # Ausschlussregion: Koralpe (muss VOR dem Erzeugen des Objekts passieren!)
        lat, lon = pixel_to_geo(original_cx, original_cy)
        if 46.7 < lat < 46.9 and 14.8 < lon < 15.2:
            debug_log(f"[SKIP] Zelle in Ausschlussregion Koralpe verworfen (lat={lat:.2f}, lon={lon:.2f})")
            continue

        current_poly = Polygon(contour[:, 0, :])
        MATCH_DISTANCE = 50
        best_id = None
        min_dist = float('inf')

        for obj_id, prev in tracking_memory.items():
            if obj_id in used_ids or prev.get("missing", 0) > 10:
                continue
            try:
                previous_poly = Polygon(np.array(prev["contour"]))
                dist = current_poly.distance(previous_poly)
                if dist < MATCH_DISTANCE and dist < min_dist:
                    best_id = obj_id
                    min_dist = dist
            except Exception:
                continue

        if best_id:
            obj_id = best_id
            used_ids.add(obj_id)
            kf = tracking_memory[obj_id]["kf"]
            kf.predict()
            kf.update([original_cx, original_cy])
            vx, vy = kf.x[2], kf.x[3]
            debug_log(f"Objekt erneut erkannt → ID: {obj_id} | Distanz: {min_dist:.2f}px")
        else:
            obj_id = generate_id()
            kf = KalmanFilter(dim_x=4, dim_z=2)
            kf.x = np.array([original_cx, original_cy, 0.0, 0.0])
            kf.F = np.array([[1, 0, 1, 0],
                             [0, 1, 0, 1],
                             [0, 0, 1, 0],
                             [0, 0, 0, 1]])
            kf.H = np.array([[1, 0, 0, 0],
                             [0, 1, 0, 0]])
            kf.P = np.eye(4) * 500
            kf.R = np.eye(2) * 10
            kf.Q = np.array([[1, 0, 0, 0],
                             [0, 1, 0, 0],
                             [0, 0, 0.5, 0],
                             [0, 0, 0, 0.5]])
            vx, vy = 0.0, 0.0
            debug_log(f"Neues Objekt erkannt → neue ID: {obj_id}")

        trend = 0
        if best_id and "core_ratio" in tracking_memory[best_id]:
            prev_core = tracking_memory[best_id]["core_ratio"]
            if core_ratio > prev_core + 0.05:
                trend = 1
            elif core_ratio < prev_core - 0.05:
                trend = -1

        new_memory[obj_id] = {
            "x": original_cx,
            "y": original_cy,
            "vx": float(vx),
            "vy": float(vy),
            "size": int(np.sqrt(area)),
            "area": float(area),
            "eccentricity": float(eccentricity),
            "core_ratio": float(core_ratio),
            "trend": trend,
            "lat": lat,
            "lon": lon,
            "kf": kf,
            "contour": contour[:, 0, :].tolist(),
            "weather_vals": {},
            "station_ids": [],
            "lstm_vx": 0.0,
            "lstm_vy": 0.0,
            "missing": 0
        }

    for obj_id, obj in tracking_memory.items():
        if obj_id not in new_memory:
            obj["missing"] = obj.get("missing", 0) + 1
            if obj["missing"] <= 10:
                new_memory[obj_id] = obj

    tracking_memory = new_memory
    for obj_id, obj in new_memory.items():
        if obj.get("missing", 0) == 0:
            previous_history = tracking_memory.get(obj_id, {}).get("history", [])

            new_entry = {
                "timestamp": timestamp,
                "vx": float(obj["vx"]),
                "vy": float(obj["vy"]),
                "core_ratio": float(obj["core_ratio"]),
                "weather_vals": {},
                "lat": obj["lat"],
                "lon": obj["lon"]
            }

            updated_history = previous_history + [new_entry]
            updated_history = updated_history[-3:]

            obj_clean = obj.copy()
            obj_clean.pop("kf", None)
            obj_clean["history"] = updated_history
            obj_clean["lstm_ignore"] = (
                len(updated_history) < 3 or any(not h.get("weather_vals") for h in updated_history) or obj.get("missing", 0) > 0
            )
            obj_clean["contour_verified"] = False
            obj_clean["forecast_verified"] = False

            contour_geo = []
            for pt in obj_clean["contour"]:
                x_pix, y_pix = pt
                lon_g, lat_g = pixel_to_geo(x_pix, y_pix)
                contour_geo.append([lon_g, lat_g])
            obj_clean["contour_geo"] = contour_geo

            objects.append(obj_clean | {"id": obj_id})

    return objects

def detect_and_track_objects(image_path=None, weather_data=None):
    
    if image_path is None:
        image_path = "data/latest.png"
    
    os.makedirs("train_data/radar", exist_ok=True)
    os.makedirs("train_data/objects", exist_ok=True)
    debug_log(f"Tracking auf Bild: {image_path}")
    if weather_data is None:
        weather_data = []

    # Timestamp ermitteln
    filename = os.path.basename(image_path).replace(".png", "")
    if "latest" in filename:
        ts_dt = datetime.now()
        timestamp = ts_dt.strftime("%Y-%m-%d_%H-%M-%S")
        debug_log(f"[INFO] Live-Modus erkannt → Timestamp gesetzt auf: {timestamp}")
    else:
        try:
            ts_dt = datetime.strptime(filename.replace("radar_", ""), "%Y-%m-%d_%H-%M-%S")
            timestamp = ts_dt.strftime("%Y-%m-%d_%H-%M-%S")
            debug_log(f"[INFO] Historischer Modus → Timestamp extrahiert: {timestamp}")
        except ValueError:
            debug_log(f"[FEHLER] Ungültiger Dateiname für Timestamp: {filename}")
            ts_dt = datetime.now()
            timestamp = ts_dt.strftime("%Y-%m-%d_%H-%M-%S")
            
    # Speichere das vergrößerte Bild mit Timestamp im Dateinamen am selben Ort
    original_scaled_path = os.path.join("data/radar", os.path.basename(image_path))
    timestamped_scaled_path = os.path.join("data/radar", f"radar_{timestamp}.png")

    img_scaled = cv2.imread(original_scaled_path)
    if img_scaled is not None:
        cv2.imwrite(timestamped_scaled_path, img_scaled)
        debug_log(f"[INFO] Timestamped Radarbild gespeichert unter: {timestamped_scaled_path}")
    else:
        debug_log(f"[WARNUNG] Skaliertes Bild nicht gefunden: {original_scaled_path}")        

    # Bild verarbeiten
    hsv, contours, mask = preprocess_image(image_path)
    objects = update_tracking_memory(hsv, contours, weather_data, timestamp)
    
    overlay_img = cv2.imread("data/radar/" + os.path.basename(image_path))
    if overlay_img is None:
        raise FileNotFoundError(f"Overlay-Bild fehlt: data/radar/{os.path.basename(image_path)}")

    for obj in objects:
        cx = int(obj["x"])
        cy = int(obj["y"])

        contour_pts = np.array(obj["contour"], dtype=np.float32).reshape(-1, 2)

        # Zeichnen in Weiß, etwas dicker
        contour_pts = contour_pts.astype(np.int32).reshape(-1, 1, 2)
        cv2.drawContours(overlay_img, [contour_pts], -1, (255, 255, 255), 2)
        
        # Schwerpunkt zeichnen (kleiner weißer Punkt)
        contour_pts = np.array(obj["contour"], dtype=np.int32).reshape(-1, 1, 2)
        M = cv2.moments(contour_pts)
        if M["m00"] != 0:
            cx = int(M["m10"] / M["m00"])
            cy = int(M["m01"] / M["m00"])
            cv2.circle(overlay_img, (cx, cy), radius=3, color=(255, 255, 255), thickness=-1)

            # Weißer Rand (dicker)
            cv2.putText(overlay_img, obj["id"], (cx + 5, cy - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 3, lineType=cv2.LINE_AA)

            # Schwarze Schrift (dünner)
            cv2.putText(overlay_img, obj["id"], (cx + 5, cy - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1, lineType=cv2.LINE_AA)

    debug_overlay_path = f"train_data/debug_overlay_{timestamp}.png"
    cv2.imwrite(debug_overlay_path, overlay_img)
    save_debug_image(debug_overlay_path, overlay_img, f"Debug-Radarbild mit Konturen gespeichert: {debug_overlay_path}")

    return objects, timestamp