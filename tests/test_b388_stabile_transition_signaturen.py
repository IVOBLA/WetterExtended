"""B388: Signaturen müssen invariant gegen die OpenCV-Konturreihenfolge sein."""
from tracking.transition_resolver import (
    confirm_candidates,
    find_merge_candidates,
    find_split_candidates,
)



class _Rect:
    def __init__(self, x1, y1, x2, y2):
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2

    @property
    def area(self):
        return max(0, self.x2 - self.x1) * max(0, self.y2 - self.y1)

    def intersection(self, other):
        return _Rect(
            max(self.x1, other.x1),
            max(self.y1, other.y1),
            min(self.x2, other.x2),
            min(self.y2, other.y2),
        )


def _box(x1, y1, x2, y2):
    return _Rect(x1, y1, x2, y2)


def test_merge_signature_survives_index_shift():
    """KERNREGRESSION: gleiche Geometrie, anderer Detektionsindex -> gleiche Signatur."""
    tracks = {"A": _box(0, 0, 70, 10), "B": _box(75, 0, 100, 10)}
    det = _box(0, 0, 100, 10)

    c_idx0 = find_merge_candidates(tracks, {0: det}, matched={0: "A"})
    # Im Folgeframe liefert cv2.findContours dieselbe Kontur an Index 3.
    c_idx3 = find_merge_candidates(tracks, {3: det}, matched={3: "A"})

    assert c_idx0 and c_idx3
    assert c_idx0[0].signature == c_idx3[0].signature, (
        "Signatur haengt am Detektionsindex — die Bestaetigung faellt auf Frame 1 zurueck"
    )


def test_merge_confirms_despite_index_shift():
    """Der Uebergang MUSS bestaetigt werden, auch wenn der Index wechselt."""
    tracks = {"A": _box(0, 0, 70, 10), "B": _box(75, 0, 100, 10)}
    det = _box(0, 0, 100, 10)

    confirmed, still, _, pending = confirm_candidates(
        find_merge_candidates(tracks, {0: det}, matched={0: "A"}), {})
    assert confirmed == [] and len(still) == 1

    # Frame 2: identische Geometrie, aber verschobener Index.
    confirmed, still, reverted, pending = confirm_candidates(
        find_merge_candidates(tracks, {7: det}, matched={7: "A"}), pending)
    assert len(confirmed) == 1, (
        "Uebergang wurde trotz unveraenderter Geometrie nicht bestaetigt"
    )
    assert reverted == [], f"Falsches revert bei Indexwechsel: {reverted}"


def test_split_signature_survives_index_shift():
    tracks = {"A": _box(0, 0, 10, 10)}
    a = find_split_candidates(tracks, {0: _box(0, 0, 4, 10), 1: _box(6, 0, 10, 10)}, matched={0: "A"})
    b = find_split_candidates(tracks, {5: _box(0, 0, 4, 10), 9: _box(6, 0, 10, 10)}, matched={5: "A"})
    assert a and b
    assert a[0].signature == b[0].signature


def test_split_confirms_despite_index_shift():
    tracks = {"A": _box(0, 0, 10, 10)}
    _, _, _, pending = confirm_candidates(
        find_split_candidates(tracks, {0: _box(0, 0, 4, 10), 1: _box(6, 0, 10, 10)}, matched={0: "A"}), {})
    confirmed, _, reverted, _ = confirm_candidates(
        find_split_candidates(tracks, {4: _box(0, 0, 4, 10), 8: _box(6, 0, 10, 10)}, matched={4: "A"}), pending)
    assert len(confirmed) == 1 and reverted == []


def test_different_child_count_is_a_different_split():
    """2er- und 3er-Split desselben Parents sind verschiedene Ereignisse."""
    tracks = {"A": _box(0, 0, 30, 10)}
    two = find_split_candidates(tracks, {0: _box(0, 0, 14, 10), 1: _box(16, 0, 30, 10)}, matched={})
    three = find_split_candidates(
        tracks, {0: _box(0, 0, 9, 10), 1: _box(10, 0, 19, 10), 2: _box(20, 0, 30, 10)}, matched={})
    assert two and three
    assert two[0].signature != three[0].signature


def test_different_parent_sets_differ():
    det = _box(0, 0, 100, 10)
    ab = find_merge_candidates({"A": _box(0, 0, 70, 10), "B": _box(75, 0, 100, 10)}, {0: det}, matched={0: "A"})
    ac = find_merge_candidates({"A": _box(0, 0, 70, 10), "C": _box(75, 0, 100, 10)}, {0: det}, matched={0: "A"})
    assert ab and ac
    assert ab[0].signature != ac[0].signature


def test_parent_order_does_not_matter():
    det = _box(0, 0, 100, 10)
    t1 = {"A": _box(0, 0, 70, 10), "B": _box(75, 0, 100, 10)}
    t2 = {"B": _box(75, 0, 100, 10), "A": _box(0, 0, 70, 10)}
    s1 = find_merge_candidates(t1, {0: det}, matched={0: "A"})[0].signature
    s2 = find_merge_candidates(t2, {0: det}, matched={0: "A"})[0].signature
    assert s1 == s2


def test_no_detection_index_in_signature_payload():
    """Regression: Detektionsindizes duerfen nicht zurueckkehren."""
    import inspect
    import tracking.transition_resolver as tr
    src = inspect.getsource(tr)
    assert 'transition_signature("merge", parents, [str(det_idx)])' not in src
    assert 'transition_signature("split", [tid], [str(c) for c in children])' not in src
    assert "_stable_merge_key" in src and "_stable_child_key" in src


def test_children_still_available_for_object_loop():
    """`children` bleibt erhalten — nur die Identitaet nutzt sie nicht mehr."""
    tracks = {"A": _box(0, 0, 10, 10)}
    cands = find_split_candidates(tracks, {2: _box(0, 0, 4, 10), 5: _box(6, 0, 10, 10)}, matched={2: "A"})
    assert sorted(cands[0].children) == [2, 5]
    assert cands[0].primary_child == 2
