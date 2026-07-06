"""
B306: forecast_speed_factor wird nur bei tatsaechlich terrain-geblockten Zellen
(terrain_blocking_score >= Schwelle) gedaempft. Frei ziehende Zellen mit
niedrigem Blocking-Score erhalten speed_factor=1.0. Die Untergrenze fuer
gedaempfte Zellen liegt bei 0.4 (statt vormals 0.1).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import orographic_module as om


def test_low_blocking_cell_gets_no_speed_damping():
    # barrier=60 -> barrier_s=0.3 -> blocking=0.18 (< 0.3 Schwelle), Zelle steht still
    # (vx=vy=0), stationary waere im ALTEN Code trotzdem > 0 -> Bug-Reproduktion.
    obj = {"dem_barrier_ahead": 60.0, "dem_slope_toward_cell": 0.0, "cape": 0.0,
           "valley_confinement": 0.0, "vx": 0.0, "vy": 0.0}
    scores = om.compute_orographic_scores(obj)
    assert scores["terrain_blocking_score"] < 0.3
    assert scores["forecast_speed_factor"] == 1.0, "gering geblockte Zelle darf nicht gedaempft werden"


def test_strongly_blocked_stationary_cell_is_damped_but_floored_at_04():
    # barrier=200 -> barrier_s=1.0, slope=0.01 -> slope_s=1.0, blocking=1.0, still.
    obj = {"dem_barrier_ahead": 200.0, "dem_slope_toward_cell": 0.01, "cape": 0.0,
           "valley_confinement": 0.0, "vx": 0.0, "vy": 0.0}
    scores = om.compute_orographic_scores(obj)
    assert scores["terrain_blocking_score"] == 1.0
    # alte Formel ergaebe 0.3 (max(0.1, 1-0.7*1.0)) -> neue Untergrenze 0.4 muss greifen
    assert scores["forecast_speed_factor"] == 0.4


def test_reported_cell_pib5z4cb_case_no_longer_dampened_when_blocking_low():
    # Reproduktion des Report-Befunds: maessiges stationary_risk (~0.2) bei niedrigem
    # Blocking-Score darf nach dem Fix nicht mehr zu einem Abschlag fuehren.
    obj = {"dem_barrier_ahead": 40.0, "dem_slope_toward_cell": 0.0, "cape": 0.0,
           "valley_confinement": 0.0, "vx": 0.0, "vy": 0.0}
    scores = om.compute_orographic_scores(obj)
    assert scores["terrain_blocking_score"] < 0.3
    assert scores["forecast_speed_factor"] == 1.0


def test_runtime_override_threshold(monkeypatch):
    class _Stub:
        @staticmethod
        def get(name, default=None):
            return {"OROGRAPHIC_BLOCKING_MIN_FOR_DAMPING": 0.0}.get(name, default)
    monkeypatch.setattr(om, "_runtime_cfg", _Stub())
    # Mit Schwelle 0.0 wird selbst eine gering geblockte Zelle gedaempft.
    obj = {"dem_barrier_ahead": 60.0, "dem_slope_toward_cell": 0.0, "cape": 0.0,
           "valley_confinement": 0.0, "vx": 0.0, "vy": 0.0}
    scores = om.compute_orographic_scores(obj)
    assert scores["forecast_speed_factor"] < 1.0


def test_runtime_override_floor(monkeypatch):
    class _Stub:
        @staticmethod
        def get(name, default=None):
            return {"OROGRAPHIC_SPEED_FACTOR_FLOOR": 0.5}.get(name, default)
    monkeypatch.setattr(om, "_runtime_cfg", _Stub())
    obj = {"dem_barrier_ahead": 200.0, "dem_slope_toward_cell": 0.01, "cape": 0.0,
           "valley_confinement": 0.0, "vx": 0.0, "vy": 0.0}
    scores = om.compute_orographic_scores(obj)
    assert scores["forecast_speed_factor"] == 0.5


def test_assign_orographic_scores_still_works_end_to_end():
    objs = [{"dem_barrier_ahead": 0.0, "dem_slope_toward_cell": 0.0, "cape": 0.0,
             "valley_confinement": 0.0, "vx": 5.0, "vy": 0.0}]
    out = om.assign_orographic_scores(objs)
    assert out[0]["forecast_speed_factor"] == 1.0
