"""
B209: update_tracking_memory speichert obj["x"]/["y"] subpixel-genau (float),
nicht auf das 0,33-km-Raster (int Original-px) gerundet.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_centroid_is_subpixel(monkeypatch):
    pytest.importorskip("cv2")
    pytest.importorskip("shapely")
    pytest.importorskip("filterpy")
    np = pytest.importorskip("numpy")

    import object_tracking
    from config import UPSCALE_FACTOR

    object_tracking.tracking_memory = {}
    monkeypatch.setattr(object_tracking, "pixel_to_geo", lambda x, y: (46.7, 14.3))
    monkeypatch.setattr(object_tracking, "calculate_core_ratio", lambda hsv, c: 0.2)
    monkeypatch.setattr(object_tracking, "get_dem_features",
                        lambda *a, **k: {"dem_elevation_m": 0.0, "dem_slope_toward_cell": 0.0, "dem_barrier_ahead": 0.0})
    monkeypatch.setattr(object_tracking, "get_valley_features",
                        lambda *a, **k: {"valley_alignment": 0.0, "valley_distance_km": 999.0, "valley_confinement": 0.0})
    monkeypatch.setattr(object_tracking, "compute_stratiform_environment",
                        lambda *a, **k: {"strat_area_px": 0.0, "strat_intensity_mean": 0.0, "strat_dbz_gradient": 0.0})

    hsv = np.zeros((240, 240, 3), dtype=np.uint8)
    # Quadrat in SKALIERTEN px mit Schwerpunkt (70, 58):
    contour = np.array([[[60, 48]], [[80, 48]], [[80, 68]], [[60, 68]]], dtype=np.int32)

    objects = object_tracking.update_tracking_memory(hsv, [contour], {}, "2026-06-17_10-00-00")
    assert objects, "Mindestens ein Objekt erwartet"
    o = objects[0]

    exp_x = 70.0 / float(UPSCALE_FACTOR)   # 23.333… bei UF=3
    exp_y = 58.0 / float(UPSCALE_FACTOR)   # 19.333…
    assert abs(float(o["x"]) - exp_x) < 0.05, f"x nicht subpixel: {o['x']} (erwartet ~{exp_x:.3f})"
    assert abs(float(o["y"]) - exp_y) < 0.05, f"y nicht subpixel: {o['y']} (erwartet ~{exp_y:.3f})"
    # Gegenprobe: alte int-Quantisierung hätte exakt 23 / 19 geliefert.
    assert float(o["x"]) != float(int(exp_x)), "x wurde fälschlich ganzzahlig gerundet"
