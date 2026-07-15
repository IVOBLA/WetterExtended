"""B396: Ein bestätigter Übergang wird genau einmal gemeldet, danach `closed`."""

from tracking.transition_resolver import (
    _pending_entry,
    confirm_candidates,
    find_merge_candidates,
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


def _tracks_and_det():
    tracks = {"A": _box(0, 0, 70, 10), "B": _box(75, 0, 100, 10)}
    det = {0: _box(0, 0, 100, 10)}
    return tracks, det, {0: "A"}


def test_confirmed_is_emitted_exactly_once():
    """KERNREGRESSION: 10 Folgeframes -> genau EINE Bestaetigung."""
    tracks, det, matched = _tracks_and_det()
    pending, emitted = {}, 0
    for _ in range(10):
        confirmed, _, _, pending = confirm_candidates(
            find_merge_candidates(tracks, det, matched), pending)
        emitted += len(confirmed)
    assert emitted == 1, f"Uebergang wurde {emitted}x als bestaetigt gemeldet, erwartet 1"


def test_phase_becomes_closed_after_confirmation():
    tracks, det, matched = _tracks_and_det()
    _, _, _, pending = confirm_candidates(find_merge_candidates(tracks, det, matched), {})
    confirmed, _, _, pending = confirm_candidates(find_merge_candidates(tracks, det, matched), pending)
    assert confirmed and confirmed[0].phase == "confirmed"

    confirmed3, still3, _, pending = confirm_candidates(
        find_merge_candidates(tracks, det, matched), pending)
    assert confirmed3 == [], "Frame 3 darf keine erneute Bestaetigung liefern"
    assert still3 == [], "Ein abgeschlossener Uebergang ist kein Kandidat mehr"
    sig = list(pending)[0]
    assert pending[sig]["phase"] == "closed"


def test_candidate_phase_unchanged_before_confirmation():
    """B391 haengt an phase == 'candidate' — das darf sich nicht aendern."""
    tracks, det, matched = _tracks_and_det()
    confirmed, still, _, pending = confirm_candidates(
        find_merge_candidates(tracks, det, matched), {})
    assert confirmed == [] and len(still) == 1
    assert still[0].phase == "candidate"
    assert pending[still[0].signature]["phase"] == "candidate"


def test_reverted_still_works():
    tracks, det, matched = _tracks_and_det()
    _, _, _, pending = confirm_candidates(find_merge_candidates(tracks, det, matched), {})
    confirmed, still, reverted, pending2 = confirm_candidates([], pending)
    assert len(reverted) == 1 and confirmed == [] and pending2 == {}


def test_reverted_works_after_closed():
    """Auch ein abgeschlossener Uebergang verschwindet sauber aus dem State."""
    tracks, det, matched = _tracks_and_det()
    pending = {}
    for _ in range(3):
        _, _, _, pending = confirm_candidates(find_merge_candidates(tracks, det, matched), pending)
    _, _, reverted, pending2 = confirm_candidates([], pending)
    assert len(reverted) == 1 and pending2 == {}


def test_legacy_int_pending_is_readable():
    """Abwaertskompatibel: vor B396 war der Wert eine blanke Zahl."""
    assert _pending_entry(2) == {"frames_seen": 2, "phase": "candidate"}
    assert _pending_entry(None) == {"frames_seen": 0, "phase": "candidate"}
    assert _pending_entry({"frames_seen": 3, "phase": "closed"})["phase"] == "closed"


def test_legacy_state_confirms_once_not_twice():
    """Ein Alt-State (int) darf nach dem Deployment nicht doppelt bestaetigen."""
    tracks, det, matched = _tracks_and_det()
    cands = find_merge_candidates(tracks, det, matched)
    legacy = {cands[0].signature: 5}          # Alt-Format, weit ueber der Schwelle
    confirmed, _, _, pending = confirm_candidates(cands, legacy)
    assert len(confirmed) == 1, "Alt-State muss genau einmal bestaetigen"
    confirmed2, _, _, _ = confirm_candidates(find_merge_candidates(tracks, det, matched), pending)
    assert confirmed2 == [], "Danach ist der Uebergang closed"


def test_new_constellation_confirms_independently():
    """Ein anderes Ereignis darf durch ein closed nicht blockiert werden."""
    tracks, det, matched = _tracks_and_det()
    pending = {}
    for _ in range(3):
        _, _, _, pending = confirm_candidates(find_merge_candidates(tracks, det, matched), pending)
    other = {"C": _box(0, 20, 70, 30), "D": _box(75, 20, 100, 30)}
    det2 = {1: _box(0, 20, 100, 30)}
    pending2 = dict(pending)
    emitted = 0
    for _ in range(2):
        confirmed, _, _, pending2 = confirm_candidates(
            find_merge_candidates(other, det2, {1: "C"}), pending2)
        emitted += len(confirmed)
    assert emitted == 1
