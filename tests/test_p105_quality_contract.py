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


def test_local_analysis_separates_five_finding_classes():
    payload = validate_payload({"zusammenfassung": "x", "fehler": [], "loesungen": [], "verbesserungen": [], "prompts": []})
    for name in ("verification_findings", "tracking_lineage_findings", "kinematic_findings", "ml_model_findings", "routing_findings"):
        assert name in payload
    assert payload["quality_state"] == "plateau"
