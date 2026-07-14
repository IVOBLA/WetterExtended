"""B370: merge_close_contours() muss transitiv und reihenfolgeinvariant sein."""
import itertools

import numpy as np
import pytest

import object_tracking as ot


SHAPE = (200, 200)


def _rect(x1, y1, x2, y2):
    """Rechteckige Kontur im OpenCV-Format (N,1,2)."""
    pts = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
    return np.array(pts, dtype=np.int32).reshape(-1, 1, 2)


def _areas(result):
    return sorted(round(float(abs(_shoelace(c))), 3) for c in result)


def _shoelace(cnt):
    p = cnt[:, 0, :].astype(float)
    x, y = p[:, 0], p[:, 1]
    return 0.5 * np.dot(x, np.roll(y, -1)) - 0.5 * np.dot(y, np.roll(x, -1))


def test_transitive_chain_yields_single_component():
    """A beruehrt B, B beruehrt C, A beruehrt C nicht -> genau EINE Gruppe."""
    a = _rect(10, 10, 40, 40)
    b = _rect(40, 10, 70, 40)   # teilt Kante mit A
    c = _rect(70, 10, 100, 40)  # teilt Kante mit B, nicht mit A
    result = ot.merge_close_contours([a, b, c], SHAPE, min_touch=1, dilate_px=0)
    assert len(result) == 1, f"Transitive Kette nicht zusammengefuehrt: {len(result)} Gruppen"


def test_order_invariance_all_permutations():
    """Alle Eingabereihenfolgen muessen dasselbe Ergebnis liefern."""
    a = _rect(10, 10, 40, 40)
    b = _rect(40, 10, 70, 40)
    c = _rect(70, 10, 100, 40)
    reference = None
    for perm in itertools.permutations([a, b, c]):
        result = ot.merge_close_contours(list(perm), SHAPE, min_touch=1, dilate_px=0)
        signature = (len(result), _areas(result))
        if reference is None:
            reference = signature
        assert signature == reference, f"Reihenfolgeabhaengig: {signature} != {reference}"


def test_disjoint_contours_stay_separate():
    """Weit getrennte Konturen duerfen NICHT gruppiert werden."""
    a = _rect(10, 10, 30, 30)
    b = _rect(150, 150, 180, 180)
    result = ot.merge_close_contours([a, b], SHAPE, min_touch=1, dilate_px=0)
    assert len(result) == 2, "Disjunkte Konturen faelschlich zusammengefuehrt"


def test_empty_input_returns_empty():
    assert ot.merge_close_contours([], SHAPE, min_touch=1, dilate_px=0) == []


def test_single_contour_passthrough():
    a = _rect(10, 10, 40, 40)
    result = ot.merge_close_contours([a], SHAPE, min_touch=1, dilate_px=0)
    assert len(result) == 1


def test_bbox_pruning_does_not_drop_real_touches():
    """Das Bounding-Box-Gate darf echte Beruehrungen mit dilate_px>0 nicht verwerfen."""
    a = _rect(10, 10, 40, 40)
    b = _rect(42, 10, 70, 40)  # 2px Luecke -> nur mit dilate_px=2 beruehrend
    merged_with_dilate = ot.merge_close_contours([a, b], SHAPE, min_touch=1, dilate_px=2)
    assert len(merged_with_dilate) == 1, "dilate_px=2 haette die 2px-Luecke schliessen muessen"
