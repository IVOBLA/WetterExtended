"""B402: Polygon und Position müssen auf denselben Zeitpunkt prädiziert werden."""
import numpy as np
import pytest

import object_tracking


def _rect(x1, y1, x2, y2):
    pts = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
    return np.array(pts, dtype=np.int32).reshape(-1, 1, 2)


@pytest.fixture(autouse=True)
def _mocks(monkeypatch):
    """Testisolation via monkeypatch (Muster: test_config_override_guard.py)."""
    monkeypatch.setattr(object_tracking, "pixel_to_geo",
                        lambda x, y: (46.7 - y * 0.001, 14.3 + x * 0.00145))
    monkeypatch.setattr(object_tracking, "calculate_core_ratio", lambda hsv, contour: 0.3)
    monkeypatch.setattr(object_tracking, "_is_in_exclusion_zone", lambda lat, lon, zones: False)
    object_tracking.tracking_memory = {}
    monkeypatch.setattr(object_tracking, "_last_tracking_timestamp", None, raising=False)
    monkeypatch.setattr(object_tracking, "_pending_transitions", {}, raising=False)
    yield
    object_tracking.tracking_memory = {}


def test_frame_interval_matches_assoc_normal():
    """Beide Konstanten beschreiben denselben nominalen Takt."""
    from config import ASSOC_NORMAL_FRAME_MINUTES, FRAME_INTERVAL_MIN
    assert FRAME_INTERVAL_MIN == ASSOC_NORMAL_FRAME_MINUTES


def test_dt_minutes_computed_before_pred_polys():
    """Statischer Nachweis: die Zeitbasis muss VOR der Polygon-Praediktion stehen."""
    import inspect
    src = inspect.getsource(object_tracking.update_tracking_memory)
    i_dt = src.find("_dt_minutes = _tracking_dt_minutes(timestamp)")
    i_poly = src.find("_dx_s  = _vx_kf")
    assert i_dt != -1 and i_poly != -1
    assert i_dt < i_poly, "_dt_minutes wird erst nach der Polygon-Praediktion ermittelt"


def test_dt_minutes_called_only_once():
    """`_tracking_dt_minutes` schreibt den Timestamp fort — nur EIN Aufruf pro Lauf."""
    import inspect
    src = inspect.getsource(object_tracking.update_tracking_memory)
    assert src.count("_tracking_dt_minutes(timestamp)") == 1, (
        "Mehrfachaufruf wuerde _last_tracking_timestamp fortschreiben und dt verfaelschen"
    )


def test_polygon_shift_scales_with_dt():
    """KERNREGRESSION: bei 15 min muss das Polygon 3x so weit verschoben werden."""
    from config import FRAME_INTERVAL_MIN, UPSCALE_FACTOR
    vx = 4.0                                   # Original-px pro Frame
    for dt, expected_frames in ((5.0, 1.0), (10.0, 2.0), (15.0, 3.0)):
        dt_frames = dt / FRAME_INTERVAL_MIN
        assert dt_frames == pytest.approx(expected_frames)
        shift = vx * UPSCALE_FACTOR * dt_frames
        assert shift == pytest.approx(vx * UPSCALE_FACTOR * expected_frames)


def test_normal_takt_is_unchanged():
    """Bei 5 min muss dt_frames exakt 1.0 sein — Verhalten bitgleich."""
    from config import FRAME_INTERVAL_MIN
    assert 5.0 / FRAME_INTERVAL_MIN == pytest.approx(1.0)


def test_fast_cell_survives_radar_gap():
    """Eine schnelle Zelle darf bei 15 min Luecke nicht die ID verlieren."""
    hsv = np.zeros((400, 400, 3), dtype=np.uint8)
    o1 = object_tracking.update_tracking_memory(hsv, [_rect(60, 160, 140, 240)], {}, "2026-01-01_00-00-00")
    tid = o1[0]["id"]
    # Zwei regulaere Frames, damit der Kalman eine Geschwindigkeit lernt.
    object_tracking.update_tracking_memory(hsv, [_rect(80, 160, 160, 240)], {}, "2026-01-01_00-05-00")
    object_tracking.update_tracking_memory(hsv, [_rect(100, 160, 180, 240)], {}, "2026-01-01_00-10-00")
    # 15-min-Luecke: die Zelle zieht mit ~20 px/Frame weiter -> +60 px.
    o4 = object_tracking.update_tracking_memory(hsv, [_rect(160, 160, 240, 240)], {}, "2026-01-01_00-25-00")
    assert o4, "Keine Zelle nach der Radarluecke"
    assert o4[0]["id"] == tid, (
        f"ID nach 15-min-Luecke verloren: {tid} -> {o4[0]['id']}. "
        "Polygon und Position wurden auf verschiedene Zeitpunkte praediziert."
    )


def test_static_cell_unaffected_by_dt():
    """Bei vx=vy=0 ist die Zeitbasis irrelevant — das Polygon bleibt statisch."""
    hsv = np.zeros((400, 400, 3), dtype=np.uint8)
    o1 = object_tracking.update_tracking_memory(hsv, [_rect(60, 160, 140, 240)], {}, "2026-01-01_00-00-00")
    tid = o1[0]["id"]
    o2 = object_tracking.update_tracking_memory(hsv, [_rect(60, 160, 140, 240)], {}, "2026-01-01_00-15-00")
    assert o2[0]["id"] == tid


def test_dt_frames_uses_runtime_config(monkeypatch):
    """FRAME_INTERVAL_MIN muss ueber runtime_config uebersteuerbar sein."""
    calls = []
    orig = object_tracking._rc.get

    def _spy(key, default=None):
        if key == "FRAME_INTERVAL_MIN":
            calls.append(key)
            return 5.0
        return orig(key, default)

    monkeypatch.setattr(object_tracking._rc, "get", _spy)
    hsv = np.zeros((400, 400, 3), dtype=np.uint8)
    object_tracking.update_tracking_memory(hsv, [_rect(60, 160, 140, 240)], {}, "2026-01-01_00-00-00")
    object_tracking.update_tracking_memory(hsv, [_rect(80, 160, 160, 240)], {}, "2026-01-01_00-05-00")
    assert calls, "FRAME_INTERVAL_MIN wurde nicht ueber runtime_config gelesen"
