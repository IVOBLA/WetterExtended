import os
import cv2
import numpy as np
from datetime import datetime
from filterpy.kalman import KalmanFilter
from shapely.geometry import Polygon
from shapely.ops import unary_union
from config import UPSCALE_FACTOR, FILTER_CONFIG as _DEFAULT_FILTER_CONFIG, CORE_HSV_RANGES as _DEFAULT_CORE_HSV_RANGES, BBOX_KAERNTEN_EXTENDED as BBOX
import runtime_config as _rc
from geo_utils import pixel_to_geo
from utils import generate_id
from utils_weather import find_n_nearest_stations, weighted_average_weather
from debug_utils import save_debug_image, debug_log
from geo_utils import crop_and_upscale_to_bbox
from config import MIN_CONTOUR_OVERLAP
from config import MIN_CONTOUR_TOUCH


try:
    from dem_feature import get_dem_features
except Exception:
    def get_dem_features(*args, **kwargs):
        return {"dem_elevation_m": 0.0, "dem_slope_toward_cell": 0.0,
                "dem_barrier_ahead": 0.0}

try:
    from valley_feature import get_valley_features
except Exception:
    def get_valley_features(*args, **kwargs):
        return {"valley_alignment": 0.0, "valley_distance_km": 999.0,
                "valley_confinement": 0.0}

try:
    from orographic_module import assign_orographic_scores as _assign_orog
except Exception:
    def _assign_orog(objs):
        for o in objs:
            o.setdefault("terrain_blocking_score", 0.0)
            o.setdefault("orographic_lift_score",  0.0)
            o.setdefault("stationary_risk",        0.0)
            o.setdefault("forecast_speed_factor",  1.0)
        return objs

tracking_memory = {}

# ---------------------------------------------------------------------------
# Statische Ausschlusszonen (False-Positive-Filter)
# ---------------------------------------------------------------------------
try:
    from config import STATIC_EXCLUSION_ZONES as _DEFAULT_EXCLUSION_ZONES
except Exception:
    _DEFAULT_EXCLUSION_ZONES = []


