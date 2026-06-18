import importlib


def _classify():
    return importlib.import_module("prediction")._classify_tendency


def test_core_ratio_growth_with_shrinking_area_is_compact_not_stronger():
    obj = {
        "trend": 0,
        "size_trend": -1,
        "delta_core_ratio": 0.20,
        "delta_area_pct": -0.50,
        "delta_core_area_pct": 0.0,
        "core_compact_signal": 1,
    }
    _classify()(obj, has_ml=False)
    assert obj["intensity_tendency"] == "kompakt"
    assert obj["size_tendency"] == "schrumpft"


def test_absolute_core_area_growth_classifies_stronger():
    obj = {
        "trend": 1,
        "size_trend": 1,
        "delta_core_ratio": 350 / 1100 - 0.20,
        "delta_area_pct": 0.10,
        "delta_core_area_pct": 0.75,
    }
    _classify()(obj, has_ml=False)
    assert obj["intensity_tendency"] == "staerker"
    assert obj["size_tendency"] in {"waechst", "stabil"}


def test_area_and_core_area_shrink_classifies_weaker():
    obj = {
        "trend": -1,
        "size_trend": -1,
        "delta_core_ratio": 80 / 600 - 0.20,
        "delta_area_pct": -0.40,
        "delta_core_area_pct": -0.60,
    }
    _classify()(obj, has_ml=False)
    assert obj["intensity_tendency"] == "schwaecher"
    assert obj["size_tendency"] == "schrumpft"


def test_ml_core_ratio_only_with_shrinking_area_is_not_stronger():
    obj = {
        "delta_core_ratio_pred": 0.20,
        "delta_area_pred": -0.50,
        "delta_core_area_pct_pred": 0.0,
    }
    _classify()(obj, has_ml=True)
    assert obj["intensity_tendency"] == "kompakt"
    assert obj["size_tendency"] == "schrumpft"


def test_ml_core_ratio_growth_without_core_area_prediction_classifies_stronger():
    obj = {
        "delta_core_ratio_pred": 0.20,
        "delta_area_pred": 0.00,
        "delta_core_area_pct": 0.0,
    }
    _classify()(obj, has_ml=True)
    assert obj["intensity_tendency"] == "staerker"
    assert obj["size_tendency"] == "stabil"
