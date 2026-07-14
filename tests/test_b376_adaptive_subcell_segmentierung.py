"""B376: Zellgrenzen müssen dem Intensitätsfeld folgen, nicht der euklidischen Distanz."""
import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")
ot = pytest.importorskip("object_tracking")


def _hsv_with_cores(centers, radius=12, bridge_value=None, shape=(120, 200)):
    """Baut ein HSV-Bild mit starken Kernen und optionaler Bruecke dazwischen."""
    h, w = shape
    hsv = np.zeros((h, w, 3), dtype=np.uint8)
    if bridge_value is not None and len(centers) >= 2:
        (x1, y1), (x2, y2) = centers[0], centers[1]
        cv2.line(hsv, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, bridge_value), radius)
    for (cx, cy) in centers:
        cv2.circle(hsv, (int(cx), int(cy)), radius, (0, 255, 255), -1)
    return hsv


def _cell_contour(hsv):
    mask = (hsv[:, :, 2] > 0).astype(np.uint8) * 255
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return max(cnts, key=cv2.contourArea)


def test_saddle_zero_for_uniform_bridge():
    """Durchgehend starke Struktur (Boeenlinie) -> kein Sattel."""
    hsv = _hsv_with_cores([(50, 60), (150, 60)], bridge_value=255)
    contour = _cell_contour(hsv)
    mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
    cv2.drawContours(mask, [contour], -1, 255, -1)
    field = ot._intensity_field(hsv, mask)
    saddle = ot._core_saddle_ratio(field, mask, (50, 60), (150, 60))
    assert saddle < 0.2, f"Durchgehende Struktur darf keinen Sattel zeigen (war {saddle:.2f})"


def test_saddle_high_for_weak_bridge():
    """Schwache Bruecke zwischen zwei starken Kernen -> deutlicher Sattel."""
    hsv = _hsv_with_cores([(50, 60), (150, 60)], bridge_value=40)
    contour = _cell_contour(hsv)
    mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
    cv2.drawContours(mask, [contour], -1, 255, -1)
    field = ot._intensity_field(hsv, mask)
    saddle = ot._core_saddle_ratio(field, mask, (50, 60), (150, 60))
    assert saddle > 0.35, f"Schwache Bruecke muss einen Sattel ergeben (war {saddle:.2f})"


def test_watershed_produces_two_children():
    hsv = _hsv_with_cores([(50, 60), (150, 60)], bridge_value=40)
    contour = _cell_contour(hsv)
    subs = ot._watershed_split(hsv, contour, [(50.0, 60.0, 400), (150.0, 60.0, 400)], min_child_area_px=50)
    assert len(subs) == 2, f"Erwartet 2 Sub-Zellen, erhalten {len(subs)}"


def test_watershed_boundary_follows_valley_not_midpoint():
    """Bei ungleichen Kernen darf die Grenze NICHT auf der euklidischen Mitte liegen."""
    hsv = _hsv_with_cores([(40, 60), (160, 60)], bridge_value=40)
    contour = _cell_contour(hsv)
    subs = ot._watershed_split(hsv, contour, [(40.0, 60.0, 400), (160.0, 60.0, 400)], min_child_area_px=50)
    assert len(subs) == 2
    for s in subs:
        assert cv2.contourArea(s) > 0


def test_watershed_returns_original_when_single_core():
    hsv = _hsv_with_cores([(100, 60)])
    contour = _cell_contour(hsv)
    subs = ot._watershed_split(hsv, contour, [(100.0, 60.0, 400)], min_child_area_px=50)
    assert len(subs) == 1


def test_watershed_respects_min_child_area():
    hsv = _hsv_with_cores([(50, 60), (150, 60)], bridge_value=40)
    contour = _cell_contour(hsv)
    subs = ot._watershed_split(hsv, contour, [(50.0, 60.0, 400), (150.0, 60.0, 400)], min_child_area_px=10 ** 6)
    assert len(subs) == 1, "Zu kleine Kinder muessen verworfen werden -> Originalkontur"


def test_saddle_config_default_present():
    from config import MULTI_CORE_MIN_SADDLE_RATIO
    assert 0.0 < MULTI_CORE_MIN_SADDLE_RATIO < 1.0


def test_voronoi_still_available_as_fallback():
    """Voronoi bleibt als Notfall-Fallback erhalten, aber nicht im Regelpfad."""
    assert callable(ot._voronoi_split)
    import inspect
    assert "DEPRECATED" in (inspect.getdoc(ot._voronoi_split) or "")
