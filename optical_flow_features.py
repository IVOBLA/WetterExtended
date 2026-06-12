# optical_flow_features.py
"""
Berechnet Lucas-Kanade Optical-Flow-Bewegungsfelder zwischen aufeinander-
folgenden Radarbildern via pysteps und weist jedem Objekt 4 Features zu:
  of_vx, of_vy    — Flow-Vektor am Objektzentrum (original Pixeleinheiten/Frame)
  of_speed        — Betrag des Flow-Vektors
  of_divergence   — lokale Divergenz aus 3×3 Nachbarschaft (Indikator für
                    konvergente/divergente Strömung → Intensivierung)

Fällt pysteps nicht installiert oder ein Bild fehlt, werden alle Werte
auf 0.0 gesetzt (of_available=0) — das Modell lernt dies als "fehlend".
"""

import os
import importlib.util
from debug_utils import debug_log

_pysteps_ok = importlib.util.find_spec("pysteps") is not None
_np_ok = importlib.util.find_spec("numpy") is not None


def _load_gray(path: str):
    """Lädt Radarbild als float32-Graustufen-Array (normiert 0..1)."""
    try:
        import cv2
        import numpy as np
        img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            return None
        return img.astype("float32") / 255.0
    except Exception as e:
        debug_log(f"[OPTFLOW] Bild konnte nicht geladen werden ({path}): {e}")
        return None


def _zero_flow(objects: list) -> list:
    """Setzt alle OF-Features auf 0 (Fallback)."""
    for obj in objects:
        obj.update({"of_vx": 0.0, "of_vy": 0.0, "of_speed": 0.0,
                    "of_divergence": 0.0, "of_available": 0})
    return objects


