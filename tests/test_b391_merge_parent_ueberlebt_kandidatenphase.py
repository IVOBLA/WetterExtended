"""B391: Parents eines ausstehenden Übergangs müssen bis zur Entscheidung leben."""
import numpy as np
import pytest

import object_tracking


def _square(cx, cy, half=20):
    pts = [[cx - half, cy - half], [cx + half, cy - half],
           [cx + half, cy + half], [cx - half, cy + half]]
    return np.array(pts, dtype=np.int32).reshape(-1, 1, 2)


def _rect_contour(x1, y1, x2, y2):
    """B394: RECHTECK statt Quadrat.

    Zwei nebeneinanderliegende Parents brauchen eine breite, FLACHE Merge-Kontur.
    Ein Quadrat, das beide horizontal umschliesst, ist zwangsläufig auch vertikal
    riesig -- und damit groesstenteils leer. Genau das machte die alte Geometrie
    zum Scheinmerge (explained=0.195), den find_merge_candidates() korrekt verwarf:
    kein Kandidat -> _pending_parent_ids leer -> der B391-Fix konnte nicht greifen.
    """
    pts = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
    return np.array(pts, dtype=np.int32).reshape(-1, 1, 2)


@pytest.fixture(autouse=True)
def _mocks(monkeypatch):
    """Testisolation via monkeypatch (Muster: test_config_override_guard.py)."""
    monkeypatch.setattr(object_tracking, "pixel_to_geo",
                        lambda x, y: (46.7 - y * 0.001, 14.3 + x * 0.00145))
    monkeypatch.setattr(object_tracking, "calculate_core_ratio", lambda hsv, contour: 0.2)
    monkeypatch.setattr(object_tracking, "_is_in_exclusion_zone", lambda lat, lon, zones: False)
    object_tracking.tracking_memory = {}
    monkeypatch.setattr(object_tracking, "_last_tracking_timestamp", None, raising=False)
    monkeypatch.setattr(object_tracking, "_pending_transitions", {}, raising=False)
    yield
    object_tracking.tracking_memory = {}


def _run_merge_sequence():
    """B394: Geometrie so, dass die Parents die Merge-Kontur tatsaechlich ERKLAEREN.

    Parent 1: 60..140 x 160..240  (80x80 = 6.400 px)
    Parent 2: 150..230 x 160..240 (80x80 = 6.400 px)
    Merge   : 60..230 x 160..240  (170x80 = 13.600 px)

    coverage je Parent = 6.400/6.400 = 1.00   (>= TRANSITION_MERGE_MIN_PARENT_COVERAGE)
    explained          = 12.800/13.600 = 0.94 (>= TRANSITION_MERGE_MIN_EXPLAINED)

    Das entspricht realer Konvektion: im Debug-Export vom 14.07.2026 liegt explained
    ueber 160 Merge-Beobachtungen im Median bei 1.00 (p10 = 0.48). Die alte
    Testgeometrie erreichte 0.195 -- weit unter dem 10 %-Perzentil.
    """
    hsv = np.zeros((400, 400, 3), dtype=np.uint8)
    parent_a = _rect_contour(60, 160, 140, 240)
    parent_b = _rect_contour(150, 160, 230, 240)
    o1 = object_tracking.update_tracking_memory(
        hsv, [parent_a, parent_b], {}, "2026-01-01_00-00-00")
    merged = _rect_contour(60, 160, 230, 240)
    o2 = object_tracking.update_tracking_memory(hsv, [merged], {}, "2026-01-01_00-05-00")
    # B398: Objekt-Dicts snapshotten; vollständiges deepcopy des KalmanFilters ist unnötig.
    mem_after_f2 = {
        obj_id: obj.copy()
        for obj_id, obj in object_tracking.tracking_memory.items()
    }
    o3 = object_tracking.update_tracking_memory(hsv, [merged], {}, "2026-01-01_00-10-00")
    return o1, o2, mem_after_f2, o3


def test_secondary_parent_survives_candidate_frame():
    """KERNREGRESSION: Nach dem Kandidatenframe muessen BEIDE Parents leben."""
    o1, _, mem_after_f2, _ = _run_merge_sequence()
    ids1 = {o["id"] for o in o1}
    assert len(ids1) == 2
    assert ids1.issubset(set(mem_after_f2)), (
        f"Parent verschwand im Kandidatenframe: {ids1 - set(mem_after_f2)}. "
        "Damit kann der Merge in Frame 3 nie bestaetigt werden (len(parents) < 2)."
    )


