"""B373: Globale Datenassoziation für Radar-Zelltracking.

Ersetzt die greedy, konturweise ID-Vergabe durch eine global optimale 1:1-Zuordnung.

Warum global statt greedy
-------------------------
Die bisherige Schleife `for contour in contours` entfernt bereits vergebene alte IDs
über `used_ids` aus allen folgenden Kandidatenlisten. Damit entscheidet die zufällige
OpenCV-Konturreihenfolge über die Identität:

    X passt gut zu A und etwas schlechter zu B.
    Y passt ausschliesslich zu A.

Greedy (X zuerst) -> X=A, Y=new. Global optimal -> X=B, Y=A.

Physikalische Gates
-------------------
Alle Gates rechnen in echten Kilometern und mit dem TATSAECHLICHEN Zeitabstand zwischen
zwei Radarbildern, nicht in skalierten Pixeln pro Frame. Der bisherige Stage-2-Cap
(MAX_CELL_SPEED_KMH / PX_TO_KMH) * UPSCALE_FACTOR * 1.5 = 168.75 px unterstellt implizit
einen festen 5-Minuten-Takt. Bei Radarausfällen (10/15 min Lücke) ist er zu eng, im
Normalbetrieb zu weit.

Suchellipse statt Suchkreis: Zellen bewegen sich entlang ihres Vektors. Ein Kreis erlaubt
quer zur Bewegung dieselbe Distanz wie längs -- physikalisch unplausibel und die Hauptquelle
für Fehlzuordnungen an unabhängige Nachbarzellen.

Diese Bibliothek ist bewusst frei von OpenCV- und Kalman-Abhängigkeiten: reine Geometrie und
Optimierung, damit sie ohne Radarbild testbar ist. Die Integration erfolgt in B374.
"""
from __future__ import annotations

import math
import itertools
import importlib.util
from dataclasses import dataclass, field
from typing import Any

if importlib.util.find_spec("scipy") is not None and importlib.util.find_spec("scipy.optimize") is not None:
    from scipy.optimize import linear_sum_assignment

    _HAS_SCIPY = True
else:  # pragma: no cover - scipy ist in requirements.txt gepinnt
    _HAS_SCIPY = False

if importlib.util.find_spec("runtime_config") is not None:
    import runtime_config as _rc
else:  # pragma: no cover
    _rc = None


# --- Defaults (per runtime_config überschreibbar) ---------------------------
_DEFAULTS = {
    "ASSOC_MAX_COST": 1.0,
    "ASSOC_W_POS": 0.35,
    "ASSOC_W_IOU": 0.25,
    "ASSOC_W_AREA": 0.15,
    "ASSOC_W_DIR": 0.10,
    "ASSOC_W_CORE": 0.10,
    "ASSOC_W_AGE": 0.05,
    # Suchellipse: quer zur Bewegung deutlich enger als längs.
    "ASSOC_ELLIPSE_CROSS_FACTOR": 0.45,
    # Grundunsicherheit der Position in km (Segmentierungsrauschen, Schwerpunktzittern).
    "ASSOC_BASE_UNCERTAINTY_KM": 2.0,
    # Maximal plausible Flächenänderung als Faktor pro Minute.
    "ASSOC_MAX_AREA_GROWTH_PER_MIN": 1.25,
    # Junge Tracks haben keinen belastbaren Bewegungsvektor -> Richtungsgate aussetzen.
    "ASSOC_MIN_AGE_FRAMES_FOR_DIR_GATE": 3,
    "ASSOC_MAX_DIR_DEVIATION_DEG": 75.0,
}


def _cfg(key: str, default: Any = None) -> Any:
    if default is None:
        default = _DEFAULTS.get(key)
    if _rc is not None:
        try:
            return _rc.get(key, default)
        except Exception:
            pass
    return default


