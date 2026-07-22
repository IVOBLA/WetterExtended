"""B456: Cross-Horizont-Konsistenz -- kein Zickzack bei mixed ml/kinematic."""
from math import atan2, pi
import prediction as p
HORIZONS = [10, 20, 30, 40, 60]
XS = {10: 788.0, 20: 792.3, 30: 823.7, 40: 820.2, 60: 848.1}
def _mk_obj(modes):
    obj = {"id": "T1", "x": 780.0, "y": 500.0, "lat": 46.60, "lon": 14.00}
    for h in HORIZONS:
        obj[f"forecast_x_{h}"] = XS[h]; obj[f"forecast_y_{h}"] = 500.0
        obj[f"forecast_lat_{h}"] = 46.60; obj[f"forecast_lon_{h}"] = 14.00 + (XS[h] - 780.0) * 0.001
        obj[f"forecast_mode_{h}"] = modes[h]
    return obj
def _max_seg_jump(obj):
    pts = [(780.0, 500.0)] + [(obj[f"forecast_x_{h}"], obj[f"forecast_y_{h}"]) for h in HORIZONS]
    angs = [(atan2(b[1]-a[1], b[0]-a[0]) * 180.0 / pi) % 360.0 for a, b in zip(pts, pts[1:])]
    jumps = []
    for a1, a2 in zip(angs, angs[1:]):
        d = abs(a1-a2) % 360.0; jumps.append(d if d <= 180.0 else 360.0-d)
    return max(jumps)
def test_mixed_sequence_reversal_is_repaired():
    modes = {10: "ml", 20: "kinematic_fallback", 30: "ml", 40: "kinematic_fallback", 60: "kinematic_fallback"}
    obj = _mk_obj(modes); assert _max_seg_jump(obj) > 45.0
    p._enforce_cross_horizon_consistency(obj, HORIZONS, None)
    assert _max_seg_jump(obj) <= 45.0
    assert obj.get("forecast_consistency_adjusted_40") is True
    assert obj.get("forecast_consistency_adjusted") is True
    assert 823.7 < obj["forecast_x_40"] < 848.1
    assert obj["forecast_x_10"] == 788.0; assert obj["forecast_x_30"] == 823.7
    assert obj["forecast_displacement_km_40"] > 0; assert obj["forecast_speed_kmh_40"] > 0
def test_uniform_ml_sequence_untouched():
    obj = _mk_obj({h: "ml" for h in HORIZONS})
    p._enforce_cross_horizon_consistency(obj, HORIZONS, None)
    assert obj["forecast_x_40"] == 820.2
    assert "forecast_consistency_adjusted_40" not in obj
    assert "forecast_consistency_adjusted" not in obj
def test_forecasts_entry_kept_in_sync():
    modes = {10: "ml", 20: "kinematic_fallback", 30: "ml", 40: "kinematic_fallback", 60: "kinematic_fallback"}
    obj = _mk_obj(modes); entry = {"id": "T1", "x": 820.2, "y": 500.0, "lat": 46.60, "lon": 14.0402}
    forecasts = {h: [] for h in HORIZONS}; forecasts[40] = [entry]
    p._enforce_cross_horizon_consistency(obj, HORIZONS, forecasts)
    assert entry["consistency_adjusted"] is True
    assert entry["x"] == obj["forecast_x_40"]; assert entry["lat"] == obj["forecast_lat_40"]