def test_merge_is_confirmed_in_frame_three():
    """Das eigentliche Ziel: der Merge wird bestaetigt."""
    _, o2, _, o3 = _run_merge_sequence()
    assert o2[0]["lineage"] == "continued", "Frame 2 ist der Kandidatenframe"
    lineages3 = [o["lineage"] for o in o3]
    assert "merged" in lineages3, (
        f"Frame 3 meldet keinen bestaetigten Merge: {lineages3}"
    )


def test_pending_parent_is_not_emitted_as_cell():
    """Der wartende Parent darf nicht als eigene Zelle erscheinen."""
    _, o2, _, _ = _run_merge_sequence()
    assert len(o2) == 1, f"Pending-Parent wurde als Zelle ausgegeben: {[o['id'] for o in o2]}"


def test_pending_parent_has_merge_pending_state():
    o1, _, mem_after_f2, _ = _run_merge_sequence()
    pending = [v for v in mem_after_f2.values() if v.get("tracking_state") == "merge_pending"]
    assert pending, "Kein Track im Zustand merge_pending"
    assert pending[0]["is_active_cell"] is False
    assert pending[0]["silent_tracking"] is True


def test_pending_parent_is_excluded_from_neighbor_features():
    """B397/B399: technisch erhaltener Parent ist keine ausgegebene ML-Zelle."""
    _, emitted_frame2, mem_after_f2, _ = _run_merge_sequence()

    pending = [
        (track_id, value)
        for track_id, value in mem_after_f2.items()
        if value.get("tracking_state") == "merge_pending"
    ]
    assert len(pending) == 1

    pending_parent_id, pending_parent = pending[0]

    assert pending_parent["silent_tracking"] is True
    assert object_tracking._is_neighbor_feature_eligible(pending_parent) is False

    emitted_ids = {
        str(obj["id"])
        for obj in emitted_frame2
    }
    assert str(pending_parent_id) not in emitted_ids


def test_frame_two_snapshot_is_not_mutated_by_frame_three():
    _, _, mem_after_f2, _ = _run_merge_sequence()

    pending = [
        obj for obj in mem_after_f2.values()
        if obj.get("tracking_state") == "merge_pending"
    ]
    assert len(pending) == 1
    assert pending[0]["transition_phase"] == "candidate"
    assert pending[0]["silent_tracking"] is True


def test_confirmed_merge_ends_the_pending_state():
    """Nach der Bestaetigung darf kein merge_pending mehr uebrig bleiben."""
    _run_merge_sequence()
    hsv = np.zeros((400, 400, 3), dtype=np.uint8)
    object_tracking.update_tracking_memory(
        hsv, [_rect_contour(60, 160, 230, 240)], {}, "2026-01-01_00-15-00")
    still_pending = [k for k, v in object_tracking.tracking_memory.items()
                     if v.get("tracking_state") == "merge_pending"]
    assert not still_pending, f"merge_pending haengt nach der Bestaetigung: {still_pending}"


def test_dissolved_cell_without_transition_still_expires():
    """Regression: eine echte aufgeloeste Zelle darf NICHT kuenstlich am Leben bleiben."""
    hsv = np.zeros((400, 400, 3), dtype=np.uint8)
    o1 = object_tracking.update_tracking_memory(
        hsv, [_rect_contour(60, 160, 140, 240)], {}, "2026-01-01_00-00-00")
    tid = o1[0]["id"]
    object_tracking.update_tracking_memory(hsv, [], {}, "2026-01-01_00-05-00")
    obj = object_tracking.tracking_memory.get(tid)
    assert obj is None or obj.get("tracking_state") != "merge_pending", (
        "Zelle ohne Uebergang wurde faelschlich als merge_pending gehalten"
    )


def test_confirm_frames_unchanged():
    """B391 darf die Bestaetigungsschwelle nicht aufweichen."""
    from tracking.transition_resolver import _cfg
    assert int(_cfg("TRANSITION_CONFIRM_FRAMES")) == 2
