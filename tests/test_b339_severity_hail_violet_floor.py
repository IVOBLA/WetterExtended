"""B339 — severity._hail_index() beruecksichtigt core_violet_ratio (P72) als
Floor, analog main.py._compute_hail_warning()s hail_prob_violet. Verhindert
hail_cat="keiner" bei kompaktem violetten Kern bei gleichzeitig niedrigem
CAPE/SHIP. Zusaetzlich: Regressionsschutz, dass der separate Kartenmarker
entfernt wurde und die Haupt-Popup-Zeile in beiden Kartendateien erhalten
blieb.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from severity_predict import _hail_index
from config import HAIL_VIOLET_RATIO_SATURATION


def _read(path):
    return Path(path).read_text(encoding="utf-8")


# ── _hail_index Violett-Floor ────────────────────────────────────────────────

def test_high_violet_ratio_overrides_low_ship_low_cape():
    """Reproduziert den Screenshot-Fall: core_ratio=0.48, kein SHIP/CAPE-Signal,
    aber deutlicher violetter Kern -> hail_cat darf NICHT 'keiner' bleiben."""
    obj = {
        "ship_index": 0.0,
        "arome_fl_height": 4000.0,
        "core_ratio": 0.48,
        "vil_proxy": 0.0,
        "overshooting_top": 0.0,
        "core_violet_ratio": HAIL_VIOLET_RATIO_SATURATION,  # erreicht Floor=1.0
    }
    prob, cat = _hail_index(obj)
    assert prob >= 0.99, f"Erwartete Floor nahe 1.0, bekam {prob}"
    assert cat == "gross"


def test_moderate_violet_ratio_lifts_category_above_keiner():
    """Ein violetter Kernanteil deutlich unter der Saettigung soll trotzdem
    aus der Kategorie 'keiner' herausheben, wenn die uebrigen Terme niedrig sind."""
    obj = {
        "ship_index": 0.2,
        "arome_fl_height": 4000.0,
        "core_ratio": 0.10,
        "vil_proxy": 0.0,
        "overshooting_top": 0.0,
        "core_violet_ratio": HAIL_VIOLET_RATIO_SATURATION * 0.30,
    }
    prob, cat = _hail_index(obj)
    assert prob >= 0.30
    assert cat != "keiner"


def test_zero_violet_ratio_behaves_exactly_as_before():
    """Regressionsschutz: core_violet_ratio=0 (oder fehlend) darf das bisherige
    Ergebnis NICHT veraendern (violet_floor=0 -> max(score, 0) == score)."""
    obj_without = {
        "ship_index": 1.0,
        "arome_fl_height": 3000.0,
        "core_ratio": 0.30,
        "vil_proxy": 0.20,
        "overshooting_top": 1.0,
    }
    obj_with_zero = dict(obj_without, core_violet_ratio=0.0)
    assert _hail_index(obj_without) == _hail_index(obj_with_zero)


def test_missing_core_violet_ratio_field_defaults_to_zero_no_crash():
    """Alte Objekte ohne core_violet_ratio-Feld (Legacy-Snapshots) duerfen
    keine Exception werfen."""
    obj = {"ship_index": 0.5, "arome_fl_height": 3500.0, "core_ratio": 0.2}
    prob, cat = _hail_index(obj)
    assert isinstance(prob, float)
    assert cat in ("keiner", "klein", "gross")


# ── Frontend-Regression: Marker entfernt, Popup-Zeile erhalten ─────────────

def test_standalone_hail_marker_removed_from_both_map_files():
    for path in ("frontend/src/pages/MapView.jsx", "frontend/src/pages/MapFullscreen.jsx"):
        src = _read(path)
        assert "🧊 Hagel {" not in src, (
            f"{path}: separater Hagel-Marker wurde nicht entfernt (B339)"
        )


def test_popup_hail_line_still_present_in_both_map_files():
    for path in ("frontend/src/pages/MapView.jsx", "frontend/src/pages/MapFullscreen.jsx"):
        src = _read(path)
        assert "o.severity.hail_cat !== 'keiner'" in src, (
            f"{path}: Haupt-Popup-Hagelzeile fehlt oder wurde versehentlich entfernt"
        )
        assert "o.severity.hail_prob" in src
