"""B375: Übergänge sind Ereignisse, keine Dauerzustände. Split muss erreichbar sein."""


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

from tracking.transition_resolver import (
    confirm_candidates,
    find_merge_candidates,
    find_split_candidates,
    transition_signature,
)


def _box(x1, y1, x2, y2):
    return _Rect(x1, y1, x2, y2)


def test_split_candidate_is_detected():
    """Der Kernbefund: 0 Splits in 724 Beobachtungen trotz P66-Sub-Zellen."""
    parent = {"A": _box(0, 0, 10, 10)}
    children = {0: _box(0, 0, 4, 10), 1: _box(6, 0, 10, 10)}
    cands = find_split_candidates(parent, children, matched={})
    assert len(cands) == 1
    assert cands[0].kind == "split"
    assert sorted(cands[0].children) == [0, 1]


def test_split_needs_at_least_two_children():
    parent = {"A": _box(0, 0, 10, 10)}
    cands = find_split_candidates(parent, {0: _box(0, 0, 9, 10)}, matched={})
    assert cands == []


def test_merge_candidate_requires_relevant_parent_contribution():
    """Kleiner Randtrack darf kein Merge-Parent werden (alter 0.30-Fallback)."""
    tracks = {"A": _box(0, 0, 10, 10), "B": _box(0, 0, 10, 10)}
    detections = {0: _box(0, 0, 12, 12)}
    cands = find_merge_candidates(tracks, detections, matched={})
    assert len(cands) == 1 and sorted(cands[0].parents) == ["A", "B"]


def test_merge_rejected_when_parents_explain_too_little():
    """Riesige Systemkontur, die die Parents nicht erklaeren -> kein Merge."""
    tracks = {"A": _box(0, 0, 2, 2), "B": _box(3, 0, 5, 2)}
    detections = {0: _box(0, 0, 100, 100)}
    cands = find_merge_candidates(tracks, detections, matched={})
    assert cands == [], "Scheinmerge einer Systemhuelle wurde nicht abgelehnt"


def test_candidate_confirmed_only_after_two_frames():
    tracks = {"A": _box(0, 0, 10, 10), "B": _box(0, 0, 10, 10)}
    detections = {0: _box(0, 0, 12, 12)}
    cands = find_merge_candidates(tracks, detections, matched={})

    confirmed, still, reverted, pending = confirm_candidates(cands, {})
    assert confirmed == [] and len(still) == 1, "Frame 1 darf noch nicht bestaetigen"

    cands2 = find_merge_candidates(tracks, detections, matched={})
    confirmed, still, reverted, pending = confirm_candidates(cands2, pending)
    assert len(confirmed) == 1 and confirmed[0].phase == "confirmed"


def test_vanished_candidate_is_reverted():
    tracks = {"A": _box(0, 0, 10, 10), "B": _box(0, 0, 10, 10)}
    detections = {0: _box(0, 0, 12, 12)}
    _, _, _, pending = confirm_candidates(find_merge_candidates(tracks, detections, {}), {})
    confirmed, still, reverted, pending2 = confirm_candidates([], pending)
    assert len(reverted) == 1 and confirmed == [] and pending2 == {}


def test_repeated_merge_confirms_once_not_every_frame():
    """Kernregression: 10 Folgeframes duerfen nicht 10 Ereignisse erzeugen."""
    tracks = {"A": _box(0, 0, 10, 10), "B": _box(0, 0, 10, 10)}
    detections = {0: _box(0, 0, 12, 12)}
    pending, signatures = {}, []
    for _ in range(10):
        cands = find_merge_candidates(tracks, detections, matched={})
        confirmed, _, _, pending = confirm_candidates(cands, pending)
        signatures.extend(c.signature for c in confirmed)
    assert len(set(signatures)) == 1, "Es darf nur EINE Ereignissignatur geben"


def test_signature_is_order_invariant():
    assert transition_signature("merge", ["A", "B"], ["0"]) == transition_signature("merge", ["B", "A"], ["0"])


def test_empty_inputs_are_safe():
    assert find_merge_candidates({}, {}, {}) == []
    assert find_split_candidates({}, {}, {}) == []
