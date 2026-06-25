import copy
import json

import feature_schema


def test_compute_feature_schema_stable_hash():
    a = feature_schema.get_current_feature_schema()
    b = feature_schema.get_current_feature_schema()
    assert a["feature_schema_hash"] == b["feature_schema_hash"]
    assert a["num_features"] == len(a["feature_names"])


def test_hash_changes_when_cell_features_change(monkeypatch):
    base = feature_schema.get_current_feature_schema()["feature_schema_hash"]
    monkeypatch.setattr(feature_schema, "_cfg", lambda name, default=None: ["changed"] if name == "ML_CELL_FEATURES" else feature_schema.__dict__["_orig_cfg"](name, default), raising=False)
    assert feature_schema.get_current_feature_schema()["feature_schema_hash"] != base


def test_compare_legacy_and_mismatch():
    cur = feature_schema.get_current_feature_schema()
    assert feature_schema.compare_sample_schema({}, cur) == (False, "legacy_missing_schema")
    bad = copy.deepcopy(cur)
    bad["feature_schema_hash"] = "sha256:bad"
    bad["feature_names"] = ["bad"]
    assert feature_schema.compare_sample_schema(bad, cur) == (False, "feature_names_mismatch")


def test_scan_training_sources_counts(tmp_path):
    obj = tmp_path / "objects"; w = tmp_path / "weather"
    obj.mkdir(); w.mkdir()
    cur = feature_schema.get_current_feature_schema()
    (obj / "2026-01-01_00-00-00.json").write_text(json.dumps([{"id": 1, "feature_schema_hash": cur["feature_schema_hash"]}]), encoding="utf-8")
    (w / "2026-01-01_00-00-00.json").write_text("[]", encoding="utf-8")
    (obj / "2026-01-01_00-05-00.json").write_text(json.dumps([{"id": 1}]), encoding="utf-8")
    (w / "2026-01-01_00-05-00.json").write_text("[]", encoding="utf-8")
    scan = feature_schema.scan_training_sources({"objects": str(obj), "weather": str(w)}, allow_legacy=False)
    assert scan["compatible_samples"] == 1
    assert scan["legacy_samples"] == 1
    assert scan["rejected_samples"] == 1

feature_schema._orig_cfg = feature_schema._cfg
