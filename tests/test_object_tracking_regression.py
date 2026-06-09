import pytest


def test_update_tracking_memory_does_not_shadow_upscale_factor(monkeypatch):
    pytest.importorskip("cv2")
    pytest.importorskip("shapely")
    pytest.importorskip("filterpy")
    np = pytest.importorskip("numpy")

    import object_tracking

    object_tracking.tracking_memory = {}
    monkeypatch.setattr(object_tracking, "pixel_to_geo", lambda x, y: (46.7, 14.3))
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

    hsv = np.zeros((240, 240, 3), dtype=np.uint8)
    contour = np.array([[[30, 30]], [[140, 30]], [[140, 140]], [[30, 140]]], dtype=np.int32)

    try:
        objects = object_tracking.update_tracking_memory(hsv, [contour], {}, "2026-06-09T00:00:00Z")
    except UnboundLocalError as exc:
        pytest.fail(f"update_tracking_memory darf UPSCALE_FACTOR nicht als lokale Variable shadowen: {exc}")

    assert isinstance(objects, list)
