import sys
import types
import pytest

# B96: severity_dataset importiert dataset_builder (numpy) + pandas auf Modulebene.
# Ohne importorskip führt ein defektes numpy/pandas zu einem Sammlungsfehler
# statt einem sauberen Skip.
pytest.importorskip("numpy")   # transitiv über dataset_builder
pytest.importorskip("pandas")  # severity_dataset.py: pd = importlib.import_module("pandas")

sys.modules.setdefault(
    "debug_utils",
    types.SimpleNamespace(debug_log=lambda *args, **kwargs: None),
)

from severity_dataset import _gust_kmh


def test_b89_gust_kmh_ignores_arome_mean_wind_when_no_nowcast():
    obj = {
        "nowcast_ffx_kmh": 0.0,
        "FFX": 0.0,
        "wind_gust_10m_kmh": 6.1,
        "arome_ff10m": 14.7,
        "tawes_max_gust_kmh": 32.0,
    }

    assert _gust_kmh(obj) == 6.1


def test_b89_gust_kmh_keeps_real_gust_source_maximum():
    obj = {
        "nowcast_ffx_kmh": 21.24,
        "FFX": 32.04,
        "wind_gust_10m_kmh": 18.0,
        "arome_ff10m": 80.0,
    }

    assert _gust_kmh(obj) == 32.0


def test_b116_gust_kmh_ignores_nowcast_ffx_field():
    obj = {
        "nowcast_ffx_kmh": 99.0,
        "FFX": 12.0,
        "wind_gust_10m_kmh": 18.0,
    }

    assert _gust_kmh(obj) == 18.0
