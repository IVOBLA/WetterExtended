"""B380: Das Intensitätsfeld muss die ARSO-Reflektivität ordnungserhaltend abbilden."""
import cv2
import numpy as np
import pytest

import object_tracking as ot

# Identisch zu tests/test_b275_multi_core_gap_check.py
RED_BGR = (0, 0, 200)        # Hue ~0   -> 54 dBZ
ORANGE_BGR = (0, 150, 230)   # Hue ~15  -> 48-51 dBZ
VIOLET_BGR = (200, 0, 150)   # Hue ~145 -> 57 dBZ
GREEN_BGR = (0, 200, 0)      # Hue ~60  -> 36-41 dBZ


def _field_value(bgr):
    """Intensitaetswert eines einfarbigen Blocks."""
    img = np.zeros((20, 20, 3), dtype=np.uint8)
    img[:] = bgr
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = np.full((20, 20), 255, dtype=np.uint8)
    return float(ot._intensity_field(hsv, mask)[10, 10])


def test_intensity_order_matches_dbz_scale():
    """Kernanforderung: gruen < orange < rot < violett."""
    gruen, orange, rot, violett = (_field_value(c) for c in (GREEN_BGR, ORANGE_BGR, RED_BGR, VIOLET_BGR))
    assert gruen < orange < rot < violett, (
        f"Reihenfolge verletzt: gruen={gruen}, orange={orange}, rot={rot}, violett={violett}"
    )


def test_red_and_orange_are_distinguishable():
    """Der konkrete B275-Fall: v*s lieferte fuer beide denselben Wert."""
    assert _field_value(RED_BGR) > _field_value(ORANGE_BGR), (
        "Rot (54 dBZ) muss staerker sein als Orange (49 dBZ) — sonst kann Watershed "
        "einen roten Kern nicht von einer orangen Bruecke trennen."
    )


def test_red_wrap_hue_maps_same_as_red():
    """Rot wrapt ueber Hue 0/179 — beide Enden muessen denselben Proxy liefern."""
    img_lo = np.zeros((20, 20, 3), dtype=np.uint8); img_lo[:] = (0, 0, 200)
    hsv_lo = cv2.cvtColor(img_lo, cv2.COLOR_BGR2HSV)
    hsv_hi = hsv_lo.copy()
    hsv_hi[:, :, 0] = 172                      # Rot-Wrap-Bereich
    mask = np.full((20, 20), 255, dtype=np.uint8)
    lo = float(ot._intensity_field(hsv_lo, mask)[10, 10])
    hi = float(ot._intensity_field(hsv_hi, mask)[10, 10])
    assert lo == hi, f"Rot-Wrap inkonsistent: hue~0 -> {lo}, hue=172 -> {hi}"


def test_unsaturated_pixel_is_zero():
    """Graustufen/Kartenrand duerfen kein Echo erzeugen."""
    img = np.zeros((20, 20, 3), dtype=np.uint8)
    img[:] = (128, 128, 128)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = np.full((20, 20), 255, dtype=np.uint8)
    assert float(ot._intensity_field(hsv, mask)[10, 10]) == 0.0


def test_mask_is_respected():
    img = np.zeros((20, 20, 3), dtype=np.uint8)
    img[:] = VIOLET_BGR
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = np.zeros((20, 20), dtype=np.uint8)
    assert float(ot._intensity_field(hsv, mask)[10, 10]) == 0.0


def test_core_peak_is_robust_against_single_pixel_noise():
    """Ein einzelner Ausreisser-Pixel darf das Kernmaximum nicht bestimmen."""
    field = np.full((40, 40), 200, dtype=np.uint8)
    field[20, 20] = 0                     # Rauschpixel exakt im Zentrum
    mask = np.full((40, 40), 255, dtype=np.uint8)
    assert ot._core_peak_intensity(field, mask, (20, 20)) == pytest.approx(200.0)


def test_saddle_uses_weaker_core_as_reference():
    """Referenz ist das schwaechere Kernmaximum, nicht das staerkere."""
    field = np.zeros((40, 120), dtype=np.uint8)
    mask = np.full((40, 120), 255, dtype=np.uint8)
    field[:, :] = 100          # Tal
    field[15:25, 5:15] = 255   # starker Kern links
    field[15:25, 105:115] = 150  # schwacher Kern rechts
    saddle = ot._core_saddle_ratio(field, mask, (10, 20), (110, 20))
    # Referenz min(255,150)=150, Tal=100 -> 1 - 100/150 = 0.333
    assert saddle == pytest.approx(1.0 - 100.0 / 150.0, abs=0.05)


def test_u_shape_with_real_gap_is_still_split():
    """B275-Regression: zwei rote Kerne, verbunden nur ueber eine orange U-Bruecke."""
    img = np.zeros((100, 150, 3), dtype=np.uint8)
    cv2.rectangle(img, (10, 10), (30, 90), ORANGE_BGR, -1)
    cv2.rectangle(img, (10, 70), (130, 90), ORANGE_BGR, -1)
    cv2.rectangle(img, (110, 10), (130, 90), ORANGE_BGR, -1)
    cv2.rectangle(img, (10, 10), (30, 30), RED_BGR, -1)
    cv2.rectangle(img, (110, 10), (130, 30), RED_BGR, -1)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = ((hsv[:, :, 1] > 50) & (hsv[:, :, 2] > 60)).astype(np.uint8) * 255
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    assert len(contours) == 1
    result = ot.split_multi_core_contours(contours, hsv)
    assert len(result) == 2, f"U-Form mit echter Luecke wurde nicht gesplittet: {len(result)}"
