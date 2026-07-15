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
    # B400: ERREICHBARE Schwelle. Alle Kostenkomponenten sind auf [0,1] normiert und
    # die Gewichte summieren sich auf exakt 1.00 -- die teuerste moegliche Paarung
    # kostet damit 1.00. Verworfen wurde bei `cost > max_cost` mit max_cost=1.0, also
    # NIE. Die Schwelle war toter Code; es filterten ausschliesslich die harten Gates.
    # 0.75 heisst: ein Paar muss im gewichteten Mittel mindestens "mittelmaessig"
    # passen. Der Wert ist NICHT gegen reale Daten kalibriert (siehe Changelog).
    "ASSOC_MAX_COST": 0.75,
    # B400: Kosten einer bewussten NICHT-Zuordnung. Hungarian muss jeder Zeile eine
    # Spalte zuweisen -- ohne Dummy-Spalte kann der Solver "keine Zuordnung" nicht
    # waehlen und verdraengt gute Paare, um die Gesamtsumme zu minimieren.
    # Muss knapp ueber ASSOC_MAX_COST liegen: ein Paar unterhalb der Schwelle soll
    # immer der Nicht-Zuordnung vorgezogen werden.
    "ASSOC_UNMATCHED_COST": 0.80,
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
    # B379: Flaechengate muss Merge UND Split zulassen.
    # Vorher: 1.25^dt -> bei dt=5min nur 3.05x. Eine Merge-Kontur waechst aber genau
    # um ein Vielfaches (im B117-Test 6.25x) -> das Gate verwarf JEDEN Merge, die
    # Kontur wurde `new` und verlor die Parent-ID. Der Legacy-Stage-2-Code erlaubte
    # ueber `_aratio2 >= 0.10` rund 10x; B373 war damit strenger als der ersetzte Code.
    # Basisfaktor deckt Merge/Split ab (bis ~10 verschmelzende Zellen), der
    # Zeitanteil kommt NUR fuer Radarluecken oberhalb des Normaltakts dazu.
    "ASSOC_MAX_AREA_RATIO_BASE": 10.0,
    "ASSOC_MAX_AREA_GROWTH_PER_MIN": 1.25,
    "ASSOC_NORMAL_FRAME_MINUTES": 5.0,
    # B379: B365-Kernschwaeche. Eine schwache/sterbende Zelle darf sich nicht ueber
    # den vollen MAX_CELL_SPEED_KMH-Radius mit einer entfernten Kontur fortsetzen.
    "ASSOC_WEAK_CORE_THRESHOLD": 0.05,
    "ASSOC_WEAK_MAX_SPEED_KMH": 60.0,
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


def _effective_max_speed(track: TrackCandidate, max_speed_kmh: float) -> float:
    """B379: B365-Semantik — schwache Zellen bekommen einen engeren Suchradius.

    B374 behauptete, B365 sei "in den physikalischen Gates aufgegangen". Das war
    falsch: object_tracking.py uebergab MAX_CELL_SPEED_KMH (150) fuer ALLE Tracks.
    Eine sterbende Zelle (core_ratio unter der Schwelle) konnte sich dadurch ueber
    den vollen Radius mit einer entfernten, unabhaengigen Kontur fortsetzen --
    genau die Fehlzuordnung, die B365 verhindern sollte.

    Die Kostenkomponenten c_core/c_age helfen hier nicht, weil das GATE vorher greift.
    """
    if track.core_ratio < float(_cfg("ASSOC_WEAK_CORE_THRESHOLD")):
        return min(float(max_speed_kmh), float(_cfg("ASSOC_WEAK_MAX_SPEED_KMH")))
    return float(max_speed_kmh)


def _max_area_ratio(dt_minutes: float) -> float:
    """B379: zulaessiges Flaechenverhaeltnis (Merge-/Split-tauglich).

    Basisfaktor deckt den Normalfall inkl. Merge/Split ab. Der zeitabhaengige
    Anteil greift NUR fuer Luecken oberhalb des normalen Radartakts -- bei 5 min
    bleibt es exakt beim Basisfaktor.
    """
    base = float(_cfg("ASSOC_MAX_AREA_RATIO_BASE"))
    normal = float(_cfg("ASSOC_NORMAL_FRAME_MINUTES"))
    extra = max(float(dt_minutes) - normal, 0.0)
    return base * (float(_cfg("ASSOC_MAX_AREA_GROWTH_PER_MIN")) ** extra)


