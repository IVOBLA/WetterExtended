"""B394: Die Testgeometrien müssen einen gültigen Merge-Kandidaten erzeugen."""
import pytest
from shapely.geometry import Polygon

from tracking.transition_resolver import _cfg, find_merge_candidates


def _box(x1, y1, x2, y2):
    return Polygon([(x1, y1), (x2, y1), (x2, y2), (x1, y2)])


def test_new_geometry_explains_the_merge_contour():
    """Die B394-Geometrie muss ueber der Erklaerungsschwelle liegen."""
    a = _box(60, 160, 140, 240)
    b = _box(150, 160, 230, 240)
    merged = _box(60, 160, 230, 240)
    cands = find_merge_candidates({"A": a, "B": b}, {0: merged}, matched={0: "A"})
    assert len(cands) == 1, "Die neue Testgeometrie erzeugt keinen Merge-Kandidaten"
    assert cands[0].explained >= float(_cfg("TRANSITION_MERGE_MIN_EXPLAINED"))
    assert cands[0].explained == pytest.approx(0.94, abs=0.02)


def test_old_square_geometry_was_correctly_rejected():
    """Belegt, dass der Code richtig lag: die alte Geometrie IST ein Scheinmerge."""
    a = _box(60, 160, 140, 240)      # _square(100,200,half=40)
    b = _box(225, 175, 275, 225)     # _square(250,200,half=25)
    merged = _box(80, 105, 270, 295)  # _square(175,200,half=95)
    explained = (a.intersection(merged).area + b.intersection(merged).area) / merged.area
    assert explained < 0.20, f"Testannahme falsch: explained={explained:.3f}"
    assert find_merge_candidates({"A": a, "B": b}, {0: merged}, matched={0: "A"}) == [], (
        "Eine Kontur, die 4x groesser ist als die Summe ihrer Parents, darf kein "
        "Merge sein — sie ist eine Systemhuelle (Analyse 5.9)"
    )


def test_each_parent_meets_coverage():
    a = _box(60, 160, 140, 240)
    b = _box(150, 160, 230, 240)
    merged = _box(60, 160, 230, 240)
    min_cov = float(_cfg("TRANSITION_MERGE_MIN_PARENT_COVERAGE"))
    for p in (a, b):
        assert p.intersection(merged).area / p.area >= min_cov


def test_threshold_matches_real_convection():
    """Die Schwelle liegt unter dem realen p10 (0.48) — sie verwirft keine echten Merges.

    Kalibrierung gegen den Debug-Export 14.07.2026 (160 Merge-Beobachtungen mit
    Parent-Geometrie, explained nach B387-Union): Median 1.00, p25 0.69, p10 0.48.
    """
    assert float(_cfg("TRANSITION_MERGE_MIN_EXPLAINED")) <= 0.50


def test_rect_helper_present_in_both_tests():
    for path in ("tests/test_b385_pre_frame_parent_snapshot.py",
                 "tests/test_b391_merge_parent_ueberlebt_kandidatenphase.py"):
        src = open(path, encoding="utf-8").read()
        assert "_rect_contour" in src, f"{path} nutzt weiterhin nur Quadrate"
