import importlib
import json


def _write_history(tmp_path, by_mode):
    ev = tmp_path / "evaluation"
    ev.mkdir()
    (ev / "accuracy_history.jsonl").write_text(
        json.dumps({"timestamp_utc": "2026-06-20T00:00:00Z", "breakdown_by_forecast_mode": by_mode}) + "\n",
        encoding="utf-8",
    )
    return ev


def _prediction(monkeypatch, tmp_path, by_mode=None, **runtime):
    prediction = importlib.import_module("prediction")
    ev = _write_history(tmp_path, by_mode or {})
    monkeypatch.setitem(prediction.SAVE_PATHS, "evaluation", str(ev))
    def _get(name, default=None):
        return runtime.get(name, default)
    monkeypatch.setattr(prediction, "_runtime_cfg", type("RC", (), {"get": staticmethod(_get)})())
    return prediction


def _stats(ml_mae, kin_mae, ml_n=20, kin_n=20):
    return {
        "ml": {"mae_km": ml_mae, "verified": ml_n},
        "kinematic": {"mae_km": kin_mae, "verified": kin_n},
    }


def test_ml_schlechter_als_kinematik_wird_geblockt(monkeypatch, tmp_path):
    p = _prediction(monkeypatch, tmp_path, {"10": _stats(57.0, 3.9)})
    gate = p._ml_runtime_gate_by_horizon([10], {"runtime_mode": "ml"})
    assert gate[10]["allow_ml"] is False
    assert gate[10]["reason"] == "ml_mae_worse_than_kinematic"


def test_ml_besser_als_kinematik_wird_erlaubt(monkeypatch, tmp_path):
    p = _prediction(monkeypatch, tmp_path, {"10": _stats(3.0, 4.0)})
    gate = p._ml_runtime_gate_by_horizon([10], {"runtime_mode": "ml"})
    assert gate[10]["allow_ml"] is True
    assert gate[10]["reason"] == "ml_mae_better_or_equal"


def test_ml_nur_fuer_10_min_besser(monkeypatch, tmp_path):
    p = _prediction(monkeypatch, tmp_path, {"10": _stats(3.0, 4.0), "20": _stats(10.0, 4.0)})
    gate = p._ml_runtime_gate_by_horizon([10, 20], {"runtime_mode": "ml"})
    assert gate[10]["allow_ml"] is True
    assert gate[20]["allow_ml"] is False


def test_keine_vergleichsdaten_cold_start_ist_kinematik(monkeypatch, tmp_path):
    p = _prediction(monkeypatch, tmp_path, {})
    gate = p._ml_runtime_gate_by_horizon([10], {"runtime_mode": "ml", "fallback_reason": "cold_start_promoted_low_confidence", "low_confidence": True})
    assert gate[10]["allow_ml"] is False
    assert gate[10]["reason"] == "insufficient_comparison_data_cold_or_low_confidence"


def test_force_kinematic_immer_kinematik(monkeypatch, tmp_path):
    p = _prediction(monkeypatch, tmp_path, {"10": _stats(1.0, 99.0)}, ML_FORCE_KINEMATIC=True)
    gate = p._ml_runtime_gate_by_horizon([10, 20], {"runtime_mode": "ml"})
    assert gate[10]["allow_ml"] is False
    assert gate[20]["allow_ml"] is False
    assert gate[10]["reason"] == "force_kinematic"
