import pytest


def _patch_tracking_dependencies(monkeypatch, object_tracking):
    monkeypatch.setattr(object_tracking, "pixel_to_geo", lambda x, y: (46.7, 14.3))
    monkeypatch.setattr(object_tracking, "save_tracking_snapshot", lambda: None)
    monkeypatch.setattr(object_tracking, "calculate_core_ratio", lambda hsv, contour: 0.2)
    monkeypatch.setattr(
        object_tracking,
        "get_dem_features",
        lambda *args, **kwargs: {
            "dem_elevation_m": 0.0,
            "dem_slope_toward_cell": 0.0,
            "dem_barrier_ahead": 0.0,
        },
    )
    monkeypatch.setattr(
        object_tracking,
        "get_valley_features",
        lambda *args, **kwargs: {
            "valley_alignment": 0.0,
            "valley_distance_km": 999.0,
            "valley_confinement": 0.0,
        },
    )
    monkeypatch.setattr(
        object_tracking,
        "compute_stratiform_environment",
        lambda *args, **kwargs: {
            "strat_area_px": 0.0,
            "strat_intensity_mean": 0.0,
            "strat_dbz_gradient": 0.0,
        },
    )


def _square(np, x0, y0, x1, y1):
    return np.array([[[x0, y0]], [[x1, y0]], [[x1, y1]], [[x0, y1]]], dtype=np.int32)


def _require_real_numpy(np):
    if not hasattr(np, "zeros"):
        pytest.skip("benötigt ein echtes numpy-Paket")


def _snapshot_obj(obj_id, contour, *, x=None, y=None, history=None, vx=0.0, vy=0.0, area=1000.0):
    pts = contour[:, 0, :].tolist()
    if x is None:
        x = sum(point[0] for point in pts) / len(pts) / 3.0
    if y is None:
        y = sum(point[1] for point in pts) / len(pts) / 3.0
    return {
        "id": obj_id,
        "x": x,
        "y": y,
        "vx": vx,
        "vy": vy,
        "area": area,
        "core_ratio": 0.2,
        "core_area_px": 200.0,
        "contour": pts,
        "missing": 0,
        "history": history or [],
        "lat": 46.7,
        "lon": 14.3,
        "first_seen": "2026-06-09_00-00-00",
        "total_active_frames": 1,
    }


def test_update_tracking_memory_does_not_shadow_upscale_factor(monkeypatch):
    pytest.importorskip("cv2")
    pytest.importorskip("shapely")
    pytest.importorskip("filterpy")
    np = pytest.importorskip("numpy")
    _require_real_numpy(np)

    import object_tracking

    object_tracking.tracking_memory = {}
    _patch_tracking_dependencies(monkeypatch, object_tracking)

    hsv = np.zeros((240, 240, 3), dtype=np.uint8)
    contour = np.array([[[30, 30]], [[140, 30]], [[140, 140]], [[30, 140]]], dtype=np.int32)

    try:
        objects = object_tracking.update_tracking_memory(hsv, [contour], {}, "2026-06-09T00:00:00Z")
    except UnboundLocalError as exc:
        pytest.fail(f"update_tracking_memory darf UPSCALE_FACTOR nicht als lokale Variable shadowen: {exc}")

    assert isinstance(objects, list)


def test_restored_snapshot_without_kf_continues_same_id(monkeypatch):
    pytest.importorskip("cv2")
    pytest.importorskip("shapely")
    pytest.importorskip("filterpy")
    np = pytest.importorskip("numpy")
    _require_real_numpy(np)

    import object_tracking

    contour = _square(np, 30, 30, 120, 120)
    object_tracking.tracking_memory = {
        "CELL1": _snapshot_obj("CELL1", contour)
    }
    _patch_tracking_dependencies(monkeypatch, object_tracking)

    objects = object_tracking.update_tracking_memory(
        np.zeros((180, 180, 3), dtype=np.uint8),
        [contour],
        {},
        "2026-06-09_00-05-00",
    )

    assert [obj["id"] for obj in objects] == ["CELL1"]
    assert "CELL1" in object_tracking.tracking_memory
    assert "kf" in object_tracking.tracking_memory["CELL1"]