def _predict_track_state_for_gate(track: TrackCandidate, dt_minutes: float, max_speed_kmh: float) -> tuple[float, float]:
    """B379: Praediktion fuer Gate/Kosten mit derselben effektiven Speed-Basis."""
    speed = math.hypot(track.vx_kmh, track.vy_kmh)
    if speed > float(max_speed_kmh) > 0.0:
        scale = float(max_speed_kmh) / speed
        dt_h = max(float(dt_minutes), 0.0) / 60.0
        return (
            track.pred_x_km + track.vx_kmh * scale * dt_h,
            track.pred_y_km + track.vy_kmh * scale * dt_h,
        )
    return predict_track_state(track, dt_minutes)


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
        # B389: isotroper Kreis mit dem WEITEREN Radius (a_km), nicht dem engeren.
        #
        # Der Querradius b_km ist eng, WEIL die Bewegungsrichtung bekannt ist: eine
        # nach Osten ziehende Zelle springt nicht 12 km nach Norden. Diese
        # Einschraenkung setzt den Vektor voraus. Fehlt er, gibt es kein "quer" --
        # die Zelle kann in JEDE Richtung mit voller Geschwindigkeit ziehen.
        #
        # Vorher wurde b_km isotrop verwendet: bei MAX_CELL_SPEED_KMH=150 und
        # dt=5min also 7.62 km statt 14.50 km -- 39 % zu eng, ausgerechnet fuer die
        # Tracks mit der GROESSTEN Positionsunsicherheit:
        #   - jede neue Zelle im zweiten Frame (Kalman noch ohne Geschwindigkeit),
        #   - stationaere, orografisch gebundene Konvektion,
        #   - Tracks ohne Kalman-Filter (vx/vy fehlen im Snapshot).
        # Folge: Match verworfen -> neue ID -> Verlust von Kalman-Zustand, Trend,
        # Lebensdauer und ML-Sequenz.
        #
        # Der Schwach-Cap aus B379 bleibt unberuehrt und wirkt jetzt sogar schaerfer,
        # weil er gegen den richtigen Radius greift (60 km/h -> 7.00 km).
        return (a_km, a_km, 1.0, 0.0)
    return (a_km, b_km, track.vx_kmh / speed, track.vy_kmh / speed)


