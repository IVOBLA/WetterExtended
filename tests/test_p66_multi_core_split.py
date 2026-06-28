"""
tests/test_p66_multi_core_split.py

P66 – Multi-Core-Split: Unit-Tests für _detect_core_components,
_voronoi_split und split_multi_core_contours.
"""
import pytest


def _require_deps():
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    if not hasattr(np, "zeros"):
        pytest.skip("Benötigt echtes numpy")
    return cv2, np


def _red_hsv():
    return (5, 200, 200)


def _make_image_with_blobs(np, h, w, blobs_red, bg_hsv=(0, 0, 0)):
    img = np.zeros((h, w, 3), dtype=np.uint8)
    if bg_hsv != (0, 0, 0):
        img[:] = bg_hsv
    for cx, cy, r in blobs_red:
        for y in range(max(0, cy - r), min(h, cy + r + 1)):
            for x in range(max(0, cx - r), min(w, cx + r + 1)):
                if (x - cx) ** 2 + (y - cy) ** 2 <= r ** 2:
                    img[y, x] = _red_hsv()
    return img


def _rect_contour(np, x0, y0, x1, y1):
    return np.array([[[x0, y0]], [[x1, y0]], [[x1, y1]], [[x0, y1]]], dtype=np.int32)


_CORE_HSV_RANGES_TEST = [([0, 100, 120], [10, 255, 255]), ([165, 100, 120], [179, 255, 255])]


class TestDetectCoreComponents:
    def test_single_core_returns_one_entry(self):
        cv2, np = _require_deps()
        import object_tracking
        hsv = _make_image_with_blobs(np, 200, 200, [(100, 100, 15)])
        cores = object_tracking._detect_core_components(hsv, _rect_contour(np, 70, 70, 130, 130), _CORE_HSV_RANGES_TEST, 50)
        assert len(cores) == 1
        cx, cy, area = cores[0]
        assert abs(cx - 100) < 5
        assert abs(cy - 100) < 5
        assert area >= 50

    def test_two_separated_cores_returns_two_entries(self):
        cv2, np = _require_deps()
        import object_tracking
        hsv = _make_image_with_blobs(np, 300, 300, [(80, 150, 15), (200, 150, 15)])
        cores = object_tracking._detect_core_components(hsv, _rect_contour(np, 50, 110, 240, 190), _CORE_HSV_RANGES_TEST, 50)
        assert len(cores) == 2

    def test_small_core_below_min_area_ignored(self):
        cv2, np = _require_deps()
        import object_tracking
        hsv = _make_image_with_blobs(np, 200, 200, [(100, 100, 3)])
        cores = object_tracking._detect_core_components(hsv, _rect_contour(np, 80, 80, 120, 120), _CORE_HSV_RANGES_TEST, 100)
        assert len(cores) == 0

    def test_no_red_pixels_returns_empty(self):
        cv2, np = _require_deps()
        import object_tracking
        hsv = np.zeros((200, 200, 3), dtype=np.uint8)
        cores = object_tracking._detect_core_components(hsv, _rect_contour(np, 50, 50, 150, 150), _CORE_HSV_RANGES_TEST, 10)
        assert len(cores) == 0

    def test_pixels_outside_contour_ignored(self):
        cv2, np = _require_deps()
        import object_tracking
        hsv = _make_image_with_blobs(np, 300, 300, [(250, 150, 15)])
        cores = object_tracking._detect_core_components(hsv, _rect_contour(np, 10, 10, 200, 280), _CORE_HSV_RANGES_TEST, 50)
        assert len(cores) == 0


