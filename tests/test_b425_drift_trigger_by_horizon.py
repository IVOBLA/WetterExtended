"""B425: Der relative Drift-Trigger vergleicht gleiche Horizonte."""
from datetime import datetime, timedelta, timezone

import pytest

import drift_detector as dd


def _record(age_h, values):
    return {
        "timestamp_utc": (datetime.now(timezone.utc) - timedelta(hours=age_h)).isoformat(),
        "horizons": [{"horizon": h, "mae_km": mae} for h, mae in values.items()],
    }


def _run(monkeypatch, recent, baseline):
    monkeypatch.setattr(dd, "_read_history", lambda: recent + baseline)
    monkeypatch.setattr(dd, "DRIFT_MIN_POINTS", 1)
    return dd.check_drift()


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(dd, "_EVAL_DIR", str(tmp_path))
    monkeypatch.setattr(dd, "_STATUS_FILE", str(tmp_path / "drift_status.json"))


def test_live_values_are_improved_at_every_horizon(monkeypatch):
    recent_values = {10: 3.7, 20: 6.5, 30: 9.6, 40: 11.8, 60: 14.8}
    baseline_values = {10: 4.0, 20: 7.9, 30: 11.4, 40: 14.1, 60: 17.0}
    result = _run(monkeypatch, [_record(1, recent_values)], [_record(40, baseline_values)])
    assert result["drift_detected"] is False
    assert result["triggering_horizons"] == []
    assert all(delta < 0 for delta in result["delta_by_horizon"].values())


def test_simpsons_paradox_does_not_trigger(monkeypatch):
    baseline = [_record(40 + index, {10: 4.0}) for index in range(9)] + [_record(60, {60: 17.0})]
    recent = [_record(1, {10: 3.7})] + [_record(2 + index, {60: 14.8}) for index in range(9)]
    old_delta = dd._mean_mae(recent) - dd._mean_mae(baseline)
    result = _run(monkeypatch, recent, baseline)
    assert old_delta > dd.DRIFT_MAE_THRESHOLD_KM
    assert result["delta_by_horizon"] == {10.0: -0.3, 60.0: -2.2}
    assert result["drift_detected"] is False


def test_short_horizon_worsening_triggers(monkeypatch):
    result = _run(monkeypatch, [_record(1, {10: 5.1, 20: 6})], [_record(40, {10: 3, 20: 6})])
    assert result["drift_detected"] is True
    assert result["triggering_horizons"] == [10.0]


def test_long_horizon_worsening_does_not_trigger(monkeypatch):
    result = _run(monkeypatch, [_record(1, {10: 3, 60: 10})], [_record(40, {10: 3, 60: 1})])
    assert result["drift_detected"] is False
    assert result["triggering_horizons"] == []


def test_one_sided_horizon_is_skipped(monkeypatch):
    result = _run(monkeypatch, [_record(1, {10: 3, 60: 20})], [_record(40, {10: 3})])
    assert result["skipped_horizons_not_in_both_windows"] == [60.0]
    assert result["drift_detected"] is False


def test_no_common_horizon_is_explained(monkeypatch):
    result = _run(monkeypatch, [_record(1, {10: 3})], [_record(40, {20: 3})])
    assert result["delta_by_horizon"] == {}
    assert result["delta_km"] is None
    assert "Keine gemeinsamen Kurzhorizonte" in result["message"]


def test_empty_records_are_safe(monkeypatch):
    result = _run(monkeypatch, [], [])
    assert result["drift_detected"] is False
    assert result["mae_recent_by_horizon"] == {}


def test_delta_is_largest_short_horizon_delta_and_maps_are_present(monkeypatch):
    result = _run(monkeypatch, [_record(1, {10: 4, 20: 9, 60: 20})], [_record(40, {10: 3, 20: 5, 60: 1})])
    assert result["delta_km"] == 4.0
    assert result["mae_recent_by_horizon"] == {10.0: 4.0, 20.0: 9.0, 60.0: 20.0}
    assert result["mae_baseline_by_horizon"] == {10.0: 3.0, 20.0: 5.0, 60.0: 1.0}
    assert result["delta_by_horizon"] == {10.0: 1.0, 20.0: 4.0, 60.0: 19.0}


def test_absolute_quality_check_is_unchanged(monkeypatch):
    result = _run(monkeypatch, [_record(1, {10: 10})], [_record(40, {10: 10})])
    assert result["quality_target_met"] is False
    assert result["quality_status"] == "missed"
    assert result["drift_detected"] is False
