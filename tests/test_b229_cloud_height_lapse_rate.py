"""B229 — fehlender LAPSE_RATE-Import (NameError -> alle None) behoben +
Resolve-Diagnose. Regressions- und Funktionstest."""
import os
import sys
import types

import pytest

# Testumgebung kann ohne optionale Laufzeit-Dependencies laufen; für den
# reinen Import-Regressionscheck genügen minimale Modul-Stubs.
_requests_stubbed = "requests" not in sys.modules
sys.modules.setdefault("requests", types.SimpleNamespace())
_numpy_stubbed = "numpy" not in sys.modules
_np_stub = types.SimpleNamespace(float32=object(), float64=object(), isnan=lambda value: False)
sys.modules.setdefault("numpy", _np_stub)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cloud_height_from_eumetview as chm

if _numpy_stubbed:
    sys.modules.pop("numpy", None)
if _requests_stubbed:
    sys.modules.pop("requests", None)


def test_lapse_rate_is_importable_regression():
    # Vor dem Fix: hasattr == False -> NameError zur Laufzeit -> alle Punkte None.
    assert hasattr(chm, "LAPSE_RATE"), "LAPSE_RATE muss im Modul gebunden sein"


def test_point_inside_tiff_resolves(monkeypatch, tmp_path):
    rasterio = pytest.importorskip("rasterio")
    np = pytest.importorskip("numpy")
    from rasterio.transform import from_bounds

    monkeypatch.setattr(chm, "SAVE_DIR", str(tmp_path))
    monkeypatch.setattr(chm, "get_adaptive_nan_threshold", lambda h: 300.0)
    monkeypatch.setattr(chm, "_EVAL_DIR", str(tmp_path))
    monkeypatch.setattr(chm, "_EUMETVIEW_DEBUG_FILE", str(tmp_path / "eumetview_debug.jsonl"))

    west, south, east, north = 13.0, 46.5, 14.0, 47.0
    W = H = 10
    band = np.full((H, W), 150, dtype="uint8")  # pixel 150 -> bt_k ~241.8 K -> kalt -> aufloesbar
    path = tmp_path / "ir108_test.tif"
    with rasterio.open(
        str(path), "w", driver="GTiff", height=H, width=W, count=1,
        dtype="uint8", crs="EPSG:4326",
        transform=from_bounds(west, south, east, north, W, H),
    ) as dst:
        dst.write(band, 1)

    inside = (46.75, 13.5)
    outside = (10.0, 10.0)
    res = chm.fetch_cloud_height_for_points([inside, outside])

    assert res[inside] is not None and res[inside] > 0, "Punkt im TIFF darf nicht None sein"
    assert res[outside] is None, "Punkt ausserhalb des Extents muss None sein"