def _is_in_exclusion_zone(lat: float, lon: float, zones: list) -> bool:
    """
    Gibt True zurück wenn (lat, lon) innerhalb einer konfigurierten
    Ausschlusszone liegt (Haversine-Distanz ≤ radius_km).
    """
    if not zones or lat is None or lon is None:
        return False
    try:
        from geo_utils import haversine_distance
    except Exception:
        return False
    for zone in zones:
        z_lat = zone.get("lat")
        z_lon = zone.get("lon")
        r_km  = float(zone.get("radius_km", 5.0))
        if z_lat is None or z_lon is None:
            continue
        if haversine_distance(float(lat), float(lon),
                              float(z_lat), float(z_lon)) <= r_km:
            return True
    return False

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
    FILTER_CONFIG = _rc.get("FILTER_CONFIG", _DEFAULT_FILTER_CONFIG)
    CORE_HSV_RANGES = _rc.get("CORE_HSV_RANGES", _DEFAULT_CORE_HSV_RANGES)
    # Bild mit geo-zuschnitt & hochskalierung laden
    from config import BBOX_KAERNTEN_EXTENDED

    processed_img = crop_and_upscale_to_bbox(image_path, BBOX_KAERNTEN_EXTENDED, UPSCALE_FACTOR)
    hsv = cv2.cvtColor(processed_img, cv2.COLOR_BGR2HSV)

    mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
    for lower, upper in FILTER_CONFIG["allowed_hsv_ranges"]:
        mask |= cv2.inRange(hsv, np.array(lower), np.array(upper))

    # Morphologisches Closing — identisch mit detect_and_track_objects()
    _close_size = int(_rc.get("MORPH_CLOSE_SIZE", 7))
    kernel = np.ones((_close_size, _close_size), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    merged = merge_close_contours(contours, hsv.shape[:2], min_touch=MIN_CONTOUR_TOUCH)
    return hsv, merged, mask
    
def compute_stratiform_environment(hsv: np.ndarray, contour: np.ndarray,
                                   vx: float = 0.0,
                                   vy: float = 0.0) -> dict:
    """
    Berechnet stratiforme Umgebungsfeatures (36–47 dBZ) im
    STRATIFORM_SEARCH_RADIUS_PX-Umkreis der Zell-Kontur.

    Rückgabe: dict mit strat_area_px, strat_intensity_mean, strat_dbz_gradient
    Fallback: alle 0.0 bei Fehler oder fehlenden Imports.
    """
    _default = {
        "strat_area_px": 0.0,
        "strat_intensity_mean": 0.0,
        "strat_dbz_gradient": 0.0,
    }
    try:
        from config import STRATIFORM_HSV_RANGES, STRATIFORM_SEARCH_RADIUS_PX
    except ImportError:
        return _default

    try:
        h_img, w_img = hsv.shape[:2]
        x_pts = contour[:, 0, 0]
        y_pts = contour[:, 0, 1]
        r = int(STRATIFORM_SEARCH_RADIUS_PX)

        # Region of Interest um die Zell-Kontur
        x0 = max(0, int(x_pts.min()) - r)
        x1 = min(w_img, int(x_pts.max()) + r)
        y0 = max(0, int(y_pts.min()) - r)
        y1 = min(h_img, int(y_pts.max()) + r)
        roi = hsv[y0:y1, x0:x1]
        if roi.size == 0:
            return _default

        # Stratiforme Maske (Grün + GelbGrün)
        strat_mask = np.zeros(roi.shape[:2], dtype=np.uint8)
        for lower, upper in STRATIFORM_HSV_RANGES:
            strat_mask |= cv2.inRange(
                roi,
                np.array(lower, dtype=np.uint8),
                np.array(upper, dtype=np.uint8),
            )

        # Zell-Kontur aus Maske ausschneiden (keine Doppelzählung)
        cell_roi = np.zeros(roi.shape[:2], dtype=np.uint8)
        cnt_shift = contour.copy()
        cnt_shift[:, 0, 0] = np.clip(cnt_shift[:, 0, 0] - x0, 0, x1 - x0 - 1)
        cnt_shift[:, 0, 1] = np.clip(cnt_shift[:, 0, 1] - y0, 0, y1 - y0 - 1)
        cv2.drawContours(cell_roi, [cnt_shift], -1, 255, -1)
        strat_mask = cv2.bitwise_and(strat_mask, cv2.bitwise_not(cell_roi))

        area = float(cv2.countNonZero(strat_mask))

        # Mittlere Helligkeit der stratiformen Pixel
        if area > 0:
            val_ch = roi[:, :, 2].astype(np.float32) / 255.0
            intensity_mean = float(cv2.mean(val_ch, mask=strat_mask)[0])
        else:
            intensity_mean = 0.0

        # dBZ-Gradient in Bewegungsrichtung
        # Verschobene Maske vergleichen: mehr stratiforme Pixel voraus = positiv
        gradient = 0.0
        speed = float(np.hypot(vx, vy))
        if speed > 0.01:
            shift_dist = max(1, int(r * 0.25))
            dx = int(round(vx / speed * shift_dist))
            dy = int(round(vy / speed * shift_dist))
            M_aff = np.float32([[1, 0, dx], [0, 1, dy]])
            shifted = cv2.warpAffine(
                strat_mask, M_aff,
                (strat_mask.shape[1], strat_mask.shape[0]),
            )
            area_ahead = float(cv2.countNonZero(shifted))
            gradient = (area_ahead - area) / max(area, 1.0)

        return {
            "strat_area_px": round(area, 1),
            "strat_intensity_mean": round(intensity_mean, 4),
            "strat_dbz_gradient": round(gradient, 4),
        }

    except Exception as exc:
        debug_log(f"[STRAT] compute_stratiform_environment Fehler: {exc}")
        return _default


def calculate_core_ratio(hsv, contour):
    CORE_HSV_RANGES = _rc.get("CORE_HSV_RANGES", _DEFAULT_CORE_HSV_RANGES)
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
    FILTER_CONFIG = _rc.get("FILTER_CONFIG", _DEFAULT_FILTER_CONFIG)
    # F7-FIX: BBOX live aus runtime_config — Admin-Panel-Änderungen wirken sofort.
    from config import BBOX_KAERNTEN_EXTENDED as _DEFAULT_BBOX
    _BBOX_LIVE = _rc.get("BBOX_KAERNTEN_EXTENDED", _DEFAULT_BBOX)
    global tracking_memory
    objects = []
    new_memory = {}
    used_ids = set()

    def is_within_bbox(lat, lon, bbox):
        return (
            bbox["south"] <= lat <= bbox["north"] and
            bbox["west"] <= lon <= bbox["east"]
        )

    previous_snapshot = tracking_memory.copy()
    history_len = int(_rc.get("TRACK_HISTORY_LEN", 3))
    prev_polys = []
    for prev_id, prev_obj in previous_snapshot.items():
        try:
            if prev_obj.get("missing", 0) <= 10:
                prev_polys.append((prev_id, Polygon(np.array(prev_obj["contour"]))))
        except Exception:
            continue

    assigned_old_to_new = {}

    for contour in contours:
        M = cv2.moments(contour)
        if M["m00"] == 0:
            continue
        cx = int(M["m10"] / M["m00"])
        cy = int(M["m01"] / M["m00"])
        original_cx = int(cx / UPSCALE_FACTOR)
        original_cy = int(cy / UPSCALE_FACTOR)
        area, eccentricity = calculate_shape_features(contour)
        core_ratio = calculate_core_ratio(hsv, contour)
        if area < FILTER_CONFIG["min_object_area"] and core_ratio < 0.05:
            continue
        # pixel_to_geo erwartet SKALIERTE Koordinaten (teilt intern durch upscale)
        lat, lon = pixel_to_geo(cx, cy)

        # Ausschlusszone prüfen — bekannte Artefakte (Radarmaste, Sendeanlagen)
        _zones = _rc.get("STATIC_EXCLUSION_ZONES", _DEFAULT_EXCLUSION_ZONES)
        if _is_in_exclusion_zone(lat, lon, _zones):
            debug_log(
                f"[TRACKING] Kontur bei ({lat:.3f}°N, {lon:.3f}°E) in "
                f"Ausschlusszone — übersprungen."
            )
            continue
        if not is_within_bbox(lat, lon, _BBOX_LIVE):
            continue

        current_poly = Polygon(contour[:, 0, :])
        overlaps = []
        area_new = max(current_poly.area, 1e-6)
        for old_id, old_poly in prev_polys:
            try:
                ratio = current_poly.intersection(old_poly).area / area_new
                if ratio >= 0.3:
                    overlaps.append((old_id, ratio))
            except Exception:
                continue
        overlaps.sort(key=lambda t: t[1], reverse=True)

        lineage = "new"
        parents = []
        best_id = None
        obj_id = None

        if len(overlaps) >= 2:
            obj_id = generate_id()
            lineage = "merged"
            parents = [oid for oid, _ in overlaps]
            for merged_old_id in parents:
                old_obj = previous_snapshot.get(merged_old_id, {})
                old_obj["children"] = [obj_id]
                old_obj["lineage_end"] = f"merged_into:{obj_id}"
                previous_snapshot[merged_old_id] = old_obj
                used_ids.add(merged_old_id)
        elif len(overlaps) == 1:
            best_id = overlaps[0][0]
            obj_id = best_id
            lineage = "continued"
            parents = [best_id]

        if obj_id and obj_id in previous_snapshot:
            used_ids.add(obj_id)
            kf = previous_snapshot[obj_id]["kf"]
            kf.predict()
            _prev_vx = float(kf.x[2])
            _prev_vy = float(kf.x[3])
            kf.update([original_cx, original_cy])
            _clamp_kalman_velocity(kf, _prev_vx, _prev_vy)
            vx, vy = kf.x[2], kf.x[3]
        else:
            if obj_id is None:
                obj_id = generate_id()
            kf = KalmanFilter(dim_x=4, dim_z=2)
            kf.x = np.array([original_cx, original_cy, 0.0, 0.0])
            kf.F = np.array([[1, 0, 1, 0], [0, 1, 0, 1], [0, 0, 1, 0], [0, 0, 0, 1]])
            kf.H = np.array([[1, 0, 0, 0], [0, 1, 0, 0]])
            kf.P = np.eye(4) * 500
            kf.R = np.eye(2) * 10
            kf.Q = np.array([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0.5, 0], [0, 0, 0, 0.5]])
            vx, vy = 0.0, 0.0

        trend = 0
        if best_id and best_id in previous_snapshot and "core_ratio" in previous_snapshot[best_id]:
            prev_core = previous_snapshot[best_id]["core_ratio"]
            if core_ratio > prev_core + 0.05:
                trend = 1
            elif core_ratio < prev_core - 0.05:
                trend = -1

        dem    = get_dem_features(lat, lon, vx=float(vx), vy=float(vy))
        valley = get_valley_features(lat, lon, vx=float(vx), vy=float(vy))
        strat  = compute_stratiform_environment(
            hsv, contour, vx=float(vx), vy=float(vy)
        )
        new_memory[obj_id] = {
            "x": original_cx, "y": original_cy, "vx": float(vx), "vy": float(vy),
            "size": int(np.sqrt(area)), "area": float(area), "eccentricity": float(eccentricity),
            "core_ratio": float(core_ratio), "trend": trend, "lat": lat, "lon": lon,
            "dem_elevation_m":        dem["dem_elevation_m"],
            "dem_slope_toward_cell":  dem["dem_slope_toward_cell"],
            "dem_barrier_ahead":      dem.get("dem_barrier_ahead", 0.0),
            "valley_alignment":       valley["valley_alignment"],
            "valley_distance_km":     valley["valley_distance_km"],
            "valley_confinement":     valley["valley_confinement"],
            "terrain_blocking_score": 0.0,
            "orographic_lift_score":  0.0,
            "stationary_risk":        0.0,
            "forecast_speed_factor":  1.0,
            "strat_area_px": strat["strat_area_px"],
            "strat_intensity_mean": strat["strat_intensity_mean"],
            "strat_dbz_gradient": strat["strat_dbz_gradient"],
            "lightning_count_10km": 0,
            "kf": kf, "contour": contour[:, 0, :].tolist(), "weather_vals": {}, "station_ids": [],
            "lstm_vx": 0.0, "lstm_vy": 0.0, "missing": 0,
            "lineage": lineage, "parents": parents, "children": [], "lineage_end": None,
        }
        for parent_id in parents:
            assigned_old_to_new.setdefault(parent_id, []).append(obj_id)

    for old_id, new_ids in assigned_old_to_new.items():
        uniq = []
        for nid in new_ids:
            if nid not in uniq:
                uniq.append(nid)
        if len(uniq) >= 2 and old_id in new_memory:
            areas = [(nid, float(new_memory.get(nid, {}).get("area", 0.0))) for nid in uniq if nid in new_memory]
            if not areas:
                continue
            areas.sort(key=lambda item: item[1], reverse=True)
            keep_id = areas[0][0]
            children = [keep_id]
            for sid, _ in areas[1:]:
                src = new_memory.get(sid)
                if not src:
                    continue
                new_id = generate_id()
                while new_id in new_memory:
                    new_id = generate_id()
                split_obj = src.copy()
                split_obj["lineage"] = "split"
                split_obj["parents"] = [old_id]
                new_memory[new_id] = split_obj
                del new_memory[sid]
                children.append(new_id)
            old_obj = previous_snapshot.get(old_id, {})
            old_obj["children"] = children
            old_obj["lineage_end"] = f"split_into:{children}"
            previous_snapshot[old_id] = old_obj

    for obj_id, obj in previous_snapshot.items():
        if obj_id not in new_memory:
            lat, lon = obj.get("lat"), obj.get("lon")
            if is_within_bbox(lat, lon, _BBOX_LIVE):
                obj["missing"] = obj.get("missing", 0) + 1
                if obj["missing"] <= 10:
                    new_memory[obj_id] = obj

    if len(set(new_memory.keys())) != len(new_memory):
        debug_log("[TRACKING] WARN: Doppelte IDs in new_memory erkannt")
    # Orographische Scores werden in main.py nach assign_cape gesetzt
    # (brauchen CAPE-Werte die hier noch nicht verfügbar sind).
    tracking_memory = new_memory
    for obj_id, obj in new_memory.items():
        if obj.get("missing", 0) == 0:
            # F2-FIX: History aus previous_snapshot lesen (vor Überschreiben),
            # nicht aus tracking_memory (= new_memory, hat noch kein "history"-Key).
            previous_history = previous_snapshot.get(obj_id, {}).get("history", [])
            new_entry = {"timestamp": timestamp, "vx": float(obj["vx"]), "vy": float(obj["vy"]), "core_ratio": float(obj["core_ratio"]), "weather_vals": {}, "lat": obj["lat"], "lon": obj["lon"]}
            updated_history = (previous_history + [new_entry])[-history_len:]
            obj_clean = obj.copy(); obj_clean.pop("kf", None); obj_clean["history"] = updated_history
            if not isinstance(obj_clean.get("lineage"), str): obj_clean["lineage"] = "new"
            obj_clean.setdefault("parents", []); obj_clean.setdefault("children", []); obj_clean.setdefault("lineage_end", None)
            objects.append({"id": obj_id, **obj_clean})
    return objects


