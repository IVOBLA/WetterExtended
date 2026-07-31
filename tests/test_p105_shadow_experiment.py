import json

import config
from experiment_contract import evaluate_paired_cases
from prediction import compute_kinematic_forecast


def _object():
    return {"id": "o1", "cell_id": "c1", "lat": 46.0, "lon": 14.0, "x": 0, "y": 0,
            "history": [{"timestamp": "2026-07-31_00-00-00", "x": 0, "y": 0},
                        {"timestamp": "2026-07-31_00-05-00", "x": 1, "y": 0}]}


def test_kinematic_candidate_is_computed_without_runtime_patch(monkeypatch):
    import prediction
    monkeypatch.setattr(prediction._runtime_cfg, "patch", lambda _: (_ for _ in ()).throw(AssertionError()))
    low = compute_kinematic_forecast(_object(), 10, {}, {"KINEMATIC_EWMA_ALPHA": .3})
    high = compute_kinematic_forecast(_object(), 10, {}, {"KINEMATIC_EWMA_ALPHA": .9})
    assert low["lat"] == high["lat"]  # ein Intervall, aber beide real berechnet


def test_parameter_target_system_mapping_is_explicit():
    assert config.AUTONOMOUS_TUNING_PARAMS["STEERING_BLEND_WEIGHT"]["target_system"] == "kinematic"
    assert config.AUTONOMOUS_TUNING_PARAMS["OF_MAX_FRAME_INTERVAL_MIN"]["target_system"] == "kinematic"


def test_duplicate_case_keys_are_rejected():
    row = {"case_key": "same", "horizon_min": 10, "event_id": "e", "cell_id": "c",
           "incumbent_error_km": 2.0, "candidate_error_km": 1.0}
    assert evaluate_paired_cases([row, dict(row)], {"10": 1})["reason"] == "duplicate_case_key"


def test_default_switches_are_off():
    assert config.AUTONOMOUS_TUNING_ENABLED is False
    assert config.FORECAST_EXPERIMENTS_ENABLED is False
