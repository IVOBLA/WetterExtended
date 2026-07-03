"""B294: _model_usage_from_accuracy_history darf 0-Sample-Zeilen nicht gewinnen lassen."""
import importlib.util
import os

_SPEC = importlib.util.spec_from_file_location(
    "diagnose_forecast_quality",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "diagnose_forecast_quality.py"),
)
dfq = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(dfq)


def test_latest_zero_sample_row_does_not_win():
    rows = [
        {"timestamp_utc": "2026-07-01T20:00:00Z", "horizon": 10, "samples": 500, "mae_km": 4.6, "hit_rate": 0.11},
        {"timestamp_utc": "2026-07-02T21:50:00Z", "horizon": 10, "samples": 0, "mae_km": None, "hit_rate": None},
    ]
    out = dfq._model_usage_from_accuracy_history(rows)
    assert out["status"] == "available"
    assert out["by_horizon"]["10"]["samples"] == 500
    assert out["by_horizon"]["10"]["mae_km"] == 4.6
    assert out["total_samples"] == 500


def test_total_samples_consistent_with_by_horizon():
    rows = [
        {"timestamp_utc": "2026-07-01T20:00:00Z", "horizon": 10, "samples": 300, "mae_km": 4.0, "hit_rate": 0.1},
        {"timestamp_utc": "2026-07-01T20:00:00Z", "horizon": 20, "samples": 200, "mae_km": 9.0, "hit_rate": 0.05},
        {"timestamp_utc": "2026-07-02T21:50:00Z", "horizon": 10, "samples": 0, "mae_km": None, "hit_rate": None},
        {"timestamp_utc": "2026-07-02T21:50:00Z", "horizon": 20, "samples": 0, "mae_km": None, "hit_rate": None},
    ]
    out = dfq._model_usage_from_accuracy_history(rows)
    assert out["total_samples"] == sum(v["samples"] for v in out["by_horizon"].values())
    assert out["total_samples"] == 500


def test_all_zero_rows_return_not_available():
    rows = [{"timestamp_utc": "2026-07-02T21:50:00Z", "horizon": 10, "samples": 0}]
    out = dfq._model_usage_from_accuracy_history(rows)
    assert out["status"] == "not_available"


def test_newer_nonzero_row_replaces_older_nonzero():
    rows = [
        {"timestamp_utc": "2026-07-01T10:00:00Z", "horizon": 10, "samples": 100, "mae_km": 5.0, "hit_rate": 0.1},
        {"timestamp_utc": "2026-07-01T22:00:00Z", "horizon": 10, "samples": 250, "mae_km": 4.2, "hit_rate": 0.12},
    ]
    out = dfq._model_usage_from_accuracy_history(rows)
    assert out["by_horizon"]["10"]["samples"] == 250
    assert out["by_horizon"]["10"]["mae_km"] == 4.2
