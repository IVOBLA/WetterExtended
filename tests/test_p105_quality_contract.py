from feature_schema import structured_schema_mismatch
from quality_contract import PROVENANCE_FIELDS, classify_artifact, provenance
from tools.run_local_analysis import validate_payload


def test_quality_artifacts_share_versioned_provenance_fields():
    value = provenance(generated_by="test", records=[{"x": 1}], git_commit="abc")
    assert set(PROVENANCE_FIELDS) <= set(value)
    assert classify_artifact(value)["comparable"] is True
    assert classify_artifact({})["classification"] == "legacy_incomparable"


def test_feature_schema_mismatch_is_structured():
    mismatch = structured_schema_mismatch(
        {"feature_schema_hash": "old", "feature_names": ["a", "b"], "feature_dtypes": {"a": "float"}},
        {"feature_schema_hash": "new", "feature_names": ["b", "c"], "feature_dtypes": {"a": "int"}},
        affected_model_versions=["v1"], affected_horizons=[10], runtime_fallback_reason="schema")
    assert mismatch["missing_features"] == ["a"]
    assert mismatch["additional_features"] == ["c"]
    assert mismatch["dtype_mismatch"]["a"] == {"expected": "float", "actual": "int"}


# B514: alle fuenf Finding-Objekte sind Pflicht und tragen die neuen Messfelder.
_VALID_FINDING = {
    "current_quality": "unklar", "distance_to_target": None,
    "dominant_error_class": "unknown", "evidence": [],
    "last_attempted_improvement": None, "result": "plateau",
    "next_falsifiable_action": "Naechsten Export gegen denselben Gold-Snapshot messen",
    "eligible_for_autonomous_experiment": False,
    "affected_horizons": [],
    "expected_metric_change": {"metric": "mae_km", "direction": "unchanged", "minimum_change": 0.0},
}
_FINDING_NAMES = ("verification_findings", "tracking_lineage_findings", "kinematic_findings",
                  "ml_model_findings", "routing_findings")

def _payload():
    return {"zusammenfassung": "x", "fehler": [], "loesungen": [], "verbesserungen": [], "prompts": [],
            **{name: dict(_VALID_FINDING) for name in _FINDING_NAMES}}

def test_local_analysis_separates_five_finding_classes():
    payload = validate_payload(_payload())
    for name in _FINDING_NAMES:
        assert name in payload
    assert payload["quality_state"] == "plateau"

def test_local_analysis_rejects_missing_finding_object():
    import pytest
    payload = _payload(); del payload["routing_findings"]
    with pytest.raises(ValueError, match="routing_findings"):
        validate_payload(payload)

def test_local_analysis_rejects_finding_without_affected_horizons():
    import pytest
    payload = _payload(); del payload["kinematic_findings"]["affected_horizons"]
    with pytest.raises(ValueError, match="unvollständig"):
        validate_payload(payload)

def test_local_analysis_rejects_finding_with_invalid_direction():
    import pytest
    payload = _payload()
    payload["ml_model_findings"]["expected_metric_change"] = {"metric": "mae_km", "direction": "sideways", "minimum_change": 0.0}
    with pytest.raises(ValueError, match="direction"):
        validate_payload(payload)
