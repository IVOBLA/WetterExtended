import sys
import types
from pathlib import Path

import pytest


def _write_kml(path: Path):
    path.write_text(
        """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<kml xmlns=\"http://www.opengis.net/kml/2.2\"><GroundOverlay><LatLonBox>
<north>47.50</north><south>45.80</south><east>16.00</east><west>12.00</west>
</LatLonBox></GroundOverlay></kml>""",
        encoding="utf-8",
    )


class _FakeImage:
    def __init__(self, height, width, channels=3):
        self.shape = (height, width, channels)

    def __getitem__(self, item):
        y_slice, x_slice = item[:2]
        y_start, y_stop, _ = y_slice.indices(self.shape[0])
        x_start, x_stop, _ = x_slice.indices(self.shape[1])
        return _FakeImage(max(0, y_stop - y_start), max(0, x_stop - x_start), self.shape[2])


class _FakeCv2:
    INTER_NEAREST = 0

    def __init__(self, image):
        self.image = image
        self.saved = {}

    def imread(self, path):
        return self.image

    def resize(self, image, dsize, fx=1.0, fy=1.0, interpolation=None):
        return _FakeImage(int(image.shape[0] * fy), int(image.shape[1] * fx), image.shape[2])

    def imwrite(self, path, image):
        self.saved[str(path)] = image
        return True


@pytest.fixture()
def geo_module(monkeypatch, tmp_path):
    (tmp_path / "data").mkdir()
    _write_kml(tmp_path / "data/latest.kml")
    fake_cv2 = _FakeCv2(_FakeImage(600, 800, 3))
    monkeypatch.chdir(tmp_path)
    sys.modules.pop("geo_utils", None)
    monkeypatch.setitem(sys.modules, "debug_utils", types.SimpleNamespace(debug_log=lambda *args, **kwargs: None))
    import geo_utils

    monkeypatch.setattr(geo_utils, "cv2", fake_cv2)
    geo_utils.kml_bounds.clear()
    return geo_utils, fake_cv2, tmp_path


def test_pixel_to_geo_initializes_processed_transform_from_kml_bbox(geo_module):
    geo_utils, _fake_cv2, _tmp_path = geo_module

    from config import UPSCALE_FACTOR

    lat, lon = geo_utils.pixel_to_geo(300 * UPSCALE_FACTOR, 300 * UPSCALE_FACTOR)

    assert 44 < lat < 49
    assert 10 < lon < 18
    assert "pixel_offset_x" in geo_utils.kml_bounds
    assert geo_utils.kml_bounds["orig_width"] == 800
    assert geo_utils.kml_bounds["orig_height"] == 600


def test_crop_uses_raw_transform_and_pixel_roundtrip_stays_stable(geo_module):
    geo_utils, _fake_cv2, tmp_path = geo_module

    from config import BBOX_KAERNTEN_EXTENDED, UPSCALE_FACTOR

    image_path = tmp_path / "data/latest.png"
    image_path.write_bytes(b"synthetic")
    scaled = geo_utils.crop_and_upscale_to_bbox(str(image_path), BBOX_KAERNTEN_EXTENDED, UPSCALE_FACTOR)

    assert scaled.shape[0] > 0
    assert scaled.shape[1] > 0

    x, y = 300 * UPSCALE_FACTOR, 300 * UPSCALE_FACTOR
    lat, lon = geo_utils.pixel_to_geo(x, y)
    round_x, round_y = geo_utils.geo_to_pixel(lat, lon)

    assert 44 < lat < 49
    assert 10 < lon < 18
    assert abs(round_x - x) <= UPSCALE_FACTOR
    assert abs(round_y - y) <= UPSCALE_FACTOR
