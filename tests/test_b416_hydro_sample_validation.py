import copy, math
import hydro_flood_ml as h

def valid_row():
    features={name: 1.0 for name in h.HYDRO_FLOOD_ML_FEATURES}
    return {"sample_kind":h.SAMPLE_KIND_LIVE,"feature_snapshot_complete":True,"feature_schema_version":h.FEATURE_SCHEMA_VERSION,"feature_schema_hash":h._feature_schema_hash(),"features":features,"target_q_delta_m3s":1.0,"target_missing":False,"station_id":"s","sample_start_time":"2026-01-01T00:00:00Z"}

def test_strict_snapshot_hash_required_and_optional_allowed():
    row=valid_row(); row.pop("feature_snapshot_complete")
    assert not h.validate_trainable_sample(row)[0]
    row=valid_row(); row["feature_schema_hash"]="wrong"
    assert not h.validate_trainable_sample(row)[0]
    row=valid_row(); row["features"].pop(next(iter(h.HYDRO_OPTIONAL_FEATURES)))
    assert h.validate_trainable_sample(row)[0]

def test_required_values_and_flags_are_strict():
    name=h.HYDRO_REQUIRED_FEATURES[0]
    for value in ("text", math.nan):
        row=valid_row(); row["features"][name]=value
        ok,reasons=h.validate_trainable_sample(row)
        assert not ok and any(name in reason for reason in reasons)
    row=valid_row(); row["features"][h.HYDRO_MISSING_INDICATOR_FEATURES[0]]=0.5
    assert not h.validate_trainable_sample(row)[0]
