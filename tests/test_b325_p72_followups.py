"""
B325: Zwei Korrekturen zu P72 (Violett-Kernanteil / core_violet_ratio).

1) Codex-Review: calculate_core_ratio() klassifizierte ein CORE_HSV_RANGES-Band
   nur anhand seiner Hue-Untergrenze (lower[0] >= CORE_VIOLET_HUE_MIN) als
   "violett". Erweitert ein Operator ueber /api/thresholds ein Band so, dass es
   mit einer Untergrenze UNTER CORE_VIOLET_HUE_MIN beginnt, aber weiterhin bis
   in den Violett-Bereich hineinreicht, wurde das gesamte Band verworfen - auch
   der echte Violett-Anteil ging verloren.

2) test_predict_positions_marks_partial_lgbm_horizons_per_horizon (P-T08) las
   ungemockt das reale training_meta.json vom lokalen current-Modell (via
   ml_readiness.get_forecast_runtime_status) und wurde dadurch vom lokalen
   Trainingsstand abhaengig - nach P72 (neues ML-Feature core_violet_ratio)
   schlug er auf Maschinen mit noch nicht nachtrainiertem Modell fehl, obwohl
   die getestete Partial-Horizont-Logik selbst unveraendert korrekt ist.
"""
import ast
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_widened_violet_band_below_hue_min_still_counts_overlap(monkeypatch):
    """Reproduziert das Codex-Review-Szenario: Violett-Band manuell auf
    Hue 90-155 verbreitert (Standard: 125-155). Nur der echte Ueberlapp mit
    [CORE_VIOLET_HUE_MIN, CORE_VIOLET_HUE_MAX] darf zu core_violet_ratio
    zaehlen, nicht das gesamte Band."""
    pytest.importorskip("cv2")
    pytest.importorskip("filterpy")
    pytest.importorskip("shapely")
    np = pytest.importorskip("numpy")
    import object_tracking

    widened_ranges = [
        ([0, 100, 120], [10, 255, 255]),      # Rot 1
        ([165, 100, 120], [179, 255, 255]),   # Rot 2 (wrap)
        ([90, 100, 120], [155, 255, 255]),    # Violett verbreitert: 90-155 statt 125-155
    ]
    # runtime_config.get() liefert bei bekannten Config-Schluesseln stets den
    # (ggf. echten) Config-Wert und ignoriert den hier uebergebenen Fallback -
    # daher direkt object_tracking._rc.get() patchen statt nur den Fallback-
    # Parameter zu aendern.
    monkeypatch.setattr(
        object_tracking._rc, "get",
        lambda key, default=None: widened_ranges if key == "CORE_HSV_RANGES" else default,
    )

    hsv = np.zeros((100, 100, 3), dtype=np.uint8)
    # Linke Haelfte: Hue=95 - im verbreiterten Band enthalten, aber NICHT
    # echtes Violett (< CORE_VIOLET_HUE_MIN=100).
    hsv[:, 0:50] = (95, 200, 200)
    # Rechte Haelfte: Hue=140 - echtes Violett (100 <= 140 <= 160).
    hsv[:, 50:100] = (140, 200, 200)
    contour = np.array([[[0, 0]], [[99, 0]], [[99, 99]], [[0, 99]]], dtype=np.int32)

    result = object_tracking.calculate_core_ratio(hsv, contour)
    # Beide Haelften zaehlen zum (verbreiterten) Kern.
    assert result["core_ratio"] > 0.95
    # NUR die echte Violett-Haelfte darf zu core_violet_ratio zaehlen.
    # Vor dem Fix (lower[0]=90 < CORE_VIOLET_HUE_MIN=100) waere das gesamte
    # Band verworfen worden -> core_violet_ratio faelschlich 0.0.
    assert 0.45 < result["core_violet_ratio"] < 0.55, (
        f"Erwartet ~0.5 (nur echte Violett-Haelfte), bekam {result['core_violet_ratio']}"
    )


def test_band_entirely_below_violet_window_contributes_nothing(monkeypatch):
    """Gegenprobe: ein Band, das komplett unterhalb des Violett-Fensters liegt
    (z.B. reines Orange 10-27), darf auch nach dem Overlap-Fix keinen
    Violett-Beitrag liefern."""
    pytest.importorskip("cv2")
    pytest.importorskip("filterpy")
    pytest.importorskip("shapely")
    np = pytest.importorskip("numpy")
    import object_tracking

    ranges = [([10, 100, 120], [27, 255, 255])]   # nur Orange, komplett < CORE_VIOLET_HUE_MIN
    monkeypatch.setattr(
        object_tracking._rc, "get",
        lambda key, default=None: ranges if key == "CORE_HSV_RANGES" else default,
    )

    hsv = np.zeros((50, 50, 3), dtype=np.uint8)
    hsv[:, :] = (20, 200, 200)
    contour = np.array([[[0, 0]], [[49, 0]], [[49, 49]], [[0, 49]]], dtype=np.int32)

    result = object_tracking.calculate_core_ratio(hsv, contour)
    assert result["core_violet_ratio"] == 0.0


def test_red_wrap_band_still_excluded_after_overlap_fix(monkeypatch):
    """Regression: Rot 2 (wrap, Hue 165-179) darf auch nach dem Overlap-Fix
    NICHT als violett gezaehlt werden (kein Overlap mit [100,160])."""
    pytest.importorskip("cv2")
    pytest.importorskip("filterpy")
    pytest.importorskip("shapely")
    np = pytest.importorskip("numpy")
    import object_tracking

    ranges = [([165, 100, 120], [179, 255, 255])]
    monkeypatch.setattr(
        object_tracking._rc, "get",
        lambda key, default=None: ranges if key == "CORE_HSV_RANGES" else default,
    )

    hsv = np.zeros((50, 50, 3), dtype=np.uint8)
    hsv[:, :] = (170, 200, 200)
    contour = np.array([[[0, 0]], [[49, 0]], [[49, 49]], [[0, 49]]], dtype=np.int32)

    result = object_tracking.calculate_core_ratio(hsv, contour)
    assert result["core_ratio"] > 0.95
    assert result["core_violet_ratio"] == 0.0


def test_pt08_partial_horizon_no_longer_depends_on_local_model_state():
    """Statische Pruefung: der P-T08-Test mockt get_forecast_runtime_status,
    damit sein Ergebnis nicht vom zufaelligen Trainingsstand des lokalen
    current-Modells abhaengt."""
    text = Path("tests/test_pt08_partial_horizon.py").read_text(encoding="utf-8")
    assert "ml_readiness.get_forecast_runtime_status" in text
    assert '"training_meta": {}' in text
