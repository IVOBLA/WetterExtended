# orographic_module.py
"""
Orographische Risk-Scores — kombiniert DEM + Tal + Atmosphäre.

  terrain_blocking_score  – Gelände blockiert Zugbahn (0..1)
  orographic_lift_score   – Staulage / Hebung am Hang (0..1)
  stationary_risk         – Risiko "Gewitter bleibt am Berg hängen" (0..1)
  forecast_speed_factor   – Dämpfung für kinematischen Fallback (0.1..1.0)

Das Modell lernt aus Trainingsdaten welche Scores zu Stationärgewittern
führen. Die Scores kodieren physikalische Plausibilität, nicht Regeln.
Angezeigt im Admin-Panel als Diagnose-Felder.
"""
from __future__ import annotations
import math

try:
    from debug_utils import debug_log
except Exception:
    def debug_log(msg):
        print(msg)

_BARRIER_M  = 200.0   # Höhengewinn voraus für blocking=1.0
_SLOPE_TH   = 0.005   # Gradient m/m für signifikanten Stau
_SPEED_TH   = 1.5     # Pixel/Frame — "langsame" Zelle
_CAPE_TH    = 500.0   # J/kg


def _c01(x):
    return max(0.0, min(1.0, x))


def compute_orographic_scores(obj):
    try:
        barrier  = float(obj.get("dem_barrier_ahead",     0.0))
        slope    = float(obj.get("dem_slope_toward_cell", 0.0))
        cape     = float(obj.get("cape",                  0.0))
        confined = float(obj.get("valley_confinement",    0.0))
        vx       = float(obj.get("vx", 0.0))
        vy       = float(obj.get("vy", 0.0))
        speed    = math.hypot(vx, vy)

        barrier_s = _c01(max(0.0, barrier) / _BARRIER_M)
        slope_s   = _c01(max(0.0, slope)   / _SLOPE_TH)
        # Tal fängt die Zelle → reduziert Blocking
        valley_f  = 1.0 - 0.4 * confined
        blocking  = _c01((0.6*barrier_s + 0.4*slope_s) * valley_f)

        cape_f = _c01(cape / _CAPE_TH)
        lift   = _c01(slope_s * (0.5 + 0.5*cape_f))

        speed_f    = _c01(1.0 - speed / max(_SPEED_TH, 0.01))
        stationary = _c01(blocking * (0.5 + 0.5*speed_f))

        speed_factor = round(max(0.1, 1.0 - 0.7*stationary), 3)

        return {
            "terrain_blocking_score": round(blocking,   3),
            "orographic_lift_score":  round(lift,       3),
            "stationary_risk":        round(stationary, 3),
            "forecast_speed_factor":  speed_factor,
        }
    except Exception as exc:
        debug_log(f"[OROGRAPHIC] Fehler: {exc}")
        return {"terrain_blocking_score": 0.0, "orographic_lift_score": 0.0,
                "stationary_risk": 0.0, "forecast_speed_factor": 1.0}


def assign_orographic_scores(objects):
    for obj in objects:
        obj.update(compute_orographic_scores(obj))
    debug_log(f"[OROGRAPHIC] Scores für {len(objects)} Objekte.")
    return objects
