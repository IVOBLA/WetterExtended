"""B117: Track-Kontinuität über mehrere Frames.

1) Eine durchgehend sichtbare Zelle muss active_frames/total_active_frames und
   history über die Frames AKKUMULIEREN und first_seen STABIL halten.
2) Eine Merge-Situation darf die Identität des dominanten Parents fortführen
   (Merge-Zelle erbt eine der Parent-IDs statt jeden Frame neu zu minten).
"""
import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")
pytest.importorskip("shapely")

from object_tracking import update_tracking_memory, tracking_memory


def _square(cx, cy, half=12):
    return np.array([
        [[cx - half, cy - half]], [[cx + half, cy - half]],
        [[cx + half, cy + half]], [[cx - half, cy + half]],
    ], dtype=np.int32)


def test_active_frames_accumulate_for_continued_cell():
    tracking_memory.clear()
    hsv = np.zeros((400, 400, 3), dtype=np.uint8)
    cnt = _square(200, 200)
    ts = ["2026-01-01_00-00-00", "2026-01-01_00-05-00",
          "2026-01-01_00-10-00", "2026-01-01_00-15-00"]
    last = None
    for t in ts:
        objs, _ = update_tracking_memory(hsv, [cnt], [], t)
        assert objs, "kein Objekt erkannt"
        last = objs[0]
    # Nach 4 Frames: total_active_frames muss > 1 sein und first_seen stabil.
    assert last["total_active_frames"] >= 3, \
        f"total_active_frames akkumuliert nicht: {last['total_active_frames']}"
    assert last["active_frames"] >= 2, \
        f"active_frames akkumuliert nicht: {last['active_frames']}"
    assert last["first_seen"] == ts[0], \
        f"first_seen nicht stabil: {last['first_seen']} != {ts[0]}"
    assert len(last.get("history", [])) >= 2, "history akkumuliert nicht"


def test_merge_inherits_dominant_parent_id():
    tracking_memory.clear()
    hsv = np.zeros((400, 400, 3), dtype=np.uint8)
    # Frame 1: zwei getrennte Zellen, eine GROSS (dominant), eine klein
    big   = _square(150, 200, half=30)
    small = _square(260, 200, half=12)
    objs1, _ = update_tracking_memory(hsv, [big, small], [], "2026-01-01_00-00-00")
    ids1 = {o["id"] for o in objs1}
    assert len(ids1) == 2
    # Frame 2: beide überlappen → eine gemergte Kontur
    merged = _square(205, 200, half=70)
    objs2, _ = update_tracking_memory(hsv, [merged], [], "2026-01-01_00-05-00")
    merged_cells = [o for o in objs2 if o.get("lineage") == "merged"]
    assert merged_cells, "keine merged-Zelle erkannt"
    m = merged_cells[0]
    # B117: Merge-Zelle muss eine der Parent-IDs aus Frame 1 fortführen
    assert m["id"] in ids1, \
        f"Merge-Zelle mintet neue ID {m['id']} statt Parent-ID fortzuführen"
    # Frame 3: Merge bleibt bestehen → ID muss STABIL bleiben (nicht neu minten)
    objs3, _ = update_tracking_memory(hsv, [merged], [], "2026-01-01_00-10-00")
    assert any(o["id"] == m["id"] for o in objs3), \
        "Merge-ID nicht stabil über Folgeframe"
