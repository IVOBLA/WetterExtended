import json
import pickle
import sys
import types

import pytest

import size_regressor as sr


class FakeModel:
    def __init__(self, n, value=1.0):
        self.n = n
        self.value = value
        self.calls = 0

    def num_feature(self):
        return self.n

    def predict(self, fv):
        self.calls += 1
        return [self.value]


def _fake_numpy(monkeypatch):
    class FakeArray(list):
        @property
        def shape(self):
            return (len(self), len(self[0]) if self else 0)
    fake = types.SimpleNamespace(float32=float, array=lambda data, dtype=None: FakeArray(data))
    monkeypatch.setitem(sys.modules, "numpy", fake)


def _patch_paths(monkeypatch, tmp_path):
    model = tmp_path / "models" / "size_regressor.pkl"
    meta = tmp_path / "models" / "size_regressor_meta.json"
    labels = tmp_path / "train_data" / "size_labels" / "size_labels.jsonl"
    monkeypatch.setattr(sr, "SIZE_MODEL_PATH", str(model))
    monkeypatch.setattr(sr, "SIZE_META_PATH", str(meta))
    monkeypatch.setattr(sr, "SIZE_LABELS_PATH", str(labels))
    model.parent.mkdir(parents=True, exist_ok=True)
    labels.parent.mkdir(parents=True, exist_ok=True)
    return model, meta, labels


def _write_model(model_path, meta_path, n=None, keys=None, schema=None):
    keys = list(sr._FEATURE_KEYS if keys is None else keys)
    n = len(keys) if n is None else n
    payload = {"area": FakeModel(n, 50.0), "radius": FakeModel(n, 5.0), "feature_keys": keys}
    if schema is not None:
        payload["feature_schema_version"] = schema
    with open(model_path, "wb") as f:
        pickle.dump(payload, f)
    meta = {"n_samples": 100, "feature_keys": keys, "feature_count": n, "feature_schema_version": schema or sr.SIZE_FEATURE_SCHEMA_VERSION}
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    return payload


def test_old_14_feature_model_is_not_used(monkeypatch, tmp_path):
    model_path, meta_path, _ = _patch_paths(monkeypatch, tmp_path)
    _write_model(model_path, meta_path, n=14, keys=sr._FEATURE_KEYS[:-1], schema=1)
    r = sr.SizeRegressor()
    assert r._model is None
    status = r.status()
    assert status["compatibility_status"] == "feature_mismatch"
    assert status["retrain_required"] is True
    assert status["fallback_active"] is True
    out = r.predict({"area_px": 100, "radius_px": 10}, "2026-01-01_00-00", 1.0, 1.0)
    assert out["size_source"] == "geometric"


def test_compatible_model_is_used(monkeypatch, tmp_path):
    _fake_numpy(monkeypatch)
    model_path, meta_path, _ = _patch_paths(monkeypatch, tmp_path)
    _write_model(model_path, meta_path)
    r = sr.SizeRegressor()
    out = r.predict({"area_px": 100, "radius_px": 10}, "2026-01-01_00-00", 1.0, 1.0)
    assert out["size_source"] == "lgbm"


def test_wrong_feature_order_is_mismatch(monkeypatch, tmp_path):
    model_path, meta_path, _ = _patch_paths(monkeypatch, tmp_path)
    keys = list(sr._FEATURE_KEYS)
    keys[0], keys[1] = keys[1], keys[0]
    _write_model(model_path, meta_path, keys=keys)
    assert sr.SizeRegressor().status()["compatibility_status"] == "feature_mismatch"


def test_meta_without_feature_count_uses_model_num_feature(monkeypatch, tmp_path):
    model_path, meta_path, _ = _patch_paths(monkeypatch, tmp_path)
    _write_model(model_path, meta_path, n=14, keys=sr._FEATURE_KEYS[:-1], schema=1)
    meta = json.loads(meta_path.read_text())
    meta.pop("feature_count")
    meta.pop("feature_keys")
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    assert sr.SizeRegressor().status()["feature_count_model"] == 14
    assert sr.SizeRegressor().status()["compatibility_status"] == "feature_mismatch"


def test_retraining_on_mismatch(monkeypatch, tmp_path):
    model_path, meta_path, labels = _patch_paths(monkeypatch, tmp_path)
    _write_model(model_path, meta_path, n=14, keys=sr._FEATURE_KEYS[:-1], schema=1)
    labels.write_text("x\n" * sr.SIZE_MIN_SAMPLES, encoding="utf-8")
    called = {"n": 0}
    def fake_train(force=False):
        called["n"] += 1
        return {"n_samples": sr.SIZE_MIN_SAMPLES}
    monkeypatch.setattr(sr, "train_size_regressor", fake_train)
    monkeypatch.setattr(sr.SizeRegressor, "reload", lambda self: None)
    r = sr.SizeRegressor()
    r.maybe_trigger_training()
    assert called["n"] == 1


def test_no_predict_call_on_runtime_feature_mismatch(monkeypatch, tmp_path):
    _fake_numpy(monkeypatch)
    model_path, meta_path, _ = _patch_paths(monkeypatch, tmp_path)
    _write_model(model_path, meta_path)
    r = sr.SizeRegressor()
    r._model["area"].n = 14
    out = r.predict({"area_px": 100, "radius_px": 10}, "2026-01-01_00-00", 1.0, 1.0)
    assert out["size_source"] == "geometric"
    assert out["size_regressor_status"] == "feature_mismatch"
    assert r._model is None


def test_api_status_reports_feature_mismatch(monkeypatch, tmp_path):
    model_path, meta_path, _ = _patch_paths(monkeypatch, tmp_path)
    _write_model(model_path, meta_path, n=14, keys=sr._FEATURE_KEYS[:-1], schema=1)
    monkeypatch.setattr(sr, "_size_regressor", None)
    pytest.importorskip("flask")
    import app as app_module
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        resp = client.get("/api/size_regressor_status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["fallback_active"] is True
    assert data["retrain_required"] is True
    assert data["feature_count_model"] == 14
    assert data["feature_count_current"] == 15
