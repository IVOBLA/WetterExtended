"""
tests/test_b125_eumetview_caps_robust.py

B125: get_latest_wms_time() ist robust gegen abgeschnittene/kaputte
GetCapabilities-Antworten.
  1. Abgeschnitten beim 1. Versuch, vollstaendig beim 2. -> Timestamp.
  2. Dauerhaft kaputt -> None (kein Crash).
  3. Vollstaendig valide beim 1. Versuch -> Timestamp (Regression).

Ausfuehrbar: python3 -m pytest tests/test_b125_eumetview_caps_robust.py -v
"""
import sys
import types
import pytest

pytest.importorskip("numpy")

sys.modules.setdefault("requests", types.SimpleNamespace())
sys.modules.setdefault("utils", types.SimpleNamespace(log=lambda *a, **k: None))
sys.modules.setdefault("http_retry", types.SimpleNamespace(retry_get=lambda *a, **k: None))

import cloud_height_from_eumetview as mod

_GOOD_XML = (
    "<WMS_Capabilities><Capability><Layer>"
    "<Layer><Name>msg_fes:ir108</Name>"
    "<Extent name='time' default='2026-06-11T21:00:00.000Z'>x</Extent></Layer>"
    "</Layer></Capability></WMS_Capabilities>"
)
_TRUNCATED = _GOOD_XML[: len(_GOOD_XML) - 40]


class _Resp:
    def __init__(self, content: bytes, ok=True, status=200):
        self.content = content
        self.ok = ok
        self.status_code = status
        self.headers = {"Content-Type": "application/vnd.ogc.wms_xml"}


def _patch_common(monkeypatch):
    monkeypatch.setattr(mod, "cache_get", lambda *a, **k: None)
    monkeypatch.setattr(mod, "cache_set", lambda *a, **k: None)
    monkeypatch.setattr(mod, "log_http_response", lambda **k: None)


def test_truncated_then_complete_retries_and_succeeds(monkeypatch):
    _patch_common(monkeypatch)
    seq = [_Resp(_TRUNCATED.encode()), _Resp(_GOOD_XML.encode())]
    calls = {"n": 0}

    def _fake_get(*a, **k):
        i = min(calls["n"], len(seq) - 1)
        calls["n"] += 1
        return seq[i]

    monkeypatch.setattr(sys.modules["http_retry"], "retry_get", _fake_get)
    assert mod.get_latest_wms_time() == "2026-06-11T21:00:00Z"
    assert calls["n"] >= 2


def test_always_broken_returns_none(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr(sys.modules["http_retry"], "retry_get",
                        lambda *a, **k: _Resp(b"<WMS_Capabilities><broke"))
    assert mod.get_latest_wms_time() is None


def test_complete_first_try(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr(sys.modules["http_retry"], "retry_get",
                        lambda *a, **k: _Resp(_GOOD_XML.encode()))
    assert mod.get_latest_wms_time() == "2026-06-11T21:00:00Z"
