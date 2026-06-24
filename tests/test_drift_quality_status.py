"""Regressionstests für getrennte Drift- und Qualitätsziel-Logik."""
import importlib
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

sys.modules.setdefault("cv2", SimpleNamespace(imwrite=lambda *args, **kwargs: True))
sys.modules.setdefault("utils", SimpleNamespace(log=lambda *args, **kwargs: None))
dd = importlib.import_module("drift_detector")


def _rec(age_h, mae, short=None):
    ts = (datetime.now(timezone.utc) - timedelta(hours=age_h)).isoformat(timespec="seconds")
    horizons = [{"horizon": 60, "mae_km": mae}]
    if short is not None:
        horizons.append({"horizon": 10, "mae_km": short})
    return {"timestamp_utc": ts, "horizons": horizons}


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(dd, "_EVAL_DIR", str(tmp_path), raising=True)
    monkeypatch.setattr(dd, "_STATUS_FILE", str(tmp_path / "drift_status.json"), raising=True)
    monkeypatch.setattr(dd, "_has_ml_model", lambda: True, raising=True)
    monkeypatch.setattr(dd, "DRIFT_MIN_POINTS", 1, raising=True)
    yield


def test_improvement_with_missed_quality_target_is_not_drift(monkeypatch):
    recent = [_rec(1, 14, 8), _rec(2, 8, 8)]  # Gesamt-MAE 11, short 8
    baseline = [_rec(40, 20), _rec(41, 20)]
    monkeypatch.setattr(dd, "_read_history", lambda: recent + baseline, raising=True)
    monkeypatch.setattr(dd, "DRIFT_MAE_ABS_MAX_KM", 1.0, raising=True)

    res = dd.check_drift()

    assert res["drift_detected"] is False
    assert res["model_status"] == "improved"
    assert res["quality_target_met"] is False
    assert res["quality_status"] == "missed"


def test_relative_worsening_over_threshold_is_drift(monkeypatch):
    recent = [_rec(1, 14), _rec(2, 14)]
    baseline = [_rec(40, 10), _rec(41, 10)]
    monkeypatch.setattr(dd, "_read_history", lambda: recent + baseline, raising=True)
    monkeypatch.setattr(dd, "DRIFT_MAE_THRESHOLD_KM", 2.0, raising=True)

    res = dd.check_drift()

    assert res["drift_detected"] is True
    assert res["model_status"] == "drift"
    assert res["drift_reason"] == "relative"


def test_small_worsening_within_threshold_is_stable(monkeypatch):
    recent = [_rec(1, 10.5), _rec(2, 10.5)]
    baseline = [_rec(40, 10), _rec(41, 10)]
    monkeypatch.setattr(dd, "_read_history", lambda: recent + baseline, raising=True)
    monkeypatch.setattr(dd, "DRIFT_MAE_THRESHOLD_KM", 2.0, raising=True)

    res = dd.check_drift()

    assert res["drift_detected"] is False
    assert res["model_status"] == "stable"
