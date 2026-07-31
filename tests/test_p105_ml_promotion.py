import json

from ml_promotion import evaluate_ml_candidate, write_active_manifest


def _rows(candidate=.5, kinematic=1.0, active=.9, count=24):
    return [{"case_key": f"gold-{i}", "horizon_min": 10, "event_id": f"event-{i}",
             "cell_id": f"cell-{i}", "verification_state": "final",
             "eligible_for_model_tuning": True, "match_class": "exact_id",
             "candidate_error_km": candidate, "kinematic_error_km": kinematic,
             "active_ml_error_km": active} for i in range(count)]


def test_ml_candidate_active_ml_and_kinematic_share_sample_set_id():
    result = evaluate_ml_candidate(_rows(), candidate_version="v2", active_version="v1", minimum_samples={"10": 20})
    h = result["by_horizon"]["10"]
    assert h["candidate_vs_active_ml"]["sample_set_id"] == h["candidate_vs_kinematic"]["sample_set_id"]
    assert h["candidate_vs_active_ml"]["case_keys"] == h["candidate_vs_kinematic"]["case_keys"]


def test_equal_and_tiny_improvement_are_never_promoted():
    equal = evaluate_ml_candidate(_rows(candidate=1, kinematic=1, active=1), candidate_version="v2", active_version="v1", minimum_samples={"10": 20})
    tiny = evaluate_ml_candidate(_rows(candidate=.999, kinematic=1, active=1), candidate_version="v2", active_version="v1", minimum_samples={"10": 20})
    assert equal["by_horizon"]["10"]["state"] != "promoted"
    assert tiny["by_horizon"]["10"]["state"] != "promoted"


def test_cold_start_and_coverage_guard():
    cold = evaluate_ml_candidate(_rows(candidate=1, kinematic=1), candidate_version="v1", active_version=None, minimum_samples={"10": 20})
    assert cold["by_horizon"]["10"]["state"] != "promoted"
    rows = _rows(); rows[0].pop("candidate_error_km")
    coverage = evaluate_ml_candidate(rows, candidate_version="v2", active_version="v1", minimum_samples={"10": 20})
    assert coverage["by_horizon"]["10"]["state"] == "rejected"


def test_manifest_routes_only_promoted_versions(tmp_path):
    result = evaluate_ml_candidate(_rows(), candidate_version="v2", active_version="v1", minimum_samples={"10": 20})
    manifest = write_active_manifest(tmp_path / "active.json", result)
    assert manifest["schema"] == "wetterextended.active-forecast-models.v1"
    assert manifest["by_horizon"]["10"] == {"mode": "ml", "model_version": "v2", "family": "lgbm"}
    assert json.loads((tmp_path / "active.json").read_text())["source_hash"].startswith("sha256:")
