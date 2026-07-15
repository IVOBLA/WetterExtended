import os
import cv2
import numpy as np
from datetime import datetime
from radar_download import get_acquisition_timestamp
from filterpy.kalman import KalmanFilter
from shapely.geometry import Polygon
from shapely.ops import unary_union
from config import UPSCALE_FACTOR, FILTER_CONFIG as _DEFAULT_FILTER_CONFIG, CORE_HSV_RANGES as _DEFAULT_CORE_HSV_RANGES, BBOX_KAERNTEN_EXTENDED as BBOX, CORE_VIOLET_HUE_MIN, CORE_VIOLET_HUE_MAX, RADAR_DBZ_BANDS as _DEFAULT_RADAR_DBZ_BANDS
import math as _math_ot
import runtime_config as _rc
from geo_utils import pixel_to_geo
from utils import generate_id
from utils_weather import find_n_nearest_stations, weighted_average_weather
from debug_utils import save_debug_image, debug_log
from geo_utils import crop_and_upscale_to_bbox
from config import MIN_CONTOUR_OVERLAP
from config import MIN_CONTOUR_TOUCH
from config import MERGE_TOUCH_DILATE_PX
from config import (
    TENDENCY_AREA_PCT_STABLE,
    TENDENCY_CORE_DELTA_STABLE,
    TENDENCY_CORE_AREA_PCT_STABLE,
    TENDENCY_CONTRADICTION_AREA_SHRINK_PCT,
    TENDENCY_COMPACT_CORE_RATIO_DELTA,
)


def _compute_neighbor_ahead(self_obj, all_objs, *,
                            range_km, half_angle_deg, min_speed_kmh,
                            px_to_kmh, upscale):
    """B94: Weggefährten-Features im Bewegungs-Zielkorridor.

    Rückgabe-dict: neighbor_count_ahead, neighbor_max_core_ahead,
                   neighbor_min_dist_km_ahead, strat_area_ahead_px
    """
    import math

    neutral = {
        "neighbor_count_ahead": 0.0,
        "neighbor_max_core_ahead": 0.0,
        "neighbor_min_dist_km_ahead": 999.0,
        "strat_area_ahead_px": 0.0,
    }
    lat0 = self_obj.get("lat")
    lon0 = self_obj.get("lon")
    if lat0 is None or lon0 is None:
        return neutral
    lat0 = float(lat0)
    lon0 = float(lon0)

    vx = float(self_obj.get("vx") or 0.0)
    vy = float(self_obj.get("vy") or 0.0)
    kmh_per_scaled_px = px_to_kmh / max(float(upscale), 1.0)
    speed_kmh = math.hypot(vx, vy) * kmh_per_scaled_px
    if speed_kmh < min_speed_kmh:
        return neutral

    dir_x = vx
    dir_y = -vy   # Bildkoord y→unten/Süd → für Geo invertieren
    norm = math.hypot(dir_x, dir_y)
    if norm < 1e-9:
        return neutral
    dir_x /= norm
    dir_y /= norm

    cos_half = math.cos(math.radians(half_angle_deg))
    count = 0
    max_core = 0.0
    min_dist = 999.0
    strat_ahead = 0.0
    self_id = self_obj.get("id")
    coslat = math.cos(math.radians(lat0)) or 1e-6

    for other in all_objs:
        if other is self_obj or other.get("id") == self_id:
            continue
        olat = other.get("lat")
        olon = other.get("lon")
        if olat is None or olon is None:
            continue
        dnorth = (float(olat) - lat0) * 111.0
        deast = (float(olon) - lon0) * 111.0 * coslat
        dist = math.hypot(dnorth, deast)
        if dist <= 0.0 or dist > range_km:
            continue
        ox = deast / dist
        oy = dnorth / dist
        if (ox * dir_x + oy * dir_y) < cos_half:
            continue
        count += 1
        max_core = max(max_core, float(other.get("core_ratio") or 0.0))
        min_dist = min(min_dist, dist)
        strat_ahead += float(other.get("strat_area_px") or 0.0)

    return {
        "neighbor_count_ahead": float(count),
        "neighbor_max_core_ahead": float(max_core),
        "neighbor_min_dist_km_ahead": float(min_dist),
        "strat_area_ahead_px": float(strat_ahead),
    }


def _validate_bbox(bbox: object, fallback: dict) -> dict:
    """
    Prüft ob bbox ein gültiges BBOX-Dict ist.
    Gibt bbox zurück wenn gültig, sonst fallback.
    Verhindert KeyError/TypeError in crop_and_upscale_to_bbox bei fehlerhaftem
    Admin-Eintrag oder beschädigtem runtime_overrides.json.
    """
    if not isinstance(bbox, dict):
        return fallback
    try:
        s = float(bbox["south"])
        w = float(bbox["west"])
        n = float(bbox["north"])
        e = float(bbox["east"])
        if not (-90 <= s < n <= 90) or not (-180 <= w < e <= 180):
            return fallback
    except (KeyError, TypeError, ValueError):
        return fallback
    return bbox


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


def _suppress_inactive_rain_warning_fields(obj: dict) -> dict:
    """Entfernt Karten-Warnmarker von still nachverfolgten Regenresten."""
    if obj.get("tracking_state") == "inactive_rain" or obj.get("silent_tracking") is True:
        obj["hail_warning"] = False
        obj["stationary_marker"] = False
        obj["hail_prob"] = 0.0
        obj["hail_prob_effective"] = 0.0
        obj["stationary_risk"] = 0.0
    return obj


# B121: Snapshot-Pfad — wird beim Service-Start via load_tracking_snapshot() geladen.
# Kein Import von SAVE_PATHS auf Modulebene um zirkuläre Imports zu vermeiden.
_SNAPSHOT_FILENAME = "tracking_memory_snapshot.json"


def _snapshot_path() -> str:
    """Gibt den vollständigen Pfad der Snapshot-Datei zurück."""
    try:
        from config import SAVE_PATHS as _SP
        return os.path.join(
            _SP.get("evaluation", "train_data/evaluation"),
            _SNAPSHOT_FILENAME,
        )
    except Exception:
        return os.path.join("train_data", "evaluation", _SNAPSHOT_FILENAME)


def _json_safe(obj):
    """JSON-Serialisierer für numpy-Arrays und ähnliche Typen."""
    if hasattr(obj, "tolist"):
        return obj.tolist()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def save_tracking_snapshot() -> None:
    """B121: Persistiert tracking_memory als JSON-Snapshot auf Disk.

    Wird am Ende jedes update_tracking_memory()-Aufrufs aufgerufen.
    Speichert alle Zellen ohne den nicht-serialisierbaren KalmanFilter (kf).
    Numpy-Arrays (contour) werden via _json_safe in Python-Listen konvertiert.
    Schreibt atomar via .tmp-Datei.
    """
    global tracking_memory
    snap_path = _snapshot_path()
    try:
        os.makedirs(os.path.dirname(snap_path), exist_ok=True)
        snapshot = {}
        for obj_id, obj in tracking_memory.items():
            snapshot[obj_id] = {k: v for k, v in obj.items() if k != "kf"}
        tmp_path = snap_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as _f:
            import json as _json_snap
            _json_snap.dump(snapshot, _f, default=_json_safe, ensure_ascii=False)
        os.replace(tmp_path, snap_path)
    except Exception as _exc:
        debug_log(f"[SNAPSHOT] Speicherfehler: {_exc}")


def load_tracking_snapshot() -> float:
    """B121: Lädt tracking_memory aus dem letzten Snapshot (falls vorhanden und aktuell).

    Rückgabe: Alter der Snapshot-Datei in Sekunden, oder float('inf') wenn
    kein Snapshot geladen wurde. Wird von main.py für _last_cells_active_ts genutzt.

    Snapshot wird nur geladen wenn sein Alter < INACTIVE_CELL_TRACK_DURATION_S
    (Standard 20 min). Ältere Snapshots werden ignoriert — die enthaltenen Zellen
    wären ohnehin aus tracking_memory gefallen.

    Zellen werden OHNE KalmanFilter-Zustand geladen. Der Filter wird im nächsten
    Zyklus durch das 3-Stage-Matching neu aufgebaut (Stage-2/3 genügen).
    """
    global tracking_memory
    import time as _t_snap
    import json as _json_load

    snap_path = _snapshot_path()
    if not os.path.exists(snap_path):
        return float("inf")

    try:
        from config import INACTIVE_CELL_TRACK_DURATION_S as _ICTD
        import runtime_config as _rc_snap
        max_age_s = float(_rc_snap.get("INACTIVE_CELL_TRACK_DURATION_S", _ICTD))
    except Exception:
        max_age_s = 1200.0  # 20 min Fallback

    try:
        snap_age_s = _t_snap.time() - os.path.getmtime(snap_path)
    except Exception:
        return float("inf")

    if snap_age_s > max_age_s:
        debug_log(
            f"[SNAPSHOT] Zu alt ({snap_age_s:.0f}s > {max_age_s:.0f}s) — ignoriert"
        )
        # P-S01: Die Zellen im verworfenen Snapshot sind endgültig tot —
        # Lifecycle-Datensätze nachtragen, damit kein Track unprotokolliert endet.
        try:
            from datetime import datetime as _dt_ps01
            from track_statistics import write_track_end as _wte_snap
            with open(snap_path, "r", encoding="utf-8") as _f_snap:
                _old_snap = _json_load.load(_f_snap)
            if isinstance(_old_snap, dict):
                _end_ts = _dt_ps01.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
                for _oid, _oobj in _old_snap.items():
                    if isinstance(_oobj, dict):
                        _wte_snap(_oobj, "service_restart", _end_ts)
        except Exception as _e_te4:
            debug_log(f"[P-S01] track_end service_restart Fehler: {_e_te4}")
        return float("inf")

    try:
        with open(snap_path, "r", encoding="utf-8") as _f:
            snapshot = _json_load.load(_f)
        if not isinstance(snapshot, dict):
            return float("inf")

        loaded = 0
        for obj_id, obj in snapshot.items():
            if isinstance(obj, dict):
                tracking_memory[obj_id] = obj
                loaded += 1

        debug_log(
            f"[SNAPSHOT] {loaded} Zellen geladen "
            f"(Snapshot-Alter: {snap_age_s:.0f}s)"
        )
        return snap_age_s
    except Exception as _exc:
        debug_log(f"[SNAPSHOT] Ladefehler: {_exc}")
        return float("inf")

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
    
def are_contours_touching_edges(cnt1, cnt2, shape, min_touch=3, dilate_px=0):
    mask1 = np.zeros(shape, dtype=np.uint8)
    mask2 = np.zeros(shape, dtype=np.uint8)

    # Nur Ränder zeichnen (keine Fläche)
    cv2.drawContours(mask1, [cnt1], -1, 255, thickness=1)
    cv2.drawContours(mask2, [cnt2], -1, 255, thickness=1)

    # B274: Puffer gegen Ein-Pixel-Luecken aus der Konturextraktion (Anti-Aliasing
    # am HSV-Schwellwertrand). Ohne Dilatation gilt schon eine einzige Pixelreihe
    # Abstand als "nicht beruehrend", obwohl es sich um dieselbe zusammenhaengende
    # Zelle handelt.
    if dilate_px > 0:
        kernel = np.ones((2 * dilate_px + 1, 2 * dilate_px + 1), np.uint8)
        mask1 = cv2.dilate(mask1, kernel)
        mask2 = cv2.dilate(mask2, kernel)

    # Überlappung der Ränder prüfen
    overlap = cv2.bitwise_and(mask1, mask2)
    return cv2.countNonZero(overlap) >= min_touch
    

def calculate_shape_features(contour):
    """
    Gibt (area_px, eccentricity) zurück.
    Eccentricity: 0.0 = Kreis, → 1.0 = sehr gestreckte Ellipse.
    Formel: sqrt(1 - (minor/major)²) — immer in [0, 1].

    Finding #2 Fix:
    - Achsen sortieren (major = max, minor = min) damit Wert nie > 1 wird.
    - Korrekte geometrische Formel statt einfaches Verhältnis.
    - area == 0 → (0, 0.0) statt (0, 0.0) mit if-Fallthrough.
    """
    area = cv2.contourArea(contour)
    if area <= 0:
        return float(area), 0.0
    if len(contour) >= 5:
        # fitEllipse gibt (center, (width, height), angle) zurück.
        # width/height können je nach Orientierung tauschen → immer sortieren.
        _, (axis_a, axis_b), _ = cv2.fitEllipse(contour)
        major = max(float(axis_a), float(axis_b))
        minor = min(float(axis_a), float(axis_b))
        if major > 0.0:
            ratio = minor / major
            # Clamp wegen Floating-Point: ratio > 1 theoretisch unmöglich, aber sicher
            ratio = min(ratio, 1.0)
            eccentricity = _math_ot.sqrt(1.0 - ratio ** 2)
        else:
            eccentricity = 0.0
    else:
        # < 5 Punkte → Ellipsen-Fit nicht möglich → Kreis-Annahme
        eccentricity = 0.0
    # Hard-Clamp: data_quality.py prüft ECCENTRICITY_MIN=0.0, ECCENTRICITY_MAX=1.0
    eccentricity = max(0.0, min(1.0, eccentricity))
    return float(area), float(eccentricity)

def _uf_find(parent, i):
    """Union-Find: Wurzel von i mit Pfadkompression (iterativ, kein Rekursionslimit)."""
    root = i
    while parent[root] != root:
        root = parent[root]
    while parent[i] != root:
        parent[i], i = root, parent[i]
    return root


def _uf_union(parent, rank, a, b):
    """Union-Find: vereinigt die Komponenten von a und b (Union by Rank)."""
    ra, rb = _uf_find(parent, a), _uf_find(parent, b)
    if ra == rb:
        return
    if rank[ra] < rank[rb]:
        ra, rb = rb, ra
    parent[rb] = ra
    if rank[ra] == rank[rb]:
        rank[ra] += 1


def _bbox_of(cnt):
    """Achsenparallele Bounding-Box (x_min, y_min, x_max, y_max) einer Kontur."""
    xs = cnt[:, 0, 0]
    ys = cnt[:, 0, 1]
    return (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))


def _bboxes_can_touch(b1, b2, slack):
    """Schnelltest: koennen sich zwei Konturen bei gegebenem Puffer ueberhaupt beruehren?
    Nur wenn die um `slack` erweiterten Bounding-Boxen ueberlappen. Spart auf dem Pi den
    teuren Vollbild-Maskenvergleich fuer weit entfernte Konturpaare."""
    return not (
        b1[2] + slack < b2[0] or b2[2] + slack < b1[0]
        or b1[3] + slack < b2[1] or b2[3] + slack < b1[1]
    )