import math as _math

def _clamp_kalman_velocity(kf, prev_vx: float, prev_vy: float) -> None:
    """
    Plausibilitätsprüfung (F14): Klemmt Kalman-Geschwindigkeit auf physikalisch
    sinnvolle Werte. Verhindert Sprünge durch Mess-Artefakte oder kurzzeitige
    Zellverwechslungen.

    Grenzen aus config.py:
      MAX_CELL_SPEED_KMH       — absolute Obergrenze Zellgeschwindigkeit
      MAX_SPEED_CHANGE_PER_CYCLE_KMH — max. Änderung pro 5-min-Zyklus
    """
    try:
        from config import MAX_CELL_SPEED_KMH, MAX_SPEED_CHANGE_PER_CYCLE_KMH
    except ImportError:
        MAX_CELL_SPEED_KMH = 150.0
        MAX_SPEED_CHANGE_PER_CYCLE_KMH = 60.0

    # Pixel/Frame zu km/h umrechnen (1 px ≈ 1 km bei UPSCALE_FACTOR=3)
    PIXEL_TO_KMH = 12.0  # empirisch: 1 px/Frame ≈ 12 km/h

    vx = float(kf.x[2])
    vy = float(kf.x[3])
    speed = _math.hypot(vx, vy) * PIXEL_TO_KMH

    # 1. Absolute Geschwindigkeitsobergrenze
    if speed > MAX_CELL_SPEED_KMH:
        scale = (MAX_CELL_SPEED_KMH / PIXEL_TO_KMH) / max(_math.hypot(vx, vy), 1e-9)
        kf.x[2] = vx * scale
        kf.x[3] = vy * scale

    # 2. Maximale Beschleunigung pro Zyklus
    dvx = float(kf.x[2]) - prev_vx
    dvy = float(kf.x[3]) - prev_vy
    delta_speed = _math.hypot(dvx, dvy) * PIXEL_TO_KMH
    if delta_speed > MAX_SPEED_CHANGE_PER_CYCLE_KMH:
        scale = (MAX_SPEED_CHANGE_PER_CYCLE_KMH / PIXEL_TO_KMH) / max(_math.hypot(dvx, dvy), 1e-9)
        kf.x[2] = prev_vx + dvx * scale
        kf.x[3] = prev_vy + dvy * scale

