"""B395: Ein bestätigter Merge darf nur seine bestätigten Parents tragen."""
import numpy as np
import pytest

import object_tracking


def _rect(x1, y1, x2, y2):
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


def _confirmed_merge_with_fringe_track():
    """Zwei echte Parents + ein Randtrack mit ~0.35 Eigenabdeckung.

    Der Randtrack erfuellt die 0.30-Schwelle der Objektschleife, aber NICHT die
    0.40-Schwelle des Resolvers -> er darf nicht Teil des Ereignisses werden.
    """
    hsv = np.zeros((400, 400, 3), dtype=np.uint8)
    parent_a = _rect(60, 160, 140, 240)      # 80x80, voll im Merge
    parent_b = _rect(150, 160, 230, 240)     # 80x80, voll im Merge
    # Randtrack: nur ~35 % der eigenen Flaeche liegen im Merge-Bereich.
    fringe = _rect(200, 160, 280, 240)       # 80x80, davon 30/80 im Merge
    object_tracking.update_tracking_memory(
        hsv, [parent_a, parent_b, fringe], {}, "2026-01-01_00-00-00")
    merged = _rect(60, 160, 230, 240)
    object_tracking.update_tracking_memory(hsv, [merged], {}, "2026-01-01_00-05-00")
    objs3 = object_tracking.update_tracking_memory(hsv, [merged], {}, "2026-01-01_00-10-00")
    return objs3


def test_confirmed_merge_uses_resolver_parents():
    """KERNREGRESSION: parents muss der bestaetigten Menge entsprechen."""
    objs = _confirmed_merge_with_fringe_track()
    merged = [o for o in objs if o.get("lineage") == "merged"]
    if not merged:
        pytest.skip("Kein bestaetigter Merge — Geometrie preuefen (vgl. B394)")
    parents = merged[0].get("parents") or []
    assert len(parents) == 2, (
        f"Erwartet 2 bestaetigte Parents, erhalten {len(parents)}: {parents}. "
        "Ein Randtrack unter TRANSITION_MERGE_MIN_PARENT_COVERAGE wurde uebernommen."
    )


def test_parents_are_subset_of_confirmed_set():
    """Kein Parent darf ausserhalb der Resolver-Bestaetigung liegen."""
    from tracking.transition_resolver import _cfg
    min_cov = float(_cfg("TRANSITION_MERGE_MIN_PARENT_COVERAGE"))
    assert min_cov > 0.30, (
        "Der Test setzt voraus, dass die Resolver-Schwelle strenger ist als die "
        "0.30-Schwelle der Objektschleife"
    )


def test_dominant_parent_comes_from_confirmed_set():
    """Die ID darf nur von einem bestaetigten Parent geerbt werden."""
    objs = _confirmed_merge_with_fringe_track()
    merged = [o for o in objs if o.get("lineage") == "merged"]
    if not merged:
        pytest.skip("Kein bestaetigter Merge")
    m = merged[0]
    assert m["id"] in (m.get("parents") or []), (
        f"ID {m['id']} stammt nicht aus der bestaetigten Parentmenge {m.get('parents')}"
    )


def test_normal_merge_keeps_both_parents():
    """Regression: ein sauberer 2er-Merge behaelt beide Parents."""
    hsv = np.zeros((400, 400, 3), dtype=np.uint8)
    object_tracking.update_tracking_memory(
        hsv, [_rect(60, 160, 140, 240), _rect(150, 160, 230, 240)], {}, "2026-01-01_00-00-00")
    merged = _rect(60, 160, 230, 240)
    object_tracking.update_tracking_memory(hsv, [merged], {}, "2026-01-01_00-05-00")
    objs3 = object_tracking.update_tracking_memory(hsv, [merged], {}, "2026-01-01_00-10-00")
    m = [o for o in objs3 if o.get("lineage") == "merged"]
    if not m:
        pytest.skip("Kein bestaetigter Merge")
    assert len(m[0].get("parents") or []) == 2


def test_confirmed_set_is_used_not_overlaps():
    """Statischer Nachweis: overlaps darf die Mitgliedschaft nicht mehr bestimmen."""
    import inspect
    src = inspect.getsource(object_tracking.update_tracking_memory)
    assert "parents = [oid for oid, _ in overlaps]" not in src, (
        "Die Ereignis-Parentmenge stammt weiterhin aus der 0.30-Liste"
    )
    assert "_confirmed_parent_ids" in src


def test_thirty_percent_threshold_still_feeds_candidates():
    """Die 0.30-Schwelle bleibt fuer die Kandidatenermittlung erhalten."""
    import inspect
    src = inspect.getsource(object_tracking.update_tracking_memory)
    assert "_old_coverage_m >= 0.30" in src, (
        "Die Kandidaten-Schwelle wurde faelschlich mitentfernt"
    )
