"""B117: Track-Kontinuität über mehrere Frames.

1) Eine durchgehend sichtbare Zelle muss active_frames/total_active_frames und
   history über die Frames AKKUMULIEREN und first_seen STABIL halten.
2) Eine Merge-Situation darf die Identität des dominanten Parents fortführen
   (Merge-Zelle erbt eine der Parent-IDs statt jeden Frame neu zu minten).

Technische Hinweise:
- update_tracking_memory() gibt eine einfache list zurück (keine 2-Tuple).
- Die Funktion ruft intern pixel_to_geo, calculate_core_ratio, get_dem_features,
  get_valley_features und compute_stratiform_environment auf — alle müssen gemockt
  werden, damit der Bbox-Filter Testzellen nicht herausfiltert.
- Muster übernommen von tests/test_object_tracking_regression.py.
"""
import pytest

np = pytest.importorskip("numpy")
if not hasattr(np, "zeros"):
    pytest.skip("benötigt ein echtes numpy-Paket", allow_module_level=True)
pytest.importorskip("cv2")
pytest.importorskip("shapely")
pytest.importorskip("filterpy")

import object_tracking


# ---------------------------------------------------------------------------
# Fixtures / Helfer
# ---------------------------------------------------------------------------


def _square(cx, cy, half=12):
    """Erstellt ein quadratisches OpenCV-Contour-Array (4 Punkte, dtype int32)."""
    return np.array(
        [
            [[cx - half, cy - half]],
            [[cx + half, cy - half]],
            [[cx + half, cy + half]],
            [[cx - half, cy + half]],
        ],
        dtype=np.int32,
    )


def _rect_contour(x1, y1, x2, y2):
    pts = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
    return np.array(pts, dtype=np.int32).reshape(-1, 1, 2)


def _apply_mocks(monkeypatch):
    """Setzt alle Mocks die update_tracking_memory für einen Testlauf benötigt.

    pixel_to_geo wird positions-abhängig gemockt, damit zwei nebeneinander
    liegende Testzellen verschiedene (aber beide gültige) Kärnten-Koordinaten
    erhalten und der Bbox-Filter sie nicht fälschlich ausschließt.
    """
    # Pixel → Geo: leicht positions-abhängig, damit mehrere Zellen unterschiedliche
    # Koordinaten bekommen — alle innerhalb BBOX_KAERNTEN_EXTENDED.
    monkeypatch.setattr(
        object_tracking,
        "pixel_to_geo",
        lambda x, y: (46.7 + y * 0.0001, 14.3 + x * 0.0001),
    )
    monkeypatch.setattr(
        object_tracking,
        "calculate_core_ratio",
        lambda hsv, contour: 0.2,
    )
    monkeypatch.setattr(
        object_tracking,
        "get_dem_features",
        lambda *a, **kw: {
            "dem_elevation_m": 0.0,
            "dem_slope_toward_cell": 0.0,
            "dem_barrier_ahead": 0.0,
        },
    )
    monkeypatch.setattr(
        object_tracking,
        "get_valley_features",
        lambda *a, **kw: {
            "valley_alignment": 0.0,
            "valley_distance_km": 999.0,
            "valley_confinement": 0.0,
        },
    )
    monkeypatch.setattr(
        object_tracking,
        "compute_stratiform_environment",
        lambda *a, **kw: {
            "strat_area_px": 0.0,
            "strat_intensity_mean": 0.0,
            "strat_dbz_gradient": 0.0,
        },
    )


# ---------------------------------------------------------------------------
# Test 1: active_frames und history akkumulieren
# ---------------------------------------------------------------------------


def test_active_frames_accumulate_for_continued_cell(monkeypatch):
    """B117-A: akkumulierte Track-Felder werden in tracking_memory persistiert."""
    _apply_mocks(monkeypatch)
    object_tracking.tracking_memory = {}  # globalen Zustand zurücksetzen

    hsv = np.zeros((400, 400, 3), dtype=np.uint8)
    cnt = _square(200, 200, half=30)  # groß genug für Bbox-Filter
    timestamps = [
        "2026-01-01_00-00-00",
        "2026-01-01_00-05-00",
        "2026-01-01_00-10-00",
        "2026-01-01_00-15-00",
    ]

    last_objs = None
    for ts in timestamps:
        last_objs = object_tracking.update_tracking_memory(hsv, [cnt], {}, ts)

    assert isinstance(last_objs, list), "Rückgabe muss list sein"
    assert last_objs, "Nach 4 Frames muss mindestens 1 Objekt erkannt sein"

    # Zelle mit dem höchsten total_active_frames finden
    last = max(last_objs, key=lambda o: o.get("total_active_frames", 0))

    assert last["total_active_frames"] >= 3, (
        f"total_active_frames akkumuliert nicht: {last['total_active_frames']} "
        f"(B117-Schreib-Fix nicht angewandt?)"
    )
    assert last["active_frames"] >= 2, (
        f"active_frames akkumuliert nicht: {last['active_frames']}"
    )
    assert last["first_seen"] == timestamps[0], (
        f"first_seen nicht stabil: {last['first_seen']} != {timestamps[0]}"
    )
    assert len(last.get("history", [])) >= 2, "history akkumuliert nicht"


# ---------------------------------------------------------------------------
# Test 2: Merge-Zelle erbt dominant-Parent-ID
# ---------------------------------------------------------------------------


def test_merge_inherits_dominant_parent_id(monkeypatch):
    """B117/B398: gültiger Merge führt die ID des dominanten Parents fort."""
    _apply_mocks(monkeypatch)
    object_tracking.tracking_memory = {}
    monkeypatch.setattr(object_tracking, "_last_tracking_timestamp", None, raising=False)
    monkeypatch.setattr(object_tracking, "_pending_transitions", {}, raising=False)

    hsv = np.zeros((400, 400, 3), dtype=np.uint8)

    # big: 90x80 = 7.200 px; small: 60x80 = 4.800 px
    # merge: 160x80 = 12.800 px; explained = 12.000/12.800 = 0.9375
    big = _rect_contour(60, 160, 150, 240)
    small = _rect_contour(160, 160, 220, 240)

    objs1 = object_tracking.update_tracking_memory(
        hsv, [big, small], {}, "2026-01-01_00-00-00"
    )
    assert len(objs1) == 2

    big_obj = max(objs1, key=lambda obj: float(obj.get("area") or 0.0))
    small_obj = min(objs1, key=lambda obj: float(obj.get("area") or 0.0))
    assert big_obj["id"] != small_obj["id"]
    dominant_parent_id = big_obj["id"]

    merged_cnt = _rect_contour(60, 160, 220, 240)

    objs2 = object_tracking.update_tracking_memory(
        hsv, [merged_cnt], {}, "2026-01-01_00-05-00"
    )
    assert len(objs2) == 1
    assert objs2[0].get("lineage") == "continued"
    assert objs2[0]["id"] == dominant_parent_id

    objs3 = object_tracking.update_tracking_memory(
        hsv, [merged_cnt], {}, "2026-01-01_00-10-00"
    )
    assert len(objs3) == 1
    assert objs3[0]["id"] == dominant_parent_id
    assert objs3[0].get("lineage") == "merged"
    assert len(objs3[0].get("parents") or []) == 2
