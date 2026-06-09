"""B110: Keras-Callbacks werden beim Lazy-Reimport korrekt behandelt."""
import importlib

import pytest


def _get_lstm_module():
    """Findet das Modul mit _build_lstm()."""
    for mod_name in ["model_training", "train_lstm", "lstm_trainer", "prediction"]:
        try:
            mod = importlib.import_module(mod_name)
        except ImportError:
            continue
        if hasattr(mod, "_build_lstm"):
            return mod
    pytest.skip("_build_lstm nicht gefunden – Dateiname unbekannt")


def test_b110_build_lstm_imports_callbacks():
    """Nach _build_lstm() sind Keras-Callbacks gesetzt, wenn TensorFlow verfügbar ist."""
    pytest.importorskip("tensorflow")
    mod = _get_lstm_module()
    mod.EarlyStopping = None
    mod.ModelCheckpoint = None

    mod._build_lstm()

    assert mod.EarlyStopping is not None, "EarlyStopping muss nach _build_lstm() gesetzt sein"
    assert mod.ModelCheckpoint is not None, "ModelCheckpoint muss nach _build_lstm() gesetzt sein"


def test_b110_train_lstm_no_crash_without_callbacks(monkeypatch, tmp_path):
    """train_lstm() übergibt None an model.fit(), wenn Callbacks fehlen."""
    mod = _get_lstm_module()

    class FakeHistory:
        history = {"val_loss": [0.25]}

    class FakeModel:
        callbacks_seen = object()

        def fit(self, *args, **kwargs):
            self.callbacks_seen = kwargs.get("callbacks")
            return FakeHistory()

    fake_model = FakeModel()
    monkeypatch.setattr(mod, "Sequential", object())
    monkeypatch.setattr(mod, "train_test_split", object())
    monkeypatch.setattr(mod, "EarlyStopping", None)
    monkeypatch.setattr(mod, "ModelCheckpoint", None)
    monkeypatch.setattr(mod, "_build_lstm", lambda n_horizons=0: fake_model)

    import config

    monkeypatch.setattr(config, "MIN_SEQUENCES_LSTM", 2, raising=False)
    result = mod.train_lstm(["x0", "x1", "x2"], ["y0", "y1", "y2"], str(tmp_path))

    assert result["trained"] is True
    assert fake_model.callbacks_seen is None
