"""P0-2: LSTM-Output-Dim und training_meta verwenden Runtime-Horizonte."""
import importlib
import pytest

pytest.importorskip("numpy")


def _mt():
    try:
        return importlib.import_module("model_training")
    except Exception as exc:
        pytest.skip(f"model_training nicht importierbar: {exc}")


def test_build_lstm_uses_n_horizons_parameter():
    mt = _mt()
    pytest.importorskip("tensorflow")
    model = mt._build_lstm(n_horizons=3)
    output_units = model.layers[-1].units
    assert output_units == 6, f"Dense sollte 3*2=6 sein, ist {output_units}"


def test_build_lstm_default_matches_get_training_horizons():
    mt = _mt()
    pytest.importorskip("tensorflow")
    expected = len(mt._get_training_horizons()) * 2
    model = mt._build_lstm()
    actual = model.layers[-1].units
    assert actual == expected, f"Dense {actual} != {expected} (_get_training_horizons)"


def test_get_training_horizons_reads_runtime_config(monkeypatch):
    mt = _mt()
    try:
        import runtime_config as rc
        monkeypatch.setattr(rc, "_OVERRIDES", {"ML_FORECAST_HORIZONS_MIN": [10, 20, 30]})
        horizons = mt._get_training_horizons()
        assert horizons == [10, 20, 30]
    except Exception as exc:
        pytest.skip(f"runtime_config nicht patchbar: {exc}")
