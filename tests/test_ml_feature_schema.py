import importlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_feature_schema_hash_is_stable_and_changes(monkeypatch):
    fs = importlib.import_module("feature_schema")
    schema1 = fs.get_current_feature_schema()
    schema2 = fs.get_current_feature_schema()
    assert schema1["feature_schema_hash"] == schema2["feature_schema_hash"]

    original = list(schema1["cell_feature_names"])
    monkeypatch.setattr(fs, "_cfg", lambda name, default=None: original + ["schema_test_extra"] if name == "ML_CELL_FEATURES" else default)
    changed = fs.get_current_feature_schema()
    assert changed["feature_schema_hash"] != schema1["feature_schema_hash"]


def test_compare_sample_schema_accepts_compatible_and_rejects_legacy_and_mismatch():
    fs = importlib.import_module("feature_schema")
    current = fs.get_current_feature_schema()
    assert fs.compare_sample_schema({"feature_schema_hash": current["feature_schema_hash"]}, current) == (True, None)
    assert fs.compare_sample_schema({}, current) == (False, "legacy_missing_schema")
    ok, reason = fs.compare_sample_schema({"feature_schema_hash": "sha256:wrong"}, current)
    assert ok is False
    assert reason == "feature_schema_mismatch"


def test_scan_training_sources_counts_compatible_legacy_and_mismatch(tmp_path):
    fs = importlib.import_module("feature_schema")
    objects = tmp_path / "objects"
    weather = tmp_path / "weather"
    objects.mkdir(); weather.mkdir()
    current = fs.schema_metadata()

    (objects / "2026-01-01_00-00-00.json").write_text(json.dumps([{**current, "id": "ok"}]), encoding="utf-8")
    (weather / "2026-01-01_00-00-00.json").write_text(json.dumps([{**current}]), encoding="utf-8")

    (objects / "2026-01-01_00-05-00.json").write_text(json.dumps([{"id": "legacy"}]), encoding="utf-8")
    (weather / "2026-01-01_00-05-00.json").write_text(json.dumps([{}]), encoding="utf-8")

    mismatch = {**current, "feature_schema_hash": "sha256:mismatch"}
    (objects / "2026-01-01_00-10-00.json").write_text(json.dumps([{**mismatch, "id": "bad"}]), encoding="utf-8")
    (weather / "2026-01-01_00-10-00.json").write_text(json.dumps([{**mismatch}]), encoding="utf-8")

    scan = fs.scan_training_sources({"objects": str(objects), "weather": str(weather)}, allow_legacy=False)
    assert scan["compatible_samples"] == 1
    assert scan["legacy_samples"] == 1
    assert scan["mismatch_samples"] == 1
    assert scan["used_samples"] == 1
    assert scan["rejected_samples"] == 2
    assert scan["rejection_reasons"]["legacy_missing_schema"] == 1
    assert scan["rejection_reasons"]["feature_schema_mismatch"] == 1


def test_training_control_forces_compatible_only_for_scheduler_and_manual_sources():
    text = (ROOT / "training_control.py").read_text(encoding="utf-8")
    assert 'allow_legacy = "allow_legacy" in str(source)' in text
    assert 'runtime_config.patch({"ML_ALLOW_LEGACY_SAMPLES": allow_legacy})' in text
    assert 'source: str = "manual"' in text


def test_scheduler_and_admin_training_use_shared_locked_pipeline():
    scheduler = (ROOT / "scheduler.py").read_text(encoding="utf-8")
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    assert 'run_training_with_lock(source=f"scheduler:{job_name}")' in scheduler
    assert 'start_training_background(source="manual")' in app
    assert 'start_training_background(source=f"admin_ml_retrain:{policy}")' in app


def test_install_uses_model_training_schema_compatibility_gate():
    install = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert "_check_model_compatibility" in install
    assert "Feature-Schema" in install or "ML-Modell/Feature-Kompatibilität" in install


def test_model_with_wrong_schema_is_rejected(tmp_path):
    mt = importlib.import_module("model_training")
    meta = {
        "feature_schema_hash": "sha256:not-current",
        "horizons_trained": mt._get_training_horizons(),
        "feature_count": importlib.import_module("config").ML_NUM_FEATURES,
    }
    (tmp_path / "training_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    res = mt._check_model_compatibility(str(tmp_path))
    assert res["compatible"] is False
    assert "Feature-Schema-Hash" in res["reason"]


def test_admin_schema_api_routes_exist_and_do_not_train():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    assert '@app.route("/api/admin/ml/schema")' in app
    assert '@app.route("/api/admin/ml/dataset-scan", methods=["POST"])' in app
    dataset_scan_body = app.split('def api_admin_ml_dataset_scan():', 1)[1].split('@app.route("/api/admin/ml/retrain"', 1)[0]
    assert "scan_training_sources" in dataset_scan_body
    assert "start_training_background" not in dataset_scan_body
    assert "retrain_all" not in dataset_scan_body
