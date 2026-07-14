"""B377: Radar- und Fachebene müssen dieselbe Primary-Policy verwenden."""
import pytest

import cell_lineage as cl
from tracking.primary_policy import (
    VALID_POLICIES,
    continuity_score,
    select_primary_parent,
)


def _parent(pid, area, core, age=10, cell_id=None):
    return {"id": pid, "cell_id": cell_id or f"C{pid}", "area": area,
            "core_ratio": core, "total_active_frames": age}


def test_largest_area_no_longer_wins_by_default():
    """Kernbefund: eine zerfallende Systemhuelle darf nicht allein wegen Flaeche gewinnen."""
    huge_weak = _parent("A", area=50000.0, core=0.01, age=2)
    small_strong = _parent("B", area=3000.0, core=0.75, age=20)
    winner = select_primary_parent([huge_weak, small_strong], policy="continuity_score")
    assert winner["id"] == "B", "Aktiver, etablierter Kern muss die Identitaet behalten"


def test_largest_area_policy_still_available():
    huge_weak = _parent("A", area=50000.0, core=0.01)
    small_strong = _parent("B", area=3000.0, core=0.75)
    winner = select_primary_parent([huge_weak, small_strong], policy="largest_area")
    assert winner["id"] == "A"


def test_highest_core_ratio_policy_still_available():
    a = _parent("A", area=50000.0, core=0.10)
    b = _parent("B", area=100.0, core=0.90)
    assert select_primary_parent([a, b], policy="highest_core_ratio")["id"] == "B"


def test_survivor_first_policy_honours_survivor():
    a = _parent("A", area=100.0, core=0.9, cell_id="CA")
    b = _parent("B", area=50000.0, core=0.1, cell_id="CB")
    winner = select_primary_parent([a, b], policy="survivor_first", survivor_id="CB", id_key="cell_id")
    assert winner["cell_id"] == "CB"


def test_survivor_first_falls_back_when_survivor_absent():
    a = _parent("A", area=100.0, core=0.9, cell_id="CA")
    winner = select_primary_parent([a], policy="survivor_first", survivor_id="CX", id_key="cell_id")
    assert winner is not None


def test_age_matters_in_continuity_score():
    """Bei gleicher Flaeche/Kernstaerke gewinnt der laenger etablierte Track."""
    young = _parent("A", area=1000.0, core=0.5, age=1)
    old = _parent("B", area=1000.0, core=0.5, age=30)
    assert select_primary_parent([young, old], policy="continuity_score")["id"] == "B"


def test_score_is_bounded():
    p = _parent("A", area=1000.0, core=1.0, age=999)
    s = continuity_score(p, max_area=1000.0, max_core_area=1000.0)
    assert 0.0 <= s <= 1.0


def test_selection_is_deterministic_on_tie():
    a = _parent("A", area=1000.0, core=0.5, age=10)
    b = _parent("B", area=1000.0, core=0.5, age=10)
    first = select_primary_parent([a, b], policy="continuity_score")["id"]
    for _ in range(5):
        assert select_primary_parent([a, b], policy="continuity_score")["id"] == first


def test_invalid_policy_falls_back_to_continuity():
    a = _parent("A", area=50000.0, core=0.01, age=2)
    b = _parent("B", area=3000.0, core=0.75, age=20)
    assert select_primary_parent([a, b], policy="nonexistent_policy")["id"] == "B"


def test_empty_parents_returns_none():
    assert select_primary_parent([]) is None
    assert select_primary_parent(None) is None


def test_cell_lineage_delegates_to_shared_policy():
    """Die Fachebene muss dieselbe Entscheidung treffen wie die Radarebene."""
    a = _parent("A", area=50000.0, core=0.01, age=2, cell_id="CA")
    b = _parent("B", area=3000.0, core=0.75, age=20, cell_id="CB")
    shared = select_primary_parent([a, b], policy="continuity_score", id_key="cell_id")
    fach = cl.select_primary_merge_parent([a, b], policy="continuity_score")
    assert fach["cell_id"] == shared["cell_id"] == "CB"


def test_all_valid_policies_are_selectable():
    a = _parent("A", area=1000.0, core=0.5)
    b = _parent("B", area=2000.0, core=0.2)
    for policy in VALID_POLICIES:
        assert select_primary_parent([a, b], policy=policy) is not None


def test_object_tracking_passes_global_survivor_to_survivor_first_policy():
    """Radar-Ebene muss den globalen Survivor an survivor_first weiterreichen."""
    source = __import__("pathlib").Path("object_tracking.py").read_text(encoding="utf-8")
    call_start = source.index("_primary_parent = _select_primary_parent(")
    call_end = source.index(")", call_start)
    call = source[call_start:call_end]
    assert "survivor_id=_global_match_id" in call
