"""
B314: Adaptiver Fallback-Schwellwert fuer das ML-Runtime-Gate. Wird die Standard-
Schwelle (ML_RUNTIME_MIN_SAMPLES_PER_MODE) in keiner accuracy_history-Zeile erreicht,
greift ein niedrigerer Fallback-Schwellwert (ML_RUNTIME_MIN_SAMPLES_FALLBACK), damit
ML in datenarmen Phasen nicht dauerhaft blockiert bleibt.
"""
import json
import pytest

pred = pytest.importorskip("prediction")
accuracy_tracker = pytest.importorskip("accuracy_tracker")


@pytest.fixture(autouse=True)
def _disable_runtime_config(monkeypatch):
    monkeypatch.setattr(pred, "_runtime_cfg", None)


def _write_history(tmp_path, rows):
    ev_dir = tmp_path / "evaluation"
    ev_dir.mkdir(parents=True, exist_ok=True)
    p = ev_dir / "accuracy_history.jsonl"
    with p.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return ev_dir


def test_standard_threshold_used_when_available(monkeypatch, tmp_path):
    ev_dir = _write_history(tmp_path, [
        {"breakdown_by_forecast_mode": {"10": {"ml": {"verified": 25, "mae_km": 1.7}}}},
    ])
    monkeypatch.setitem(pred.SAVE_PATHS, "evaluation", str(ev_dir))
    monkeypatch.setattr(accuracy_tracker, "get_runtime_kinematic_mae_by_horizon",
                         lambda min_samples: {"10": {"kinematic_mae": 2.6, "kinematic_samples": 30}})
    result = pred._latest_runtime_mae_by_horizon(min_samples=20)
    assert "10" in result
    assert result["10"]["ml_samples"] == 25
    assert "reduced_sample_threshold" not in result["10"]


def test_fallback_kicks_in_when_standard_never_met(monkeypatch, tmp_path):
    # Nur 5 ML-Samples in jeder Zeile -> Standardschwelle (20) nie erreicht.
    ev_dir = _write_history(tmp_path, [
        {"breakdown_by_forecast_mode": {"10": {"ml": {"verified": 5, "mae_km": 1.7}}}},
        {"breakdown_by_forecast_mode": {"10": {"ml": {"verified": 5, "mae_km": 1.8}}}},
    ])
    monkeypatch.setitem(pred.SAVE_PATHS, "evaluation", str(ev_dir))
    monkeypatch.setattr(accuracy_tracker, "get_runtime_kinematic_mae_by_horizon",
                         lambda min_samples: {"10": {"kinematic_mae": 2.6, "kinematic_samples": 30}})
    result = pred._latest_runtime_mae_by_horizon(min_samples=20)
    assert "10" in result
    assert result["10"]["reduced_sample_threshold"] is True
    assert result["10"]["ml_samples"] == 5


def test_fallback_disabled_when_zero(monkeypatch, tmp_path):
    ev_dir = _write_history(tmp_path, [
        {"breakdown_by_forecast_mode": {"10": {"ml": {"verified": 3, "mae_km": 1.7}}}},
    ])
    monkeypatch.setitem(pred.SAVE_PATHS, "evaluation", str(ev_dir))
    monkeypatch.setattr(pred, "_STATIC_ML_RUNTIME_MIN_SAMPLES_FALLBACK", 0)
    monkeypatch.setattr(accuracy_tracker, "get_runtime_kinematic_mae_by_horizon",
                         lambda min_samples: {"10": {"kinematic_mae": 2.6, "kinematic_samples": 30}})
    result = pred._latest_runtime_mae_by_horizon(min_samples=20)
    assert "10" not in result


def test_fallback_still_respects_its_own_minimum(monkeypatch, tmp_path):
    # 1 Sample ist auch fuer den Fallback (Default 5) zu wenig.
    ev_dir = _write_history(tmp_path, [
        {"breakdown_by_forecast_mode": {"10": {"ml": {"verified": 1, "mae_km": 1.7}}}},
    ])
    monkeypatch.setitem(pred.SAVE_PATHS, "evaluation", str(ev_dir))
    monkeypatch.setattr(accuracy_tracker, "get_runtime_kinematic_mae_by_horizon",
                         lambda min_samples: {"10": {"kinematic_mae": 2.6, "kinematic_samples": 30}})
    result = pred._latest_runtime_mae_by_horizon(min_samples=20)
    assert "10" not in result
