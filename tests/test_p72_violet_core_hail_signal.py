"""
P72: Violette Radarpixel (>=57 dBZ) sind ein staerkeres, eigenstaendiges
Hagelsignal als Rot (54 dBZ), wurden aber in core_ratio bisher gleichwertig
mit Rot zusammengefasst. calculate_core_ratio liefert jetzt zusaetzlich
core_violet_ratio; _compute_hail_warning nutzt es als dritten Fusionskandidaten.
"""
import ast
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_functions(path: str, names):
    module = ast.parse(Path(path).read_text(encoding="utf-8"))
    wanted = set(names)
    found = [n for n in module.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
    assert len(found) == len(wanted), f"Nicht alle Funktionen gefunden: {wanted - {n.name for n in found}}"
    code = compile(ast.Module(body=found, type_ignores=[]), path, "exec")
    ns = {}
    exec(code, ns)
    return ns


def test_calculate_core_ratio_distinguishes_red_from_violet():
    pytest.importorskip("cv2")
    pytest.importorskip("filterpy")
    pytest.importorskip("shapely")
    np = pytest.importorskip("numpy")
    import object_tracking

    hsv = np.zeros((100, 100, 3), dtype=np.uint8)
    # Linke Haelfte (0-49, ganze Hoehe): Rot (54 dBZ) -> H=5
    hsv[:, 0:50] = (5, 200, 200)
    # Rechte Haelfte (50-99, ganze Hoehe): Violett (57 dBZ) -> H=140
    hsv[:, 50:100] = (140, 200, 200)

    contour = np.array([[[0, 0]], [[99, 0]], [[99, 99]], [[0, 99]]], dtype=np.int32)

    result = object_tracking.calculate_core_ratio(hsv, contour)
    assert isinstance(result, dict)
    # Gesamte Zelle ist Kern (Rot + Violett) -> core_ratio nahe 1.0
    assert result["core_ratio"] > 0.95
    # Nur die violette Haelfte zaehlt zu core_violet_ratio -> nahe 0.5
    assert 0.45 < result["core_violet_ratio"] < 0.55
    # Violett-Pixel sind eine echte Teilmenge der Kern-Pixel
    assert result["core_violet_pixels"] <= result["core_pixels"]


def test_calculate_core_ratio_zero_violet_when_only_red():
    pytest.importorskip("cv2")
    pytest.importorskip("filterpy")
    pytest.importorskip("shapely")
    np = pytest.importorskip("numpy")
    import object_tracking

    hsv = np.zeros((100, 100, 3), dtype=np.uint8)
    hsv[:, :] = (5, 200, 200)   # komplett Rot, kein Violett
    contour = np.array([[[0, 0]], [[99, 0]], [[99, 99]], [[0, 99]]], dtype=np.int32)

    result = object_tracking.calculate_core_ratio(hsv, contour)
    assert result["core_ratio"] > 0.95
    assert result["core_violet_ratio"] == 0.0


def test_hail_warning_triggers_via_violet_core_alone():
    """Belegt den P72-Nutzen: schwacher hail_prob und hail_prob2, aber ein
    deutlicher Violett-Kernanteil muss trotzdem eine Warnung ausloesen."""
    ns = _load_functions("main.py", ["_compute_hail_prob", "_compute_hail_warning"])
    ns["HAIL_WARN_THRESHOLD"] = 0.45
    ns["HAIL_VIOLET_RATIO_SATURATION"] = 0.10
    obj = {
        "core_ratio": 0.10,
        "cape": 300.0,
        "arome_fl_height": 4200.0,
        "hail_prob2": 0.10,
        "core_violet_ratio": 0.12,   # > Saturation 0.10 -> voller Boost
    }
    hp, hp_eff, warn = ns["_compute_hail_warning"](obj)
    assert hp < 0.45
    assert hp_eff == 1.0
    assert warn is True


def test_hail_prob_violet_scales_linearly_until_saturation():
    ns = _load_functions("main.py", ["_compute_hail_prob", "_compute_hail_warning"])
    ns["HAIL_WARN_THRESHOLD"] = 0.45
    ns["HAIL_VIOLET_RATIO_SATURATION"] = 0.10
    obj = {
        "core_ratio": 0.0, "cape": 0.0, "arome_fl_height": 5000.0,
        "hail_prob2": 0.0, "core_violet_ratio": 0.03,   # 30% der Saettigung
    }
    hp, hp_eff, warn = ns["_compute_hail_warning"](obj)
    assert hp_eff == 0.3
    assert warn is False   # noch unter HAIL_WARN_THRESHOLD


def test_hail_prob_violet_reaches_warning_before_full_saturation():
    ns = _load_functions("main.py", ["_compute_hail_prob", "_compute_hail_warning"])
    ns["HAIL_WARN_THRESHOLD"] = 0.45
    ns["HAIL_VIOLET_RATIO_SATURATION"] = 0.10
    obj = {
        "core_ratio": 0.0, "cape": 0.0, "arome_fl_height": 5000.0,
        "hail_prob2": 0.0, "core_violet_ratio": 0.05,   # halbe Saettigung
    }
    hp, hp_eff, warn = ns["_compute_hail_warning"](obj)
    assert hp_eff == 0.5
    assert warn is True   # 0.5 >= HAIL_WARN_THRESHOLD (0.45)


def test_hail_warning_unaffected_without_violet_core():
    """Regression: Zellen ohne core_violet_ratio (Feld fehlt/0.0) verhalten
    sich exakt wie unter B324."""
    ns = _load_functions("main.py", ["_compute_hail_prob", "_compute_hail_warning"])
    ns["HAIL_WARN_THRESHOLD"] = 0.45
    ns["HAIL_VIOLET_RATIO_SATURATION"] = 0.10
    obj = {"core_ratio": 0.60, "cape": 1600.0, "arome_fl_height": 2800.0, "hail_prob2": 0.05}
    hp, hp_eff, warn = ns["_compute_hail_warning"](obj)
    assert hp_eff == hp
    assert warn is True


def test_ml_cell_features_includes_core_violet_ratio():
    import config
    assert "core_violet_ratio" in config.ML_CELL_FEATURES


def test_core_violet_hue_min_separates_red_orange_from_violet():
    """Statische Konsistenzpruefung: das Intervall [CORE_VIOLET_HUE_MIN,
    CORE_VIOLET_HUE_MAX] darf NUR das Violett-Band treffen, nicht Rot 1
    (Hue ~0-10) und nicht Rot 2/wrap (Hue ~165-179, OpenCV-Hue ist zyklisch
    0-179)."""
    import config
    for lower, upper in config.CORE_HSV_RANGES:
        hue_lower = lower[0]
        is_violet_band = config.CORE_VIOLET_HUE_MIN <= hue_lower <= config.CORE_VIOLET_HUE_MAX
        if hue_lower < 30 or hue_lower > 160:
            assert not is_violet_band, f"Band mit Hue-lower={hue_lower} faelschlich als violett erkannt"
