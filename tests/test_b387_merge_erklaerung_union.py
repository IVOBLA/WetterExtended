"""B387: Die Merge-Erklärung muss den Survivor enthalten und darf nicht doppelt zählen."""
import pytest

shapely_geometry = pytest.importorskip("shapely.geometry")
try:
    _probe = shapely_geometry.Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
    assert hasattr(_probe, "intersection")
except Exception as exc:  # pragma: no cover - nur fuer minimale Test-Stubs
    pytest.skip(f"echte shapely-Polygonklasse nicht verfuegbar: {exc}", allow_module_level=True)
Polygon = shapely_geometry.Polygon

from tracking.transition_resolver import _explained_union_ratio, find_merge_candidates


def _box(x1, y1, x2, y2):
    return Polygon([(x1, y1), (x2, y1), (x2, y2), (x1, y2)])


def test_survivor_contribution_is_counted():
    """KERNFALL: Survivor 70 % + Secondary 25 % = 95 % -> Merge muss bestaetigt werden.

    Vorher wurde der Survivor mit 0.0 gezaehlt -> nur 25 % -> Merge verworfen.
    """
    det = _box(0, 0, 100, 10)
    tracks = {
        "SURV": _box(0, 0, 70, 10),    # 70 % der neuen Kontur
        "SEC":  _box(75, 0, 100, 10),  # 25 %
    }
    cands = find_merge_candidates(tracks, {0: det}, matched={0: "SURV"})
    assert len(cands) == 1, "Merge mit 95 % Erklaerung wurde verworfen"
    assert set(cands[0].parents) == {"SURV", "SEC"}
    assert cands[0].explained >= 0.90, f"explained={cands[0].explained} — Survivor fehlt"


def test_overlapping_parents_are_not_double_counted():
    """Zwei stark ueberlappende Parents duerfen explained nicht ueber 1.0 treiben."""
    det = _box(0, 0, 100, 10)
    a = _box(0, 0, 90, 10)
    b = _box(5, 0, 95, 10)   # ueberlappt a fast vollstaendig
    ratio = _explained_union_ratio(det, [a, b])
    assert ratio <= 1.0, f"explained={ratio} > 1.0 — Doppelzaehlung"
    assert ratio == pytest.approx(0.95, abs=0.02)


def test_explained_ratio_is_bounded():
    """Abnahmekriterium: explained_ratio liegt immer in [0, 1]."""
    det = _box(0, 0, 10, 10)
    parents = [_box(0, 0, 10, 10) for _ in range(5)]   # 5x dieselbe Flaeche
    ratio = _explained_union_ratio(det, parents)
    assert 0.0 <= ratio <= 1.0
    assert ratio == pytest.approx(1.0)


def test_sum_would_have_exceeded_one():
    """Gegenprobe: die alte Summenlogik haette hier 5.0 ergeben."""
    det = _box(0, 0, 10, 10)
    parents = [_box(0, 0, 10, 10) for _ in range(5)]
    naive_sum = sum(det.intersection(p).area for p in parents) / det.area
    assert naive_sum == pytest.approx(5.0), "Testaufbau prueft die Doppelzaehlung nicht"
    assert _explained_union_ratio(det, parents) == pytest.approx(1.0)


def test_track_matched_to_other_detection_is_no_parent():
    """Ein Track, der 1:1 einer ANDEREN Detektion zugeordnet ist, lebt eigenstaendig weiter."""
    det0 = _box(0, 0, 100, 10)
    det1 = _box(0, 20, 100, 30)
    tracks = {
        "SURV":  _box(0, 0, 70, 10),
        "OTHER": _box(0, 0, 60, 10),    # ueberlappt det0 stark, ist aber det1 zugeordnet
    }
    cands = find_merge_candidates(tracks, {0: det0, 1: det1}, matched={0: "SURV", 1: "OTHER"})
    merge0 = [c for c in cands if c.children == [0]]
    assert not merge0, "Ein anderweitig gematchter Track wurde faelschlich Merge-Parent"


def test_secondary_below_coverage_is_rejected():
    """Die Eigenabdeckungsschranke je Parent bleibt wirksam."""
    det = _box(0, 0, 100, 10)
    tracks = {
        "SURV": _box(0, 0, 70, 10),
        "TINY": _box(95, 0, 100, 200),   # nur ~2 % der eigenen Flaeche im Ziel
    }
    cands = find_merge_candidates(tracks, {0: det}, matched={0: "SURV"})
    assert not cands, "Randtrack unter MIN_PARENT_COVERAGE wurde Merge-Parent"


def test_single_parent_is_no_merge():
    det = _box(0, 0, 100, 10)
    cands = find_merge_candidates({"SURV": _box(0, 0, 70, 10)}, {0: det}, matched={0: "SURV"})
    assert cands == []


def test_parents_explaining_too_little_are_rejected():
    """Riesige Systemkontur, die die Parents nicht erklaeren -> kein Merge."""
    det = _box(0, 0, 100, 100)
    tracks = {"A": _box(0, 0, 5, 5), "B": _box(10, 0, 15, 5)}
    assert find_merge_candidates(tracks, {0: det}, matched={}) == []


def test_empty_and_none_inputs_are_safe():
    assert find_merge_candidates({}, {}, {}) == []
    assert _explained_union_ratio(_box(0, 0, 10, 10), []) == 0.0
    assert _explained_union_ratio(_box(0, 0, 10, 10), [None]) == 0.0
