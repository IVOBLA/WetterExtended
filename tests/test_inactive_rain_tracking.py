import json

import pytest


def _setup(monkeypatch, tmp_path):
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    pytest.importorskip("shapely")
    pytest.importorskip("filterpy")

    import config
    import object_tracking

    object_tracking.tracking_memory = {}
    monkeypatch.setattr(object_tracking, "save_tracking_snapshot", lambda: None)
    monkeypatch.setattr(object_tracking, "pixel_to_geo", lambda x, y: (46.7, 14.3))
    monkeypatch.setattr(object_tracking, "get_dem_features", lambda *a, **k: {
        "dem_elevation_m": 0.0,
        "dem_slope_toward_cell": 0.0,
        "dem_barrier_ahead": 0.0,
    })
    monkeypatch.setattr(object_tracking, "get_valley_features", lambda *a, **k: {
        "valley_alignment": 0.0,
        "valley_distance_km": 999.0,
        "valley_confinement": 0.0,
    })
    monkeypatch.setattr(object_tracking, "compute_stratiform_environment", lambda *a, **k: {
        "strat_area_px": 0.0,
        "strat_intensity_mean": 0.0,
        "strat_dbz_gradient": 0.0,
    })
    monkeypatch.setattr(object_tracking, "calculate_core_ratio", lambda *a, **k: {
        "core_ratio": 0.3,
        "core_area_px": 100.0,
        "cell_area_px": 900.0,
    })
    monkeypatch.setattr(config, "SAVE_PATHS", {**config.SAVE_PATHS, "objects": str(tmp_path)})
    return object_tracking, np, cv2


def _contour(np, x=90, y=90, size=60):
    return np.array([[[x, y]], [[x + size, y]], [[x + size, y + size]], [[x, y + size]]], dtype=np.int32)


def _support_mask(np, cv2, shape=(300, 300), center=(120, 120), radius=35):
    mask = np.zeros(shape, dtype=np.uint8)
    cv2.circle(mask, center, radius, 255, -1)
    return mask


def test_active_cell_becomes_inactive_rain_with_same_id(monkeypatch, tmp_path):
    ot, np, cv2 = _setup(monkeypatch, tmp_path)
    hsv = np.zeros((300, 300, 3), dtype=np.uint8)
    first = ot.update_tracking_memory(hsv, [_contour(np)], {}, "2026-06-18_10-00-00")
    cell_id = first[0]["id"]

    second = ot.update_tracking_memory(
        hsv, [], {}, "2026-06-18_10-05-00",
        rain_support_mask=_support_mask(np, cv2),
    )

    assert [o["id"] for o in second] == [cell_id]
    assert second[0]["tracking_state"] == "inactive_rain"
    assert second[0]["is_active_cell"] is False
    assert second[0]["silent_tracking"] is True
    assert second[0]["rain_supported"] is True


def test_inactive_rain_reactivates_without_new_id(monkeypatch, tmp_path):
    ot, np, cv2 = _setup(monkeypatch, tmp_path)
    hsv = np.zeros((300, 300, 3), dtype=np.uint8)
    first = ot.update_tracking_memory(hsv, [_contour(np)], {}, "2026-06-18_10-00-00")
    cell_id = first[0]["id"]
    ot.update_tracking_memory(hsv, [], {}, "2026-06-18_10-05-00", rain_support_mask=_support_mask(np, cv2))

    third = ot.update_tracking_memory(hsv, [_contour(np, 92, 92)], {}, "2026-06-18_10-10-00")

    assert third[0]["id"] == cell_id
    assert third[0]["tracking_state"] == "reactivated"
    assert third[0]["reactivated_from_inactive"] is True
    assert third[0]["is_active_cell"] is True
    assert third[0]["missing"] == 0


def test_active_cell_expires_without_rain_support(monkeypatch, tmp_path):
    ot, np, _cv2 = _setup(monkeypatch, tmp_path)
    hsv = np.zeros((300, 300, 3), dtype=np.uint8)
    first = ot.update_tracking_memory(hsv, [_contour(np)], {}, "2026-06-18_10-00-00")
    cell_id = first[0]["id"]

    second = ot.update_tracking_memory(hsv, [], {}, "2026-06-18_10-05-00", rain_support_mask=np.zeros((300, 300), dtype=np.uint8))

    assert cell_id not in [o["id"] for o in second]
    assert cell_id not in ot.tracking_memory


def test_inactive_rain_expires_after_30_minutes_even_with_support(monkeypatch, tmp_path):
    ot, np, cv2 = _setup(monkeypatch, tmp_path)
    hsv = np.zeros((300, 300, 3), dtype=np.uint8)
    first = ot.update_tracking_memory(hsv, [_contour(np)], {}, "2026-06-18_10-00-00")
    cell_id = first[0]["id"]
    ot.update_tracking_memory(hsv, [], {}, "2026-06-18_10-05-00", rain_support_mask=_support_mask(np, cv2))

    later = ot.update_tracking_memory(hsv, [], {}, "2026-06-18_10-40-01", rain_support_mask=_support_mask(np, cv2))

    assert cell_id not in [o["id"] for o in later]
    assert cell_id not in ot.tracking_memory


def test_object_frame_meta_ignores_inactive_rain(tmp_path, monkeypatch):
    pytest.importorskip("flask")
    import app
    import config

    objects_dir = tmp_path / "objects"
    objects_dir.mkdir()
    monkeypatch.setitem(config.SAVE_PATHS, "objects", str(objects_dir))
    monkeypatch.setitem(app.SAVE_PATHS, "objects", str(objects_dir))
    (objects_dir / "2026-06-18_10-05-00.json").write_text(json.dumps([
        {"id": "A", "tracking_state": "inactive_rain", "is_active_cell": False, "missing": 1}
    ]))

    meta = app._object_frame_meta("2026-06-18_10-05-00")

    assert meta["object_count"] == 1
    assert meta["cells_active"] is False


def test_object_frame_meta_counts_only_active_cells(tmp_path, monkeypatch):
    pytest.importorskip("flask")
    import app
    import config

    objects_dir = tmp_path / "objects"
    objects_dir.mkdir()
    monkeypatch.setitem(config.SAVE_PATHS, "objects", str(objects_dir))
    monkeypatch.setitem(app.SAVE_PATHS, "objects", str(objects_dir))
    (objects_dir / "2026-06-18_10-05-00.json").write_text(json.dumps([
        {"id": "A", "tracking_state": "inactive_rain", "is_active_cell": False, "missing": 1},
        {"id": "B", "tracking_state": "active", "is_active_cell": True, "missing": 0},
    ]))

    meta = app._object_frame_meta("2026-06-18_10-05-00")

    assert meta["object_count"] == 2
    assert meta["cells_active"] is True
