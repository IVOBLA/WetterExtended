# tests/test_p53_ml_shadow_verify.py
"""P53 — _accumulate_ml_shadow bucht den ML-Schatten ausschliesslich in by_mode['ml'],
ohne Champion/globale Metriken zu beruehren."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import accuracy_tracker as at
from config import VERIFICATION_TOLERANCE_KM as TOL

_MATCHED = {"lat": 46.5, "lon": 13.5}


def test_close_shadow_counts_as_hit():
    bm = {}
    obj = {"forecast_ml_lat_10": 46.5, "forecast_ml_lon_10": 13.5, "forecast_mode_10": "kinematic_fallback"}
    d = at._accumulate_ml_shadow(bm, obj, 10, _MATCHED, TOL)
    assert d is not None and d <= TOL
    assert bm["ml"]["verified"] == 1 and bm["ml"]["hits"] == 1 and bm["ml"]["samples"] == 1
    assert set(bm.keys()) == {"ml"}  # nur ml-Bucket beruehrt


def test_far_shadow_counts_as_miss():
    bm = {}
    obj = {"forecast_ml_lat_10": 47.6, "forecast_ml_lon_10": 14.6, "forecast_mode_10": "kinematic_fallback"}
    d = at._accumulate_ml_shadow(bm, obj, 10, _MATCHED, TOL)
    assert d > TOL
    assert bm["ml"]["verified"] == 1 and bm["ml"]["hits"] == 0


def test_no_shadow_fields_is_noop():
    bm = {}
    assert at._accumulate_ml_shadow(bm, {"forecast_mode_10": "kinematic_fallback"}, 10, _MATCHED, TOL) is None
    assert bm == {}


def test_delivered_ml_is_skipped():
    bm = {}
    obj = {"forecast_ml_lat_10": 46.5, "forecast_ml_lon_10": 13.5, "forecast_mode_10": "ml"}
    assert at._accumulate_ml_shadow(bm, obj, 10, _MATCHED, TOL) is None
    assert bm == {}


def test_no_match_is_noop():
    bm = {}
    obj = {"forecast_ml_lat_10": 46.5, "forecast_ml_lon_10": 13.5}
    assert at._accumulate_ml_shadow(bm, obj, 10, None, TOL) is None
    assert bm == {}


def test_bucket_schema_matches_finish():
    # by_mode['ml'] muss dieselben Keys tragen wie _finish erwartet (sum_km/verified).
    bm = {}
    at._accumulate_ml_shadow(bm, {"forecast_ml_lat_10": 46.5, "forecast_ml_lon_10": 13.5}, 10, _MATCHED, TOL)
    for key in ("samples", "verified", "hits", "missed", "no_target_frame", "sum_km", "sum_km2"):
        assert key in bm["ml"]
