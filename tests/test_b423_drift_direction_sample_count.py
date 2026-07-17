"""B423: P71 liest die von accuracy_tracker geschriebene Sample-Zahl ``count``."""

import importlib
import sys
from types import SimpleNamespace

import pytest

sys.modules.setdefault("cv2", SimpleNamespace(imwrite=lambda *args, **kwargs: True))
sys.modules.setdefault("utils", SimpleNamespace(log=lambda *args, **kwargs: None))
dd = importlib.import_module("drift_detector")


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(dd, "_EVAL_DIR", str(tmp_path), raising=True)
    monkeypatch.setattr(dd, "_STATUS_FILE", str(tmp_path / "drift_status.json"), raising=True)


def _check(monkeypatch, *, direction=None, speed=None):
    record = {}
    if direction is not None:
        record["direction_stats_by_horizon"] = {"10": direction}
    if speed is not None:
        record["speed_stats_by_horizon"] = {"10": speed}
    monkeypatch.setattr(dd, "_read_history", lambda: [record], raising=True)
    return dd.check_drift()


def test_live_direction_count_triggers_alarm(monkeypatch):
    result = _check(monkeypatch, direction={
        "count": 435,
        "p90_direction_error_deg": 106.9,
        "median_direction_error_deg": 29.4,
    })

    assert result["direction_drift_alarm"] is True
    assert "10" in result["direction_drift_by_horizon"]


def test_live_speed_count_triggers_alarm(monkeypatch):
    result = _check(monkeypatch, speed={
        "count": 435,
        "p90_speed_error_kmh": 106.9,
        "median_speed_error_kmh": 29.4,
    })

    assert result["speed_drift_alarm"] is True
    assert "10" in result["speed_drift_by_horizon"]


def test_count_below_minimum_keeps_gate_closed(monkeypatch):
    result = _check(monkeypatch, direction={"count": 19, "p90_direction_error_deg": 106.9})

    assert result["direction_drift_alarm"] is False


def test_count_above_minimum_below_threshold_does_not_alarm(monkeypatch):
    result = _check(monkeypatch, direction={"count": 435, "p90_direction_error_deg": 89.9})

    assert result["direction_drift_alarm"] is False


@pytest.mark.parametrize("sample_key", ["samples", "n"])
def test_legacy_sample_keys_still_trigger_alarm(monkeypatch, sample_key):
    result = _check(monkeypatch, direction={sample_key: 435, "p90_direction_error_deg": 106.9})

    assert result["direction_drift_alarm"] is True


@pytest.mark.parametrize("stats", [{}, {"count": None, "p90_direction_error_deg": 106.9}])
def test_missing_or_none_count_does_not_alarm(monkeypatch, stats):
    result = _check(monkeypatch, direction=stats)

    assert result["direction_drift_alarm"] is False
