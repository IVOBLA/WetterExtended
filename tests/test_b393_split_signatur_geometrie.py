"""B393: Split-Signaturen brauchen Kindgeometrie, nicht nur die Anzahl."""
from tracking.transition_resolver import confirm_candidates, find_split_candidates

class _Rect:
    def __init__(self, x1, y1, x2, y2):
        self.x1 = float(x1); self.y1 = float(y1); self.x2 = float(x2); self.y2 = float(y2)
    @property
    def area(self):
        return max(0.0, self.x2 - self.x1) * max(0.0, self.y2 - self.y1)
    @property
    def bounds(self):
        return self.x1, self.y1, self.x2, self.y2
    def intersection(self, other):
        return _Rect(max(self.x1, other.x1), max(self.y1, other.y1), min(self.x2, other.x2), min(self.y2, other.y2))

def _box(x1, y1, x2, y2): return _Rect(x1, y1, x2, y2)

def _signature(parent, children, matched=None):
    candidates = find_split_candidates({"A": parent}, children, matched or {})
    assert len(candidates) == 1
    return candidates[0].signature

def test_same_geometry_survives_detection_index_shift():
    parent = _box(0, 0, 100, 100)
    first = _signature(parent, {0: _box(0, 0, 45, 100), 1: _box(55, 0, 100, 100)}, {0: "A"})
    second = _signature(parent, {7: _box(0, 0, 45, 100), 9: _box(55, 0, 100, 100)}, {7: "A"})
    assert first == second

def test_child_order_does_not_change_signature():
    parent = _box(0, 0, 100, 100); left = _box(0, 0, 45, 100); right = _box(55, 0, 100, 100)
    assert _signature(parent, {0: left, 1: right}) == _signature(parent, {0: right, 1: left})

def test_common_translation_is_invariant():
    first = _signature(_box(0, 0, 100, 100), {0: _box(0, 0, 45, 100), 1: _box(55, 0, 100, 100)})
    translated = _signature(_box(200, 300, 300, 400), {4: _box(200, 300, 245, 400), 8: _box(255, 300, 300, 400)})
    assert first == translated

def test_common_scale_is_invariant():
    first = _signature(_box(0, 0, 100, 100), {0: _box(0, 0, 45, 100), 1: _box(55, 0, 100, 100)})
    scaled = _signature(_box(0, 0, 200, 200), {4: _box(0, 0, 90, 200), 8: _box(110, 0, 200, 200)})
    assert first == scaled

def test_horizontal_and_vertical_two_child_splits_differ():
    parent = _box(0, 0, 100, 100)
    left_right = _signature(parent, {0: _box(0, 0, 45, 100), 1: _box(55, 0, 100, 100)})
    top_bottom = _signature(parent, {0: _box(0, 0, 100, 45), 1: _box(0, 55, 100, 100)})
    assert left_right != top_bottom

def test_replaced_child_changes_signature():
    parent = _box(0, 0, 100, 100)
    original = _signature(parent, {0: _box(0, 0, 45, 100), 1: _box(55, 0, 100, 100)})
    replaced = _signature(parent, {0: _box(0, 0, 45, 100), 1: _box(55, 50, 100, 100)})
    assert original != replaced

def test_same_count_but_different_area_shares_differ():
    parent = _box(0, 0, 100, 100)
    balanced = _signature(parent, {0: _box(0, 0, 45, 100), 1: _box(55, 0, 100, 100)})
    unbalanced = _signature(parent, {0: _box(0, 0, 70, 100), 1: _box(80, 0, 100, 100)})
    assert balanced != unbalanced

def test_small_segmentation_jitter_remains_same_signature():
    parent = _box(0, 0, 100, 100)
    first = _signature(parent, {0: _box(0, 0, 45, 100), 1: _box(55, 0, 100, 100)})
    jittered = _signature(parent, {2: _box(1, 0, 46, 100), 3: _box(54, 0, 99, 100)})
    assert first == jittered

def test_different_geometry_does_not_inherit_pending_counter():
    parent = _box(0, 0, 100, 100)
    vertical = find_split_candidates({"A": parent}, {0: _box(0, 0, 45, 100), 1: _box(55, 0, 100, 100)}, {0: "A"})
    confirmed, still, _, pending = confirm_candidates(vertical, {})
    assert confirmed == []
    assert len(still) == 1
    horizontal = find_split_candidates({"A": parent}, {4: _box(0, 0, 100, 45), 8: _box(0, 55, 100, 100)}, {4: "A"})
    confirmed, still, reverted, pending = confirm_candidates(horizontal, pending)
    assert confirmed == []
    assert len(still) == 1
    assert len(reverted) == 1
    assert list(pending.values()) == [1]