@dataclass
class TrackCandidate:
    """Ein alter Track zum Zeitpunkt t-1, bereits auf t prädiziert."""
    track_id: str
    pred_x_km: float
    pred_y_km: float
    vx_kmh: float = 0.0
    vy_kmh: float = 0.0
    area_px: float = 0.0
    core_ratio: float = 0.0
    age_frames: int = 0
    missing: int = 0
    polygon: Any = None


@dataclass
class DetectionCandidate:
    """Eine neue Detektion zum Zeitpunkt t."""
    index: int
    x_km: float
    y_km: float
    area_px: float = 0.0
    core_ratio: float = 0.0
    polygon: Any = None


@dataclass
class AssociationResult:
    """Ergebnis der globalen Zuordnung — vollständig diagnosefähig."""
    matches: dict = field(default_factory=dict)          # detection_index -> track_id
    unmatched_detections: list = field(default_factory=list)
    unmatched_tracks: list = field(default_factory=list)
    cost_matrix: list = field(default_factory=list)
    candidate_pairs: list = field(default_factory=list)
    rejected_matches: list = field(default_factory=list)
    method: str = "hungarian"


def predict_track_state(track: TrackCandidate, dt_minutes: float) -> tuple[float, float]:
    """Prädiziert die Trackposition in km über den TATSAECHLICHEN Zeitabstand."""
    dt_h = max(float(dt_minutes), 0.0) / 60.0
    return (track.pred_x_km + track.vx_kmh * dt_h, track.pred_y_km + track.vy_kmh * dt_h)


def _search_radii_km(track: TrackCandidate, dt_minutes: float, max_speed_kmh: float) -> tuple[float, float, float, float]:
    """Halbachsen der Suchellipse in km plus Richtungsvektor.

    Längs der Bewegung: maximal plausible Verlagerung bei max_speed_kmh über dt.
    Quer: ASSOC_ELLIPSE_CROSS_FACTOR davon. Zusätzlich eine Grundunsicherheit, damit
    stehende oder frische Zellen nicht sofort aus dem Gate fallen.
    """
    dt_h = max(float(dt_minutes), 0.0) / 60.0
    reach_km = float(max_speed_kmh) * dt_h
    base = float(_cfg("ASSOC_BASE_UNCERTAINTY_KM"))
    a_km = reach_km + base                                     # längs
    b_km = reach_km * float(_cfg("ASSOC_ELLIPSE_CROSS_FACTOR")) + base  # quer
    speed = math.hypot(track.vx_kmh, track.vy_kmh)
    if speed < 1.0:
        # Kein belastbarer Vektor -> isotroper Kreis mit dem engeren Radius.
        return (b_km, b_km, 1.0, 0.0)
    return (a_km, b_km, track.vx_kmh / speed, track.vy_kmh / speed)


def passes_physical_gate(track: TrackCandidate, det: DetectionCandidate, dt_minutes: float,
                         max_speed_kmh: float) -> tuple[bool, str]:
    """Harte physikalische Gates. Gibt (ok, Ablehnungsgrund) zurück."""
    px, py = predict_track_state(track, dt_minutes)
    dx, dy = det.x_km - px, det.y_km - py

    a_km, b_km, ux, uy = _search_radii_km(track, dt_minutes, max_speed_kmh)
    # Projektion auf Längs-/Querachse der Bewegung.
    along = dx * ux + dy * uy
    cross = -dx * uy + dy * ux
    if (along / max(a_km, 1e-6)) ** 2 + (cross / max(b_km, 1e-6)) ** 2 > 1.0:
        return (False, f"outside_search_ellipse(a={a_km:.1f}km,b={b_km:.1f}km)")

    # Flächengate: zeitabhängig statt fixem 10x-Faktor.
    if track.area_px > 0 and det.area_px > 0:
        max_factor = float(_cfg("ASSOC_MAX_AREA_GROWTH_PER_MIN")) ** max(float(dt_minutes), 1.0)
        ratio = max(det.area_px, track.area_px) / max(min(det.area_px, track.area_px), 1e-6)
        if ratio > max_factor:
            return (False, f"area_ratio={ratio:.1f}>max={max_factor:.1f}")

    # Richtungsgate nur für Tracks mit belastbarem Vektor.
    speed = math.hypot(track.vx_kmh, track.vy_kmh)
    if track.age_frames >= int(_cfg("ASSOC_MIN_AGE_FRAMES_FOR_DIR_GATE")) and speed >= 5.0:
        move = math.hypot(dx, dy)
        if move > 1.0:
            cos_dev = (dx * ux + dy * uy) / max(move, 1e-6)
            dev_deg = math.degrees(math.acos(max(-1.0, min(1.0, cos_dev))))
            if dev_deg > float(_cfg("ASSOC_MAX_DIR_DEVIATION_DEG")):
                return (False, f"direction_deviation={dev_deg:.0f}deg")
    return (True, "")


