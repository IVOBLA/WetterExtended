"""B275: split_multi_core_contours() darf zwei erkannte Konvektionskerne nur
splitten, wenn zwischen ihnen eine ECHTE Luecke in der aeusseren Zell-Maske
existiert. Bleibt die Verbindungslinie zwischen den Kern-Zentren komplett
innerhalb der Maske, handelt es sich um eine einzige zusammenhaengende
Wetterstruktur (z. B. eine elongierte Boeenlinie mit mehreren Reflektivitaets-
Maxima) und darf nicht gesplittet werden.

Verifiziert am realen Debug-Export 2026-06-30, 17:35-Frame: die Zellen
I45JTRXI/9WMB6Q7Q stammten aus EINER 18.586-px-Kontur mit zwei 170px
(ca. 18,9 km) entfernten Kernen, deren Verbindungslinie zu 0/100 Samples
ausserhalb der Zell-Maske lag -- die Tests hier bilden dieses Muster
synthetisch nach (Boegenlinie ohne Luecke vs. U-Form mit echter Luecke).
"""
import cv2
import numpy as np
import pytest

ot = pytest.importorskip("object_tracking")

RED_BGR = (0, 0, 200)       # -> Hue ~0, in CORE_HSV_RANGES
ORANGE_BGR = (0, 150, 230)  # -> Hue ~15, in allowed_hsv_ranges, NICHT in CORE_HSV_RANGES


def _contour_from_bgr(img_bgr):
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
    mask[(img_bgr.sum(axis=2) > 0)] = 255
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return hsv, contours


def test_core_path_gap_px_zero_for_continuous_mask():
    """Verbindungslinie verlaeuft komplett innerhalb der Maske -> gap=0.0."""
    mask = np.zeros((60, 200), dtype=np.uint8)
    cv2.rectangle(mask, (10, 20), (189, 39), 255, -1)
    gap = ot._core_path_gap_px(mask, (20, 29), (180, 29))
    assert gap == 0.0


def test_core_path_gap_px_detects_real_gap():
    """U-Form: Verbindungslinie zwischen den Spitzen verlaeuft durch die
    echte Luecke in der Mitte -> deutlich messbare Luecke."""
    mask = np.zeros((100, 150), dtype=np.uint8)
    cv2.rectangle(mask, (10, 10), (30, 90), 255, -1)
    cv2.rectangle(mask, (10, 70), (130, 90), 255, -1)
    cv2.rectangle(mask, (110, 10), (130, 90), 255, -1)
    gap = ot._core_path_gap_px(mask, (20, 20), (120, 20))
    assert gap > 50.0


def test_squall_line_with_two_cores_is_not_split():
    """Realfall-Muster: ein durchgehender Balken (eine einzige Boeenlinie)
    mit zwei Kernen an den Enden, dazwischen durchgehend mind. die
    allowed_hsv_ranges-Schwelle (orange) -- darf NICHT gesplittet werden."""
    img = np.zeros((60, 220, 3), dtype=np.uint8)
    cv2.rectangle(img, (10, 20), (209, 39), ORANGE_BGR, -1)
    cv2.rectangle(img, (10, 15), (40, 44), RED_BGR, -1)
    cv2.rectangle(img, (180, 15), (209, 44), RED_BGR, -1)
    hsv, contours = _contour_from_bgr(img)
    assert len(contours) == 1
    result = ot.split_multi_core_contours(contours, hsv)
    assert len(result) == 1


def test_u_shape_with_two_cores_and_real_gap_is_split():
    """Echte Luecke zwischen den Kernen (Verbindung nur ueber Umweg/Boegen,
    nicht direkt) -- Split bleibt korrekt erhalten."""
    img = np.zeros((100, 150, 3), dtype=np.uint8)
    cv2.rectangle(img, (10, 10), (30, 90), ORANGE_BGR, -1)
    cv2.rectangle(img, (10, 70), (130, 90), ORANGE_BGR, -1)
    cv2.rectangle(img, (110, 10), (130, 90), ORANGE_BGR, -1)
    cv2.rectangle(img, (10, 10), (30, 30), RED_BGR, -1)
    cv2.rectangle(img, (110, 10), (130, 30), RED_BGR, -1)
    hsv, contours = _contour_from_bgr(img)
    assert len(contours) == 1
    result = ot.split_multi_core_contours(contours, hsv)
    assert len(result) == 2


def test_close_cores_still_blocked_by_distance_check_regardless_of_gap():
    """Regression: Kerne naeher als MULTI_CORE_MIN_DIST_PX duerfen weiterhin
    nicht gesplittet werden, auch wenn (hypothetisch) eine Luecke vorlaege --
    der bestehende Abstands-Check greift weiterhin VOR dem neuen Gap-Check."""
    img = np.zeros((60, 80, 3), dtype=np.uint8)
    cv2.rectangle(img, (10, 20), (69, 39), ORANGE_BGR, -1)
    cv2.rectangle(img, (15, 18), (25, 41), RED_BGR, -1)
    cv2.rectangle(img, (35, 18), (45, 41), RED_BGR, -1)  # nur ~20px von Kern 1 entfernt
    hsv, contours = _contour_from_bgr(img)
    result = ot.split_multi_core_contours(contours, hsv)
    assert len(result) == 1


def test_config_default_gap_threshold_is_2():
    import config
    assert config.MULTI_CORE_MIN_GAP_PX == 2.0
