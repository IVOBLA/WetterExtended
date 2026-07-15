"""B385: Die Fachebene muss die ECHTEN Pre-Frame-Parent-Daten bewerten."""
import pytest

pytest.importorskip("cv2")
import object_tracking
from tracking.primary_policy import select_primary_parent


def _np():
    np = pytest.importorskip("numpy")
    if not all(hasattr(np, attr) for attr in ("array", "zeros", "int32", "uint8")):
        pytest.skip("numpy ist in dieser Testumgebung nur als Stub verfuegbar")
    return np


def _square(cx, cy, half=20):
    np = _np()
    pts = [[cx - half, cy - half], [cx + half, cy - half],
           [cx + half, cy + half], [cx - half, cy + half]]
    return np.array(pts, dtype=np.int32).reshape(-1, 1, 2)


def _rect_contour(x1, y1, x2, y2):
    """B394: RECHTECK — zwei nebeneinanderliegende Parents brauchen eine breite,
    flache Merge-Kontur, damit sie diese tatsaechlich erklaeren (explained >= 0.50).
    Die alte Quadrat-Geometrie erreichte nur 0.119 und erzeugte damit gar keinen
    Merge-Kandidaten."""
    np = _np()
    pts = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
    return np.array(pts, dtype=np.int32).reshape(-1, 1, 2)


@pytest.fixture(autouse=True)
def _mocks(monkeypatch):
    """Testisolation via monkeypatch (Muster: test_config_override_guard.py)."""
    monkeypatch.setattr(object_tracking, "pixel_to_geo",
                        lambda x, y: (46.7 + y * 0.0001, 14.3 + x * 0.0001))
    monkeypatch.setattr(object_tracking, "calculate_core_ratio", lambda hsv, contour: 0.2)
    monkeypatch.setattr(object_tracking, "_is_in_exclusion_zone", lambda lat, lon, zones: False)
    object_tracking.tracking_memory = {}
    object_tracking.last_previous_snapshot = {}
    monkeypatch.setattr(object_tracking, "_last_tracking_timestamp", None, raising=False)
    monkeypatch.setattr(object_tracking, "_pending_transitions", {}, raising=False)
    yield
    object_tracking.tracking_memory = {}
    object_tracking.last_previous_snapshot = {}


def test_snapshot_attribute_exists():
    assert hasattr(object_tracking, "last_previous_snapshot")


def test_snapshot_holds_pre_frame_state_not_new_memory():
    """KERNREGRESSION: Nach dem Lauf muss der Snapshot den ALTEN Stand tragen."""
    np = _np()
    hsv = np.zeros((400, 400, 3), dtype=np.uint8)
    objs1 = object_tracking.update_tracking_memory(
        hsv, [_square(100, 200, half=40), _square(280, 200, half=15)], {}, "2026-01-01_00-00-00")
    ids1 = {o["id"] for o in objs1}
    areas1 = {o["id"]: o["area"] for o in objs1}

    object_tracking.update_tracking_memory(
        hsv, [_square(190, 200, half=100)], {}, "2026-01-01_00-05-00")

    snap = object_tracking.last_previous_snapshot
    assert set(snap.keys()) == ids1, (
        f"Snapshot muss die Frame-1-Tracks tragen. Erwartet {ids1}, erhalten {set(snap.keys())}"
    )
    for tid, area in areas1.items():
        assert snap[tid]["area"] == pytest.approx(area), (
            f"{tid}: Snapshot traegt {snap[tid]['area']} statt der Pre-Frame-Flaeche {area}"
        )


