"""B382: Die Merge-Kandidatenphase darf die ID-Kontinuität nicht brechen."""
import numpy as np
import pytest

import object_tracking


def _square(cx, cy, half=20):
    pts = [[cx - half, cy - half], [cx + half, cy - half],
           [cx + half, cy + half], [cx - half, cy + half]]
    return np.array(pts, dtype=np.int32).reshape(-1, 1, 2)


@pytest.fixture(autouse=True)
def _mocks(monkeypatch):
    """Testisolation via monkeypatch (Muster: test_config_override_guard.py)."""
    monkeypatch.setattr(object_tracking, "pixel_to_geo",
                        lambda x, y: (46.7 + y * 0.0001, 14.3 + x * 0.0001))
    monkeypatch.setattr(object_tracking, "calculate_core_ratio", lambda hsv, contour: 0.2)
    monkeypatch.setattr(object_tracking, "_is_in_exclusion_zone", lambda lat, lon, zones: False)
    object_tracking.tracking_memory = {}
    monkeypatch.setattr(object_tracking, "_last_tracking_timestamp", None, raising=False)
    monkeypatch.setattr(object_tracking, "_pending_transitions", {}, raising=False)
    yield
    object_tracking.tracking_memory = {}


def test_merge_candidate_frame_keeps_dominant_parent_id():
    """KERNREGRESSION: Im ersten Merge-Frame darf KEINE neue ID entstehen."""
    hsv = np.zeros((400, 400, 3), dtype=np.uint8)
    objs1 = object_tracking.update_tracking_memory(
        hsv, [_square(100, 200, half=40), _square(280, 200, half=15)], {}, "2026-01-01_00-00-00")
    assert len(objs1) >= 2
    big_id = max(objs1, key=lambda o: o.get("area", 0))["id"]

    objs2 = object_tracking.update_tracking_memory(
        hsv, [_square(190, 200, half=100)], {}, "2026-01-01_00-05-00")
    assert len(objs2) == 1
    ids2 = [o["id"] for o in objs2]
    assert big_id in ids2, (
        f"ID-Kontinuitaet gebrochen: {big_id} verschwunden, stattdessen {ids2}. "
        "Die Kandidatenphase darf die Identitaet nicht neu vergeben."
    )
    assert objs2[0]["lineage"] != "new", "Merge-Kandidat darf nicht als Neuzelle gelten"


def test_candidate_frame_is_continued_not_merged():
    """Das EREIGNIS bleibt verzoegert — nur die Identitaet ist sofort."""
    hsv = np.zeros((400, 400, 3), dtype=np.uint8)
    object_tracking.update_tracking_memory(
        hsv, [_square(100, 200, half=40), _square(280, 200, half=15)], {}, "2026-01-01_00-00-00")
    objs2 = object_tracking.update_tracking_memory(
        hsv, [_square(190, 200, half=100)], {}, "2026-01-01_00-05-00")
    assert objs2[0]["lineage"] == "continued", (
        f"Kandidatenframe muss `continued` sein, war {objs2[0]['lineage']}"
    )


def test_candidate_frame_has_single_parent():
    """In der Kandidatenphase darf keine Merge-Parentmenge entstehen."""
    hsv = np.zeros((400, 400, 3), dtype=np.uint8)
    object_tracking.update_tracking_memory(
        hsv, [_square(100, 200, half=40), _square(280, 200, half=15)], {}, "2026-01-01_00-00-00")
    objs2 = object_tracking.update_tracking_memory(
        hsv, [_square(190, 200, half=100)], {}, "2026-01-01_00-05-00")
    assert len(objs2[0].get("parents") or []) <= 1


def test_normal_one_to_one_still_continued():
    """Regression: der einfache 1:1-Fall bleibt unveraendert."""
    hsv = np.zeros((400, 400, 3), dtype=np.uint8)
    o1 = object_tracking.update_tracking_memory(hsv, [_square(100, 200, half=40)], {}, "2026-01-01_00-00-00")
    tid = o1[0]["id"]
    o2 = object_tracking.update_tracking_memory(hsv, [_square(105, 200, half=40)], {}, "2026-01-01_00-05-00")
    assert o2[0]["id"] == tid
    assert o2[0]["lineage"] == "continued"


def test_kalman_state_survives_candidate_phase():
    """Der Kalman-Zustand darf beim Merge-Kandidaten nicht verloren gehen."""
    hsv = np.zeros((400, 400, 3), dtype=np.uint8)
    object_tracking.update_tracking_memory(
        hsv, [_square(100, 200, half=40), _square(280, 200, half=15)], {}, "2026-01-01_00-00-00")
    object_tracking.update_tracking_memory(
        hsv, [_square(190, 200, half=100)], {}, "2026-01-01_00-05-00")
    surviving = [v for v in object_tracking.tracking_memory.values() if v.get("kf") is not None]
    assert surviving, "Kein Track mit Kalman-Zustand ueberlebt den Merge-Kandidatenframe"


def test_branch_condition_is_not_exact_one():
    """Die alte Bedingung `len(overlaps) == 1` darf nicht zurueckkehren."""
    import inspect
    src = inspect.getsource(object_tracking.update_tracking_memory)
    assert "elif len(overlaps) == 1:" not in src, (
        "Alte Bedingung wieder vorhanden — Kandidatenphase faellt erneut durch alle Zweige"
    )
    assert "_candidate_phase_dominant" in src
