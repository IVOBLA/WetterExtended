import math

import pytest


def _patch_tracking_dependencies(monkeypatch, object_tracking):
    # B384: REALISTISCHER Geo-Mock statt konstanter Koordinate.
    #
    # Vorher lieferte der Mock fuer JEDE Kontur (46.7, 14.3) -- die Distanz zwischen
    # altem Track und neuer Detektion war immer 0 km. Bis B374 war das folgenlos, weil
    # Stage 2 in skalierten Pixeln aus Konturmomenten rechnete und pixel_to_geo gar
    # nicht benutzte. Seit B373/B374 rechnen alle Gates in echten Kilometern aus
    # lat/lon -- ein konstanter Mock macht jedes Distanzgate wirkungslos.
    #
    # Massstab aus config.py abgeleitet:
    #   PX_TO_KMH = 4.0   -> 1 Original-Pixel/5-min-Frame = 4.0 * (5/60) = 0.333 km
    #   UPSCALE_FACTOR = 3 -> 1 skalierter Pixel = 0.333 / 3 = 0.111 km
    # Die Konturen dieses Tests liegen in skalierten Pixeln.
    _KM_PER_SCALED_PX = 0.111
    _KM_PER_DEG_LAT = 111.32
    _LAT0, _LON0 = 46.7, 14.3
    _KM_PER_DEG_LON = _KM_PER_DEG_LAT * math.cos(math.radians(_LAT0))
    monkeypatch.setattr(
        object_tracking,
        "pixel_to_geo",
        lambda x, y: (
            _LAT0 - (float(y) * _KM_PER_SCALED_PX) / _KM_PER_DEG_LAT,   # y waechst nach Sueden
            _LON0 + (float(x) * _KM_PER_SCALED_PX) / _KM_PER_DEG_LON,
        ),
    )
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


def _snapshot_obj(obj_id, contour, *, core_ratio, x=None, y=None, area=8100.0):
    pts = contour[:, 0, :].tolist()
    if x is None:
        x = sum(point[0] for point in pts) / len(pts) / 3.0
    if y is None:
        y = sum(point[1] for point in pts) / len(pts) / 3.0
    return {
        "id": obj_id,
        "x": x,
        "y": y,
        "vx": 0.0,
        "vy": 0.0,
        "area": area,
        "core_ratio": core_ratio,
        "core_area_px": 200.0,
        "contour": pts,
        "missing": 0,
        "history": [],
        "lat": 46.7,
        "lon": 14.3,
        "first_seen": "2026-07-14_00-00-00",
        "total_active_frames": 1,
    }


def test_weak_cell_does_not_match_distant_unrelated_contour(monkeypatch):
    """B365: Eine fast aufgeloeste Zelle (core_ratio 0.0) darf NICHT mit
    einer 90 skalierte-px (~innerhalb des alten, zu weiten Caps von
    168.75px, aber ausserhalb des neuen Weak-Cell-Caps von 45px)
    entfernten, unabhaengigen Kontur fortgesetzt werden."""
    pytest.importorskip("cv2")
    pytest.importorskip("shapely")
    pytest.importorskip("filterpy")
    np = pytest.importorskip("numpy")
    _require_real_numpy(np)

    import object_tracking

    old_contour = _square(np, 30, 30, 120, 120)      # Zentrum ~(75, 75)
    new_contour = _square(np, 120, 30, 210, 120)     # Zentrum ~(165, 75) -> Distanz 90px

    object_tracking.tracking_memory = {
        "WEAKCELL": _snapshot_obj("WEAKCELL", old_contour, core_ratio=0.0)
    }
    _patch_tracking_dependencies(monkeypatch, object_tracking)

    objects = object_tracking.update_tracking_memory(
        np.zeros((300, 300, 3), dtype=np.uint8),
        [new_contour],
        {},
        "2026-07-14_00-05-00",
    )

    ids = [obj["id"] for obj in objects]
    assert "WEAKCELL" not in ids, (
        "Fehlzuordnung: schwache Zelle wurde faelschlich mit entfernter, "
        "unabhaengiger Kontur fortgesetzt (B365-Regression)."
    )


def test_strong_cell_still_matches_at_same_distance(monkeypatch):
    """Regressionsschutz: eine AKTIVE Zelle (core_ratio >= Schwelle) darf bei
    derselben Distanz (90px, weiterhin < altem Cap 168.75px) weiterhin ueber
    Stage 2 zugeordnet werden — die B365-Aenderung darf legitime, schnelle
    Zellen nicht ausbremsen."""
    pytest.importorskip("cv2")
    pytest.importorskip("shapely")
    pytest.importorskip("filterpy")
    np = pytest.importorskip("numpy")
    _require_real_numpy(np)

    import object_tracking

    old_contour = _square(np, 30, 30, 120, 120)
    new_contour = _square(np, 120, 30, 210, 120)

    object_tracking.tracking_memory = {
        "STRONGCELL": _snapshot_obj("STRONGCELL", old_contour, core_ratio=0.5)
    }
    _patch_tracking_dependencies(monkeypatch, object_tracking)

    objects = object_tracking.update_tracking_memory(
        np.zeros((300, 300, 3), dtype=np.uint8),
        [new_contour],
        {},
        "2026-07-14_00-05-00",
    )

    ids = [obj["id"] for obj in objects]
    assert "STRONGCELL" in ids, (
        "Regression: aktive, kraeftige Zelle wurde durch B365 faelschlich "
        "nicht mehr zugeordnet."
    )
