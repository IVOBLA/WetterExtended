"""B515 — expected_effect ist ein strukturiertes Objekt statt Freitext.

Analog zu B510 (FINDING_CONTRACT/P105) wird hier sichergestellt, dass die
PROPOSAL_FIELDS-Namen in docs/LOCAL_ANALYSIS_PROMPT.md dokumentiert bleiben,
und dass validate_tuning_proposals() expected_effect als strukturiertes
{metric, direction, minimum_change}-Objekt durchsetzt statt als Freitext-String.
"""
import uuid
from pathlib import Path

import pytest

from experiment_contract import PROPOSAL_FIELDS, validate_tuning_proposals

PROMPT = Path("docs/LOCAL_ANALYSIS_PROMPT.md")

_WHITELIST = {
    "KINEMATIC_EWMA_ALPHA": {"target_system": "kinematic", "min": 0.1, "max": 0.9,
                             "step": 0.05, "max_change_per_experiment": 0.05},
}


def _base_payload(expected_effect):
    return {
        "schema": "wetterextended.local-analysis.v2",
        "analysis_run_id": "run-1", "source_snapshot_id": "sha256:a", "git_commit": "abc",
        "result_id": str(uuid.uuid4()), "generated_at_utc": "2026-08-06T08:00:00Z",
        "tuning_proposals": [{
            "experiment_id": str(uuid.uuid4()), "target_system": "kinematic",
            "target_horizons": [10], "parameter": "KINEMATIC_EWMA_ALPHA",
            "old_value": 0.6, "new_value": 0.55, "code_ref": "prediction.py:_append_kinematic",
            "evidence_refs": ["case:1"], "expected_effect": expected_effect,
            "minimum_paired_samples": {"10": 2}, "maximum_runtime_hours": 48,
        }],
    }


def _validate(expected_effect):
    return validate_tuning_proposals(_base_payload(expected_effect), _WHITELIST,
                                      current_value=lambda name: 0.6, valid_horizons={10, 20, 30, 40, 60})


def test_all_proposal_field_names_are_documented_in_backticks():
    prompt = PROMPT.read_text(encoding="utf-8")
    missing = [field for field in PROPOSAL_FIELDS if f"`{field}`" not in prompt]
    assert missing == []


def test_expected_effect_accepts_valid_structured_object():
    result = _validate({"metric": "mae_km", "direction": "decrease", "minimum_change": 0.05})
    assert result[0]["expected_effect"]["metric"] == "mae_km"


def test_expected_effect_rejects_plain_string():
    with pytest.raises(ValueError, match="expected_effect muss ein Objekt sein"):
        _validate("MAE sinkt")


def test_expected_effect_rejects_missing_subfield():
    with pytest.raises(ValueError, match="unvollstaendig"):
        _validate({"metric": "mae_km", "direction": "decrease"})


def test_expected_effect_rejects_invalid_direction():
    with pytest.raises(ValueError, match="direction"):
        _validate({"metric": "mae_km", "direction": "sideways", "minimum_change": 0.05})


def test_expected_effect_rejects_non_numeric_minimum_change():
    with pytest.raises(ValueError, match="minimum_change"):
        _validate({"metric": "mae_km", "direction": "decrease", "minimum_change": "viel"})


def test_expected_effect_rejects_empty_metric():
    with pytest.raises(ValueError, match="expected_effect.metric fehlt"):
        _validate({"metric": "", "direction": "decrease", "minimum_change": 0.05})
