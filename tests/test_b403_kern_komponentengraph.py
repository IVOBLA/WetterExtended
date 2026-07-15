"""B403: Ein untrennbares Kernpaar darf nicht den ganzen Komplex blockieren."""
import cv2
import numpy as np

import object_tracking as ot

RED_BGR = (0, 0, 200)        # starkes Band
ORANGE_BGR = (0, 150, 230)   # schwaecheres Band


def _field_and_mask(img):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = ((hsv[:, :, 1] > 50) & (hsv[:, :, 2] > 60)).astype(np.uint8) * 255
    return hsv, ot._intensity_field(hsv, mask), mask


def _line_plus_separate_cell():
    """A━━B (durchgehende Linie, kein Sattel) + C (klar getrennt)."""
    img = np.zeros((120, 300, 3), dtype=np.uint8)
    cv2.rectangle(img, (10, 40), (150, 70), RED_BGR, -1)     # Linie A..B, durchgehend stark
    cv2.rectangle(img, (150, 50), (200, 60), ORANGE_BGR, -1)  # schwache Bruecke zu C
    cv2.rectangle(img, (200, 40), (260, 70), RED_BGR, -1)     # Zelle C
    return img


def test_line_plus_cell_yields_two_components():
    """KERNREGRESSION: A-B untrennbar, C trennbar -> 2 Komponenten (vorher: 0 Splits)."""
    hsv, field, mask = _field_and_mask(_line_plus_separate_cell())
    cores = [(40.0, 55.0, 400), (120.0, 55.0, 400), (230.0, 55.0, 400)]   # A, B, C
    groups = ot._core_components(field, mask, cores, min_dist_px=15,
                                min_saddle=0.35, min_gap_px=2.0)
    assert len(groups) == 2, f"Erwartet 2 Komponenten, erhalten {len(groups)}: {groups}"
    sizes = sorted(len(g) for g in groups)
    assert sizes == [1, 2], f"Erwartet {{A,B}} und {{C}}, erhalten Groessen {sizes}"


def test_line_cores_stay_together():
    """A und B duerfen nicht gegeneinander segmentiert werden."""
    hsv, field, mask = _field_and_mask(_line_plus_separate_cell())
    cores = [(40.0, 55.0, 400), (120.0, 55.0, 400), (230.0, 55.0, 400)]
    groups = ot._core_components(field, mask, cores, 15, 0.35, 2.0)
    pair = [g for g in groups if len(g) == 2]
    assert pair and set(pair[0]) == {0, 1}, f"A und B nicht in derselben Komponente: {groups}"


def test_uniform_line_is_one_component():
    """Reine Boeenlinie ohne Sattel -> KEIN Split (Regression aus B376)."""
    img = np.zeros((120, 300, 3), dtype=np.uint8)
    cv2.rectangle(img, (10, 40), (260, 70), RED_BGR, -1)
    hsv, field, mask = _field_and_mask(img)
    cores = [(40.0, 55.0, 400), (135.0, 55.0, 400), (230.0, 55.0, 400)]
    groups = ot._core_components(field, mask, cores, 15, 0.35, 2.0)
    assert len(groups) == 1, f"Durchgehende Linie wurde gesplittet: {groups}"


def test_all_separate_yields_all_components():
    """Drei klar getrennte Kerne -> drei Komponenten."""
    img = np.zeros((120, 300, 3), dtype=np.uint8)
    for cx in (40, 135, 230):
        cv2.rectangle(img, (cx - 20, 40), (cx + 20, 70), RED_BGR, -1)
    hsv, field, mask = _field_and_mask(img)
    cores = [(40.0, 55.0, 400), (135.0, 55.0, 400), (230.0, 55.0, 400)]
    groups = ot._core_components(field, mask, cores, 15, 0.35, 2.0)
    assert len(groups) == 3


def test_cores_below_min_dist_are_merged():
    """Zu dicht beieinander -> ein Kern, nicht trennbar."""
    img = np.zeros((120, 300, 3), dtype=np.uint8)
    cv2.rectangle(img, (10, 40), (260, 70), RED_BGR, -1)
    hsv, field, mask = _field_and_mask(img)
    cores = [(100.0, 55.0, 400), (105.0, 55.0, 400)]     # 5 px < min_dist 15
    groups = ot._core_components(field, mask, cores, 15, 0.35, 2.0)
    assert len(groups) == 1


def test_single_core_is_one_component():
    img = np.zeros((120, 300, 3), dtype=np.uint8)
    cv2.rectangle(img, (10, 40), (80, 70), RED_BGR, -1)
    hsv, field, mask = _field_and_mask(img)
    assert len(ot._core_components(field, mask, [(45.0, 55.0, 400)], 15, 0.35, 2.0)) == 1


def test_empty_cores_is_safe():
    img = np.zeros((60, 60, 3), dtype=np.uint8)
    hsv, field, mask = _field_and_mask(img)
    assert ot._core_components(field, mask, [], 15, 0.35, 2.0) == []


def test_components_are_deterministic():
    """Union-Find muss reihenfolgeinvariant sein (analog B370)."""
    hsv, field, mask = _field_and_mask(_line_plus_separate_cell())
    cores = [(40.0, 55.0, 400), (120.0, 55.0, 400), (230.0, 55.0, 400)]
    first = ot._core_components(field, mask, cores, 15, 0.35, 2.0)
    for _ in range(3):
        assert ot._core_components(field, mask, cores, 15, 0.35, 2.0) == first


def test_conjunction_removed():
    """Statischer Nachweis: die Alles-oder-Nichts-Bedingung ist weg."""
    import inspect
    src = inspect.getsource(ot.split_multi_core_contours)
    assert "_pairs_ok == _pairs_checked" not in src, "Konjunktion noch vorhanden"
    assert "_core_components" in src


def test_split_produces_two_children_for_line_plus_cell():
    """End-to-End: Linie + separate Zelle -> 2 Sub-Konturen."""
    img = _line_plus_separate_cell()
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = ((hsv[:, :, 1] > 50) & (hsv[:, :, 2] > 60)).astype(np.uint8) * 255
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    assert len(contours) == 1, "Testaufbau: erwartet EINE zusammenhaengende Kontur"
    result = ot.split_multi_core_contours(contours, hsv)
    assert len(result) == 2, (
        f"Linie + separate Zelle ergab {len(result)} statt 2 Sub-Zellen — "
        "das untrennbare Linienpaar blockiert weiterhin den Komplex"
    )
