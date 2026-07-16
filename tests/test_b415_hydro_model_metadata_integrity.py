import json
import math
import pickle

import pytest

import hydro_flood_ml as h


def _install_model(monkeypatch, tmp_path, *, promoted=True, prediction=0.25):
    monkeypatch.setattr(h, "HYDRO_MODEL_CURRENT_DIR", tmp_path)
    monkeypatch.setattr(h, "HYDRO_MODEL_FILENAME", "model.joblib")
    h._MODEL_CACHE.clear()
    meta = {
        "promoted": promoted,
        "feature_schema_version": h.FEATURE_SCHEMA_VERSION,
        "feature_schema_hash": h._feature_schema_hash(),
        "feature_names": h.HYDRO_FLOOD_ML_FEATURES,
        "new_active_version": "b415-test",
    }
    artifact = {
        "feature_schema_version": h.FEATURE_SCHEMA_VERSION,
        "feature_schema_hash": h._feature_schema_hash(),
        "feature_names": h.HYDRO_FLOOD_ML_FEATURES,
        "type": "feature_linear_residual",
        "model": {"feature_idx": 0, "slope": 0.0, "intercept": prediction},
    }
    (tmp_path / "model.joblib").write_bytes(pickle.dumps(artifact))
    (tmp_path / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    h._write_model_manifest(tmp_path, meta)
    return meta


def _row():
    row = {name: 1.0 for name in h.HYDRO_FLOOD_ML_FEATURES}
    row.update(current_q_m3s=2.0, physical_predicted_q_delta_m3s=0.5)
    return row


def _assert_error(code):
    with pytest.raises(ValueError, match=code):
        h.load_active_hydro_model(force_reload=True)
    pred = h.predict_q_delta(_row())
    assert pred["prediction_source"] == "physical_fallback"
    assert pred["model_rejection_reason"] == "model_integrity_error"


def test_model_hash_mismatch_falls_back(monkeypatch, tmp_path):
    _install_model(monkeypatch, tmp_path)
    with (tmp_path / "model.joblib").open("ab") as stream:
        stream.write(b"tampered")
    _assert_error("model_integrity_error:model_hash_mismatch")


@pytest.mark.parametrize("promoted", [True, False])
def test_metadata_hash_mismatch_never_self_heals(monkeypatch, tmp_path, promoted):
    _install_model(monkeypatch, tmp_path, promoted=promoted)
    manifest_before = (tmp_path / "manifest.json").read_bytes()
    with (tmp_path / "metadata.json").open("a", encoding="utf-8") as stream:
        stream.write(" ")
    _assert_error("model_integrity_error:metadata_hash_mismatch")
    assert (tmp_path / "manifest.json").read_bytes() == manifest_before


@pytest.mark.parametrize("mutation", ["changed", "missing"])
def test_manifest_field_mismatch(monkeypatch, tmp_path, mutation):
    _install_model(monkeypatch, tmp_path)
    path = tmp_path / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if mutation == "changed":
        manifest["model_filename"] = "other.joblib"
    else:
        manifest.pop("model_filename")
    path.write_text(json.dumps(manifest), encoding="utf-8")
    _assert_error("model_integrity_error:manifest_field_mismatch")


def test_unknown_manifest_schema_is_rejected(monkeypatch, tmp_path):
    _install_model(monkeypatch, tmp_path)
    path = tmp_path / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["manifest_schema_version"] = "future"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    _assert_error("model_integrity_error:manifest_schema_unsupported")


def test_schema_hash_mismatch(monkeypatch, tmp_path):
    _install_model(monkeypatch, tmp_path)
    path = tmp_path / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["artifact_schema_hash"] = "tampered"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    _assert_error("model_integrity_error:schema_hash_mismatch")


def test_non_finite_probe_inference(monkeypatch, tmp_path):
    _install_model(monkeypatch, tmp_path, prediction=math.nan)
    _assert_error("model_integrity_error:non_finite_probe_inference")


def test_valid_model_loads_and_predicts(monkeypatch, tmp_path):
    _install_model(monkeypatch, tmp_path)
    loaded = h.load_active_hydro_model(force_reload=True)
    assert loaded["model_cache_status"] == "miss"
    assert h.predict_q_delta(_row())["prediction_source"] == "hydro_ml"
