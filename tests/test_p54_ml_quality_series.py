"""P54 — ml_quality_series extrahiert Champion(Kinematik)- vs. Challenger(ML)-MAE
je Horizont aus breakdown_by_forecast_mode."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from accuracy_tracker import ml_quality_series

_HIST = [
    {"timestamp_utc": "2026-06-22T08:00:00Z", "breakdown_by_forecast_mode": {
        "10": {"kinematic_fallback": {"mae_km": 7.0, "verified": 40}, "ml": {"mae_km": 9.0, "verified": 25}},
        "30": {"kinematic": {"mae_km": 12.0, "verified": 30}}}},
    {"timestamp_utc": "2026-06-22T09:00:00Z", "breakdown_by_forecast_mode": {
        "10": {"kinematic_fallback": {"mae_km": 6.5, "verified": 42}, "ml": {"mae_km": 6.0, "verified": 28}}}},
]


def test_champion_and_challenger_extracted():
    s = ml_quality_series(_HIST, [10, 30])
    assert s["10"][0]["champion_mae_km"] == 7.0
    assert s["10"][0]["challenger_mae_km"] == 9.0
    assert s["10"][0]["challenger_samples"] == 25
    assert s["10"][1]["challenger_mae_km"] == 6.0


def test_kinematic_fallback_then_kinematic():
    # h30 hat nur 'kinematic' (kein _fallback) -> als Champion verwendet, kein ML -> None
    s = ml_quality_series(_HIST, [30])
    assert s["30"][0]["champion_mae_km"] == 12.0
    assert s["30"][0]["challenger_mae_km"] is None


def test_missing_horizon_yields_none():
    s = ml_quality_series(_HIST, [30])
    assert s["30"][1]["champion_mae_km"] is None  # 2. Record hat kein h30


def test_empty_inputs_are_safe():
    assert ml_quality_series([], [10]) == {"10": []}
    assert ml_quality_series(None, None) == {}


def test_index_is_one_based():
    s = ml_quality_series(_HIST, [10])
    assert [p["idx"] for p in s["10"]] == [1, 2]
