import json
import math
import uuid
from datetime import datetime, timedelta, timezone

import pytest

import config
from experiment_contract import LOCAL_ANALYSIS_SCHEMA, evaluate_paired_cases, validate_tuning_proposals
from tools.run_local_analysis import extract_payload, validate_payload
import tools.tuning_apply as ta


# B514: alle fuenf Finding-Objekte sind Pflicht.
_VALID_FINDING = {
    "current_quality": "unklar", "distance_to_target": None,
    "dominant_error_class": "unknown", "evidence": [],
    "last_attempted_improvement": None, "result": "plateau",
    "next_falsifiable_action": "Naechsten Export gegen denselben Gold-Snapshot messen",
    "eligible_for_autonomous_experiment": False,
    "affected_horizons": [10],
    "expected_metric_change": {"metric": "mae_km", "direction": "decrease", "minimum_change": 0.05},
}


def _payload(**proposal_changes):
    proposal = {
        "experiment_id": str(uuid.uuid4()), "target_system": "kinematic",
        "target_horizons": [10], "parameter": "KINEMATIC_EWMA_ALPHA",
        "old_value": 0.6, "new_value": 0.55, "code_ref": "prediction.py:_append_kinematic",
        "evidence_refs": ["case:1"], "expected_effect": "MAE sinkt um mindestens 0.05 km",
        "minimum_paired_samples": {"10": 2}, "maximum_runtime_hours": 48,
    }
    proposal.update(proposal_changes)
    return {"schema": LOCAL_ANALYSIS_SCHEMA, "analysis_run_id": str(uuid.uuid4()),
            "source_snapshot_id": "sha256:a", "git_commit": "abc", "result_id": str(uuid.uuid4()),
            "generated_at_utc": "2026-07-31T12:00:00Z", "zusammenfassung": "x", "fehler": [],
            "loesungen": [], "verbesserungen": [], "prompts": [], "tuning_proposals": [proposal],
            **{name: dict(_VALID_FINDING) for name in ("verification_findings", "tracking_lineage_findings", "kinematic_findings", "ml_model_findings", "routing_findings")}}


def test_tuning_proposals_survive_validate_and_extract_payload():
    payload = _payload()
    assert validate_payload(payload)["tuning_proposals"] == payload["tuning_proposals"]
    outer = json.dumps({"result": json.dumps(payload)})
    assert extract_payload(outer)["tuning_proposals"] == payload["tuning_proposals"]


def test_strict_proposal_rejects_unknown_bool_nonfinite_and_old_mismatch():
    current = lambda _: 0.6
    validate_tuning_proposals(_payload(), config.AUTONOMOUS_TUNING_PARAMS, current, {10})
    for changes in ({"surprise": 1}, {"new_value": True}, {"new_value": math.inf}, {"old_value": .65}):
        with pytest.raises(ValueError):
            validate_tuning_proposals(_payload(**changes), config.AUTONOMOUS_TUNING_PARAMS, current, {10})


def test_one_parameter_experiment_only():
    payload = _payload()
    payload["tuning_proposals"].append(dict(payload["tuning_proposals"][0], experiment_id=str(uuid.uuid4())))
    with pytest.raises(ValueError):
        validate_tuning_proposals(payload, config.AUTONOMOUS_TUNING_PARAMS, lambda _: .6, {10})


def _cases(candidate_delta, count=20):
    return [{"case_key": str(i), "horizon_min": 10, "event_id": f"e{i // 2}",
             "cell_id": f"c{i // 2}", "incumbent_error_km": 2.0,
             "candidate_error_km": 2.0 + candidate_delta} for i in range(count)]


def test_decision_requires_margin_and_confidence_without_rounding():
    assert evaluate_paired_cases(_cases(-.01), {"10": 20})["state"] == "plateau"
    assert evaluate_paired_cases(_cases(-.2), {"10": 20})["state"] == "improved"
    assert evaluate_paired_cases(_cases(.001), {"10": 20})["state"] == "rejected"


def test_missing_and_nonfinite_measurements_abort_without_sentinel():
    assert evaluate_paired_cases([], {"10": 1})["state"] == "invalid_measurement"
    cases = _cases(-.2)
    cases[0]["candidate_error_km"] = math.inf
    assert evaluate_paired_cases(cases, {"10": 1})["state"] == "invalid_measurement"


def test_apply_creates_shadow_and_never_patches_runtime(tmp_path, monkeypatch):
    payload = _payload()
    started = datetime.fromisoformat(payload["generated_at_utc"].replace("Z", "+00:00")) - timedelta(seconds=1)
    status = {k: payload[k] for k in ("analysis_run_id", "source_snapshot_id", "git_commit", "result_id")}
    status.update({"state": "ok", "run_started_at_utc": started.strftime("%Y-%m-%dT%H:%M:%SZ")})
    for name, value in (("analysis_result.json", payload), ("local_analysis_status.json", status)):
        (tmp_path / name).write_text(json.dumps(value))
    monkeypatch.setattr(ta, "RESULT_FILE", tmp_path / "analysis_result.json")
    monkeypatch.setattr(ta, "STATUS_FILE", tmp_path / "local_analysis_status.json")
    monkeypatch.setattr(ta, "STATE_FILE", tmp_path / "tuning_state.json")
    monkeypatch.setattr(ta, "HISTORY_FILE", tmp_path / "history.jsonl")
    monkeypatch.setattr(ta, "_enabled", lambda: True)
    monkeypatch.setattr(ta, "_experiments_enabled", lambda: True)
    monkeypatch.setattr(ta.runtime_config, "get", lambda name, default=None: .6 if name == "KINEMATIC_EWMA_ALPHA" else default)
    patched = {}
    monkeypatch.setattr(ta.runtime_config, "patch", lambda values: patched.update(values))
    assert ta.cmd_apply() == 0
    assert patched == {}
    assert json.loads((tmp_path / "tuning_state.json").read_text())["pending"]["state"] == "shadow_collecting"
