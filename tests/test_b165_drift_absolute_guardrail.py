"""
tests/test_b165_drift_absolute_guardrail.py

B165: Der Drift-Detektor erkennt jetzt auch einen KONSTANT hohen Kurzhorizont-Fehler
(Verletzung der Zieldefinition ≤30 min < 1 km), nicht nur relative Verschlechterung.

_read_history und _has_ml_model werden gemockt; _STATUS_FILE/_EVAL_DIR auf tmp gelenkt.

Ausführbar: python3 -m pytest tests/test_b165_drift_absolute_guardrail.py -v
"""
import importlib
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

sys.modules.setdefault("cv2", SimpleNamespace(imwrite=lambda *args, **kwargs: True))
sys.modules.setdefault("utils", SimpleNamespace(log=lambda *args, **kwargs: None))
dd = importlib.import_module("drift_detector")


def _rec(age_h, horizons):
    ts = (datetime.now(timezone.utc) - timedelta(hours=age_h)).isoformat(timespec="seconds")
    return {"timestamp_utc": ts, "horizons": horizons}


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(dd, "_EVAL_DIR", str(tmp_path), raising=True)
    monkeypatch.setattr(dd, "_STATUS_FILE", str(tmp_path / "drift_status.json"), raising=True)
    monkeypatch.setattr(dd, "_has_ml_model", lambda: True, raising=True)
    yield


def test_absolute_guardrail_fires_on_constant_high_short_horizon(monkeypatch):
    # Konstant ~10 km bei +10/+30 min, KEINE relative Verschlechterung (recent==baseline).
    recent = [_rec(1 + i, [{"horizon": 10, "mae_km": 10.0}, {"horizon": 30, "mae_km": 10.0}]) for i in range(4)]
    baseline = [_rec(40 + i, [{"horizon": 10, "mae_km": 10.0}, {"horizon": 30, "mae_km": 10.0}]) for i in range(4)]
    monkeypatch.setattr(dd, "_read_history", lambda: recent + baseline, raising=True)

    res = dd.check_drift()
    assert res["drift_detected"] is True
    assert res["drift_reason"] in ("absolute", "relative+absolute")
    assert res["mae_recent_short_km"] is not None and res["mae_recent_short_km"] > 1.0
    # relativ stabil → der relative Pfad allein hätte NICHT ausgelöst
    assert (res["delta_km"] or 0.0) <= dd.DRIFT_MAE_THRESHOLD_KM


def test_no_alarm_when_short_horizon_within_target(monkeypatch):
    recent = [_rec(1 + i, [{"horizon": 10, "mae_km": 0.6}, {"horizon": 30, "mae_km": 0.9}]) for i in range(4)]
    baseline = [_rec(40 + i, [{"horizon": 10, "mae_km": 0.6}, {"horizon": 30, "mae_km": 0.9}]) for i in range(4)]
    monkeypatch.setattr(dd, "_read_history", lambda: recent + baseline, raising=True)

    res = dd.check_drift()
    assert res["drift_detected"] is False
    assert res["drift_reason"] is None
    assert res["mae_recent_short_km"] <= dd.DRIFT_MAE_ABS_MAX_KM


def test_long_horizon_does_not_trigger_short_guardrail(monkeypatch):
    # Nur +60 min schlecht; ≤30 min gut → Kurzhorizont-Wächter darf NICHT auslösen.
    recent = [_rec(1 + i, [{"horizon": 10, "mae_km": 0.5}, {"horizon": 60, "mae_km": 9.0}]) for i in range(4)]
    baseline = [_rec(40 + i, [{"horizon": 10, "mae_km": 0.5}, {"horizon": 60, "mae_km": 9.0}]) for i in range(4)]
    monkeypatch.setattr(dd, "_read_history", lambda: recent + baseline, raising=True)

    res = dd.check_drift()
    # Kurzhorizont-MAE (nur +10 min) ist gut → absolute Schwelle nicht verletzt
    assert res["mae_recent_short_km"] <= dd.DRIFT_MAE_ABS_MAX_KM
    assert res["drift_reason"] != "absolute"


def test_no_absolute_alarm_without_ml_model(monkeypatch):
    monkeypatch.setattr(dd, "_has_ml_model", lambda: False, raising=True)
    recent = [_rec(1 + i, [{"horizon": 10, "mae_km": 10.0}]) for i in range(4)]
    baseline = [_rec(40 + i, [{"horizon": 10, "mae_km": 10.0}]) for i in range(4)]
    monkeypatch.setattr(dd, "_read_history", lambda: recent + baseline, raising=True)

    res = dd.check_drift()
    # Ohne ML-Modell (kinematischer Fallback) KEIN absoluter Alarm.
    assert res["drift_reason"] != "absolute"


def test_relative_drift_still_detected(monkeypatch):
    # baseline gut, recent deutlich schlechter → relativer Pfad löst aus.
    recent = [_rec(1 + i, [{"horizon": 60, "mae_km": 8.0}]) for i in range(4)]
    baseline = [_rec(40 + i, [{"horizon": 60, "mae_km": 1.0}]) for i in range(4)]
    monkeypatch.setattr(dd, "_read_history", lambda: recent + baseline, raising=True)

    res = dd.check_drift()
    assert res["drift_detected"] is True
    assert "relative" in (res["drift_reason"] or "")
