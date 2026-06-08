import sys
import types
import pytest

# B96: numpy NICHT mocken — cloud_height_from_eumetview.py hat HAS_NUMPY/HAS_RASTERIO-
# Guard (try/except beim Import), der Mock ist unnötig. Ein SimpleNamespace in
# sys.modules["numpy"] korrumpiert rasterio- und pandas-Imports aller nachfolgenden
# Test-Dateien im selben pytest-Lauf.
pytest.importorskip("numpy")  # Test überspringen wenn numpy nicht nutzbar

sys.modules.setdefault("requests", types.SimpleNamespace())
sys.modules.setdefault("cv2", types.SimpleNamespace())
sys.modules.setdefault("utils", types.SimpleNamespace(log=lambda *a, **k: None))
sys.modules.setdefault("http_retry", types.SimpleNamespace(retry_get=lambda *a, **k: None))

import cloud_height_from_eumetview as mod


class DummyResponse:
    def __init__(self, content: bytes, status_code: int = 200, ok: bool = True, ctype: str = "application/vnd.ogc.wms_xml"):
        self.content = content
        self.status_code = status_code
        self.ok = ok
        self.headers = {"Content-Type": ctype}


def _run_with_xml(monkeypatch, xml_text: str):
    monkeypatch.setattr(mod, "cache_get", lambda *a, **k: None)
    monkeypatch.setattr(mod, "cache_set", lambda *a, **k: None)
    monkeypatch.setattr(mod, "log_http_response", lambda **k: None)
    monkeypatch.setattr(sys.modules["http_retry"], "retry_get", lambda *a, **k: DummyResponse(xml_text.encode("utf-8")))
    return mod.get_latest_wms_time()


def test_msg_fes_ir108_extent_default(monkeypatch):
    xml = """
    <WMS_Capabilities><Capability><Layer>
      <Layer><Name>msg_fes:ir108</Name><Extent name='time' default='2026-05-26T18:00:00.000Z'>x</Extent></Layer>
    </Layer></Capability></WMS_Capabilities>
    """
    assert _run_with_xml(monkeypatch, xml) == "2026-05-26T18:00:00Z"


def test_msg_fes_ir108_extent_interval(monkeypatch):
    xml = """
    <WMS_Capabilities><Capability><Layer>
      <Layer><Name>msg_fes:ir108</Name><Extent name='time'>2020-09-01T00:00:00.000Z/2026-05-26T18:00:00.000Z/PT15M</Extent></Layer>
    </Layer></Capability></WMS_Capabilities>
    """
    assert _run_with_xml(monkeypatch, xml) == "2026-05-26T18:00:00Z"


def test_msg_fes_ir108_missing_layer(monkeypatch):
    xml = """
    <WMS_Capabilities><Capability><Layer>
      <Layer><Name>other:layer</Name><Extent name='time' default='2026-05-26T18:00:00Z'/></Layer>
    </Layer></Capability></WMS_Capabilities>
    """
    assert _run_with_xml(monkeypatch, xml) is None


def test_extent_missing_dimension_empty(monkeypatch):
    xml = """
    <WMS_Capabilities><Capability><Layer>
      <Layer><Name>msg_fes:ir108</Name><Dimension name='time'></Dimension></Layer>
    </Layer></Capability></WMS_Capabilities>
    """
    assert _run_with_xml(monkeypatch, xml) is None


def test_invalid_xml(monkeypatch):
    monkeypatch.setattr(mod, "cache_get", lambda *a, **k: None)
    monkeypatch.setattr(mod, "cache_set", lambda *a, **k: None)
    monkeypatch.setattr(mod, "log_http_response", lambda **k: None)
    monkeypatch.setattr(sys.modules["http_retry"], "retry_get", lambda *a, **k: DummyResponse(b"<html"))
    assert mod.get_latest_wms_time() is None


def test_http_200_html_not_xml(monkeypatch):
    monkeypatch.setattr(mod, "cache_get", lambda *a, **k: None)
    monkeypatch.setattr(mod, "cache_set", lambda *a, **k: None)
    monkeypatch.setattr(mod, "log_http_response", lambda **k: None)
    monkeypatch.setattr(sys.modules["http_retry"], "retry_get", lambda *a, **k: DummyResponse(b"<html>ok</html>", 200, True, "text/html"))
    assert mod.get_latest_wms_time() is None
