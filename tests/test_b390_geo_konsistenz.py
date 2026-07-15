"""B390: Snapshot und Detektion müssen dieselbe Geo-Abbildung verwenden."""
import math

import pytest


@pytest.fixture
def object_tracking_module():
    pytest.importorskip("cv2")
    pytest.importorskip("filterpy")
    pytest.importorskip("shapely")
    import object_tracking
    return object_tracking


def test_snapshot_and_mock_use_same_source():
    """Regression: konstante lat/lon im Snapshot duerfen nicht zurueckkehren."""
    src = open("tests/test_b365_stage2_weak_cell_match_cap.py", encoding="utf-8").read()
    assert '"lat": 46.7,' not in src, (
        "Konstante Snapshot-Koordinate wieder vorhanden — der alte Track wuerde "
        "gegen den Bildursprung gemessen"
    )
    assert "_geo_from_pixel_for_test" in src


def test_ninety_px_distance_is_ten_km():
    """Der Testaufbau muss die gewollten 10 km ergeben, nicht 20 km."""
    import tests.test_b365_stage2_weak_cell_match_cap as t
    lat1, lon1 = t._geo_from_pixel_for_test(75, 75)     # Zentrum old_contour
    lat2, lon2 = t._geo_from_pixel_for_test(165, 75)    # Zentrum new_contour
    dx = (lon2 - lon1) * t._KM_PER_DEG_LON
    dy = (lat2 - lat1) * t._KM_PER_DEG_LAT
    dist = math.hypot(dx, dy)
    assert dist == pytest.approx(10.0, abs=0.3), f"Testdistanz {dist:.1f} km statt 10.0 km"


def test_track_without_latlon_is_reconstructed(monkeypatch, object_tracking_module):
    object_tracking = object_tracking_module
    """Ein Snapshot ohne lat/lon darf den Track nicht aus dem Tracking werfen."""
    monkeypatch.setattr(object_tracking, "pixel_to_geo", lambda x, y: (46.7 + y * 0.001, 14.3 + x * 0.001))
    snap = {"T1": {"id": "T1", "x": 50.0, "y": 50.0, "area": 1000.0, "core_ratio": 0.3,
                   "vx": 0.0, "vy": 0.0, "total_active_frames": 3}}
    cands = object_tracking._build_track_candidates(snap, {}, {})
    assert len(cands) == 1, "Track ohne lat/lon wurde lautlos verworfen"
    assert cands[0].track_id == "T1"


def test_track_without_any_position_is_skipped(monkeypatch, object_tracking_module):
    object_tracking = object_tracking_module
    """Ohne jede Position bleibt nur der Ausschluss — aber mit Logeintrag."""
    logged = []
    monkeypatch.setattr(object_tracking, "debug_log", lambda msg: logged.append(msg))
    snap = {"T1": {"id": "T1", "area": 1000.0, "core_ratio": 0.3}}
    cands = object_tracking._build_track_candidates(snap, {}, {})
    assert cands == []
    assert any("B390" in m and "ID-Verlust" in m for m in logged), (
        f"Ausschluss wurde nicht protokolliert: {logged}"
    )


def test_track_with_latlon_is_unaffected(monkeypatch, object_tracking_module):
    object_tracking = object_tracking_module
    """Regression: der Normalfall bleibt unveraendert."""
    snap = {"T1": {"id": "T1", "lat": 46.7, "lon": 14.3, "area": 1000.0,
                   "core_ratio": 0.3, "vx": 0.0, "vy": 0.0, "total_active_frames": 3}}
    cands = object_tracking._build_track_candidates(snap, {}, {})
    assert len(cands) == 1
    assert cands[0].pred_y_km == pytest.approx(46.7 * 111.32, abs=1.0)