def passes_physical_gate(track: TrackCandidate, det: DetectionCandidate, dt_minutes: float,
                         max_speed_kmh: float) -> tuple[bool, str]:
    """Harte physikalische Gates. Gibt (ok, Ablehnungsgrund) zurück."""
    # B379: effektive Hoechstgeschwindigkeit beruecksichtigt die Kernstaerke (B365).
    _eff_speed = _effective_max_speed(track, max_speed_kmh)
    px, py = _predict_track_state_for_gate(track, dt_minutes, _eff_speed)
    dx, dy = det.x_km - px, det.y_km - py

    a_km, b_km, ux, uy = _search_radii_km(track, dt_minutes, _eff_speed)
    # Projektion auf Längs-/Querachse der Bewegung.
    along = dx * ux + dy * uy
    cross = -dx * uy + dy * ux
    if (along / max(a_km, 1e-6)) ** 2 + (cross / max(b_km, 1e-6)) ** 2 > 1.0:
        return (False, f"outside_search_ellipse(a={a_km:.1f}km,b={b_km:.1f}km)")

    # B379: Flaechengate muss Merge (Wachstum) und Split (Schrumpfung) zulassen.
    # Es faengt nur noch absurde Verhaeltnisse ab; die Feinbewertung leistet die
    # Kostenkomponente c_area.
    if track.area_px > 0 and det.area_px > 0:
        max_factor = _max_area_ratio(dt_minutes)
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
    # B379: identische Basis wie im Gate — sonst normiert c_pos gegen einen anderen
    # Radius, als das Gate zulaesst.
    _eff_speed = _effective_max_speed(track, max_speed_kmh)
    px, py = _predict_track_state_for_gate(track, dt_minutes, _eff_speed)
    dist_km = math.hypot(det.x_km - px, det.y_km - py)
    a_km, _, ux, uy = _search_radii_km(track, dt_minutes, _eff_speed)

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
    """B401: Hungarian/Kuhn-Munkres mit Potentialen — O(n²m) statt faktoriell.

    Die vorherige Implementierung zaehlte alle Kombinationen und Permutationen
    vollstaendig auf. Fuer das Zuordnungsproblem existiert seit 1955 ein
    O(n^3)-Verfahren; die Aufzaehlung ist um Groessenordnungen schlechter.

    B400 hat den Defekt akut gemacht: Die Matrix waechst durch die Dummy-Spalten von
    n_det x n_trk auf n_det x (n_trk + n_det). Da k = min(n_rows, n_cols) weiterhin
    n_det ist, verdoppelt sich die Basis der Permutation:
        8 Zellen: 40.320 -> 518.918.400 Iterationen   (Faktor 12.870)
       10 Zellen:            670.442.572.800
    Bei der beobachteten Last von 7.78 Zellen je aktivem Frame (Debug 14.07.2026)
    sind das ~17 Minuten pro Frame auf dem Pi 5 -- bei 5-Minuten-Takt ein
    Totalausfall, kein Performanceproblem.

    Der Pfad greift nur ohne scipy und war deshalb nie getestet. Schlaegt der
    scipy-Import auf dem Pi fehl (defektes venv nach install.sh --mode=upgrade,
    ARM-Wheel-Problem), haengt der Radarzyklus stillschweigend.

    Liefert identische Ergebnisse wie scipy.optimize.linear_sum_assignment:
    (row_ind, col_ind), aufsteigend nach row_ind. Erfordert n_rows <= n_cols --
    das ist nach B400 immer erfuellt (n_det <= n_trk + n_det).
    """
    n = len(matrix)
    m = len(matrix[0]) if n else 0
    if n == 0 or m == 0:
        return [], []
    if n > m:
        # Transponieren und Ergebnis zuruecktauschen -- der Algorithmus setzt
        # n <= m voraus.
        transposed = [[matrix[i][j] for i in range(n)] for j in range(m)]
        cols_t, rows_t = _fallback_linear_sum_assignment(transposed)
        order = sorted(range(len(rows_t)), key=lambda k: rows_t[k])
        return [rows_t[k] for k in order], [cols_t[k] for k in order]

    INF = float("inf")
    u = [0.0] * (n + 1)        # Potentiale der Zeilen
    v = [0.0] * (m + 1)        # Potentiale der Spalten
    p = [0] * (m + 1)          # p[j] = der Spalte j zugeordnete Zeile (1-basiert)
    way = [0] * (m + 1)        # Vorgaenger im alternierenden Pfad

    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [INF] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = INF
            j1 = 0
            for j in range(1, m + 1):
                if used[j]:
                    continue
                cur = float(matrix[i0 - 1][j - 1]) - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j] = cur
                    way[j] = j0
                if minv[j] < delta:
                    delta = minv[j]
                    j1 = j
            if delta == INF:
                # Keine zulaessige Erweiterung -- kann bei _INF-gesaettigten Zeilen
                # auftreten. Der Solver bricht hier kontrolliert ab.
                break
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1

    rows, cols = [], []
    for j in range(1, m + 1):
        if p[j] > 0:
            rows.append(p[j] - 1)
            cols.append(j - 1)
    order = sorted(range(len(rows)), key=lambda k: rows[k])
    return [rows[k] for k in order], [cols[k] for k in order]


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

    max_cost = float(_cfg("ASSOC_MAX_COST"))
    unmatched_cost = float(_cfg("ASSOC_UNMATCHED_COST"))
    n_det, n_trk = len(detections), len(tracks)

    # ========================================================================
    # B400: Zu teure Paare VOR der Optimierung ausschliessen und dem Solver eine
    # echte Nicht-Zuordnungs-Option geben.
    #
    # Vorher wurde die Schwelle NACH linear_sum_assignment() geprueft. Der Solver
    # minimiert die GESAMTSUMME und muss jeder Zeile eine Spalte zuweisen -- eine
    # Option "keine Zuordnung" existierte nicht. Ein schlechtes Paar konnte dadurch
    # ein gutes verdraengen:
    #        T1     T2
    #   D1  0.10   0.95     Summe D1->T2 + D2->T1 = 1.15  <-- gewaehlt
    #   D2  0.20   0.99     Summe D1->T1 + D2->T2 = 1.09
    # Wurde D1->T2 danach verworfen, verlor D1 seine Zuordnung -- obwohl D1->T1 mit
    # 0.10 exzellent gewesen waere. Die nachgelagerte Filterung repariert das nicht,
    # weil die Matrix nicht neu geloest wird. Strukturell derselbe Fehler wie beim
    # Greedy-Matching, das B374 beseitigt hat.
    #
    # Jetzt: teure Paare sind unzulaessig (_INF), und jede Detektion erhaelt eine
    # Dummy-Spalte mit ASSOC_UNMATCHED_COST. Der Solver bezieht die Nicht-Zuordnung
    # damit IN die Optimierung ein.
    # ========================================================================
    solve_matrix = [[unmatched_cost for _ in range(n_trk + n_det)] for _ in range(n_det)]
    for i in range(n_det):
        for j in range(n_trk):
            c = float(matrix[i][j])
            # Gegatet ODER ueber der Qualitaetsschwelle -> unzulaessig.
            solve_matrix[i][j] = _INF if (c >= _INF or c > max_cost) else c
        # Dummy-Spalten: jede Detektion darf genau ihre eigene waehlen.
        for j in range(n_trk, n_trk + n_det):
            solve_matrix[i][j] = unmatched_cost if (j - n_trk) == i else _INF

    if _HAS_SCIPY:
        row_ind, col_ind = linear_sum_assignment(solve_matrix)
    else:
        row_ind, col_ind = _fallback_linear_sum_assignment(solve_matrix)

    matched_tracks = set()
    for i, j in zip(row_ind, col_ind):
        det_idx = detections[i].index
        if j >= n_trk:
            # Bewusste Nicht-Zuordnung -- der Solver hat sie der besten verfuegbaren
            # Paarung vorgezogen.
            _best = min((float(matrix[i][k]) for k in range(n_trk)), default=_INF)
            result.rejected_matches.append({
                "detection_index": det_idx, "track_id": None,
                "reason": "no_acceptable_track",
                "cost": None if _best >= _INF else round(_best, 4),
            })
            continue
        trk_id = tracks[j].track_id
        cost = float(matrix[i][j])
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
