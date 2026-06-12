"""
tests/test_merge_tendency.py

P-M03: Merge-bewusste Tendenz.
 - size_trend/trend vergleichen beim Merge gegen Summe/gewichtetes Mittel der
   Parents statt gegen einen einzelnen dominanten Parent.
 - of_divergence dient als Tie-Breaker in _classify_tendency (nur bei t==0).

Ausführbar: python3 -m pytest tests/test_merge_tendency.py -v
"""
import os
import sys
import importlib

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Helfer aus object_tracking ──────────────────────────────────────────────
def _ot():
    try:
        return importlib.import_module("object_tracking")
    except ImportError as e:
        pytest.skip(f"object_tracking nicht importierbar: {e}")


def test_merge_prev_area_is_sum():
    ot = _ot()
    snap = {"A": {"area": 100.0, "core_ratio": 0.2},
            "B": {"area": 300.0, "core_ratio": 0.6}}
    assert ot._merge_prev_area(["A", "B"], snap) == 400.0
    assert ot._merge_prev_area([], snap) is None
    assert ot._merge_prev_area(["X"], snap) is None


def test_merge_prev_core_is_area_weighted():
    ot = _ot()
    snap = {"A": {"area": 100.0, "core_ratio": 0.2},
            "B": {"area": 300.0, "core_ratio": 0.6}}
    # (0.2*100 + 0.6*300) / 400 = (20 + 180)/400 = 0.5
    assert abs(ot._merge_prev_core(["A", "B"], snap) - 0.5) < 1e-9


def test_merged_blob_is_stable_not_growing():
    """Vereinigte Fläche = Summe der Parents → size_trend 0 (stabil),
    NICHT +1 (was beim Vergleich gegen nur den dominanten Parent käme)."""
    ot = _ot()
    from config import TENDENCY_AREA_PCT_STABLE
    snap = {"A": {"area": 100.0, "core_ratio": 0.3},
            "B": {"area": 300.0, "core_ratio": 0.3}}
    merged_area = 400.0  # exakt die Summe

    # Merge: gegen Summe → stabil
    prev_area_merge = ot._merge_prev_area(["A", "B"], snap)
    assert ot._size_trend_vs_baseline(merged_area, prev_area_merge,
                                      TENDENCY_AREA_PCT_STABLE) == 0

    # Gegenprobe Alt-Verhalten: nur dominanter Parent B (300) → Scheinwachstum +1
    assert ot._size_trend_vs_baseline(merged_area, 300.0,
                                      TENDENCY_AREA_PCT_STABLE) == 1


def test_merged_core_no_false_intensification():
    """core_ratio der vereinigten Zelle = gewichtetes Mittel der Parents →
    trend 0; gegen den schwächeren Einzel-Parent wäre es +1."""
    ot = _ot()
    snap = {"A": {"area": 100.0, "core_ratio": 0.2},
            "B": {"area": 300.0, "core_ratio": 0.6}}
    merged_core = 0.5  # = gewichtetes Mittel

    prev_core_merge = ot._merge_prev_core(["A", "B"], snap)
    assert ot._intensity_trend_vs_baseline(merged_core, prev_core_merge, 0.05) == 0
    # gegen schwächeren Einzel-Parent A (0.2) → Scheinverstärkung +1
    assert ot._intensity_trend_vs_baseline(merged_core, 0.2, 0.05) == 1


# ── of_divergence Tie-Breaker ───────────────────────────────────────────────
def _classify():
    try:
        return importlib.import_module("prediction")._classify_tendency
    except (ImportError, AttributeError) as e:
        pytest.skip(f"_classify_tendency nicht verfügbar: {e}")


def test_divergence_breaks_tie_when_trend_neutral():
    cl = _classify()
    # t == 0, Konvergenz (negativ) → staerker
    obj = {"trend": 0, "size_trend": 0, "of_available": 1, "of_divergence": -0.1}
    cl(obj, has_ml=False)
    assert obj["intensity_tendency"] == "staerker"

    # t == 0, Divergenz (positiv) → schwaecher
    obj = {"trend": 0, "size_trend": 0, "of_available": 1, "of_divergence": 0.1}
    cl(obj, has_ml=False)
    assert obj["intensity_tendency"] == "schwaecher"


def test_divergence_does_not_override_clear_trend():
    cl = _classify()
    # eindeutiger Tracker-Trend (+1) darf NICHT von Divergenz überstimmt werden
    obj = {"trend": 1, "size_trend": 0, "of_available": 1, "of_divergence": 0.1}
    cl(obj, has_ml=False)
    assert obj["intensity_tendency"] == "staerker"