def detect_and_track_objects(image_path=None, weather_data=None):
    FILTER_CONFIG = _rc.get("FILTER_CONFIG", _DEFAULT_FILTER_CONFIG)
    CORE_HSV_RANGES = _rc.get("CORE_HSV_RANGES", _DEFAULT_CORE_HSV_RANGES)
    import os
    from datetime import datetime
    from config import BBOX_KAERNTEN_EXTENDED as BBOX, UPSCALE_FACTOR, SAVE_PATHS

    if image_path is None:
        image_path = "data/latest.png"

    os.makedirs(os.path.join("data", "radar"), exist_ok=True)
    os.makedirs(SAVE_PATHS["radar"].rstrip("/"), exist_ok=True)
    os.makedirs(SAVE_PATHS["objects"].rstrip("/"), exist_ok=True)

    debug_log(f"Tracking auf Bild: {image_path}")

    if weather_data is None:
        weather_data = []

    # 📆 Timestamp extrahieren
    filename = os.path.basename(image_path).replace(".png", "")
    if "latest" in filename:
        ts_dt = datetime.now()
        timestamp = ts_dt.strftime("%Y-%m-%d_%H-%M-%S")
        debug_log(f"[INFO] Live-Modus erkannt → Timestamp: {timestamp}")
    else:
        try:
            ts_dt = datetime.strptime(filename.replace("radar_", ""), "%Y-%m-%d_%H-%M-%S")
            timestamp = ts_dt.strftime("%Y-%m-%d_%H-%M-%S")
        except ValueError:
            ts_dt = datetime.now()
            timestamp = ts_dt.strftime("%Y-%m-%d_%H-%M-%S")

    # ✂️ Bild zuschneiden & hochskalieren
    scaled_path = os.path.join("data/radar", f"radar_{timestamp}.png")
    processed_img = crop_and_upscale_to_bbox(image_path, BBOX, UPSCALE_FACTOR, scaled_path)

    # 💾 Originalbild (unverändert) archivieren
    original_img = cv2.imread(image_path)
    if original_img is not None:
        original_path = os.path.join(SAVE_PATHS["radar"].rstrip("/"), f"radar_{timestamp}.png")
        cv2.imwrite(original_path, original_img)
        debug_log(f"[INFO] Originalbild archiviert: {original_path}")
    else:
        debug_log(f"[WARNUNG] Originalbild konnte nicht geladen werden: {image_path}")

    # 🧪 Segmentierung
    hsv = cv2.cvtColor(processed_img, cv2.COLOR_BGR2HSV)
    mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
    for lower, upper in FILTER_CONFIG["allowed_hsv_ranges"]:
        mask |= cv2.inRange(hsv, np.array(lower), np.array(upper))
    # Bildrand maskieren (entfernt KMZ-Rahmen-Artefakte)
    border_px = int(FILTER_CONFIG.get("border_mask_px", 10))
    if border_px > 0:
        mask[:border_px, :] = 0
        mask[-border_px:, :] = 0
        mask[:, :border_px] = 0
        mask[:, -border_px:] = 0
    # Morphologisches Closing — HSV-Lücken (JPEG-Artefakte, Farbinterpolation)
    # schließen. Ohne Closing → Kontur zersplittert in Fragmente < min_object_area
    # → Zellen ohne Rotkern werden verworfen (core_ratio < 0.05-Bypass greift nicht).
    # MORPH_CLOSE_SIZE=7 bei UPSCALE=3 ≈ 2.3 km Closing-Radius.
    # Überschreibbar via Admin-Panel: runtime_overrides.json "MORPH_CLOSE_SIZE": 9
    _close_size = int(_rc.get("MORPH_CLOSE_SIZE", 7))
    _kernel = np.ones((_close_size, _close_size), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, _kernel, iterations=2)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    merged = merge_close_contours(contours, hsv.shape[:2], min_touch=MIN_CONTOUR_TOUCH)

    # 📌 Objektverfolgung
    objects = update_tracking_memory(hsv, merged, weather_data, timestamp)

    # 🖼️ Overlay erstellen
    overlay_img = processed_img.copy()
    for obj in objects:
        contour = np.array(obj["contour"], dtype=np.int32).reshape(-1, 1, 2)
        cv2.drawContours(overlay_img, [contour], -1, (255, 255, 255), 2)

        M = cv2.moments(contour)
        if M["m00"] != 0:
            cx = int(M["m10"] / M["m00"])
            cy = int(M["m01"] / M["m00"])
            cv2.circle(overlay_img, (cx, cy), 3, (255, 255, 255), -1)
            cv2.putText(overlay_img, obj["id"], (cx + 5, cy - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, lineType=cv2.LINE_AA)
            cv2.putText(overlay_img, obj["id"], (cx + 5, cy - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1, lineType=cv2.LINE_AA)

    # 💾 Debug Overlay speichern
    debug_overlay_path = os.path.join(
        SAVE_PATHS["objects"].rstrip("/"),
        f"debug_overlay_{timestamp}.png"
    )
    cv2.imwrite(debug_overlay_path, overlay_img)
    cv2.imwrite("data/overlay.png", overlay_img)
    save_debug_image(debug_overlay_path, overlay_img, f"Overlay gespeichert: {debug_overlay_path}")

    # Geo-Konturen und Intensitätszonen für Karten-Darstellung berechnen
    INTENSITY_BANDS = [
        ("orange",  ( 10, 100,  80), ( 27, 255, 255), "#ff8800"),
        ("rot",     (  0, 100,  80), ( 10, 255, 255), "#cc0000"),
        ("rot_wrap",(165, 100,  80), (179, 255, 255), "#cc0000"),
        ("violett", (125, 100,  80), (155, 255, 255), "#9900cc"),
    ]
    for obj in objects:
        raw_contour = obj.get("contour")
        if not raw_contour:
            obj["contour_geo"] = []
            obj["intensity_zones"] = []
            continue

        cnt_px = np.array(raw_contour, dtype=np.int32).reshape(-1, 1, 2)

        # Äußere Kontur → Geo-Koordinaten [lon, lat] (GeoJSON-Format)
        geo_pts = []
        for pt in cnt_px[:, 0, :]:
            lat_p, lon_p = pixel_to_geo(int(pt[0]), int(pt[1]))
            geo_pts.append([round(lon_p, 6), round(lat_p, 6)])
        if len(geo_pts) >= 3:
            if geo_pts[0] != geo_pts[-1]:
                geo_pts.append(geo_pts[0])  # Polygon schließen
        obj["contour_geo"] = geo_pts

        # Intensitätszonen innerhalb der Zelle
        cell_mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
        cv2.drawContours(cell_mask, [cnt_px], -1, 255, -1)

        zones = []
        for band_name, lower, upper, color in INTENSITY_BANDS:
            band_mask = cv2.inRange(hsv, np.array(lower), np.array(upper))
            band_mask = cv2.bitwise_and(band_mask, cell_mask)
            band_cnts, _ = cv2.findContours(band_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for bc in band_cnts:
                if cv2.contourArea(bc) < 30:
                    continue
                zone_pts = []
                for pt in bc[:, 0, :]:
                    lat_p, lon_p = pixel_to_geo(int(pt[0]), int(pt[1]))
                    zone_pts.append([round(lon_p, 6), round(lat_p, 6)])
                if len(zone_pts) >= 3:
                    if zone_pts[0] != zone_pts[-1]:
                        zone_pts.append(zone_pts[0])
                    zones.append({"band": band_name, "color": color, "coords": zone_pts})
        obj["intensity_zones"] = zones

    return objects, timestamp
