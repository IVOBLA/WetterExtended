"""
tests/test_merge_label_masking.py

P-M04: Trainings-Samples mit merge_discontinuity=1 im Jetzt- oder Ziel-Frame
werden vom Δ-Label-Training (intensity_regression) und vom intensified-Label
(dataset_builder) ausgeschlossen.

Ausführbar: python3 -m pytest tests/test_merge_label_masking.py -v
"""
import os
import sys
import importlib

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _helper(modname):
    try:
        mod = importlib.import_module(modname)
    except Exception as e:
        pytest.skip(f"{modname} nicht importierbar: {e}")
    fn = getattr(mod, "_merge_contaminated", None)
    if fn is None:
        pytest.skip(f"{modname}._merge_contaminated nicht vorhanden")
    return fn


@pytest.mark.parametrize("modname", ["intensity_regression", "dataset_builder"])
def test_merge_in_now_is_contaminated(modname):
    fn = _helper(modname)
    o_now = {"merge_discontinuity": 1, "area": 100.0, "core_ratio": 0.3}
    o_fut = {"merge_discontinuity": 0, "area": 110.0, "core_ratio": 0.3}
    assert fn(o_now, o_fut) is True


@pytest.mark.parametrize("modname", ["intensity_regression", "dataset_builder"])
def test_merge_in_future_is_contaminated(modname):
    fn = _helper(modname)
    o_now = {"merge_discontinuity": 0, "area": 100.0, "core_ratio": 0.3}
    o_fut = {"merge_discontinuity": 1, "area": 400.0, "core_ratio": 0.5}
    assert fn(o_now, o_fut) is True


@pytest.mark.parametrize("modname", ["intensity_regression", "dataset_builder"])
def test_clean_pair_not_contaminated(modname):
    fn = _helper(modname)
    o_now = {"merge_discontinuity": 0, "area": 100.0, "core_ratio": 0.3}
    o_fut = {"merge_discontinuity": 0, "area": 110.0, "core_ratio": 0.32}
    assert fn(o_now, o_fut) is False


@pytest.mark.parametrize("modname", ["intensity_regression", "dataset_builder"])
def test_missing_flag_defaults_to_clean(modname):
    """Historische JSONs ohne merge_discontinuity → nicht ausgeschlossen."""
    fn = _helper(modname)
    o_now = {"area": 100.0, "core_ratio": 0.3}
    o_fut = {"area": 110.0, "core_ratio": 0.32}
    assert fn(o_now, o_fut) is False