def _iou(poly_a, poly_b) -> float:
    if poly_a is None or poly_b is None:
        return 0.0
    try:
        inter = poly_a.intersection(poly_b).area
        union = poly_a.union(poly_b).area
        return float(inter / union) if union > 1e-9 else 0.0
    except Exception:
        return 0.0


def build_candidate_features(track: TrackCandidate, det: DetectionCandidate,
                             dt_minutes: float, max_speed_kmh: float) -> dict:
    """Alle Kostenkomponenten eines Paares — einzeln exportierbar für die Diagnose."""
    px, py = predict_track_state(track, dt_minutes)
    dist_km = math.hypot(det.x_km - px, det.y_km - py)
    a_km, _, ux, uy = _search_radii_km(track, dt_minutes, max_speed_kmh)

    c_pos = min(dist_km / max(a_km, 1e-6), 1.0)
    c_iou = 1.0 - _iou(track.polygon, det.polygon)

    if track.area_px > 0 and det.area_px > 0:
        c_area = min(abs(math.log(det.area_px / track.area_px)) / math.log(10.0), 1.0)
    else:
        c_area = 0.5

    c_dir = 0.0
    speed = math.hypot(track.vx_kmh, track.vy_kmh)
    move = math.hypot(det.x_km - px, det.y_km - py)
    if speed >= 5.0 and move > 1.0:
        cos_dev = ((det.x_km - px) * ux + (det.y_km - py) * uy) / max(move, 1e-6)
        c_dir = (1.0 - max(-1.0, min(1.0, cos_dev))) / 2.0

    c_core = min(abs(det.core_ratio - track.core_ratio), 1.0)
    c_age = min(float(track.missing) / 3.0, 1.0)

    return {
        "dist_km": dist_km, "c_pos": c_pos, "c_iou": c_iou, "c_area": c_area,
        "c_dir": c_dir, "c_core": c_core, "c_age": c_age,
    }


def pair_cost(features: dict) -> float:
    """Gewichtete Gesamtkosten eines Paares."""
    return (
        float(_cfg("ASSOC_W_POS")) * features["c_pos"]
        + float(_cfg("ASSOC_W_IOU")) * features["c_iou"]
        + float(_cfg("ASSOC_W_AREA")) * features["c_area"]
        + float(_cfg("ASSOC_W_DIR")) * features["c_dir"]
        + float(_cfg("ASSOC_W_CORE")) * features["c_core"]
        + float(_cfg("ASSOC_W_AGE")) * features["c_age"]
    )


_INF = 1e6


def _fallback_linear_sum_assignment(matrix: list) -> tuple[list, list]:
    """Kleine deterministische Fallback-Zuordnung für Testumgebungen ohne scipy."""
    n_rows = len(matrix)
    n_cols = len(matrix[0]) if n_rows else 0
    k = min(n_rows, n_cols)
    best_cost = math.inf
    best_rows: tuple[int, ...] = ()
    best_cols: tuple[int, ...] = ()
    for rows in itertools.combinations(range(n_rows), k):
        for cols in itertools.permutations(range(n_cols), k):
            cost = sum(matrix[row][col] for row, col in zip(rows, cols))
            if cost < best_cost:
                best_cost = cost
                best_rows = rows
                best_cols = cols
    return list(best_rows), list(best_cols)