def merge_close_contours(contours, image_shape, min_touch=3, dilate_px=0):
    """B370: Gruppiert benachbarte Konturen TRANSITIV ueber Connected Components.

    Vorher wurde nur gegen die jeweilige Startkontur `cnt1` geprueft. Damit war das
    Ergebnis reihenfolgeabhaengig: bei A-B, B-C, aber nicht A-C entstand je nach
    OpenCV-Konturreihenfolge {A,B}+{C} oder {A,B,C}. Konsequenz waren fluktuierende
    Aussenkonturen zwischen zwei Frames und dadurch ID-Switches im Tracking.

    Jetzt: alle Paarbeziehungen bilden einen Graphen, dessen Zusammenhangskomponenten
    per Union-Find bestimmt werden. Das Ergebnis ist per Konstruktion invariant gegen
    die Eingabereihenfolge.

    Die Buffer-Union-Unbuffer-Semantik aus B276 bleibt unveraendert erhalten.
    """
    n = len(contours)
    if n == 0:
        return []

    parent = list(range(n))
    rank = [0] * n
    bboxes = [_bbox_of(c) for c in contours]
    # Puffer: beide Konturraender werden je um dilate_px dilatiert -> 2*dilate_px
    # plus 1px Toleranz fuer die Rasterisierung der Konturlinie selbst.
    slack = 2 * int(dilate_px) + 1

    for i in range(n):
        for j in range(i + 1, n):
            if _uf_find(parent, i) == _uf_find(parent, j):
                continue  # bereits in derselben Komponente -> Maskenvergleich sparen
            if not _bboxes_can_touch(bboxes[i], bboxes[j], slack):
                continue
            if are_contours_touching_edges(
                contours[i], contours[j], image_shape,
                min_touch=min_touch, dilate_px=dilate_px,
            ):
                _uf_union(parent, rank, i, j)

    components = {}
    for i in range(n):
        components.setdefault(_uf_find(parent, i), []).append(i)

    merged = []
    # Deterministische Ausgabereihenfolge: nach kleinstem Member-Index der Komponente.
    for root in sorted(components, key=lambda r: min(components[r])):
        group = [contours[i] for i in sorted(components[root])]

        # B276 (Korrektur zu B274): are_contours_touching_edges() mit
        # dilate_px>0 kann zwei Konturen mit einer winzigen echten
        # Pixel-Luecke als "beruehrend" gruppieren -- unary_union() fuehrt
        # geometrisch getrennte Polygone deswegen aber noch NICHT zusammen
        # (liefert weiterhin ein MultiPolygon mit getrennten Teilen). Daher
        # hier dieselbe Pufferdistanz auch auf die Vereinigung anwenden
        # (Buffer-Union-Unbuffer, schliesst die Luecke wie eine morphologische
        # Closing-Operation im Polygon-Raum) und danach wieder zurueckschrumpfen.
        if dilate_px > 0 and len(group) > 1:
            _buffered = [Polygon(c[:, 0, :]).buffer(dilate_px, join_style=2) for c in group]
            merged_poly = unary_union(_buffered).buffer(-dilate_px, join_style=2)
        else:
            merged_poly = unary_union([Polygon(c[:, 0, :]) for c in group])
        if merged_poly.geom_type == 'MultiPolygon':
            for part in merged_poly.geoms:
                merged.append(np.array(part.exterior.coords, dtype=np.int32).reshape(-1, 1, 2))
        else:
            merged.append(np.array(merged_poly.exterior.coords, dtype=np.int32).reshape(-1, 1, 2))

    return merged


# ---------------------------------------------------------------------------
# P66: Multi-Core-Split — Hilfs- und Hauptfunktionen
# ---------------------------------------------------------------------------

def _detect_core_components(hsv, contour, core_hsv_ranges, min_area_px):
    """Findet räumlich getrennte Konvektionskerne (rot/violett) innerhalb
    einer Kontur und gibt sie als Liste von (cx, cy, area_px) zurück.
    Nur Kerne mit area_px >= min_area_px werden zurückgegeben.
    """
    h, w = hsv.shape[:2]
    cell_mask = np.zeros((h, w), dtype=np.uint8)
    cv2.drawContours(cell_mask, [contour], -1, 255, -1)

    core_mask = np.zeros((h, w), dtype=np.uint8)
    for lower, upper in core_hsv_ranges:
        cm = cv2.inRange(hsv, np.array(lower, dtype=np.uint8),
                              np.array(upper, dtype=np.uint8))
        core_mask |= cv2.bitwise_and(cm, cell_mask)

    n_labels, _, stats, centroids = cv2.connectedComponentsWithStats(
        core_mask, connectivity=8
    )
    result = []
    for i in range(1, n_labels):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area >= min_area_px:
            result.append((float(centroids[i][0]), float(centroids[i][1]), area))
    return result


def _core_path_gap_px(cell_mask, p1, p2, step_px=1.0):
    """B275: Laengster zusammenhaengender Abschnitt (px) auf der Verbindungslinie
    zwischen zwei Kern-Zentren, der AUSSERHALB der (bereits zusammengefuehrten)
    Zell-Maske liegt. 0.0 bedeutet: die Verbindung verlaeuft komplett innerhalb
    der Zell-Maske -- keine echte Luecke, sondern eine einzige zusammenhaengende
    Wetterstruktur (z. B. eine elongierte Boeenlinie mit mehreren Reflektivitaets-
    Maxima), die trotz mehrerer erkannter Kerne NICHT gesplittet werden darf.
    """
    x1, y1 = float(p1[0]), float(p1[1])
    x2, y2 = float(p2[0]), float(p2[1])
    length_px = _math_ot.hypot(x2 - x1, y2 - y1)
    if length_px <= 0:
        return 0.0
    h, w = cell_mask.shape[:2]
    n_samples = max(2, int(length_px / max(step_px, 0.1)) + 1)
    max_run = 0
    cur_run = 0
    for i in range(n_samples):
        t = i / (n_samples - 1)
        x = int(round(x1 + t * (x2 - x1)))
        y = int(round(y1 + t * (y2 - y1)))
        inside = 0 <= x < w and 0 <= y < h and cell_mask[y, x] > 0
        if inside:
            cur_run = 0
        else:
            cur_run += 1
            max_run = max(max_run, cur_run)
    return max_run * length_px / (n_samples - 1)


def _intensity_field(hsv, cell_mask):
    """B380: ORDNUNGSERHALTENDER Reflektivitaets-Proxy ueber die ARSO-Farbbaender.

    B376 nutzte v*s. Da alle Radarfarben vollgesaettigt sind (S~255, V~255), lieferte
    das fuer Orange (49 dBZ), Rot (54 dBZ) und Violett (57 dBZ) denselben Wert -- das
    Feld war innerhalb einer Zelle uniform und Watershed hatte keine Information.
    Belegt durch die B275-Regression: zwei rote Kerne ueber eine orange Bruecke
    verbunden liessen sich nicht trennen, obwohl das meteorologisch ein klarer
    Sattel ist.

    Die Skala ist NICHT monoton in Hue (Rot wrapt ueber 0/179, Violett liegt bei
    125-160), daher ein explizites Band-Mapping aus RADAR_DBZ_BANDS.

    Vektorisiert ueber numpy-Masken -- auf dem Pi 5 kein messbarer Mehraufwand
    gegenueber der alten Multiplikation.
    """
    bands = _rc.get("RADAR_DBZ_BANDS", _DEFAULT_RADAR_DBZ_BANDS)
    min_sat = int(_rc.get("RADAR_DBZ_MIN_SAT", 50))
    min_val = int(_rc.get("RADAR_DBZ_MIN_VAL", 60))

    h = hsv[:, :, 0]
    s = hsv[:, :, 1]
    v = hsv[:, :, 2]
    valid = (s >= min_sat) & (v >= min_val)

    field = np.zeros(hsv.shape[:2], dtype=np.uint8)
    for band in bands:
        hue_min, hue_max, proxy = int(band[0]), int(band[1]), float(band[2])
        sel = valid & (h >= hue_min) & (h <= hue_max)
        # np.maximum: ueberlappende Baender gewinnen mit dem hoeheren Proxy,
        # statt vom zuletzt geprueften Band ueberschrieben zu werden.
        np.maximum(field, np.uint8(round(proxy * 255.0)), out=field, where=sel)

    return cv2.bitwise_and(field, field, mask=cell_mask)


def _core_peak_intensity(field, cell_mask, center, radius=3):
    """B380: robustes Kernmaximum aus der Kernumgebung statt aus einem Einzelpixel.

    Der Zentrumspixel allein ist rauschanfaellig (JPEG-Artefakte, Farbraender).
    """
    h, w = field.shape[:2]
    cx, cy = int(round(center[0])), int(round(center[1]))
    x0, x1 = max(cx - radius, 0), min(cx + radius + 1, w)
    y0, y1 = max(cy - radius, 0), min(cy + radius + 1, h)
    if x0 >= x1 or y0 >= y1:
        return 0.0
    patch = field[y0:y1, x0:x1]
    mask_patch = cell_mask[y0:y1, x0:x1]
    vals = patch[mask_patch > 0]
    return float(vals.max()) if vals.size else 0.0


def _core_saddle_ratio(field, cell_mask, p1, p2, n_samples=64):
    """B376: Intensitaets-Sattel zwischen zwei Kernen (0..1).

    0.0 = kein Einschnitt (durchgehend starke Struktur, z. B. elongierte
    Boeenlinie mit mehreren Maxima -> NICHT splitten).
    1.0 = vollstaendige Trennung (Verbindung verlaeuft durch Nullintensitaet).

    Ersetzt die 2-Pixel-Luecken-Pruefung auf der Geraden, die auf reines
    Quantisierungs-/JPEG-Rauschen ansprach.
    """
    x1, y1 = float(p1[0]), float(p1[1])
    x2, y2 = float(p2[0]), float(p2[1])
    h, w = field.shape[:2]
    vals = []
    for i in range(n_samples):
        t = i / float(max(n_samples - 1, 1))
        x = int(round(x1 + t * (x2 - x1)))
        y = int(round(y1 + t * (y2 - y1)))
        if 0 <= x < w and 0 <= y < h:
            vals.append(0.0 if cell_mask[y, x] == 0 else float(field[y, x]))
        else:
            vals.append(0.0)
    if not vals:
        return 0.0
    # B380: Referenz ist das SCHWAECHERE der beiden Kernmaxima -- so beschreibt es
    # auch MULTI_CORE_MIN_SADDLE_RATIO. Mit dem staerkeren Endwert (vorher
    # `max(vals[0], vals[-1])`) wurde ein Nebenmaximum leichter als getrennt
    # eingestuft. Die Kernmaxima kommen robust aus der Kernumgebung statt aus
    # einem einzelnen, rauschanfaelligen Zentrumspixel.
    peak_1 = _core_peak_intensity(field, cell_mask, p1)
    peak_2 = _core_peak_intensity(field, cell_mask, p2)
    peak = min(peak_1, peak_2)
    if peak <= 1e-6:
        return 0.0
    valley = min(vals)
    return max(0.0, min(1.0, 1.0 - (valley / peak)))


def _geodesic_priority_assign(cell_mask, field, core_centers, max_iter_per_band=10000):
    """B383: Band-priorisierte geodaetische Multi-Source-Flutung.

    Ersetzt cv2.watershed(). Dessen Meyer-Algorithmus arbeitet auf Gradienten und
    versagt, wenn der Verbindungsweg in sich uniform ist -- der Normalfall bei einer
    durchgehend gleich starken Regenbruecke. Messung an der U-Form aus B275:
    cv2.watershed lieferte [3910, 342] px statt zweier ausgewogener Haelften; mit
    MULTI_CORE_MIN_CHILD_AREA_PX=800 fiel das zweite Kind heraus und der Split
    entfiel komplett.

    Verfahren (AINT-Prinzip, arXiv:2509.02929 -- geodaetische Expansion innerhalb
    der Ursprungsregion):
      1. Beginnend beim staerksten Intensitaetsband wachsen alle Marker gleichzeitig
         um 1 px pro Schritt, aber nur innerhalb des aktuellen Bandes.
      2. Erst wenn ein Band erschoepft ist, wird das naechstschwaechere freigegeben.

    Daraus folgen beide Eigenschaften ohne Sonderfaelle:
      - uniformer Verbindungsweg -> reine geodaetische Distanz, Grenze mittig,
        Hindernisse respektiert;
      - Intensitaetssattel vorhanden -> starke Bereiche zuerst beansprucht, Grenze
        landet im schwaechsten Bereich.

    Geodaetisch, nicht euklidisch: der Weg verlaeuft innerhalb der Maske. Genau das
    unterscheidet das Verfahren vom alten Voronoi, bei dem der Weg durch die Luft lief.
    """
    labels = np.zeros(cell_mask.shape[:2], dtype=np.int32)
    h, w = cell_mask.shape[:2]
    for idx, core in enumerate(core_centers, start=1):
        xi, yi = int(round(core[0])), int(round(core[1]))
        if 0 <= xi < w and 0 <= yi < h and cell_mask[yi, xi] > 0:
            labels[yi, xi] = idx
    if not labels.any():
        return labels

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    inside = cell_mask > 0
    # Absteigende Bandgrenzen: stark zuerst. Aus RADAR_DBZ_BANDS abgeleitet, damit
    # eine Aenderung der Farbskala nicht hier nachgezogen werden muss.
    bands = _rc.get("RADAR_DBZ_BANDS", _DEFAULT_RADAR_DBZ_BANDS)
    thresholds = sorted({int(round(float(b[2]) * 255.0)) for b in bands}, reverse=True)
    thresholds.append(0)   # Restflaeche (z. B. Antialiasing-Raender) zuletzt

    for lo in thresholds:
        region = inside & (field >= lo)
        for _ in range(max_iter_per_band):
            free = region & (labels == 0)
            if not free.any():
                break
            grown = cv2.dilate(labels.astype(np.uint8), kernel)
            take = free & (grown > 0)
            if not take.any():
                break   # dieses Band ist von keinem Marker aus erreichbar
            labels[take] = grown[take]
    return labels


