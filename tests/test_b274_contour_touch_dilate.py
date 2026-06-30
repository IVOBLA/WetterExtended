"""B274: are_contours_touching_edges()/merge_close_contours() erhalten einen
Dilatations-Puffer (MERGE_TOUCH_DILATE_PX), damit eine 1-Pixel-Luecke aus der
Konturextraktion (Anti-Aliasing am HSV-Schwellwertrand) nicht mehr dazu fuehrt,
dass eine einzige zusammenhaengende Zelle als zwei separate Zellen getrackt wird.

Verifizierte Realfaelle (Debug-Export 2026-06-30, 17:35-Frame): I45JTRXI/
9WMB6Q7Q und SKU9AD2B/IHAPWM5M, je 0,140 km = exakt 1 Pixel Abstand bei
UPSCALE_FACTOR=3.
"""
import cv2
import numpy as np
import pytest

ot = pytest.importorskip("object_tracking")

SHAPE = (50, 100)


def _rect_contour(x0, y0, x1, y1, shape=SHAPE):
    mask = np.zeros(shape, dtype=np.uint8)
    cv2.rectangle(mask, (x0, y0), (x1, y1), 255, -1)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return contours[0]


def test_one_pixel_gap_not_touching_without_dilation():
    """Realer 1px-Abstand (wie im verifizierten Debug-Fall) wird ohne Puffer
    NICHT erkannt -- das ist der bisherige (fehlerhafte) Zustand vor B274."""
    a = _rect_contour(10, 10, 19, 19)
    b = _rect_contour(21, 10, 29, 19)  # 1px Luecke bei x=20
    assert ot.are_contours_touching_edges(a, b, SHAPE, min_touch=3, dilate_px=0) is False


def test_one_pixel_gap_detected_with_default_dilation():
    """Mit dilate_px=2 (Default MERGE_TOUCH_DILATE_PX) wird dieselbe 1px-Luecke
    korrekt als beruehrend erkannt."""
    a = _rect_contour(10, 10, 19, 19)
    b = _rect_contour(21, 10, 29, 19)
    assert ot.are_contours_touching_edges(a, b, SHAPE, min_touch=3, dilate_px=2) is True


def test_far_apart_contours_never_merge_even_with_dilation():
    """Echte, weit getrennte Zellen duerfen trotz Puffer nicht zusammengefuehrt
    werden (kein False-Positive durch die Dilatation)."""
    a = _rect_contour(5, 5, 14, 14)
    b = _rect_contour(70, 5, 79, 14)  # 55px entfernt
    assert ot.are_contours_touching_edges(a, b, SHAPE, min_touch=3, dilate_px=2) is False


def test_merge_close_contours_joins_one_pixel_gap_with_dilate_px():
    a = _rect_contour(10, 10, 19, 19)
    b = _rect_contour(21, 10, 29, 19)
    result = ot.merge_close_contours([a, b], SHAPE, min_touch=3, dilate_px=2)
    assert len(result) == 1  # zu EINER Kontur zusammengefuehrt


def test_merge_close_contours_keeps_separate_without_dilate_px_param():
    """Backward-Kompatibilitaet: ruft man merge_close_contours ohne dilate_px
    auf (Default 0), bleibt das bisherige Verhalten fuer alle anderen,
    unbekannten Aufrufer unveraendert."""
    a = _rect_contour(10, 10, 19, 19)
    b = _rect_contour(21, 10, 29, 19)
    result = ot.merge_close_contours([a, b], SHAPE, min_touch=3)
    assert len(result) == 2


def test_config_default_dilate_value_is_2():
    import config
    assert config.MERGE_TOUCH_DILATE_PX == 2
