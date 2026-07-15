"""B383: Sub-Zellen müssen auch ohne Intensitätsgradienten getrennt werden."""
import cv2
import numpy as np

import object_tracking as ot

RED_BGR = (0, 0, 200)        # Hue ~0  -> starkes Band
ORANGE_BGR = (0, 150, 230)   # Hue ~20 -> schwaecheres Band


def _hsv_mask(img):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = ((hsv[:, :, 1] > 50) & (hsv[:, :, 2] > 60)).astype(np.uint8) * 255
    return hsv, mask


def _u_shape():
    img = np.zeros((100, 150, 3), dtype=np.uint8)
    cv2.rectangle(img, (10, 10), (30, 90), ORANGE_BGR, -1)
    cv2.rectangle(img, (10, 70), (130, 90), ORANGE_BGR, -1)
    cv2.rectangle(img, (110, 10), (130, 90), ORANGE_BGR, -1)
    cv2.rectangle(img, (10, 10), (30, 30), RED_BGR, -1)
    cv2.rectangle(img, (110, 10), (130, 30), RED_BGR, -1)
    return img


def test_uniform_bridge_splits_evenly():
    """KERNREGRESSION: cv2.watershed lieferte [3910, 342] statt zweier Haelften."""
    hsv, mask = _hsv_mask(_u_shape())
    field = ot._intensity_field(hsv, mask)
    labels = ot._geodesic_priority_assign(mask, field, [(20.0, 20.0, 441), (120.0, 20.0, 441)])
    a1, a2 = int((labels == 1).sum()), int((labels == 2).sum())
    assert min(a1, a2) > 0.3 * max(a1, a2), f"Unausgewogene Teilung: {a1} / {a2}"


def test_u_shape_yields_two_children_at_production_min_area():
    """Mit dem LIVE-Wert MULTI_CORE_MIN_CHILD_AREA_PX=800 muessen 2 Kinder entstehen."""
    hsv, mask = _hsv_mask(_u_shape())
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    assert len(contours) == 1
    subs = ot._watershed_split(hsv, contours[0], [(20.0, 20.0, 441), (120.0, 20.0, 441)], 800)
    assert len(subs) == 2, f"Erwartet 2 Sub-Zellen bei min_child_area=800, erhalten {len(subs)}"


def test_boundary_follows_weak_bridge_not_midpoint():
    """Bei einem Sattel muss die Grenze in der schwachen Bruecke liegen."""
    img = np.zeros((60, 200, 3), dtype=np.uint8)
    cv2.rectangle(img, (0, 20), (200, 40), ORANGE_BGR, -1)
    cv2.rectangle(img, (10, 20), (60, 40), RED_BGR, -1)
    cv2.rectangle(img, (140, 20), (190, 40), RED_BGR, -1)
    hsv, mask = _hsv_mask(img)
    field = ot._intensity_field(hsv, mask)
    labels = ot._geodesic_priority_assign(mask, field, [(35.0, 30.0, 1000), (165.0, 30.0, 1000)])
    row = labels[30, :]
    boundary = [x for x in range(1, 200) if row[x] != row[x - 1] and row[x] > 0 and row[x - 1] > 0]
    assert boundary, "Keine Grenze gefunden"
    assert 60 <= boundary[0] <= 140, (
        f"Grenze bei x={boundary[0]} liegt nicht in der schwachen Bruecke (60..140)"
    )


def test_geodesic_respects_obstacles():
    """Die Distanz ist geodaetisch, nicht euklidisch — der Weg laeuft in der Maske."""
    hsv, mask = _hsv_mask(_u_shape())
    field = ot._intensity_field(hsv, mask)
    labels = ot._geodesic_priority_assign(mask, field, [(20.0, 20.0, 441), (120.0, 20.0, 441)])
    assert labels[50, 20] == 1


def test_every_masked_pixel_is_assigned():
    """Keine Wasserscheiden-Grenzpixel mehr — jeder erreichbare Pixel gehoert zu einem Kern."""
    hsv, mask = _hsv_mask(_u_shape())
    field = ot._intensity_field(hsv, mask)
    labels = ot._geodesic_priority_assign(mask, field, [(20.0, 20.0, 441), (120.0, 20.0, 441)])
    unassigned = int(((mask > 0) & (labels == 0)).sum())
    assert unassigned == 0, f"{unassigned} Pixel innerhalb der Maske blieben unzugeordnet"


def test_single_core_assigns_everything():
    hsv, mask = _hsv_mask(_u_shape())
    field = ot._intensity_field(hsv, mask)
    labels = ot._geodesic_priority_assign(mask, field, [(20.0, 20.0, 441)])
    assert int((labels == 1).sum()) == int((mask > 0).sum())


def test_marker_outside_mask_is_ignored():
    hsv, mask = _hsv_mask(_u_shape())
    field = ot._intensity_field(hsv, mask)
    labels = ot._geodesic_priority_assign(mask, field, [(20.0, 20.0, 441), (75.0, 5.0, 10)])
    assert int((labels == 2).sum()) == 0


def test_no_scikit_image_dependency():
    """Die Loesung darf keine neue Abhaengigkeit einfuehren."""
    import inspect
    src = inspect.getsource(ot)
    assert "skimage" not in src and "scikit" not in src


def test_cv2_watershed_no_longer_used():
    import inspect
    src = inspect.getsource(ot._watershed_split)
    assert "cv2.watershed" not in src, "cv2.watershed ist weiterhin im Split-Pfad"
    assert "_geodesic_priority_assign" in src