def assign_optical_flow_to_objects(
    objects: list,
    prev_radar_path: str,
    curr_radar_path: str,
) -> list:
    """
    Berechnet das Lucas-Kanade Optical-Flow-Feld zwischen zwei skalierten
    Radarbildern und weist jedem Objekt den lokalen Bewegungsvektor zu.

    Parameter
    ---------
    objects          : Liste der aktuell erkannten Objekte (dicts mit "x","y")
    prev_radar_path  : Pfad zum vorherigen skalierten Radarbild (data/radar/...)
    curr_radar_path  : Pfad zum aktuellen skalierten Radarbild (data/radar/...)

    Objekt-Koordinaten (x, y) liegen in ORIGINAL-Pixeln vor dem Upscaling.
    Die Radarbilder in data/radar/ sind bereits SKALIERT (UPSCALE_FACTOR).
    Der Flow wird auf den skalierten Bildern berechnet und auf Original-
    Pixeleinheiten zurückgerechnet (/ UPSCALE_FACTOR).
    """
    if not objects:
        return objects

    if not _pysteps_ok or not _np_ok:
        debug_log("[OPTFLOW] pysteps/numpy nicht verfügbar — Fallback auf 0")
        return _zero_flow(objects)

    if not prev_radar_path or not os.path.exists(prev_radar_path):
        debug_log("[OPTFLOW] Vorheriges Radarbild fehlt — Fallback auf 0")
        return _zero_flow(objects)

    import numpy as np
    try:
        from pysteps.motion.lucaskanade import dense_lucaskanade
    except ImportError as e:
        debug_log(f"[OPTFLOW] Import-Fehler: {e}")
        return _zero_flow(objects)

    prev = _load_gray(prev_radar_path)
    curr = _load_gray(curr_radar_path)
    if prev is None or curr is None:
        return _zero_flow(objects)

    # pysteps erwartet Stack (N, H, W); NaN für fehlende Regenwerte
    try:
        stack = np.stack([prev, curr], axis=0)
        # Schwache Pixel (< 1 %) als NaN markieren → pysteps ignoriert sie
        stack = np.where(stack < 0.01, np.nan, stack)
        UV = dense_lucaskanade(stack)          # → (2, H, W)
        U, V = UV[0], UV[1]                    # U = x-Richtung, V = y-Richtung
    except Exception as e:
        debug_log(f"[OPTFLOW] Lucas-Kanade Fehler: {e}")
        return _zero_flow(objects)

    from config import UPSCALE_FACTOR
    import cv2
    h_flow, w_flow = U.shape

    # P-M01: Divergenzfeld EINMALIG pro Frame (skalierte px-Einheiten).
    # ETITAN/TRC: feldbasierte Bewegung statt Schwerpunktverschiebung.
    with np.errstate(invalid="ignore"):
        _U_filled = np.nan_to_num(U, nan=0.0)
        _V_filled = np.nan_to_num(V, nan=0.0)
        _dUdx = np.gradient(_U_filled, axis=1)
        _dVdy = np.gradient(_V_filled, axis=0)
    DIVF = _dUdx + _dVdy  # skaliert; /UPSCALE_FACTOR erst bei Auslesung

    for obj in objects:
        # Objektzentrum in skaliertem Koordinatensystem (nur Fallback)
        cx = int(obj.get("x", 0) * UPSCALE_FACTOR)
        cy = int(obj.get("y", 0) * UPSCALE_FACTOR)
        cx = max(1, min(cx, w_flow - 2))
        cy = max(1, min(cy, h_flow - 2))

        vx_scaled = float("nan")
        vy_scaled = float("nan")
        div_scaled = float("nan")
        _used_area = 0

        # ── P-M01: Flächenmittel des Flussfeldes über die Zellkontur ──
        # obj["contour"] liegt in SKALIERTEN Pixeln vor (= U/V-Koordinaten).
        # Nur gültige (nicht-NaN) Flow-Pixel innerhalb des Polygons werden
        # gemittelt → der Merge-Schwerpunkt (oft Reflektivitätslücke = NaN)
        # verfälscht den Vektor nicht mehr.
        _contour = obj.get("contour")
        if _contour:
            try:
                _cnt = np.asarray(_contour, dtype=np.int32).reshape(-1, 1, 2)
                _poly_mask = np.zeros((h_flow, w_flow), dtype=np.uint8)
                cv2.fillPoly(_poly_mask, [_cnt], 1)
                _sel = (_poly_mask > 0) & np.isfinite(U) & np.isfinite(V)
                if int(np.count_nonzero(_sel)) > 0:
                    vx_scaled = float(np.mean(U[_sel]))
                    vy_scaled = float(np.mean(V[_sel]))
                    div_scaled = float(np.mean(DIVF[_sel]))
                    _used_area = 1
            except Exception:
                _used_area = 0

        # Fallback: Punktabtastung am Zentrum (Altverhalten) NUR wenn das
        # Polygon keine gültigen Flow-Pixel lieferte.
        if _used_area == 0:
            _pv = float(U[cy, cx])
            _pw = float(V[cy, cx])
            if np.isfinite(_pv) and np.isfinite(_pw):
                vx_scaled = _pv
                vy_scaled = _pw
                _du_dx = (float(U[cy, cx + 1]) - float(U[cy, cx - 1])) / 2.0
                _dv_dy = (float(V[cy + 1, cx]) - float(V[cy - 1, cx])) / 2.0
                div_scaled = _du_dx + _dv_dy

        # Kein gültiger Vektor (weder Fläche noch Zentrum) → als "fehlend"
        # markieren (of_available=0). P-M02 nutzt of_available als Gate.
        if not (np.isfinite(vx_scaled) and np.isfinite(vy_scaled)):
            obj["of_vx"] = 0.0
            obj["of_vy"] = 0.0
            obj["of_speed"] = 0.0
            obj["of_divergence"] = 0.0
            obj["of_available"] = 0
            continue

        # Auf original Pixeleinheiten umrechnen
        vx = vx_scaled / UPSCALE_FACTOR
        vy = vy_scaled / UPSCALE_FACTOR
        speed = float(np.hypot(vx, vy))
        divergence = (float(div_scaled) / UPSCALE_FACTOR) if np.isfinite(div_scaled) else 0.0

        obj["of_vx"] = round(vx, 4)
        obj["of_vy"] = round(vy, 4)
        obj["of_speed"] = round(speed, 4)
        obj["of_divergence"] = round(divergence, 6)
        obj["of_available"] = 1

    debug_log(f"[OPTFLOW] Optical Flow zugewiesen für {len(objects)} Objekte")
    return objects