class TestVoronoiSplit:
    def test_two_cores_produce_two_contours(self):
        cv2, np = _require_deps()
        import object_tracking
        contour = _rect_contour(np, 20, 20, 280, 280)
        result = object_tracking._voronoi_split((300, 300, 3), contour, [(80.0, 150.0, 500), (220.0, 150.0, 500)], 500)
        assert len(result) == 2

    def test_fallback_when_child_too_small(self):
        cv2, np = _require_deps()
        import object_tracking
        contour = _rect_contour(np, 100, 100, 110, 110)
        result = object_tracking._voronoi_split((300, 300, 3), contour, [(103.0, 105.0, 30), (107.0, 105.0, 30)], 800)
        assert len(result) == 1
        assert result[0] is contour

    def test_three_cores_produce_three_contours(self):
        cv2, np = _require_deps()
        import object_tracking
        contour = _rect_contour(np, 20, 20, 380, 380)
        result = object_tracking._voronoi_split((400, 400, 3), contour, [(80.0, 200.0, 500), (200.0, 200.0, 500), (320.0, 200.0, 500)], 500)
        assert len(result) == 3

    def test_all_result_contours_are_numpy_int32(self):
        cv2, np = _require_deps()
        import object_tracking
        contour = _rect_contour(np, 20, 20, 280, 280)
        result = object_tracking._voronoi_split((300, 300, 3), contour, [(80.0, 150.0, 500), (220.0, 150.0, 500)], 500)
        for cnt in result:
            assert cnt.dtype == np.int32


class TestSplitMultiCoreContours:
    def _make_rc(self, overrides=None):
        defaults = {"MULTI_CORE_SPLIT_ENABLED": True, "MULTI_CORE_MIN_CORE_AREA_PX": 50, "MULTI_CORE_MIN_DIST_PX": 15, "MULTI_CORE_MIN_CHILD_AREA_PX": 200, "CORE_HSV_RANGES": _CORE_HSV_RANGES_TEST}
        if overrides:
            defaults.update(overrides)
        class _FakeRc:
            def get(self, key, default=None):
                return defaults.get(key, default)
        return _FakeRc()

    def test_single_core_no_split(self, monkeypatch):
        cv2, np = _require_deps()
        import object_tracking
        monkeypatch.setattr(object_tracking, "_rc", self._make_rc())
        hsv = _make_image_with_blobs(np, 200, 200, [(100, 100, 15)])
        assert len(object_tracking.split_multi_core_contours([_rect_contour(np, 70, 70, 130, 130)], hsv)) == 1

    def test_two_far_apart_cores_split(self, monkeypatch):
        cv2, np = _require_deps()
        import object_tracking
        monkeypatch.setattr(object_tracking, "_rc", self._make_rc())
        hsv = _make_image_with_blobs(np, 300, 300, [(70, 150, 15), (220, 150, 15)])
        assert len(object_tracking.split_multi_core_contours([_rect_contour(np, 40, 110, 260, 190)], hsv)) == 2

    def test_two_close_cores_no_split(self, monkeypatch):
        cv2, np = _require_deps()
        import object_tracking
        monkeypatch.setattr(object_tracking, "_rc", self._make_rc({"MULTI_CORE_MIN_CORE_AREA_PX": 10}))
        hsv = _make_image_with_blobs(np, 200, 200, [(96, 100, 3), (104, 100, 3)])
        assert len(object_tracking.split_multi_core_contours([_rect_contour(np, 80, 85, 120, 115)], hsv)) == 1

    def test_disabled_via_config(self, monkeypatch):
        cv2, np = _require_deps()
        import object_tracking
        monkeypatch.setattr(object_tracking, "_rc", self._make_rc({"MULTI_CORE_SPLIT_ENABLED": False}))
        hsv = _make_image_with_blobs(np, 300, 300, [(70, 150, 15), (220, 150, 15)])
        assert len(object_tracking.split_multi_core_contours([_rect_contour(np, 40, 110, 260, 190)], hsv)) == 1

    def test_multiple_independent_contours_processed(self, monkeypatch):
        cv2, np = _require_deps()
        import object_tracking
        monkeypatch.setattr(object_tracking, "_rc", self._make_rc())
        h, w = 500, 300
        contour_a = _rect_contour(np, 70, 70, 130, 130)
        contour_b = _rect_contour(np, 50, 220, 260, 280)
        mask_a = _make_image_with_blobs(np, h, w, [(100, 100, 12)])
        mask_b = _make_image_with_blobs(np, h, w, [(80, 250, 12), (220, 250, 12)])
        hsv_combined = np.maximum(mask_a, mask_b)
        assert len(object_tracking.split_multi_core_contours([contour_a, contour_b], hsv_combined)) == 3

    def test_empty_contour_list(self, monkeypatch):
        cv2, np = _require_deps()
        import object_tracking
        monkeypatch.setattr(object_tracking, "_rc", self._make_rc())
        assert object_tracking.split_multi_core_contours([], np.zeros((100, 100, 3), dtype=np.uint8)) == []
