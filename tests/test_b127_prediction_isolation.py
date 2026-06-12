"""
tests/test_b127_prediction_isolation.py

B127: conftest entfernt ein mit numpy-Stub kontaminiertes prediction-Modul,
sodass der nächste Test echtes numpy nutzt.
  1. _drop_numpy_contaminated_modules entfernt ein Modul mit Stub-np (kein ndarray).
  2. Ein Modul mit echtem numpy bleibt erhalten.
  3. Regression: _predict_lgbm_vector liefert ein Objekt mit .shape (echtes numpy).

Ausführbar: python3 -m pytest tests/test_b127_prediction_isolation.py -v
"""
import os
import sys
import types
import importlib.util
import pytest


def _load_conftest():
    path = os.path.join(os.path.dirname(__file__), "conftest.py")
    spec = importlib.util.spec_from_file_location("conftest_b127_probe", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_contaminated_prediction_is_dropped():
    cf = _load_conftest()
    fake_np = types.ModuleType("numpy")          # Stub OHNE ndarray
    fake_pred = types.ModuleType("prediction")
    fake_pred.np = fake_np
    sys.modules["prediction"] = fake_pred
    try:
        cf._drop_numpy_contaminated_modules()
        assert "prediction" not in sys.modules
    finally:
        sys.modules.pop("prediction", None)


def test_real_numpy_prediction_is_kept():
    pytest.importorskip("numpy")
    import numpy as _np
    cf = _load_conftest()
    fake_pred = types.ModuleType("prediction")
    fake_pred.np = _np
    sys.modules["prediction"] = fake_pred
    try:
        cf._drop_numpy_contaminated_modules()
        assert sys.modules.get("prediction") is fake_pred
    finally:
        sys.modules.pop("prediction", None)


def test_predict_lgbm_vector_returns_ndarray(monkeypatch):
    pytest.importorskip("numpy")
    import prediction
    monkeypatch.setattr(prediction, "_get_horizons", lambda: [10, 20, 30, 40, 60])

    class _FakeBooster:
        def predict(self, frame):
            return [42.0]

    models = {"lgbm_h10_x": _FakeBooster(), "lgbm_h10_y": _FakeBooster()}
    vec = prediction._predict_lgbm_vector(models, [[0.0]])
    assert hasattr(vec, "shape") and vec.shape[0] == 10