def build_cost_matrix(tracks: list, detections: list, dt_minutes: float,
                      max_speed_kmh: float) -> tuple[list, list]:
    """Kostenmatrix (len(detections) x len(tracks)). Gegatete Paare erhalten _INF."""
    n_det, n_trk = len(detections), len(tracks)
    matrix = [[_INF for _ in range(n_trk)] for _ in range(n_det)]
    pairs = []
    for i, det in enumerate(detections):
        for j, trk in enumerate(tracks):
            ok, reason = passes_physical_gate(trk, det, dt_minutes, max_speed_kmh)
            if not ok:
                pairs.append({"detection_index": det.index, "track_id": trk.track_id,
                              "gated": True, "reason": reason, "cost": None})
                continue
            feats = build_candidate_features(trk, det, dt_minutes, max_speed_kmh)
            cost = pair_cost(feats)
            matrix[i][j] = cost
            pairs.append({"detection_index": det.index, "track_id": trk.track_id,
                          "gated": False, "reason": "", "cost": round(cost, 4),
                          "components": {k: round(v, 4) for k, v in feats.items()}})
    return matrix, pairs


def solve_global_assignment(tracks: list, detections: list, dt_minutes: float,
                            max_speed_kmh: float) -> AssociationResult:
    """Global optimale 1:1-Zuordnung via Hungarian; verwirft zu teure Matches."""
    result = AssociationResult()
    if not tracks or not detections:
        result.unmatched_detections = [d.index for d in detections]
        result.unmatched_tracks = [t.track_id for t in tracks]
        result.method = "empty"
        return result

    matrix, pairs = build_cost_matrix(tracks, detections, dt_minutes, max_speed_kmh)
    result.cost_matrix = [[None if v >= _INF else round(float(v), 4) for v in row] for row in matrix]
    result.candidate_pairs = pairs

    if _HAS_SCIPY:
        row_ind, col_ind = linear_sum_assignment(matrix)
    else:
        row_ind, col_ind = _fallback_linear_sum_assignment(matrix)
    max_cost = float(_cfg("ASSOC_MAX_COST"))
    matched_tracks = set()
    for i, j in zip(row_ind, col_ind):
        cost = float(matrix[i][j])
        det_idx = detections[i].index
        trk_id = tracks[j].track_id
        if cost >= _INF:
            result.rejected_matches.append({"detection_index": det_idx, "track_id": trk_id,
                                            "reason": "gated", "cost": None})
            continue
        if cost > max_cost:
            result.rejected_matches.append({"detection_index": det_idx, "track_id": trk_id,
                                            "reason": "cost_above_max", "cost": round(cost, 4)})
            continue
        result.matches[det_idx] = trk_id
        matched_tracks.add(trk_id)

    result.unmatched_detections = [d.index for d in detections if d.index not in result.matches]
    result.unmatched_tracks = [t.track_id for t in tracks if t.track_id not in matched_tracks]
    return result


def reject_high_cost_matches(result: AssociationResult, max_cost: float | None = None) -> AssociationResult:
    """Nachträgliche Verschärfung der Kostenschwelle (Diagnose/Tuning)."""
    if max_cost is None:
        return result
    keep = {}
    for det_idx, trk_id in result.matches.items():
        pair = next((p for p in result.candidate_pairs
                     if p["detection_index"] == det_idx and p["track_id"] == trk_id), None)
        cost = (pair or {}).get("cost")
        if cost is not None and cost <= max_cost:
            keep[det_idx] = trk_id
        else:
            result.rejected_matches.append({"detection_index": det_idx, "track_id": trk_id,
                                            "reason": "cost_above_max", "cost": cost})
    result.matches = keep
    matched = set(keep.values())
    result.unmatched_detections = sorted(set(result.unmatched_detections)
                                         | {p["detection_index"] for p in result.rejected_matches
                                            if p["detection_index"] not in keep})
    result.unmatched_tracks = [t for t in result.unmatched_tracks if t not in matched]
    return result
