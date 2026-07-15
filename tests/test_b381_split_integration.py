"""B381: Der Split muss NACH dem globalen 1:1-Matching erkannt werden."""
from pathlib import Path

from tracking.transition_resolver import confirm_candidates, find_split_candidates


class _Rect:
    def __init__(self, x1, y1, x2, y2):
        self.x1 = float(x1)
        self.y1 = float(y1)
        self.x2 = float(x2)
        self.y2 = float(y2)

    @property
    def area(self):
        return max(0.0, self.x2 - self.x1) * max(0.0, self.y2 - self.y1)

    def intersection(self, other):
        return _Rect(
            max(self.x1, other.x1),
            max(self.y1, other.y1),
            min(self.x2, other.x2),
            min(self.y2, other.y2),
        )


def _box(x1, y1, x2, y2):
    return _Rect(x1, y1, x2, y2)


def test_split_detected_when_parent_is_matched_to_a_child():
    """KERNFALL: Hungarian ordnet A dem Kind X zu — der Split muss trotzdem entstehen.

    Genau dieser Fall war unerreichbar, weil der Resolver nur unmatched Tracks sah.
    """
    tracks = {"A": _box(0, 0, 10, 10)}
    children = {0: _box(0, 0, 4, 10), 1: _box(6, 0, 10, 10)}
    matched = {0: "A"}                      # A ist MATCHED auf Kind 0
    cands = find_split_candidates(tracks, children, matched)
    assert len(cands) == 1, "Split mit gematchtem Parent wurde nicht erkannt"
    assert cands[0].kind == "split"
    assert cands[0].parents == ["A"]


def test_primary_child_is_the_globally_matched_one():
    tracks = {"A": _box(0, 0, 10, 10)}
    children = {0: _box(0, 0, 4, 10), 1: _box(6, 0, 10, 10)}
    cands = find_split_candidates(tracks, children, matched={1: "A"})
    assert cands[0].primary_child == 1, "Das gematchte Kind muss primaer sein"


def test_primary_child_falls_back_to_largest_when_unmatched():
    """Ohne globales Match gewinnt das flaechengroesste Kind."""
    tracks = {"A": _box(0, 0, 10, 10)}
    children = {0: _box(0, 0, 2, 10), 1: _box(4, 0, 10, 10)}   # Kind 1 groesser
    cands = find_split_candidates(tracks, children, matched={})
    assert cands[0].primary_child == 1


def test_single_child_is_no_split():
    tracks = {"A": _box(0, 0, 10, 10)}
    cands = find_split_candidates(tracks, {0: _box(0, 0, 9, 10)}, matched={0: "A"})
    assert cands == []


def test_children_must_explain_the_parent():
    """Zwei winzige Fragmente erklaeren einen grossen Parent nicht."""
    tracks = {"A": _box(0, 0, 100, 100)}
    children = {0: _box(0, 0, 2, 2), 1: _box(5, 5, 7, 7)}
    assert find_split_candidates(tracks, children, matched={}) == []


def test_split_confirmed_only_after_two_frames():
    tracks = {"A": _box(0, 0, 10, 10)}
    children = {0: _box(0, 0, 4, 10), 1: _box(6, 0, 10, 10)}
    matched = {0: "A"}
    confirmed, still, _, pending = confirm_candidates(find_split_candidates(tracks, children, matched), {})
    assert confirmed == [] and len(still) == 1
    confirmed, _, _, pending = confirm_candidates(find_split_candidates(tracks, children, matched), pending)
    assert len(confirmed) == 1 and confirmed[0].kind == "split"


def test_split_candidate_carries_primary_child_through_confirmation():
    tracks = {"A": _box(0, 0, 10, 10)}
    children = {0: _box(0, 0, 4, 10), 1: _box(6, 0, 10, 10)}
    matched = {1: "A"}
    _, _, _, pending = confirm_candidates(find_split_candidates(tracks, children, matched), {})
    confirmed, _, _, _ = confirm_candidates(find_split_candidates(tracks, children, matched), pending)
    assert confirmed[0].primary_child == 1


def test_dead_assigned_old_to_new_path_removed():
    """Der alte Split-Nachlauf darf nicht mehr existieren."""
    src = Path("object_tracking.py").read_text()
    assert 'split_obj["lineage"] = "split"' not in src, "Toter assigned_old_to_new-Pfad noch vorhanden"
    assert "_confirmed_transitions" in src, "Resolver-basierter Split-Nachlauf fehlt"


def test_object_loop_has_split_branch():
    src = Path("object_tracking.py").read_text()
    assert '_transition.kind == "split"' in src, "Objektschleife hat keinen Split-Zweig"
    assert 'lineage = "split"' in src