def test_restored_snapshot_without_kf_seeds_velocity_from_history(monkeypatch):
    pytest.importorskip("cv2")
    pytest.importorskip("shapely")
    pytest.importorskip("filterpy")
    np = pytest.importorskip("numpy")
    _require_real_numpy(np)

    import object_tracking

    contour = _square(np, 30, 30, 120, 120)
    object_tracking.tracking_memory = {
        "CELL1": _snapshot_obj(
            "CELL1",
            contour,
            history=[{"timestamp": "2026-06-09_00-00-00", "vx": 2.5, "vy": -1.25}],
        )
    }
    _patch_tracking_dependencies(monkeypatch, object_tracking)

    object_tracking.update_tracking_memory(
        np.zeros((180, 180, 3), dtype=np.uint8),
        [contour],
        {},
        "2026-06-09_00-05-00",
    )

    restored = object_tracking.tracking_memory["CELL1"]
    assert restored["vx"] == pytest.approx(2.5)
    assert restored["vy"] == pytest.approx(-1.25)
    assert restored["kf"].x[2] == pytest.approx(2.5)
    assert restored["kf"].x[3] == pytest.approx(-1.25)


def test_restored_snapshot_without_kf_or_valid_history_falls_back_cleanly(monkeypatch):
    pytest.importorskip("cv2")
    pytest.importorskip("shapely")
    pytest.importorskip("filterpy")
    np = pytest.importorskip("numpy")
    _require_real_numpy(np)

    import object_tracking

    contour = _square(np, 30, 30, 120, 120)
    object_tracking.tracking_memory = {
        "CELL1": _snapshot_obj(
            "CELL1",
            contour,
            history=[{"timestamp": "2026-06-09_00-00-00", "vx": "nan", "vy": None}],
        )
    }
    _patch_tracking_dependencies(monkeypatch, object_tracking)

    object_tracking.update_tracking_memory(
        np.zeros((180, 180, 3), dtype=np.uint8),
        [contour],
        {},
        "2026-06-09_00-05-00",
    )

    restored = object_tracking.tracking_memory["CELL1"]
    assert restored["vx"] == pytest.approx(0.0)
    assert restored["vy"] == pytest.approx(0.0)


def test_merge_with_dominant_parent_without_kf_does_not_crash(monkeypatch):
    pytest.importorskip("cv2")
    pytest.importorskip("shapely")
    pytest.importorskip("filterpy")
    np = pytest.importorskip("numpy")
    _require_real_numpy(np)

    import object_tracking

    parent_a = _square(np, 30, 30, 120, 120)
    parent_b = _square(np, 130, 30, 190, 120)
    merged = _square(np, 25, 25, 195, 125)
    object_tracking.tracking_memory = {
        "DOM": _snapshot_obj("DOM", parent_a, area=8100.0),
        "CHILD": _snapshot_obj("CHILD", parent_b, area=5400.0),
    }
    _patch_tracking_dependencies(monkeypatch, object_tracking)

    objects = object_tracking.update_tracking_memory(
        np.zeros((240, 240, 3), dtype=np.uint8),
        [merged],
        {},
        "2026-06-09_00-05-00",
    )

    assert [obj["id"] for obj in objects] == ["DOM"]
    assert object_tracking.tracking_memory["DOM"]["lineage"] == "merged"
    assert "kf" in object_tracking.tracking_memory["DOM"]


def test_update_tracking_memory_snapshots_after_station_encounter_carry_over(monkeypatch):
    pytest.importorskip("cv2")
    pytest.importorskip("shapely")
    pytest.importorskip("filterpy")
    np = pytest.importorskip("numpy")
    _require_real_numpy(np)

    import object_tracking

    contour = _square(np, 30, 30, 120, 120)
    encounter = {
        "timestamp": "2026-07-14_12-00-00",
        "station_name": "Villach",
        "distance_km": 3.2,
        "wind_kmh": 22.0,
        "gust_kmh": 48.0,
        "direction_deg": 225.0,
    }
    previous = _snapshot_obj("CELL1", contour)
    previous["last_station_encounter"] = encounter
    object_tracking.tracking_memory = {"CELL1": previous}
    _patch_tracking_dependencies(monkeypatch, object_tracking)

    snapshotted = {}

    def fake_save_tracking_snapshot():
        snapshotted.update(
            {
                oid: dict(obj)
                for oid, obj in object_tracking.tracking_memory.items()
            }
        )

    monkeypatch.setattr(object_tracking, "save_tracking_snapshot", fake_save_tracking_snapshot)

    object_tracking.update_tracking_memory(
        np.zeros((180, 180, 3), dtype=np.uint8),
        [contour],
        {},
        "2026-06-09_00-05-00",
    )

    assert snapshotted["CELL1"]["last_station_encounter"] == encounter