def test_snapshot_keeps_secondary_parent_that_new_memory_drops():
    """Der beendete Secondary-Parent MUSS im Snapshot erhalten bleiben.

    Im ersetzten tracking_memory fehlt er -> cell_lineage sah `{}` -> area=0,
    core_ratio=0 -> continuity_score=0.0 -> er verlor immer.
    """
    np = _np()
    # B394: Geometrie, die die Merge-Kontur tatsaechlich erklaert (explained = 0.94).
    # Vorher: 0.119 -> kein Merge-Kandidat -> der Secondary-Parent wurde regulaer
    # ausgebucht und der B391-Schutz konnte gar nicht greifen.
    hsv = np.zeros((400, 400, 3), dtype=np.uint8)
    objs1 = object_tracking.update_tracking_memory(
        hsv, [_rect_contour(60, 160, 140, 240), _rect_contour(150, 160, 230, 240)],
        {}, "2026-01-01_00-00-00")
    small_id = min(objs1, key=lambda o: o["area"])["id"]

    merged = _rect_contour(60, 160, 230, 240)
    object_tracking.update_tracking_memory(hsv, [merged], {}, "2026-01-01_00-05-00")

    snap = object_tracking.last_previous_snapshot
    assert small_id in snap, "Secondary-Parent fehlt im Pre-Frame-Snapshot"
    assert float(snap[small_id].get("area", 0.0)) > 0.0, (
        "Secondary-Parent hat area=0 — genau der Zustand, der continuity_score auf 0.0 zwingt"
    )


def test_snapshot_survivor_is_not_the_merged_object():
    """Der Survivor darf im Snapshot NICHT schon das verschmolzene Objekt sein."""
    np = _np()
    hsv = np.zeros((400, 400, 3), dtype=np.uint8)
    objs1 = object_tracking.update_tracking_memory(
        hsv, [_square(100, 200, half=40), _square(280, 200, half=15)], {}, "2026-01-01_00-00-00")
    big = max(objs1, key=lambda o: o["area"])
    object_tracking.update_tracking_memory(
        hsv, [_square(190, 200, half=100)], {}, "2026-01-01_00-05-00")

    snap_area = float(object_tracking.last_previous_snapshot[big["id"]]["area"])
    assert snap_area == pytest.approx(big["area"]), (
        f"Survivor traegt im Snapshot {snap_area} statt seiner Parent-Flaeche {big['area']} — "
        "der Nachher-Zustand waere bewertet worden"
    )
    assert float(object_tracking.tracking_memory[big["id"]]["area"]) > snap_area, (
        "Kontrolle: tracking_memory muss die groessere, verschmolzene Flaeche tragen"
    )


def test_empty_parent_dict_scores_zero():
    """Belegt, warum leere Secondary-Dicts fatal sind."""
    real = {"id": "B", "cell_id": "CB", "area": 5000.0, "core_ratio": 0.8, "total_active_frames": 20}
    empty = {"id": "A", "cell_id": "CA"}
    winner = select_primary_parent([empty, real], policy="continuity_score", id_key="cell_id")
    assert winner["cell_id"] == "CB"


def test_main_passes_snapshot_not_tracking_memory():
    """Der Produktionsaufruf muss den Snapshot durchreichen."""
    src = open("main.py", encoding="utf-8").read()
    assert "last_previous_snapshot" in src, "main.py reicht den Pre-Frame-Snapshot nicht durch"
    assert "previous_objects=_prev_for_lineage" in src


def test_snapshot_is_decoupled_from_tracking_memory():
    """Spaetere Aenderungen an tracking_memory duerfen den Snapshot nicht veraendern."""
    np = _np()
    hsv = np.zeros((400, 400, 3), dtype=np.uint8)
    object_tracking.update_tracking_memory(hsv, [_square(100, 200, half=40)], {}, "2026-01-01_00-00-00")
    object_tracking.update_tracking_memory(hsv, [_square(105, 200, half=40)], {}, "2026-01-01_00-05-00")
    snap_before = dict(object_tracking.last_previous_snapshot)
    object_tracking.tracking_memory["INJECTED"] = {"area": 1.0}
    assert "INJECTED" not in object_tracking.last_previous_snapshot
    assert set(snap_before) == set(object_tracking.last_previous_snapshot)
