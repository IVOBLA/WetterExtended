"""B100: LSTM Feature-Mismatch darf prediction.py nicht crashen."""

import importlib
import importlib.machinery
import sys
import types


class _Seq:
    """Minimaler Sequenz-Mock; für den Guard reicht das shape-Attribut."""

    def __init__(self, feature_count: int):
        self.shape = (1, 6, feature_count)


class FakeLSTM:
    """Minimal-LSTM-Mock mit input_shape."""

    def __init__(self, expected_features: int):
        self.input_shape = (None, 6, expected_features)
        self.predict_called = False

    def predict(self, x, verbose=0):
        self.predict_called = True
        raise ValueError(
            f"Dimensions must be equal, but are {x.shape[-1]} and {self.input_shape[-1]}"
        )


def _import_prediction_with_numpy_stub(monkeypatch):
    """Importiert prediction.py auch in Minimal-Umgebungen ohne installiertes numpy."""
    numpy_stub = types.ModuleType("numpy")
    numpy_stub.__spec__ = importlib.machinery.ModuleSpec("numpy", loader=None)
    numpy_stub.asarray = lambda value, dtype=None: value
    monkeypatch.setitem(sys.modules, "numpy", numpy_stub)
    sys.modules.pop("prediction", None)
    return importlib.import_module("prediction")


def test_mismatch_dimension_check_prevents_predict_call(monkeypatch):
    """Wenn LSTM-Feature-Mismatch erkannt wird, muss predict() übersprungen werden."""
    pred = _import_prediction_with_numpy_stub(monkeypatch)
    fake_lstm = FakeLSTM(expected_features=23)
    seq_scaled = _Seq(feature_count=102)

    ok, expected_feats, actual_feats = pred._lstm_feature_dimensions_ok(fake_lstm, seq_scaled)

    assert ok is False
    assert expected_feats == 23
    assert actual_feats == 102
    assert fake_lstm.predict_called is False


def test_dimension_check_accepts_matching_feature_count(monkeypatch):
    """Dimension-Check akzeptiert ein Modell mit passender Feature-Anzahl."""
    pred = _import_prediction_with_numpy_stub(monkeypatch)
    fake_lstm = FakeLSTM(expected_features=23)
    seq_scaled = _Seq(feature_count=23)

    ok, expected_feats, actual_feats = pred._lstm_feature_dimensions_ok(fake_lstm, seq_scaled)

    assert ok is True
    assert expected_feats == 23
    assert actual_feats == 23


def test_dimension_check_allows_unknown_model_feature_count(monkeypatch):
    """Unbekannte Modell-Feature-Dimension darf den Guard nicht selbst auslösen."""
    pred = _import_prediction_with_numpy_stub(monkeypatch)
    fake_lstm = FakeLSTM(expected_features=23)
    fake_lstm.input_shape = (None, 6, None)
    seq_scaled = _Seq(feature_count=102)

    ok, expected_feats, actual_feats = pred._lstm_feature_dimensions_ok(fake_lstm, seq_scaled)

    assert ok is True
    assert expected_feats is None
    assert actual_feats == 102