def _watershed_split(hsv, contour, core_centers, min_child_area_px):
    """B383: Marker-gesteuerte geodaetische Priority-Flutung.

    Vorher wurde jeder Pixel der gesamten Aussenkontur dem euklidisch naechsten
    Kernzentrum zugeordnet. Das erzeugte gerade/keilfoermige Grenzen, die quer
    durch starke rote/violette Flaechen schnitten, und liess den Schwerpunkt bei
    minimalen Markerbewegungen springen.

    Die Grenzen folgen nun den Reflektivitaetsbaendern: starke Kernbereiche werden
    zuerst beansprucht, schwaechere Verbindungen erst danach. In uniformen
    Verbindungswegen bleibt eine reine geodaetische Distanz innerhalb der Maske.
    """
    h, w = hsv.shape[:2]
    cell_mask = np.zeros((h, w), dtype=np.uint8)
    cv2.drawContours(cell_mask, [contour], -1, 255, -1)
    if cv2.countNonZero(cell_mask) == 0:
        return [contour]

    field = _intensity_field(hsv, cell_mask)
    markers = _geodesic_priority_assign(cell_mask, field, core_centers)

    result_contours = []
    for idx in range(1, len(core_centers) + 1):
        region_mask = np.zeros((h, w), dtype=np.uint8)
        region_mask[markers == idx] = 255
        # B383: kein Watershed-Grenzpixel (-1) mehr -- die geodaetische Flutung
        # weist jeden erreichbaren Pixel genau einem Marker zu. Der frueher noetige
        # Flaechenverlust an der Wasserscheide entfaellt.
        region_mask = cv2.bitwise_and(region_mask, cell_mask)
        region_cnts, _ = cv2.findContours(region_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not region_cnts:
            continue
        largest = max(region_cnts, key=cv2.contourArea)
        if cv2.contourArea(largest) >= min_child_area_px:
            result_contours.append(largest.astype(np.int32))

    if len(result_contours) < 2:
        return [contour]
    return result_contours


def _voronoi_split(hsv_shape, contour, core_centers, min_child_area_px):
    """DEPRECATED (B376): nur noch als Notfall-Fallback, wenn Watershed scheitert.

    Rein euklidische Zuweisung ohne Bezug zum Intensitaetsfeld -- erzeugt
    kuenstliche Teilgrenzen. Nicht mehr im regulaeren Pfad.
    """
    h, w = hsv_shape[:2]
    cell_mask = np.zeros((h, w), dtype=np.uint8)
    cv2.drawContours(cell_mask, [contour], -1, 255, -1)

    ys, xs = np.where(cell_mask > 0)
    if len(xs) == 0:
        return [contour]

    pixel_xy = np.column_stack([xs, ys]).astype(np.float32)
    centers = np.array([[cx, cy] for cx, cy, _ in core_centers], dtype=np.float32)

    diffs = pixel_xy[:, np.newaxis, :] - centers[np.newaxis, :, :]
    sq_dists = (diffs ** 2).sum(axis=2)
    assignments = np.argmin(sq_dists, axis=1)

    result_contours = []
    for idx in range(len(core_centers)):
        region_mask = np.zeros((h, w), dtype=np.uint8)
        sel = pixel_xy[assignments == idx].astype(np.int32)
        if len(sel) == 0:
            continue
        region_mask[sel[:, 1], sel[:, 0]] = 255

        region_cnts, _ = cv2.findContours(
            region_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        if not region_cnts:
            continue
        largest = max(region_cnts, key=cv2.contourArea)
        if cv2.contourArea(largest) >= min_child_area_px:
            result_contours.append(largest.astype(np.int32))

    if len(result_contours) < 2:
        return [contour]
    return result_contours


# ── P66: Multi-Core-Split ───────────────────────────────────────────────────
def split_multi_core_contours(contours, hsv):
    """Analysiert Konturen auf mehrere getrennte Konvektionskerne und splittet sie."""
    if not _rc.get("MULTI_CORE_SPLIT_ENABLED", True):
        return contours

    min_core_area = int(_rc.get("MULTI_CORE_MIN_CORE_AREA_PX", 80))
    min_dist_px = float(_rc.get("MULTI_CORE_MIN_DIST_PX", 15.0))
    min_child_area = int(_rc.get("MULTI_CORE_MIN_CHILD_AREA_PX", 800))
    min_gap_px = float(_rc.get("MULTI_CORE_MIN_GAP_PX", 2.0))
    core_hsv_ranges = _rc.get("CORE_HSV_RANGES", _DEFAULT_CORE_HSV_RANGES)

    result = []
    for contour in contours:
        cores = _detect_core_components(hsv, contour, core_hsv_ranges, min_core_area)
        if len(cores) < 2:
            result.append(contour)
            continue

        # B275: Aeussere Zell-Maske (wie nach merge_close_contours) fuer die
        # Verbindungs-Pruefung zwischen Kern-Paaren.
        cell_mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
        cv2.drawContours(cell_mask, [contour], -1, 255, -1)

        # B376: Split-Freigabe ueber einen INTENSITAETSSATTEL statt einer 2-px-
        # Luecke auf der Geraden. Zwei Pixel koennen reines Quantisierungs- oder
        # JPEG-Farbrauschen sein; ausserdem ist die Gerade kein topologisch
        # robuster Trennpfad (eine gekruemmte Verbindung wird nicht gesehen).
        # Zusaetzlich: ALLE Kernpaare muessen den Sattel erfuellen -- bisher gab
        # ein einziges geeignetes Paar den gesamten Mehrkernkomplex frei.
        _field = _intensity_field(hsv, cell_mask)
        _min_saddle = float(_rc.get("MULTI_CORE_MIN_SADDLE_RATIO", 0.35))
        _pairs_checked = 0
        _pairs_ok = 0
        for i in range(len(cores)):
            for j in range(i + 1, len(cores)):
                dx = cores[i][0] - cores[j][0]
                dy = cores[i][1] - cores[j][1]
                if _math_ot.sqrt(dx * dx + dy * dy) < min_dist_px:
                    continue
                _pairs_checked += 1
                _saddle = _core_saddle_ratio(_field, cell_mask, cores[i][:2], cores[j][:2])
                _gap_px = _core_path_gap_px(cell_mask, cores[i][:2], cores[j][:2])
                # Echte Luecke ODER ausgepraegter Intensitaetseinschnitt.
                if _saddle >= _min_saddle or _gap_px >= min_gap_px:
                    _pairs_ok += 1

        # Alle geprueften Paare muessen trennbar sein. Eine elongierte Boeenlinie
        # mit mehreren Maxima ohne Sattel bleibt damit EINE Zelle.
        eligible = _pairs_checked > 0 and _pairs_ok == _pairs_checked

        if not eligible:
            result.append(contour)
            continue

        try:
            sub_contours = _watershed_split(hsv, contour, cores, min_child_area)
        except Exception as _ws_exc:
            debug_log(f"[B376] Watershed fehlgeschlagen, Voronoi-Fallback: {_ws_exc}")
            sub_contours = _voronoi_split(hsv.shape, contour, cores, min_child_area)
        result.extend(sub_contours)
        if len(sub_contours) > 1:
            debug_log(
                f"[P66] Multi-Core-Split: {len(cores)} Kerne → "
                f"{len(sub_contours)} Sub-Zellen"
            )

    return result


# ---------------------------------------------------------------------------
# HitL — Filter-Config-Wrapper
# ---------------------------------------------------------------------------
# Liest "allowed_hsv_ranges" aus cell_filters.json (Single Source of Truth).
# Fällt bei Fehlern oder leerer Liste auf das alte Verhalten zurück, damit das
# Tracking nie ohne Filter läuft. min_object_area und border_mask_px kommen
# weiterhin aus runtime_config (globale Morphologie-Schwellwerte).
def _get_filter_config_live() -> dict:
    base = dict(_rc.get("FILTER_CONFIG", _DEFAULT_FILTER_CONFIG))
    try:
        from cell_filters import get_active_hsv_ranges
        live_ranges = get_active_hsv_ranges()
        if live_ranges:
            base["allowed_hsv_ranges"] = live_ranges
        # else: kein Override → behält FILTER_CONFIG aus runtime_config/Default
    except Exception as _exc:
        # Komplettes Fallback auf altes Verhalten — Tracking läuft weiter.
        try:
            from debug_utils import debug_log
            debug_log(f"[FILTER] cell_filters nicht verfügbar, "
                      f"benutze runtime_config: {_exc}")
        except Exception:
            pass
    return base


def preprocess_image(image_path):
    FILTER_CONFIG = _get_filter_config_live()
    CORE_HSV_RANGES = _rc.get("CORE_HSV_RANGES", _DEFAULT_CORE_HSV_RANGES)
    # Bild mit geo-zuschnitt & hochskalierung laden
    # Fix #4: Runtime-BBOX aus Admin-Panel (Fallback: config.py)
    from config import BBOX_KAERNTEN_EXTENDED as _DEFAULT_BBOX_PP
    _bbox_pp = _validate_bbox(
        _rc.get("BBOX_KAERNTEN_EXTENDED", _DEFAULT_BBOX_PP),
        _DEFAULT_BBOX_PP,
    )
    processed_img = crop_and_upscale_to_bbox(image_path, _bbox_pp, UPSCALE_FACTOR)
    hsv = cv2.cvtColor(processed_img, cv2.COLOR_BGR2HSV)

    mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
    for lower, upper in FILTER_CONFIG["allowed_hsv_ranges"]:
        mask |= cv2.inRange(hsv, np.array(lower), np.array(upper))

    # Morphologisches Closing — identisch mit detect_and_track_objects()
    _close_size = int(_rc.get("MORPH_CLOSE_SIZE", 7))
    kernel = np.ones((_close_size, _close_size), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    merged = merge_close_contours(
        contours, hsv.shape[:2], min_touch=MIN_CONTOUR_TOUCH, dilate_px=MERGE_TOUCH_DILATE_PX
    )
    return hsv, merged, mask
    

def build_rain_support_mask(hsv) -> np.ndarray:
    """Erzeugt aus dem bereits geladenen ARSO-HSV-Bild eine Regenstützungsmaske.

    Enthalten sind stratiforme Regenfarben plus aktive Zellfarben. Es werden
    ausschließlich vorhandene Bilddaten genutzt; die Funktion löst keine
    Netzwerk-/Fremdrequests aus.
    """
    filter_config = _get_filter_config_live()
    try:
        from config import STRATIFORM_HSV_RANGES as _STRAT_RANGES
    except Exception:
        _STRAT_RANGES = []
    mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
    for lower, upper in list(_STRAT_RANGES) + list(filter_config.get("allowed_hsv_ranges", [])):
        mask |= cv2.inRange(
            hsv,
            np.array(lower, dtype=np.uint8),
            np.array(upper, dtype=np.uint8),
        )
    close_size = max(1, min(int(_rc.get("INACTIVE_RAIN_SUPPORT_CLOSE_SIZE", 3)), 5))
    kernel = np.ones((close_size, close_size), np.uint8)
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)


def _timestamp_age_min(inactive_since, timestamp) -> float:
    try:
        if inactive_since is None:
            return 0.0
        if isinstance(inactive_since, (int, float)):
            import time as _time_mod
            return max(0.0, (_time_mod.time() - float(inactive_since)) / 60.0)
        from datetime import datetime as _dt
        fmt = "%Y-%m-%d_%H-%M-%S"
        return max(0.0, (_dt.strptime(str(timestamp), fmt) - _dt.strptime(str(inactive_since), fmt)).total_seconds() / 60.0)
    except Exception:
        return 0.0


def find_rain_support_for_track(old_obj, rain_support_mask, pred_centroid, pred_polygon=None) -> dict:
    """Prüft Regenstützung um eine vorhergesagte Track-Position in skalierten Pixeln."""
    result = {
        "supported": False, "support_pixels": 0, "support_overlap": 0.0,
        "support_cx": None, "support_cy": None,
    }
    if rain_support_mask is None or pred_centroid is None:
        return result
    try:
        h, w = rain_support_mask.shape[:2]
        cx, cy = float(pred_centroid[0]), float(pred_centroid[1])
        if not (0 <= cx < w and 0 <= cy < h):
            return result
        try:
            from config import (
                INACTIVE_RAIN_SUPPORT_MIN_PIXELS as _MIN_PX,
                INACTIVE_RAIN_SUPPORT_RADIUS_PX as _RAD,
                INACTIVE_RAIN_SUPPORT_MIN_OVERLAP as _MIN_OV,
                INACTIVE_RAIN_SUPPORT_MAX_DISTANCE_PX as _MAX_D,
            )
        except Exception:
            _MIN_PX, _RAD, _MIN_OV, _MAX_D = 30, 60, 0.05, 90
        min_px = int(_rc.get("INACTIVE_RAIN_SUPPORT_MIN_PIXELS", _MIN_PX))
        radius = int(_rc.get("INACTIVE_RAIN_SUPPORT_RADIUS_PX", _RAD))
        min_overlap = float(_rc.get("INACTIVE_RAIN_SUPPORT_MIN_OVERLAP", _MIN_OV))
        max_dist = float(_rc.get("INACTIVE_RAIN_SUPPORT_MAX_DISTANCE_PX", _MAX_D))
        roi_mask = np.zeros((h, w), dtype=np.uint8)
        cv2.circle(roi_mask, (int(round(cx)), int(round(cy))), max(1, radius), 255, -1)
        rain_roi = cv2.bitwise_and(rain_support_mask, rain_support_mask, mask=roi_mask)
        support_pixels = int(cv2.countNonZero(rain_roi))
        overlap = 0.0
        if pred_polygon is not None:
            poly_mask = np.zeros((h, w), dtype=np.uint8)
            pts = np.array(list(pred_polygon.exterior.coords), dtype=np.int32).reshape(-1, 1, 2)
            cv2.drawContours(poly_mask, [pts], -1, 255, -1)
            poly_area = max(1, int(cv2.countNonZero(poly_mask)))
            overlap = cv2.countNonZero(cv2.bitwise_and(rain_support_mask, rain_support_mask, mask=poly_mask)) / float(poly_area)
        moments = cv2.moments(rain_roi)
        sx = sy = None
        if moments["m00"]:
            sx = moments["m10"] / moments["m00"]
            sy = moments["m01"] / moments["m00"]
        dist_ok = sx is None or _math.hypot(float(sx) - cx, float(sy) - cy) <= max_dist
        supported = dist_ok and (support_pixels >= min_px or overlap >= min_overlap)
        result.update({
            "supported": bool(supported),
            "support_pixels": support_pixels,
            "support_overlap": float(overlap),
            "support_cx": sx,
            "support_cy": sy,
        })
    except Exception as exc:
        debug_log(f"[TRACK] Regenstützung fehlgeschlagen: {exc}")
    return result

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
    """Liefert Kernanteil plus absolute Kern-/Zellpixel.

    Rückgabe bleibt über den Schlüssel ``core_ratio`` kompatibel; Aufrufer, die
    nur den numerischen Anteil benötigen, können diesen Wert verwenden.

    P72: Zusaetzlich core_violet_ratio (Anteil NUR der Baender mit
    Hue in [CORE_VIOLET_HUE_MIN, CORE_VIOLET_HUE_MAX], d.h. >=57 dBZ statt nur
    >=54 dBZ) - staerkstes rein radarbasiertes Hagelsignal, bisher nicht
    separat erfasst.
    """
    CORE_HSV_RANGES = _rc.get("CORE_HSV_RANGES", _DEFAULT_CORE_HSV_RANGES)
    mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
    cv2.drawContours(mask, [contour], -1, 255, -1)
    core_mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
    violet_mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
    for lower, upper in CORE_HSV_RANGES:
        range_mask = cv2.inRange(hsv, np.array(lower), np.array(upper))
        range_mask = cv2.bitwise_and(range_mask, range_mask, mask=mask)
        core_mask |= range_mask

        # B325 (Codex-Review zu P72): Overlap mit dem Violett-Hue-Fenster
        # berechnen statt nur lower[0] zu pruefen. Erweitert ein Operator ueber
        # /api/thresholds ein Band so, dass es teilweise in [CORE_VIOLET_HUE_MIN,
        # CORE_VIOLET_HUE_MAX] hineinreicht, aber mit einer Untergrenze UNTER
        # CORE_VIOLET_HUE_MIN beginnt, wuerde "lower[0] >= CORE_VIOLET_HUE_MIN"
        # das gesamte Band verwerfen - auch den echten Violett-Anteil. Der
        # Hue-Bereich des Bands wird deshalb auf das Violett-Fenster geklammert;
        # nur der ueberlappende Hue-Teilbereich (bei unveraenderten S/V-Grenzen
        # des Bands) zaehlt zu core_violet_ratio.
        violet_hue_lo = max(lower[0], CORE_VIOLET_HUE_MIN)
        violet_hue_hi = min(upper[0], CORE_VIOLET_HUE_MAX)
        if violet_hue_lo <= violet_hue_hi:
            violet_lower = [violet_hue_lo, lower[1], lower[2]]
            violet_upper = [violet_hue_hi, upper[1], upper[2]]
            violet_range_mask = cv2.inRange(hsv, np.array(violet_lower), np.array(violet_upper))
            violet_range_mask = cv2.bitwise_and(violet_range_mask, violet_range_mask, mask=mask)
            violet_mask |= violet_range_mask
    core_pixels = int(cv2.countNonZero(core_mask))
    violet_pixels = int(cv2.countNonZero(violet_mask))
    total_pixels = int(cv2.countNonZero(mask))
    core_ratio = core_pixels / total_pixels if total_pixels > 0 else 0.0
    core_violet_ratio = violet_pixels / total_pixels if total_pixels > 0 else 0.0
    return {
        "core_ratio": float(core_ratio),
        "core_violet_ratio": float(core_violet_ratio),
        "core_area_px": float(core_pixels),
        "cell_area_px": float(total_pixels),
        "core_pixels": int(core_pixels),
        "total_pixels": int(total_pixels),
        "core_violet_pixels": int(violet_pixels),
    }


# ── P-M03: Merge-bewusste Tendenz-Basislinien (rein, testbar) ───────────────
def _merge_prev_area(parents, previous_snapshot):
    """Summe der Flächen aller Parent-Zellen (Merge-Basislinie für size_trend).
    None, wenn keine gültige Fläche vorliegt."""
    total = 0.0
    for pid in (parents or []):
        p = previous_snapshot.get(pid)
        if p:
            total += float(p.get("area") or 0.0)
    return total if total > 0.0 else None


def _merge_prev_core(parents, previous_snapshot):
    """Flächengewichtetes Mittel der core_ratio aller Parents (Merge-Basislinie
    für trend). None, wenn keine gültige Fläche/core_ratio vorliegt."""
    w_core = 0.0
    w_sum = 0.0
    for pid in (parents or []):
        p = previous_snapshot.get(pid)
        if not p:
            continue
        pa = float(p.get("area") or 0.0)
        if pa > 0.0 and "core_ratio" in p:
            w_core += float(p["core_ratio"]) * pa
            w_sum += pa
    return (w_core / w_sum) if w_sum > 0.0 else None


def _intensity_trend_vs_baseline(core_ratio, prev_core, delta=0.05, *, area=None, prev_area=None, core_area=None, prev_core_area=None):
    """+1 / -1 / 0 anhand absoluter Kernfläche, nicht nur core_ratio."""
    if prev_core is None:
        return 0
    delta_core_ratio = float(core_ratio) - float(prev_core)
    delta_area_pct = ((float(area) - float(prev_area)) / float(prev_area)) if prev_area else None
    if prev_core_area is not None and float(prev_core_area) == 0.0:
        delta_core_area_pct = float("inf") if float(core_area or 0.0) > 0.0 else 0.0
    else:
        delta_core_area_pct = ((float(core_area) - float(prev_core_area)) / float(prev_core_area)) if prev_core_area else None
    if delta_core_area_pct is not None:
        if (delta_core_area_pct > TENDENCY_CORE_AREA_PCT_STABLE and
                (delta_area_pct is None or delta_area_pct >= TENDENCY_CONTRADICTION_AREA_SHRINK_PCT)):
            return 1
        if delta_core_area_pct < -TENDENCY_CORE_AREA_PCT_STABLE:
            return -1
        if (delta_core_ratio > delta and delta_area_pct is not None and
                delta_area_pct < TENDENCY_CONTRADICTION_AREA_SHRINK_PCT):
            return 0
    if delta_core_ratio > delta:
        return 1
    if delta_core_ratio < -delta:
        return -1
    return 0


def _core_trend_detail(core_ratio, prev_core, area, prev_area, core_area, prev_core_area):
    delta_core_ratio = (float(core_ratio) - float(prev_core)) if prev_core is not None else 0.0
    delta_area_pct = ((float(area) - float(prev_area)) / float(prev_area)) if prev_area else 0.0
    delta_core_area_pct = ((float(core_area) - float(prev_core_area)) / float(prev_core_area)) if prev_core_area else 0.0
    is_compact = (
        delta_core_ratio > TENDENCY_COMPACT_CORE_RATIO_DELTA
        and delta_area_pct < TENDENCY_CONTRADICTION_AREA_SHRINK_PCT
        and delta_core_area_pct <= TENDENCY_CORE_AREA_PCT_STABLE
    )
    return delta_core_ratio, delta_area_pct, delta_core_area_pct, is_compact


def _size_trend_vs_baseline(area, prev_area, pct_stable):
    """+1 / -1 / 0 anhand relativer Flächenänderung zur Basislinie."""
    if not prev_area or prev_area <= 0.0:
        return 0
    pct = (float(area) - prev_area) / prev_area
    if pct > pct_stable:
        return 1
    if pct < -pct_stable:
        return -1
    return 0


def _new_kalman_filter(cx, cy, vx=0.0, vy=0.0):
    """Erzeugt einen Tracking-KalmanFilter mit den Standardmatrizen.

    x/y/vx/vy sind ORIGINAL-px pro Frame und damit identisch zu den Einheiten,
    die update_tracking_memory() in kf.x verwendet.
    """
    kf = KalmanFilter(dim_x=4, dim_z=2)
    kf.x = np.array([float(cx), float(cy), float(vx), float(vy)])
    kf.F = np.array([[1, 0, 1, 0], [0, 1, 0, 1], [0, 0, 1, 0], [0, 0, 0, 1]])
    kf.H = np.array([[1, 0, 0, 0], [0, 1, 0, 0]])
    kf.P = np.eye(4) * 500
    kf.R = np.eye(2) * 10
    kf.Q = np.array([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0.5, 0], [0, 0, 0, 0.5]])
    return kf


def _is_valid_kalman_filter(kf) -> bool:
    """Minimal robuste Strukturprüfung für wiederverwendbare KalmanFilter."""
    if kf is None or not hasattr(kf, "predict") or not hasattr(kf, "update"):
        return False
    try:
        x = np.asarray(kf.x, dtype=float).reshape(-1)
        f = np.asarray(kf.F, dtype=float)
        h = np.asarray(kf.H, dtype=float)
        p = np.asarray(kf.P, dtype=float)
        r = np.asarray(kf.R, dtype=float)
        q = np.asarray(kf.Q, dtype=float)
    except Exception:
        return False
    return (
        x.shape[0] >= 4
        and f.shape == (4, 4)
        and h.shape == (2, 4)
        and p.shape == (4, 4)
        and r.shape == (2, 2)
        and q.shape == (4, 4)
    )


def _seed_velocity_from_snapshot(prev_obj, cx, cy, previous_snapshot):
    """Seedet vx/vy aus der letzten History, sonst aus Nachbarn, sonst 0/0.

    Die zurückgegebenen Werte bleiben ORIGINAL-px pro Frame — keine Umrechnung
    in px/min oder km/h.
    """
    if isinstance(prev_obj, dict):
        history = prev_obj.get("history")
        if isinstance(history, list) and history:
            last_entry = history[-1]
            if isinstance(last_entry, dict):
                try:
                    vx = float(last_entry.get("vx"))
                    vy = float(last_entry.get("vy"))
                    if np.isfinite(vx) and np.isfinite(vy):
                        return vx, vy
                except (TypeError, ValueError):
                    pass
    return _neighbor_motion_seed(cx, cy, previous_snapshot)


# ---------------------------------------------------------------------------
# B374: Helfer für die globale Datenassoziation
# ---------------------------------------------------------------------------
_last_tracking_timestamp = None
_KM_PER_DEG_LAT = 111.32
# B385: Pre-Frame-Zustand des letzten update_tracking_memory()-Laufs.
# cell_lineage darf die alten Parent-Objekte NICHT aus dem bereits ersetzten
# tracking_memory rekonstruieren -- dort traegt der Survivor bereits das
# verschmolzene Objekt und die Secondary-Parents fehlen.
last_previous_snapshot = {}
# B375: frameuebergreifender Kandidatenspeicher (Signatur -> frames_seen).
# Ein Uebergang gilt erst nach TRANSITION_CONFIRM_FRAMES konsistenten Frames
# als bestaetigt; bis dahin bleibt die Identitaet unveraendert.
_pending_transitions = {}


def _parse_ts(ts):
    """Robuste Timestamp-Parsung über die im Projekt verwendeten Formate."""
    if not ts:
        return None
    for fmt in ("%Y-%m-%d_%H-%M-%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y%m%d_%H%M%S"):
        try:
            return datetime.strptime(str(ts), fmt)
        except ValueError:
            continue
    return None


def _tracking_dt_minutes(timestamp):
    """B374: TATSAECHLICHER Zeitabstand zum letzten Tracking-Lauf in Minuten.

    Der bisherige Stage-2-Cap unterstellte implizit einen festen 5-Minuten-Takt.
    Bei Radarluecken (10/15 min) war er dadurch zu eng, im Normalbetrieb zu weit.
    Fallback 5.0 nur beim allerersten Lauf oder unparsbarem Timestamp.
    """
    global _last_tracking_timestamp
    now = _parse_ts(timestamp)
    prev = _parse_ts(_last_tracking_timestamp)
    dt = 5.0
    if now is not None and prev is not None:
        delta = (now - prev).total_seconds() / 60.0
        if 0.5 <= delta <= 60.0:
            dt = float(delta)
        else:
            debug_log(f"[B374] dt={delta:.1f}min ausserhalb [0.5,60] — Fallback 5.0min")
    if now is not None:
        _last_tracking_timestamp = timestamp
    return dt


def _latlon_to_km(lat, lon):
    """Lokale, aequidistante Projektion für Kärnten. Ausreichend für Gate-Distanzen."""
    return (float(lon) * _KM_PER_DEG_LAT * _math_ot.cos(_math_ot.radians(float(lat))),
            float(lat) * _KM_PER_DEG_LAT)


def _is_within_bbox_values(lat, lon, bbox):
    return (
        bbox["south"] <= lat <= bbox["north"] and
        bbox["west"] <= lon <= bbox["east"]
    )


def _build_detection_candidate(c_idx, contour, hsv, bbox_live, filter_config):
    """B374: Kontur → DetectionCandidate. Filter IDENTISCH zur Hauptschleife.

    Wichtig: Wenn hier andere Filter griffen als unten, verschöben sich die
    Indizes und die globale Zuordnung liefe ins Leere.
    """
    from tracking.association import DetectionCandidate
    M = cv2.moments(contour)
    if M["m00"] == 0:
        return None
    cx_f = M["m10"] / M["m00"]
    cy_f = M["m01"] / M["m00"]
    area, _ = calculate_shape_features(contour)
    core_info = calculate_core_ratio(hsv, contour)
    core_ratio = float(core_info.get("core_ratio", 0.0) or 0.0) if isinstance(core_info, dict) else float(core_info or 0.0)
    if area < filter_config["min_object_area"] and core_ratio < 0.05:
        return None
    lat, lon = pixel_to_geo(cx_f, cy_f)
    if _is_in_exclusion_zone(lat, lon, _rc.get("STATIC_EXCLUSION_ZONES", _DEFAULT_EXCLUSION_ZONES)):
        return None
    if not _is_within_bbox_values(lat, lon, bbox_live):
        return None
    x_km, y_km = _latlon_to_km(lat, lon)
    try:
        poly = Polygon(contour[:, 0, :])
    except Exception:
        poly = None
    return DetectionCandidate(index=c_idx, x_km=x_km, y_km=y_km,
                              area_px=float(area), core_ratio=core_ratio, polygon=poly)


def _build_track_candidates(previous_snapshot, pred_polys, pred_centroids):
    """B374: previous_snapshot → TrackCandidate-Liste in km/kmh."""
    from tracking.association import TrackCandidate
    out = []
    for oid, obj in (previous_snapshot or {}).items():
        if not isinstance(obj, dict):
            continue
        lat, lon = obj.get("lat"), obj.get("lon")
        if lat is None or lon is None:
            continue
        x_km, y_km = _latlon_to_km(lat, lon)
        try:
            from config import PX_TO_KMH as _P2K
        except Exception:
            _P2K = 4.0
        # kf.x[2]/[3] sind Original-px pro Frame → km/h über PX_TO_KMH.
        vx_kmh = float(obj.get("vx", 0.0) or 0.0) * float(_P2K)
        vy_kmh = float(obj.get("vy", 0.0) or 0.0) * float(_P2K)
        out.append(TrackCandidate(
            track_id=str(oid), pred_x_km=x_km, pred_y_km=y_km,
            vx_kmh=vx_kmh, vy_kmh=-vy_kmh,   # Bildkoordinaten y wächst nach Süden
            area_px=float(obj.get("area", 0.0) or 0.0),
            core_ratio=float(obj.get("core_ratio", 0.0) or 0.0),
            age_frames=int(obj.get("total_active_frames", 0) or 0),
            missing=int(obj.get("missing", 0) or 0),
            polygon=pred_polys.get(oid),
        ))
    return out


def _resolve_origin_type(lineage, prev_obj):
    """B378: Herkunft einer Zelle als Dauerzustand (Carry-over ueber Frames).

    Regeln:
      - Ereignisframe (lineage merged/split): Herkunft wird NEU gesetzt.
      - Folgeframe (continued): Herkunft des Vorgaengers wird uebernommen.
      - Echte Neuzelle (new): "new".

    Ohne diese Fortschreibung waere origin_type nach B375 ab dem zweiten Frame
    immer "new", weil `lineage` dann "continued" lautet.
    """
    if lineage == "merged":
        return "created_by_merge"
    if lineage == "split":
        return "created_by_split"
    if lineage == "new":
        return "new"
    prev = prev_obj if isinstance(prev_obj, dict) else {}
    inherited = prev.get("origin_type")
    if inherited in ("created_by_merge", "created_by_split", "new"):
        return inherited
    return "new"


def _persist_association_diagnosis(result, timestamp, dt_minutes):
    """B374: Kandidaten, Kosten und Ablehnungsgründe pro Frame persistieren.

    Erfüllt das Abnahmekriterium „Exportierte Kandidaten-/Kosten-Diagnosen: 100 %
    der aktiven Frames“. Ohne diese Datei ist jede Fehlzuordnung im Nachhinein
    nicht rekonstruierbar.
    """
    try:
        from pathlib import Path
        import json as _json
        out_dir = Path(str(_rc.get("ASSOCIATION_DIAGNOSIS_DIR", "train_data/association")))
        out_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "timestamp": str(timestamp),
            "dt_minutes": round(float(dt_minutes), 2),
            "method": result.method,
            "matches": {str(k): v for k, v in result.matches.items()},
            "unmatched_detections": list(result.unmatched_detections),
            "unmatched_tracks": list(result.unmatched_tracks),
            "candidate_pairs": result.candidate_pairs,
            "cost_matrix": result.cost_matrix,
            "rejected_matches": result.rejected_matches,
        }
        (out_dir / f"{timestamp}.json").write_text(
            _json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        debug_log(f"[B374] Assoziations-Diagnose nicht geschrieben: {exc}")


def update_tracking_memory(hsv, contours, weather_data, timestamp, rain_support_mask=None):
    FILTER_CONFIG = _get_filter_config_live()
    # was_active-Schwellwert — runtime-überschreibbar über Admin-Panel
    from config import WAS_ACTIVE_CORE_RATIO_THRESHOLD as _WAT_CFG
    _was_active_threshold = float(_rc.get("WAS_ACTIVE_CORE_RATIO_THRESHOLD", _WAT_CFG))
    # Zeitbasiertes Hintergrund-Tracking: 30 Minuten unabhängig vom Loop-Intervall
    from config import INACTIVE_CELL_TRACK_DURATION_S as _ICTD_CFG
    _track_duration_s = float(_rc.get("INACTIVE_CELL_TRACK_DURATION_S", _ICTD_CFG))
    # F7-FIX: BBOX live aus runtime_config — Admin-Panel-Änderungen wirken sofort.
    from config import BBOX_KAERNTEN_EXTENDED as _DEFAULT_BBOX
    _BBOX_LIVE = _rc.get("BBOX_KAERNTEN_EXTENDED", _DEFAULT_BBOX)
    if rain_support_mask is None:
        rain_support_mask = build_rain_support_mask(hsv)
    try:
        from config import INACTIVE_RAIN_SUPPORT_ENABLED as _IRSE
    except Exception:
        _IRSE = True
    _rain_support_enabled = bool(_rc.get("INACTIVE_RAIN_SUPPORT_ENABLED", _IRSE))
    global tracking_memory
    # B385: unveraenderlicher Pre-Frame-Zustand fuer nachgelagerte Konsumenten
    # (cell_lineage). Muss VOR dem Ersetzen von tracking_memory gefuellt werden.
    global last_previous_snapshot
    objects = []
    new_memory = {}
    used_ids = set()

    def is_within_bbox(lat, lon, bbox):
        return (
            bbox["south"] <= lat <= bbox["north"] and
            bbox["west"] <= lon <= bbox["east"]
        )

    previous_snapshot = tracking_memory.copy()
    history_len = int(_rc.get("TRACK_HISTORY_LEN", 6))

    # ── 3-Stage-Matching-Strukturen ──────────────────────────────────────────
    # prev_polys:     (id, Polygon) an URSPRÜNGLICHER Position → Stage 3 + Merge-Fallback
    # pred_polys:     id → Polygon an KALMAN-VORHERGESAGTER Position → Stage 1
    # pred_centroids: id → (cx_skaliert, cy_skaliert) vorhergesagt → Stage 2
    # Wissenschaftliche Basis: SORT (Bewley et al. 2016), Enhanced TITAN (Han et al. 2009)
    # Kernidee: Kalman-Vorhersage schiebt altes Polygon an erwartete neue Position →
    # schnell bewegte Zellen haben hohen Overlap mit vorhergesagter statt mit alter Position.
    prev_polys     = []
    pred_polys     = {}
    pred_centroids = {}

    for prev_id, prev_obj in previous_snapshot.items():
        try:
            if prev_obj.get("missing", 0) > 10:
                continue
            _cnt_arr = np.array(prev_obj["contour"])
            if len(_cnt_arr) < 3:
                continue
            _orig_poly = Polygon(_cnt_arr)
            prev_polys.append((prev_id, _orig_poly))

            # Kalman-Verschiebung: vx/vy in ORIGINAL-px/Frame; Kontur in SKALIERTEN px.
            # → Versatz = vx * UPSCALE_FACTOR (skalierte Pixel).
            _vx_kf = float(prev_obj.get("vx", 0.0))
            _vy_kf = float(prev_obj.get("vy", 0.0))
            _dx_s  = _vx_kf * UPSCALE_FACTOR
            _dy_s  = _vy_kf * UPSCALE_FACTOR
            if abs(_dx_s) > 0.1 or abs(_dy_s) > 0.1:
                pred_polys[prev_id] = Polygon(_cnt_arr + np.array([_dx_s, _dy_s]))
            else:
                pred_polys[prev_id] = _orig_poly  # statisch: orig = pred

            # Vorhergesagter Schwerpunkt in skalierten Koordinaten
            _x_orig = float(prev_obj.get("x", 0.0))
            _y_orig = float(prev_obj.get("y", 0.0))
            pred_centroids[prev_id] = (
                (_x_orig + _vx_kf) * UPSCALE_FACTOR,
                (_y_orig + _vy_kf) * UPSCALE_FACTOR,
            )
        except Exception:
            continue

    # Max. Stage-2-Distanzschwelle: MAX_CELL_SPEED_KMH / PX_TO_KMH × UPSCALE × 1.5
    # B365: Für schwache/sterbende Zellen (core_ratio < was_active-Schwelle)
    # gilt ein engerer, ungepufferter Cap — verhindert Fehlzuordnung an
    # unabhängige, weiter entfernte Zellen bei fast aufgelöster Ursprungszelle.
    try:
        from config import (
            MAX_CELL_SPEED_KMH as _MSPD, PX_TO_KMH as _P2K_MATCH,
            STAGE2_WEAK_CELL_MAX_SPEED_KMH as _MSPD_WEAK,
        )
        _STAGE2_MAX_DIST = (_MSPD / _P2K_MATCH) * UPSCALE_FACTOR * 1.5
        _STAGE2_MAX_DIST_WEAK = (_MSPD_WEAK / _P2K_MATCH) * UPSCALE_FACTOR
    except Exception:
        _STAGE2_MAX_DIST = 80.0
        _STAGE2_MAX_DIST_WEAK = 30.0

    assigned_old_to_new = {}

    # ========================================================================
    # B374: globale 1:1-Zuordnung statt greedy Stage-1/2/3
    # ------------------------------------------------------------------------
    # Vorher entschied die OpenCV-Konturreihenfolge ueber die Zellidentitaet:
    # `for contour in contours` verarbeitete Konturen nacheinander und entfernte
    # vergebene IDs ueber used_ids aus allen folgenden Kandidatenlisten.
    # Gegenfall: X passt gut zu A und etwas schlechter zu B, Y passt nur zu A.
    # Greedy (X zuerst) -> X=A, Y=new. Global optimal -> X=B, Y=A.
    # Jetzt: alle zulaessigen Paare werden zuerst bewertet, dann wird EINMAL
    # global optimal zugeordnet (Hungarian).
    # ========================================================================
    _dt_minutes = _tracking_dt_minutes(timestamp)
    _detections = []
    _det_by_contour_idx = {}
    for _c_idx, _c in enumerate(contours):
        _det = _build_detection_candidate(_c_idx, _c, hsv, _BBOX_LIVE, FILTER_CONFIG)
        if _det is None:
            continue          # identische Filter wie in der Hauptschleife
        _detections.append(_det)
        _det_by_contour_idx[_c_idx] = _det

    _track_candidates = _build_track_candidates(previous_snapshot, pred_polys, pred_centroids)

    try:
        from tracking.association import solve_global_assignment as _solve_assoc
        _assoc_result = _solve_assoc(
            _track_candidates, _detections,
            dt_minutes=_dt_minutes,
            max_speed_kmh=float(_rc.get("MAX_CELL_SPEED_KMH", 150.0)),
        )
        debug_log(
            f"[B374] Globale Zuordnung: {len(_assoc_result.matches)} Matches, "
            f"{len(_assoc_result.unmatched_detections)} neue Detektionen, "
            f"{len(_assoc_result.unmatched_tracks)} unmatched Tracks, dt={_dt_minutes:.1f}min"
        )
    except Exception as _assoc_exc:
        # Kein stiller Fallback auf greedy: das waere genau der Defekt, den B374
        # behebt. Ein leeres Ergebnis erzeugt ausschliesslich neue IDs -- das ist
        # im Debugexport sofort sichtbar statt unbemerkt falsch.
        debug_log(f"[B374] KRITISCH: globale Zuordnung fehlgeschlagen: {_assoc_exc}")
        from tracking.association import AssociationResult as _AR
        _assoc_result = _AR(method="failed")
        _assoc_result.unmatched_detections = [d.index for d in _detections]
        _assoc_result.unmatched_tracks = [t.track_id for t in _track_candidates]

    _persist_association_diagnosis(_assoc_result, timestamp, _dt_minutes)
    _unmatched_track_ids = set(_assoc_result.unmatched_tracks)

    # ========================================================================
    # B375: Merge/Split werden NACH dem globalen 1:1-Matching aus dem
    # verbleibenden bipartiten Ueberlappungsgraphen abgeleitet -- nicht mehr
    # frameweise waehrend der Schleife. Ein Uebergang wird erst nach
    # TRANSITION_CONFIRM_FRAMES konsistenten Frames bestaetigt.
    # ========================================================================
    global _pending_transitions
    _frame_transitions = {}
    # B381: signature -> {detection_index: obj_id}. Grundlage fuer children/
    # lineage_end der bestaetigten Splits (ersetzt den toten assigned_old_to_new-Pfad).
    _split_child_obj_ids = {}
    _confirmed_transitions = []
    try:
        from tracking.transition_resolver import (
            confirm_candidates, find_merge_candidates, find_split_candidates,
        )
        _unmatched_polys = {
            tid: pred_polys.get(tid) for tid in _unmatched_track_ids if pred_polys.get(tid) is not None
        }
        # B381: Der Split-Resolver braucht ALLE alten Tracks, auch 1:1-gematchte.
        # Bei A -> X + Y ordnet Hungarian A korrekterweise X zu; A waere in
        # _unmatched_polys nicht enthalten und der Split unsichtbar.
        _all_track_polys = {
            tid: poly for tid, poly in pred_polys.items() if poly is not None
        }
        _det_polys = {d.index: d.polygon for d in _detections if d.polygon is not None}
        # B387: Auch der Merge-Resolver braucht ALLE alten Tracks. Der Survivor
        # ist per Definition gematcht und fehlte in _unmatched_polys -- sein
        # Flaechenbeitrag wurde deshalb mit 0.0 gezaehlt, obwohl er den Merge
        # typischerweise dominiert.
        _cands = (
            find_merge_candidates(_all_track_polys, _det_polys, _assoc_result.matches)
            + find_split_candidates(_all_track_polys, _det_polys, _assoc_result.matches)
        )
        _confirmed, _still, _reverted, _pending_transitions = confirm_candidates(
            _cands, _pending_transitions
        )
        for _c in _confirmed + _still:
            for _child in _c.children:
                _frame_transitions[_child] = _c
        _confirmed_transitions = list(_confirmed)
        debug_log(
            f"[B375] Uebergaenge: {len(_confirmed)} bestaetigt, {len(_still)} Kandidaten, "
            f"{len(_reverted)} verworfen"
        )
    except Exception as _tr_exc:
        debug_log(f"[B375] Transition-Resolver fehlgeschlagen: {_tr_exc}")

    for _c_idx, contour in enumerate(contours):
        M = cv2.moments(contour)
        if M["m00"] == 0:
            continue
        # B209: Subpixel-Schwerpunkt — KEINE doppelte int()-Quantisierung mehr.
        # original_cx/cy (= obj["x"]/["y"]) sind jetzt subpixel-genaue Original-px (float).
        # Geschwindigkeit (Kalman/EWMA) und Forecast-Ursprung beruhen darauf; lat/lon kommt
        # aus denselben subpixel-genauen skalierten Koordinaten → konsistent (Prio-1 <1 km).
        cx_f = M["m10"] / M["m00"]              # skaliert, subpixel
        cy_f = M["m01"] / M["m00"]
        cx = int(round(cx_f))                  # nur für cv2/Index-Zwecke
        cy = int(round(cy_f))
        original_cx = cx_f / float(UPSCALE_FACTOR)   # Original-px, subpixel (float)
        original_cy = cy_f / float(UPSCALE_FACTOR)
        area, eccentricity = calculate_shape_features(contour)
        core_info = calculate_core_ratio(hsv, contour)
        if isinstance(core_info, dict):
            core_ratio = float(core_info.get("core_ratio", 0.0) or 0.0)
            core_area_px = float(core_info.get("core_area_px", core_info.get("core_pixels", 0.0)) or 0.0)
            cell_area_px = float(core_info.get("cell_area_px", core_info.get("total_pixels", 0.0)) or 0.0)
            core_violet_ratio = float(core_info.get("core_violet_ratio", 0.0) or 0.0)
        else:
            core_ratio = float(core_info or 0.0)
            cell_area_px = float(cv2.contourArea(contour) or area or 0.0)
            core_area_px = core_ratio * cell_area_px
            core_violet_ratio = 0.0
        if area < FILTER_CONFIG["min_object_area"] and core_ratio < 0.05:
            continue
        # pixel_to_geo erwartet SKALIERTE Koordinaten (teilt intern durch upscale).
        # B209: subpixel-genaue skalierte Koordinaten → lat/lon konsistent mit obj["x"]/["y"].
        lat, lon = pixel_to_geo(cx_f, cy_f)

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
        _cx_s = float(np.mean(contour[:, 0, 0]))
        _cy_s = float(np.mean(contour[:, 0, 1]))
        area_new = max(current_poly.area, 1e-6)

        # === B374: Ergebnis der GLOBALEN 1:1-Zuordnung ========================
        # Stage 1/2/3 sind ersatzlos entfallen. Die Zuordnung wurde bereits vor
        # dieser Schleife fuer ALLE Konturen gleichzeitig optimal geloest.
        # Der Score 1.0 markiert einen bestaetigten globalen 1:1-Match; die
        # tatsaechlichen Kosten stehen in der Diagnose (association_diagnosis).
        overlaps = []
        _global_match_id = _assoc_result.matches.get(_c_idx)
        if _global_match_id and _global_match_id not in used_ids:
            overlaps.append((_global_match_id, 1.0))

        # B374: Stage 2 (Centroid-Distanz in Pixeln) und Stage 3 (IoU mit
        # Originalposition) sind ersatzlos entfallen. Beide Faelle deckt die
        # globale Kostenmatrix vollstaendig ab:
        #   - Stage-2-Fall (starke Groessenaenderung + Bewegung): Kostenkomponente
        #     c_pos + c_area, gegatet ueber die Suchellipse in echten km.
        #   - Stage-3-Fall (statische Zelle, vx=vy=0): isotroper Suchkreis, da
        #     _search_radii_km() bei speed<1 km/h auf den engen Radius zurueckfaellt.
        # B365 (STAGE2_WEAK_CELL_MAX_SPEED_KMH) ist in den physikalischen Gates
        # aufgegangen und wird durch c_age/c_core verallgemeinert.

        _overlap_by_id = {oid: score for oid, score in overlaps}
        _old_area_by_id = {}
        for _oid_m, _opoly_m in prev_polys:
            if _oid_m in used_ids or _oid_m not in previous_snapshot:
                continue
            # B374: Ein Track, der bereits global 1:1 einer ANDEREN Detektion
            # zugeordnet wurde, darf hier nicht mehr als Merge-Parent auftauchen.
            # Genau das erzeugte bisher Scheinmerges: eine grosse Systemkontur
            # "sammelte" Parents ein, die in Wahrheit eigenstaendig weiterlebten.
            # Merge-Kandidaten sind ausschliesslich UNMATCHED alte Zellen.
            if _oid_m not in _unmatched_track_ids and _oid_m != _global_match_id:
                continue
            try:
                _old_area_m = max(float(_opoly_m.area), 1e-6)
                _inter_m = current_poly.intersection(_opoly_m).area
                _old_coverage_m = _inter_m / _old_area_m
            except Exception:
                continue
            _old_area_by_id[_oid_m] = _old_area_m
            if _old_coverage_m >= 0.30:
                # Score > 1 markiert bewusst die old-coverage-Semantik und
                # hält solche Parents in der Merge-Erkennung vor schwachen
                # Distanz-/IoU-Treffern, ohne die Continued-Logik zu ändern.
                _overlap_by_id[_oid_m] = max(
                    _overlap_by_id.get(_oid_m, 0.0),
                    1.0 + _old_coverage_m,
                )

        # B377: Primary-Scores EINMAL pro Kontur über die gemeinsame Policy
        # (tracking/primary_policy.py) berechnen — identisch zur Fachebene.
        _primary_scores = {}
        if len(_overlap_by_id) >= 2:
            try:
                from tracking.primary_policy import continuity_score as _cont_score
                from tracking.primary_policy import select_primary_parent as _select_primary_parent
                _cands = []
                _parent_objs = []
                for _oid_p in _overlap_by_id:
                    _po = previous_snapshot.get(_oid_p)
                    if isinstance(_po, dict):
                        _cands.append((_oid_p, _po))
                        _po_policy = dict(_po)
                        _po_policy["id"] = _oid_p
                        _parent_objs.append(_po_policy)
                _policy = str(_rc.get("CELL_LINEAGE_PRIMARY_MERGE_POLICY", "continuity_score"))
                _primary_parent = _select_primary_parent(
                    _parent_objs,
                    policy=_policy,
                    survivor_id=_global_match_id,
                    id_key="id",
                )
                _primary_oid = (_primary_parent or {}).get("id")
                if _primary_oid is not None:
                    _primary_scores[_primary_oid] = 1.0
                if _policy == "continuity_score":
                    _max_a = max((float(o.get("area", 0.0) or 0.0) for _, o in _cands), default=0.0)
                    _max_ca = max(
                        (float(o.get("core_area_px", 0.0) or 0.0)
                         or float(o.get("core_ratio", 0.0) or 0.0) * float(o.get("area", 0.0) or 0.0)
                         for _, o in _cands),
                        default=0.0,
                    )
                    for _oid_p, _po in _cands:
                        _primary_scores[_oid_p] = _cont_score(_po, max_area=_max_a, max_core_area=_max_ca)
            except Exception as _pp_exc:
                debug_log(f"[B377] Primary-Policy fehlgeschlagen, Score-Fallback: {_pp_exc}")
                _primary_scores = {}

        if _overlap_by_id:
            def _merge_sort_key(_item):
                _oid_s, _score_s = _item
                _old_area_s = _old_area_by_id.get(_oid_s)
                if _old_area_s is None:
                    _prev_poly_s = next(
                        (p for oid, p in prev_polys if oid == _oid_s),
                        None,
                    )
                    _old_area_s = (
                        float(_prev_poly_s.area)
                        if _prev_poly_s is not None
                        else 0.0
                    )
                if len(_overlap_by_id) >= 2:
                    # B377: Nicht mehr "groesste alte Flaeche gewinnt". Diese Regel
                    # war nirgends dokumentiert und widersprach der konfigurierten
                    # CELL_LINEAGE_PRIMARY_MERGE_POLICY. Bei einer zerfallenden
                    # Systemhuelle gewann die Flaeche statt des aktiven Kerns.
                    # Jetzt entscheidet dieselbe Policy wie auf der Fachebene.
                    _primary_s = _primary_scores.get(_oid_s, 0.0)
                else:
                    _primary_s = _score_s
                return (_primary_s, _score_s)

            overlaps = sorted(
                _overlap_by_id.items(),
                key=_merge_sort_key,
                reverse=True,
            )

        lineage = "new"
        parents = []
        best_id = None
        obj_id = None

        _transition = _frame_transitions.get(_c_idx)
        if (_transition is not None and _transition.phase == "confirmed"
                and _transition.kind == "split"):
            # B381: Bestaetigter Split. Vorher hatte die Schleife ueberhaupt keinen
            # Split-Zweig -- `len(overlaps) >= 2` ist fuer ein Split-Kind nie erfuellt,
            # jedes Kind hat hoechstens einen Parent. Bestaetigte Split-Kandidaten
            # blieben damit wirkungslos.
            _split_parent = _transition.parents[0]
            lineage = "split"
            parents = [_split_parent]
            if _transition.primary_child == _c_idx and _split_parent not in used_ids:
                # Primaeres Kind fuehrt die Parent-ID fort (AINT-Regel).
                obj_id = _split_parent
                best_id = _split_parent
            else:
                # Weitere Kinder erhalten neue IDs; best_id erhaelt den Parent,
                # damit Trend-/Kern-Carry-over die Herkunft nutzen kann.
                obj_id = generate_id()
                while obj_id in new_memory or obj_id in previous_snapshot:
                    obj_id = generate_id()
                best_id = _split_parent
            _split_child_obj_ids.setdefault(_transition.signature, {})[_c_idx] = obj_id

        elif _transition is not None and _transition.phase == "confirmed" and len(overlaps) >= 2:
            # B375: `merged` NUR im bestaetigten Ereignisframe. In Folgeframes ist
            # das Objekt `continued` -- auch wenn seine Herkunft ein Merge war.
            # Vorher meldete jeder Frame erneut ein Merge (23 Serien, bis 11 Frames).
            lineage = "merged"
            parents = [oid for oid, _ in overlaps]
            # B117: Merge-Zelle ERBT die ID des dominanten Parents (groesster
            # Parent nach alter Konturflaeche = overlaps[0]), sofern noch frei.
            # Erhaelt Track-Kontinuitaet
            # (Kalman/History/first_seen werden im Enrichment uebernommen).
            # Nur wenn kein Parent mehr frei ist -> neue ID (echtes Novum).
            _dominant = next((oid for oid, _ in overlaps if oid not in used_ids), None)
            if _dominant is not None and _dominant in previous_snapshot:
                obj_id = _dominant
                best_id = _dominant      # ermoeglicht Trend-Carry-over
            else:
                obj_id = generate_id()
            for merged_old_id in parents:
                if merged_old_id == obj_id:
                    continue              # dominanter Parent lebt als obj_id weiter
                old_obj = previous_snapshot.get(merged_old_id, {})
                old_obj["children"] = [obj_id]
                old_obj["lineage_end"] = f"merged_into:{obj_id}"
                # P-S01: Merge-Parent endet hier — Lifecycle-Datensatz schreiben.
                # write_track_end ist idempotent (_track_end_written), dadurch kein
                # Doppel-Log falls der Parent später auch die Missing-Schleife trifft.
                try:
                    from track_statistics import write_track_end as _wte_merge
                    _wte_merge(old_obj, f"merged_into:{obj_id}", timestamp)
                except Exception as _e_te3:
                    debug_log(f"[P-S01] track_end merge Fehler ({merged_old_id}): {_e_te3}")
                previous_snapshot[merged_old_id] = old_obj
                used_ids.add(merged_old_id)
        elif overlaps:
            # B382: IDENTITAET SOFORT, EREIGNIS VERZOEGERT.
            #
            # Vorher lautete die Bedingung `len(overlaps) == 1`. Im ERSTEN Frame eines
            # Merges hat overlaps aber bereits 2 Parents (Merge-Fallback), waehrend
            # _transition.phase noch "candidate" ist (TRANSITION_CONFIRM_FRAMES=2).
            # Damit griff KEIN Zweig: nicht der Split-Zweig, nicht der Merge-Zweig
            # (nicht confirmed) und nicht dieser (len != 1). obj_id blieb None und die
            # Zelle bekam unten eine NEUE ID -> bei JEDEM Merge brach die
            # ID-Kontinuitaet, inklusive Kalman-Zustand, Trend, Lebensdauer und
            # ML-Sequenz. Das globale Matching hatte den richtigen Parent laengst
            # gefunden (Laufzeitbeleg: matches={0:'VDEPFC5X'}, cost=0.377).
            #
            # Die Bestaetigung darf nur das EREIGNIS verzoegern, nicht die Identitaet:
            # der dominante Parent behaelt seine ID auch waehrend der Kandidatenphase.
            # `overlaps` ist bereits nach der Primary-Policy (B377) sortiert -- der
            # erste freie Eintrag ist der dominante Parent.
            _candidate_phase_dominant = next(
                (oid for oid, _ in overlaps if oid not in used_ids), None
            )
            if _candidate_phase_dominant is not None:
                best_id = _candidate_phase_dominant
                obj_id = _candidate_phase_dominant
                lineage = "continued"
                # Nur der fortgefuehrte Parent. Die vollstaendige Parentmenge wird
                # ausschliesslich im BESTAETIGTEN Merge-Ereignis gesetzt -- sonst
                # entstuende in der Kandidatenphase eine Merge-Lineage ohne Ereignis.
                parents = [_candidate_phase_dominant]
                if len(overlaps) >= 2:
                    debug_log(
                        f"[B382] Merge-Kandidat: {_candidate_phase_dominant} fuehrt ID fort "
                        f"({len(overlaps)} Parents, Phase="
                        f"{_transition.phase if _transition is not None else 'none'})"
                    )

        if obj_id and obj_id in previous_snapshot:
            used_ids.add(obj_id)
            prev_obj = previous_snapshot.get(obj_id, {})
            kf = prev_obj.get("kf") if isinstance(prev_obj, dict) else None
            if _is_valid_kalman_filter(kf):
                kf.predict()
                _prev_vx = float(kf.x[2])
                _prev_vy = float(kf.x[3])
                kf.update([original_cx, original_cy])
                _clamp_kalman_velocity(kf, _prev_vx, _prev_vy)
                vx, vy = kf.x[2], kf.x[3]
            else:
                _seed_vx, _seed_vy = _seed_velocity_from_snapshot(
                    prev_obj, original_cx, original_cy, previous_snapshot
                )
                kf = _new_kalman_filter(original_cx, original_cy, _seed_vx, _seed_vy)
                vx, vy = _seed_vx, _seed_vy
        else:
            if obj_id is None:
                obj_id = generate_id()
            # B172: Bewegungs-Seed statt Nullvektor (siehe _neighbor_motion_seed).
            _seed_vx, _seed_vy = _neighbor_motion_seed(
                original_cx, original_cy, previous_snapshot
            )
            kf = _new_kalman_filter(original_cx, original_cy, _seed_vx, _seed_vy)
            vx, vy = _seed_vx, _seed_vy

        # P-M03: Beim Merge gegen das flächengewichtete Mittel ALLER Parent-Kerne
        # vergleichen — nicht nur gegen den dominanten Parent (sonst Scheinverstärkung).
        if lineage == "merged":
            prev_core = _merge_prev_core(parents, previous_snapshot)
        elif best_id and best_id in previous_snapshot and "core_ratio" in previous_snapshot[best_id]:
            prev_core = previous_snapshot[best_id]["core_ratio"]
        else:
            prev_core = None
        # ── B92: Größen-Tendenz aus core_ratio-/Flächen-Verlauf (Fallback) ──
        # area-Vergleich gegen vorigen Frame → relative Flächenänderung.
        # P-M03: Beim Merge gegen die SUMME der Parent-Flächen vergleichen.
        if lineage == "merged":
            prev_area = _merge_prev_area(parents, previous_snapshot)
        elif best_id and best_id in previous_snapshot and "area" in previous_snapshot[best_id]:
            prev_area = float(previous_snapshot[best_id].get("area") or 0.0) or None
        else:
            prev_area = None
        size_trend = _size_trend_vs_baseline(area, prev_area, TENDENCY_AREA_PCT_STABLE)
        if lineage == "merged":
            prev_core_area = sum(float(previous_snapshot.get(pid, {}).get("core_area_px") or 0.0) for pid in (parents or [])) if parents else None
        elif best_id and best_id in previous_snapshot:
            prev_core_area = float(previous_snapshot[best_id].get("core_area_px") or 0.0)
        else:
            prev_core_area = None
        trend = _intensity_trend_vs_baseline(
            core_ratio, prev_core, delta=TENDENCY_CORE_DELTA_STABLE,
            area=area, prev_area=prev_area, core_area=core_area_px, prev_core_area=prev_core_area,
        )
        delta_core_ratio, delta_area_pct, delta_core_area_pct, is_compact = _core_trend_detail(
            core_ratio, prev_core, area, prev_area, core_area_px, prev_core_area
        )

        dem    = get_dem_features(lat, lon, vx=float(vx), vy=float(vy))
        valley = get_valley_features(lat, lon, vx=float(vx), vy=float(vy))
        strat  = compute_stratiform_environment(
            hsv, contour, vx=float(vx), vy=float(vy)
        )
        new_memory[obj_id] = {
            "x": original_cx, "y": original_cy, "vx": float(vx), "vy": float(vy),
            "size": int(np.sqrt(area)), "area": float(area), "eccentricity": float(eccentricity),
            "core_ratio": float(core_ratio), "core_area_px": float(core_area_px),
            "core_violet_ratio": float(core_violet_ratio),
            "cell_area_px": float(cell_area_px), "prev_core_area_px": float(prev_core_area or 0.0),
            "delta_core_ratio": float(delta_core_ratio), "delta_area_pct": float(delta_area_pct),
            "delta_core_area_pct": float(delta_core_area_pct), "core_compact_signal": 1 if is_compact else 0,
            "trend": trend, "size_trend": size_trend,
            "merge_discontinuity": 1 if lineage == "merged" else 0,
            "lat": lat, "lon": lon,
            "dem_elevation_m":        dem["dem_elevation_m"],
            "dem_slope_toward_cell":  dem["dem_slope_toward_cell"],
            "dem_barrier_ahead":      dem.get("dem_barrier_ahead", 0.0),
            # B329: Status-Flag aus get_dem_features() wurde bisher nicht
            # uebernommen -> accuracy_tracker.py/diagnose_forecast_quality.py
            # lasen immer None. Werte: "computed"/"dem_partial_coverage"/
            # "no_movement_vector"/"dem_unavailable" (siehe dem_feature.py).
            "dem_slope_barrier_status": dem.get("dem_slope_barrier_status"),
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
            "is_active_cell": True,
            "tracking_state": ("reactivated" if previous_snapshot.get(obj_id, {}).get("tracking_state") == "inactive_rain" else "active"),
            "silent_tracking": False, "rain_supported": True,
            "inactive_since": None, "inactive_age_min": 0.0,
            "last_active_timestamp": timestamp,
            "reactivated_from_inactive": bool(previous_snapshot.get(obj_id, {}).get("tracking_state") == "inactive_rain"),
            "reactivated_at": (timestamp if previous_snapshot.get(obj_id, {}).get("tracking_state") == "inactive_rain" else None),
            "support_pixels": 0, "support_overlap": 0.0,
            "lineage": lineage, "parents": parents, "children": [], "lineage_end": None,
            # B375: Zustand und Ereignis sind getrennt. `transition_event` ist NUR
            # im Ereignisframe gesetzt; in Folgeframes null -> das Objekt ist
            # `continued`, auch wenn seine Herkunft ein Merge war.
            "track_state": "active",
            # B378: origin_type ist ein DAUERZUSTAND und muss fortgeschrieben werden.
            # `lineage` ist seit B375 ein Ereignis und ab dem Folgeframe "continued".
            # Ohne Carry-over fiele origin_type dann auf "new" zurueck -- eine aus
            # einem Merge hervorgegangene Zelle wuerde ab Frame 2 behaupten, sie sei
            # neu entstanden, und die Karte verloere die Verbund-Kennzeichnung.
            "origin_type": _resolve_origin_type(lineage, previous_snapshot.get(obj_id)),
            "transition_event": (
                _frame_transitions[_c_idx].kind
                if _c_idx in _frame_transitions and _frame_transitions[_c_idx].phase == "confirmed"
                else None
            ),
            "transition_phase": (
                _frame_transitions[_c_idx].phase if _c_idx in _frame_transitions else None
            ),
            "transition_signature": (
                _frame_transitions[_c_idx].signature if _c_idx in _frame_transitions else None
            ),
            "association_method": _assoc_result.method,
        }
        for parent_id in parents:
            assigned_old_to_new.setdefault(parent_id, []).append(obj_id)

    # B381: children/lineage_end der bestaetigten Splits stammen aus dem
    # Transition-Resolver. Der alte assigned_old_to_new-Nachlauf ist ersatzlos
    # entfallen: er verlangte, dass dieselbe alte ID in `parents` MEHRERER neuer
    # Objekte steht -- nach der globalen 1:1-Zuordnung ist das per Konstruktion
    # unmoeglich (parents hat bei `continued` genau einen, bei `merged` mehrere
    # Eintraege, aber nie derselbe Parent bei zwei Objekten). Der Pfad war tot und
    # damit die einzige Stelle, die lineage="split" setzen konnte.
    for _tr in _confirmed_transitions:
        if _tr.kind != "split":
            continue
        _parent_id = _tr.parents[0]
        _child_map = _split_child_obj_ids.get(_tr.signature, {})
        _children_ids = [_child_map[i] for i in _tr.children if i in _child_map]
        if len(_children_ids) < 2:
            continue
        # Primaeres Kind zuerst -- es fuehrt die Parent-ID fort.
        _primary_obj_id = _child_map.get(_tr.primary_child)
        if _primary_obj_id in _children_ids:
            _children_ids.remove(_primary_obj_id)
            _children_ids.insert(0, _primary_obj_id)
        _old_obj = previous_snapshot.get(_parent_id, {})
        _old_obj["children"] = _children_ids
        _old_obj["lineage_end"] = f"split_into:{_children_ids}"
        previous_snapshot[_parent_id] = _old_obj
        debug_log(
            f"[B381] Split bestaetigt: {_parent_id} -> {_children_ids} "
            f"(primaer={_primary_obj_id}, explained={_tr.explained})"
        )

    import time as _time_mod
    for obj_id, obj in previous_snapshot.items():
        if obj_id not in new_memory:
            lat, lon = obj.get("lat"), obj.get("lon")
            reason = "dissolved"
            if not is_within_bbox(lat, lon, _BBOX_LIVE):
                reason = "left_bbox"
            else:
                prev_state = obj.get("tracking_state", "active" if obj.get("missing", 0) == 0 else "expired")
                inactive_since = obj.get("inactive_since") or obj.get("missing_since") or timestamp
                inactive_age_min = _timestamp_age_min(inactive_since, timestamp)
                if isinstance(inactive_since, (int, float)):
                    inactive_age_min = max(0.0, (_time_mod.time() - float(inactive_since)) / 60.0)
                reason = "inactive_timeout" if inactive_age_min * 60.0 > _track_duration_s else "no_rain_support"
                support = {"supported": False, "support_pixels": 0, "support_overlap": 0.0, "support_cx": None, "support_cy": None}
                if _rain_support_enabled and prev_state in ("active", "inactive_rain", "reactivated") and inactive_age_min * 60.0 <= _track_duration_s:
                    support = find_rain_support_for_track(
                        obj, rain_support_mask, pred_centroids.get(obj_id), pred_polys.get(obj_id)
                    )
                if support.get("supported"):
                    obj = obj.copy()
                    obj["missing"] = int(obj.get("missing", 0) or 0) + 1
                    obj.setdefault("missing_since", _time_mod.time())
                    if not obj.get("inactive_since"):
                        obj["inactive_since"] = timestamp
                        inactive_age_min = 0.0
                    obj["inactive_age_min"] = round(float(inactive_age_min), 2)
                    obj["tracking_state"] = "inactive_rain"
                    obj["is_active_cell"] = False
                    obj["silent_tracking"] = True
                    obj["rain_supported"] = True
                    obj["reactivated_from_inactive"] = False
                    obj["reactivated_at"] = None
                    obj["support_pixels"] = int(support.get("support_pixels") or 0)
                    obj["support_overlap"] = float(support.get("support_overlap") or 0.0)
                    _suppress_inactive_rain_warning_fields(obj)
                    sx, sy = support.get("support_cx"), support.get("support_cy")
                    if sx is not None and sy is not None:
                        obj["x"] = float(sx) / float(UPSCALE_FACTOR)
                        obj["y"] = float(sy) / float(UPSCALE_FACTOR)
                        obj["lat"], obj["lon"] = pixel_to_geo(float(sx), float(sy))
                    new_memory[obj_id] = obj
                    continue
            try:
                from track_statistics import write_track_end as _wte_ps01
                obj["tracking_state"] = "expired"
                obj["lineage_end"] = reason
                _wte_ps01(obj, reason, timestamp)
            except Exception as _e_te1:
                debug_log(f"[P-S01] track_end {reason} Fehler ({obj_id}): {_e_te1}")

    if len(set(new_memory.keys())) != len(new_memory):
        debug_log("[TRACKING] WARN: Doppelte IDs in new_memory erkannt")

    # ── B94: Weggefährten-Features (zweiter Durchlauf, braucht alle Zellen) ──
    try:
        from config import (
            NEIGHBOR_AHEAD_RANGE_KM as _NEIGHBOR_AHEAD_RANGE_KM,
            NEIGHBOR_AHEAD_HALF_ANGLE as _NEIGHBOR_AHEAD_HALF_ANGLE,
            NEIGHBOR_MIN_SPEED_KMH as _NEIGHBOR_MIN_SPEED_KMH,
            PX_TO_KMH as _PX_TO_KMH_NEIGHBOR,
            UPSCALE_FACTOR as _UPSCALE_FACTOR_NEIGHBOR,
        )
        _all = list(new_memory.values())
        for _o in _all:
            _o.update(_compute_neighbor_ahead(
                _o, _all,
                range_km=_NEIGHBOR_AHEAD_RANGE_KM,
                half_angle_deg=_NEIGHBOR_AHEAD_HALF_ANGLE,
                min_speed_kmh=_NEIGHBOR_MIN_SPEED_KMH,
                px_to_kmh=_PX_TO_KMH_NEIGHBOR,
                upscale=_UPSCALE_FACTOR_NEIGHBOR,
            ))
    except Exception as _e:
        # B115: KEIN funktionslokaler debug_log-Import mehr.
        # Der lokale Import machte debug_log für die GESAMTE Funktion lokal und
        # führte zu UnboundLocalError bei früheren debug_log-Aufrufen (Crash).
        # debug_log ist bereits am Modulkopf global importiert.
        debug_log(f"[B94] Weggefährten-Features übersprungen: {_e}")

    # Orographische Scores werden in main.py nach assign_cape gesetzt
    # (brauchen CAPE-Werte die hier noch nicht verfügbar sind).
    # B385: Pre-Frame-Zustand explizit bereitstellen, BEVOR der globale Speicher
    # ersetzt wird.
    #
    # Danach ruft main.py die fachliche Lineage auf und uebergab bisher
    # `object_tracking.tracking_memory` als `previous_objects` -- also den bereits
    # UEBERSCHRIEBENEN Speicher. Darin traegt der Survivor schon das neue,
    # verschmolzene Objekt, und die beendeten Secondary-Parents fehlen vollstaendig
    # (`po = {}` -> area=0, core_ratio=0, total_active_frames=0). continuity_score()
    # bewertete damit auf der Fachebene andere Daten als auf der Radar-Ebene, obwohl
    # B377 dieselbe Funktion verwendet -- die Vereinheitlichung war wirkungslos.
    #
    # Flache Kopie: die enthaltenen Objekt-Dicts sind der Pre-Frame-Stand und werden
    # ab hier nicht mehr veraendert (new_memory enthaelt eigene Dicts).
    last_previous_snapshot = dict(previous_snapshot)
    tracking_memory = new_memory
    for obj_id, obj in new_memory.items():
        if obj.get("missing", 0) == 0 or obj.get("tracking_state") == "inactive_rain":
            if obj.get("missing", 0) == 0:
                obj.pop("missing_since", None)  # Zelle wieder sichtbar → Timer zurücksetzen
            # was_active: sticky Flag — True sobald core_ratio Schwellwert je erreicht.
            # Prüft auch previous_snapshot (carry-forward) falls Matching-Code das Flag
            # nicht automatisch übernimmt. Ermöglicht MISSING_LIMIT_ACTIVE statt DEFAULT.
            _prev_was_active = previous_snapshot.get(obj_id, {}).get("was_active", False)
            if _prev_was_active or float(obj.get("core_ratio", 0.0)) >= _was_active_threshold:
                obj["was_active"] = True  # setzt auch tracking_memory[obj_id] (gleiche Referenz)
            # F2-FIX: History aus previous_snapshot lesen (vor Überschreiben),
            # nicht aus tracking_memory (= new_memory, hat noch kein "history"-Key).
            previous_history = previous_snapshot.get(obj_id, {}).get("history", [])
            # Richtungsabhängige Ausdehnung aus Pixel-Kontur berechnen.
            # Wird in locations_check für N-S/E-W Wachstumsraten benötigt.
            try:
                from config import UPSCALE_FACTOR as _uf_hist
            except ImportError:
                _uf_hist = 3
            _km_per_px = 1.0 / _uf_hist                     # ~0.333 km/px
            _raw_cnt = obj.get("contour")
            if _raw_cnt is not None and len(_raw_cnt) >= 3:
                import numpy as _np_cnt
                _cnt_arr = _np_cnt.array(_raw_cnt, dtype=float)
                _xs = _cnt_arr[:, 0] if _cnt_arr.ndim == 2 else _cnt_arr[:, 0, 0]
                _ys = _cnt_arr[:, 1] if _cnt_arr.ndim == 2 else _cnt_arr[:, 0, 1]
                _lat_span_km = round(float(_ys.max() - _ys.min()) * _km_per_px, 4)
                _lon_span_km = round(float(_xs.max() - _xs.min()) * _km_per_px, 4)
            else:
                _lat_span_km = _lon_span_km = 0.0
            # area_km2: Gesamtfläche für isotrope Fallback-Berechnung
            _area_km2_hist = round(
                float(obj.get("area") or 0) * (_km_per_px ** 2), 5
            )
            new_entry = {
                "timestamp":   timestamp,
                "vx":          float(obj["vx"]),
                "vy":          float(obj["vy"]),
                "x":           float(obj.get("x", 0.0)),
                "y":           float(obj.get("y", 0.0)),
                "core_ratio":  float(obj["core_ratio"]),
                "area_km2":    _area_km2_hist,   # Gesamtfläche
                "lat_span_km": _lat_span_km,      # N-S-Ausdehnung
                "lon_span_km": _lon_span_km,      # E-W-Ausdehnung
                "weather_vals": {},
                "lat":         obj["lat"],
                "lon":         obj["lon"],
            }
            updated_history = (previous_history + [new_entry])[-history_len:]
            obj_clean = obj.copy(); obj_clean.pop("kf", None); obj_clean["history"] = updated_history
            if not isinstance(obj_clean.get("lineage"), str): obj_clean["lineage"] = "new"
            obj_clean.setdefault("parents", []); obj_clean.setdefault("children", []); obj_clean.setdefault("lineage_end", None)
            # F-FS: first_seen aus Vorperiode übernehmen oder jetzt setzen
            prev_first_seen = previous_snapshot.get(obj_id, {}).get("first_seen")
            obj_clean["first_seen"] = prev_first_seen if prev_first_seen else timestamp
            obj_clean["active_frames"] = len(obj_clean.get("history", []))
            # total_active_frames: unbegrenzter Zähler seit first_seen (history_len gekappt)
            _prev_total = previous_snapshot.get(obj_id, {}).get("total_active_frames", 0)
            obj_clean["total_active_frames"] = _prev_total + 1
            # ── P-S01: Lifecycle-Akkumulatoren (zirkuläre Richtung, Pfad, Speed) ──
            # Carry-over aus Vorperiode (B117-Pattern), dann mit aktuellem Frame
            # fortschreiben. Richtungsgewichtung = Segmentlänge in km.
            try:
                from config import (
                    TRACK_SEG_MIN_KM as _seg_min_km,
                    TRACK_SEG_DIRS_MAX as _seg_dirs_max,
                    TRACK_PATH_POINTS_MAX as _path_pts_max,
                    MIN_MOVEMENT_FOR_ARROW_KMH as _stat_min_kmh,
                    PX_TO_KMH as _px_to_kmh_ps01,
                )
                from track_statistics import bearing_deg as _bearing_ps01
                from track_statistics import haversine_km as _hav_ps01
                import math as _math_ps01
                _prev_t = previous_snapshot.get(obj_id, {})
                obj_clean["dir_sum_sin"]      = float(_prev_t.get("dir_sum_sin", 0.0) or 0.0)
                obj_clean["dir_sum_cos"]      = float(_prev_t.get("dir_sum_cos", 0.0) or 0.0)
                obj_clean["dir_km_sum"]       = float(_prev_t.get("dir_km_sum", 0.0) or 0.0)
                obj_clean["seg_dirs_deg"]     = list(_prev_t.get("seg_dirs_deg") or [])
                obj_clean["path_points"]      = list(_prev_t.get("path_points") or [])
                obj_clean["path_length_km"]   = float(_prev_t.get("path_length_km", 0.0) or 0.0)
                obj_clean["speed_sum_kmh"]    = float(_prev_t.get("speed_sum_kmh", 0.0) or 0.0)
                obj_clean["speed_n"]          = float(_prev_t.get("speed_n", 0.0) or 0.0)
                obj_clean["stationary_frames"] = int(_prev_t.get("stationary_frames", 0) or 0)
                obj_clean["max_core_ratio"]   = max(
                    float(_prev_t.get("max_core_ratio", 0.0) or 0.0),
                    float(obj_clean.get("core_ratio", 0.0) or 0.0),
                )
                # Schwere-Maxima carry-over (Werte selbst setzt main.py via
                # track_statistics.accumulate_severity_maxima)
                for _mx in ("max_severity_level", "max_hail_cat",
                            "max_hail_prob", "max_lightning_10km"):
                    if _mx in _prev_t:
                        obj_clean[_mx] = _prev_t[_mx]
                # P73: letzte Stationsbegegnung carry-over (Wert selbst setzt
                # main.py via track_statistics.accumulate_station_encounter).
                # Bleibt unveraendert, bis main.py eine NEUE, engere
                # Begegnung feststellt — daher unconditional (auch None).
                obj_clean["last_station_encounter"] = _prev_t.get("last_station_encounter")
                # Pfadpunkt anhängen (gekappt)
                obj_clean["path_points"].append([float(obj_clean["lat"]), float(obj_clean["lon"])])
                if len(obj_clean["path_points"]) > _path_pts_max:
                    obj_clean["path_points"] = obj_clean["path_points"][-_path_pts_max:]
                # Segmentrichtung aus letztem History-Punkt der VORPERIODE
                if previous_history and isinstance(previous_history[-1], dict):
                    _pl = previous_history[-1].get("lat")
                    _po = previous_history[-1].get("lon")
                    if _pl is not None and _po is not None:
                        _seg_km = _hav_ps01(float(_pl), float(_po),
                                            float(obj_clean["lat"]), float(obj_clean["lon"]))
                        obj_clean["path_length_km"] = round(
                            obj_clean["path_length_km"] + _seg_km, 3
                        )
                        if _seg_km >= _seg_min_km:
                            _b = _bearing_ps01(float(_pl), float(_po),
                                               float(obj_clean["lat"]), float(obj_clean["lon"]))
                            obj_clean["dir_sum_sin"] += _seg_km * _math_ps01.sin(_math_ps01.radians(_b))
                            obj_clean["dir_sum_cos"] += _seg_km * _math_ps01.cos(_math_ps01.radians(_b))
                            obj_clean["dir_km_sum"]  += _seg_km
                            obj_clean["seg_dirs_deg"].append(round(_b, 1))
                            if len(obj_clean["seg_dirs_deg"]) > _seg_dirs_max:
                                obj_clean["seg_dirs_deg"] = obj_clean["seg_dirs_deg"][-_seg_dirs_max:]
                # Frame-Geschwindigkeit (km/h) aus Kalman-Velocity
                try:
                    from config import speed_kmh_from_px as _spd_fn_ps01
                    _spd = _spd_fn_ps01(float(obj_clean.get("vx", 0.0) or 0.0),
                                        float(obj_clean.get("vy", 0.0) or 0.0))
                except ImportError:
                    _spd = _math_ps01.hypot(
                        float(obj_clean.get("vx", 0.0) or 0.0),
                        float(obj_clean.get("vy", 0.0) or 0.0),
                    ) * _px_to_kmh_ps01
                obj_clean["speed_sum_kmh"] += float(_spd)
                obj_clean["speed_n"]       += 1.0
                if float(_spd) < float(_stat_min_kmh):
                    obj_clean["stationary_frames"] += 1
            except Exception as _e_ps01:
                debug_log(f"[P-S01] Akkumulation übersprungen ({obj_id}): {_e_ps01}")
            # B117: Akkumulierte Track-Felder ZURUECK in tracking_memory schreiben
            # (obj == new_memory[obj_id] == tracking_memory[obj_id]). Ohne dies
            # blieben history/first_seen/active_frames jeden Frame = 1 -> keine
            # Trainings-Sequenzen (ML_SEQUENCE_LENGTH=6 nie erreicht).
            obj["history"]             = updated_history
            obj["first_seen"]          = obj_clean["first_seen"]
            obj["active_frames"]       = obj_clean["active_frames"]
            obj["total_active_frames"] = obj_clean["total_active_frames"]
            # B369: last_station_encounter-Carry-over fehlte hier — ohne dies
            # ging eine bereits bestehende Begegnung sofort wieder verloren,
            # sobald save_tracking_snapshot() lief und kein NEUER Encounter
            # im selben Zyklus gemeldet wurde (Normalfall).
            obj["last_station_encounter"] = obj_clean["last_station_encounter"]
            # P-S01: Lifecycle-Akkumulatoren ebenfalls persistieren, damit sie im
            # nächsten Frame als previous_snapshot[obj_id] verfügbar sind und beim
            # Track-Tod von write_track_end gelesen werden können.
            for _ps01_key in (
                "dir_sum_sin", "dir_sum_cos", "dir_km_sum", "seg_dirs_deg",
                "path_points", "path_length_km", "speed_sum_kmh", "speed_n",
                "stationary_frames", "max_core_ratio",
            ):
                if _ps01_key in obj_clean:
                    obj[_ps01_key] = obj_clean[_ps01_key]
            # P17: Lineage-Features als normalisierte Floats für ML_CELL_FEATURES.
            # Normierung: active_frames / 20 (gekappt) → 0..1;
            #             total_active_frames / 100 (gekappt) → 0..1
            obj_clean["active_frames_norm"] = min(
                float(obj_clean["active_frames"]), 20.0
            ) / 20.0
            obj_clean["total_active_frames_norm"] = min(
                float(obj_clean["total_active_frames"]), 100.0
            ) / 100.0
            _lin = obj_clean.get("lineage", "new")
            obj_clean["is_merged"] = 1.0 if _lin == "merged" else 0.0
            obj_clean["is_split"]  = 1.0 if _lin == "split"  else 0.0
            # Vorberechnete Geschwindigkeit [km/h] + meteorolog. Richtung [°] für Frontend.
            # B105/P0-1: vx/vy sind ORIGINAL-px/Frame (Kalman wird mit original_cx/cy
            # gefüttert). PX_TO_KMH = km/h pro Original-px/Frame → KEINE /UF-Division.
            try:
                import math as _math_spd
                from config import speed_kmh_from_px as _spd_fn
                _spd_vx = float(obj_clean.get("vx", 0.0))
                _spd_vy = float(obj_clean.get("vy", 0.0))
                _raw_speed = _spd_fn(_spd_vx, _spd_vy)  # nominal: FRAME_INTERVAL_MIN-Basis
                # B115: auf ECHTES Frame-Intervall skalieren (robust gegen fehlende
                # Frames). vx ist px pro real-Step; _spd_fn nimmt den Nominal-Step an.
                # true = nominal × (FRAME_INTERVAL_MIN / real_dt_min).
                _hist_spd = obj_clean.get("history", [])
                if len(_hist_spd) >= 2:
                    try:
                        from datetime import datetime as _dt_spd
                        from config import FRAME_INTERVAL_MIN as _FIM_spd
                        _t_a = _dt_spd.strptime(_hist_spd[-2]["timestamp"], "%Y-%m-%d_%H-%M-%S")
                        _t_b = _dt_spd.strptime(_hist_spd[-1]["timestamp"], "%Y-%m-%d_%H-%M-%S")
                        _real_dt = (_t_b - _t_a).total_seconds() / 60.0
                        if 1.0 <= _real_dt <= 30.0:
                            _raw_speed = _raw_speed * (float(_FIM_spd) / _real_dt)
                    except Exception:
                        pass
                # Sicherheitsclamp: max. MAX_CELL_SPEED_KMH (Konsistenz mit Kalman-Clamp)
                try:
                    import runtime_config as _rc_spd
                    _max_spd = float(_rc_spd.get("MAX_CELL_SPEED_KMH", 130.0))
                except Exception:
                    _max_spd = 130.0
                obj_clean["speed_kmh"] = round(min(_raw_speed, _max_spd), 1)
                # Richtung nur wenn Zelle sich bewegt (≥ 0.5 km/h).
                # Verhindert IEEE-754 atan2(0.0, -0.0) = 180° bei stationären Zellen.
                if _raw_speed >= 0.5:
                    _dir_rad = _math_spd.atan2(_spd_vx, -_spd_vy)
                    obj_clean["direction_deg"] = round(
                        (_math_spd.degrees(_dir_rad) + 360.0) % 360.0, 1
                    )
                else:
                    obj_clean["direction_deg"] = None  # stationär: keine Richtung
            except Exception:
                obj_clean.setdefault("speed_kmh", 0.0)
                obj_clean.setdefault("direction_deg", None)
            _suppress_inactive_rain_warning_fields(obj_clean)
            objects.append({"id": obj_id, **obj_clean})
    # B367: Snapshot ERST NACH der Enrichment-Schleife persistieren — sonst
    # fehlen first_seen/total_active_frames/history/P-S01-Akkumulatoren im
    # gespeicherten Zustand für alle in diesem Zyklus aktiv erkannten Zellen
    # (missing==0). Zellen mit missing>0 durchlaufen die Schleife nicht neu
    # und sind vom Zeitpunkt der Speicherung nicht betroffen.
    # B121: Nach jedem Tracking-Zyklus Snapshot persistieren.
    # Wird beim nächsten Service-Start via load_tracking_snapshot() geladen.
    save_tracking_snapshot()
    return objects


import math as _math


def _neighbor_motion_seed(cx: float, cy: float, previous_snapshot: dict):
    """B172: Mittlerer Bewegungsvektor (ORIGINAL-px/Frame) der aktiven Zellen des
    letzten Frames im Umkreis NEW_CELL_SEED_RADIUS_KM um (cx, cy). Dient als
    Start-Geschwindigkeit neu entstandener Zellen, damit der kinematische Forecast
    sie weiterbewegen kann (Prio-1, ≤30 min < 1 km). Liefert (0.0, 0.0) wenn keine
    geeigneten Nachbarn vorhanden sind (dann übernimmt der optische Fluss, sobald
    pysteps verfügbar ist). Einheiten bleiben px/Frame — identisch zu kf.x[2]/kf.x[3],
    daher keine Einheiten-/Richtungskonvention nötig."""
    try:
        from config import NEW_CELL_SEED_RADIUS_KM, UPSCALE_FACTOR
    except ImportError:
        NEW_CELL_SEED_RADIUS_KM, UPSCALE_FACTOR = 30.0, 3.0
    if not previous_snapshot:
        return 0.0, 0.0
    _km_per_px = 1.0 / float(UPSCALE_FACTOR)              # ORIGINAL-px → km
    if _km_per_px <= 0.0:
        return 0.0, 0.0
    _radius_px = float(NEW_CELL_SEED_RADIUS_KM) / _km_per_px
    _sum_vx = _sum_vy = 0.0
    _n = 0
    for _prev in previous_snapshot.values():
        # B207/Codex: Verschwundene Zellen (missing != 0) bleiben bis zum Timeout im
        # Snapshot. Sie dürfen eine neu entstehende Zelle NICHT mit ihrer veralteten
        # Geschwindigkeit seeden — der Helfer gilt nur für AKTIVE Zellen des letzten Frames.
        try:
            if int(_prev.get("missing", 0) or 0) != 0:
                continue
        except (TypeError, ValueError):
            continue
        try:
            _px = float(_prev.get("x"))
            _py = float(_prev.get("y"))
            _pvx = float(_prev.get("vx", 0.0))
            _pvy = float(_prev.get("vy", 0.0))
        except (TypeError, ValueError):
            continue
        if _pvx == 0.0 and _pvy == 0.0:
            continue                                      # ruhende Nachbarn ignorieren
        if _math.hypot(_px - cx, _py - cy) > _radius_px:
            continue
        _sum_vx += _pvx
        _sum_vy += _pvy
        _n += 1
    if _n == 0:
        return 0.0, 0.0
    return round(_sum_vx / _n, 4), round(_sum_vy / _n, 4)


def _clamp_kalman_velocity(kf, prev_vx: float, prev_vy: float) -> None:
    """
    Plausibilitätsprüfung (F14): Klemmt Kalman-Geschwindigkeit auf physikalisch
    sinnvolle Werte. Verhindert Sprünge durch Mess-Artefakte oder kurzzeitige
    Zellverwechslungen.

    Einheiten (B105/P0-1):
      Kalman-vx/vy sind ORIGINAL-px/Frame — der Filter wird mit
      original_cx/original_cy gefüttert. PX_TO_KMH = km/h pro Original-px/Frame.
      km/h = hypot(vx, vy) * PX_TO_KMH (KEINE Division durch UPSCALE_FACTOR).
      Identischer Wert wie config.speed_kmh_from_px(), locations_check.py und GUI.

    Grenzen aus config.py:
      MAX_CELL_SPEED_KMH              — absolute Obergrenze Zellgeschwindigkeit
      MAX_SPEED_CHANGE_PER_CYCLE_KMH  — max. Änderung pro Zyklus
      PX_TO_KMH                       — km/h pro Original-px/Frame
    """
    try:
        from config import (
            MAX_CELL_SPEED_KMH,
            MAX_SPEED_CHANGE_PER_CYCLE_KMH,
            PX_TO_KMH,
        )
    except ImportError:
        MAX_CELL_SPEED_KMH = 150.0
        MAX_SPEED_CHANGE_PER_CYCLE_KMH = 60.0
        PX_TO_KMH = 4.0

    # B105/P0-1: vx/vy sind ORIGINAL-px/Frame → direkt PX_TO_KMH, kein /UF.
    PIXEL_TO_KMH = float(PX_TO_KMH)  # km/h pro ORIGINAL-px/Frame

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
    FILTER_CONFIG = _get_filter_config_live()
    CORE_HSV_RANGES = _rc.get("CORE_HSV_RANGES", _DEFAULT_CORE_HSV_RANGES)
    import os
    from datetime import datetime
    # Fix #4: BBOX aus runtime_config damit Admin-Änderungen sofort wirken
    from config import BBOX_KAERNTEN_EXTENDED as _DEFAULT_BBOX_TRACK, UPSCALE_FACTOR, SAVE_PATHS
    BBOX = _validate_bbox(
        _rc.get("BBOX_KAERNTEN_EXTENDED", _DEFAULT_BBOX_TRACK),
        _DEFAULT_BBOX_TRACK,
    )

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
        _acq = get_acquisition_timestamp()
        if _acq:
            ts_dt = datetime.strptime(_acq, "%Y-%m-%d_%H-%M-%S")
            # B259: Sanity-Check — wenn ARSO-Timestamp eingefroren ist
            # (download_kmz() lieferte True = frischer Inhalt, aber KML-<when>
            # zeigt stundenlang denselben Wert), auf Systemzeit zurückfallen.
            # Verhindert dass alle Radar-PNGs denselben Dateinamen bekommen
            # und api_radar_frames sie als "zu alt" herausfiltert.
            try:
                from config import RADAR_TIMESTAMP_MAX_SKEW_MIN as _SKEW_CFG
            except Exception:
                _SKEW_CFG = 30.0
            try:
                import runtime_config as _rc_b259
                _skew_max = float(_rc_b259.get("RADAR_TIMESTAMP_MAX_SKEW_MIN", _SKEW_CFG))
            except Exception:
                _skew_max = float(_SKEW_CFG)
            _now_local = datetime.now()
            _skew_min = (_now_local - ts_dt).total_seconds() / 60.0
            if _skew_max > 0 and _skew_min > _skew_max:
                debug_log(
                    f"[WARN] B259: ARSO-Timestamp {_acq} ist {_skew_min:.0f} min "
                    f"veraltet (Grenze: {_skew_max:.0f} min) → Systemzeit als Fallback"
                )
                ts_dt = _now_local
                _acq = ts_dt.strftime("%Y-%m-%d_%H-%M-%S")
            timestamp = _acq
            debug_log(f"[INFO] Live-Modus: Aufnahme-Timestamp aus KMZ (KML-TimeStamp/PNG/Last-Modified): {timestamp}")
        else:
            ts_dt = datetime.now()
            timestamp = ts_dt.strftime("%Y-%m-%d_%H-%M-%S")
            debug_log(f"[WARN] Live-Modus: Last-Modified nicht verfügbar → Systemzeit: {timestamp}")
    else:
        try:
            ts_dt = datetime.strptime(filename.replace("radar_", ""), "%Y-%m-%d_%H-%M-%S")
            timestamp = ts_dt.strftime("%Y-%m-%d_%H-%M-%S")
        except ValueError:
            _acq = get_acquisition_timestamp()
            if _acq:
                timestamp = _acq
                ts_dt = datetime.strptime(_acq, "%Y-%m-%d_%H-%M-%S")
                debug_log(f"[WARN] Dateiname-Parse fehlgeschlagen, nutze KMZ Last-Modified: {timestamp}")
            else:
                ts_dt = datetime.now()
                timestamp = ts_dt.strftime("%Y-%m-%d_%H-%M-%S")

    # ✂️ Bild zuschneiden & hochskalieren
    scaled_path = os.path.join("data/radar", f"{timestamp}.png")
    processed_img = crop_and_upscale_to_bbox(image_path, BBOX, UPSCALE_FACTOR, scaled_path)

    # 💾 Originalbild (unverändert) archivieren
    original_img = cv2.imread(image_path)
    if original_img is not None:
        original_path = os.path.join(SAVE_PATHS["radar"].rstrip("/"), f"{timestamp}.png")
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
    merged = merge_close_contours(
        contours, hsv.shape[:2], min_touch=MIN_CONTOUR_TOUCH, dilate_px=MERGE_TOUCH_DILATE_PX
    )

    # P66: Multi-Core-Split — Konturen mit mehreren Konvektionskernen aufteilen
    merged = split_multi_core_contours(merged, hsv)

    # 📌 Objektverfolgung
    rain_support_mask = build_rain_support_mask(hsv)
    objects = update_tracking_memory(hsv, merged, weather_data, timestamp, rain_support_mask=rain_support_mask)

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
    # Intensitätszonen live aus runtime_config — Admin-Panel-Änderungen wirken sofort.
    # Fallback: INTENSITY_BANDS_DEFAULT aus config.py.
    try:
        from config import INTENSITY_BANDS_DEFAULT as _IB_DEFAULT
    except ImportError:
        _IB_DEFAULT = [
            ["orange",   [10,  100,  80], [27,  255, 255], "#ff8800"],
            ["rot",      [0,   100,  80], [10,  255, 255], "#cc0000"],
            ["rot_wrap", [165, 100,  80], [179, 255, 255], "#cc0000"],
            ["violett",  [125, 100,  80], [155, 255, 255], "#9900cc"],
        ]
    _raw_bands = _rc.get("INTENSITY_BANDS", _IB_DEFAULT)
    INTENSITY_BANDS = [
        (
            entry[0],
            tuple(int(v) for v in entry[1]),
            tuple(int(v) for v in entry[2]),
            entry[3],
        )
        for entry in _raw_bands
        if len(entry) == 4
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
