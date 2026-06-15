"""B151: fetch_geosphere_nowcast nutzt retry_get + breaker_service="geosphere_nowcast";
B131-OOC bleibt (nur echte 4xx markieren)."""
import os
import sys

import types

import pytest


class _DummyHTTPError(Exception):
    def __init__(self, *args, response=None):
        super().__init__(*args)
        self.response = response


class _DummyCircuitOpenError(Exception):
    pass


sys.modules.setdefault(
    "requests",
    types.SimpleNamespace(
        exceptions=types.SimpleNamespace(HTTPError=_DummyHTTPError),
        get=lambda *a, **k: None,
    ),
)
sys.modules.setdefault(
    "http_retry",
    types.SimpleNamespace(
        retry_get=lambda *a, **k: None,
        requests=sys.modules["requests"],
        CircuitOpenError=_DummyCircuitOpenError,
    ),
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_source_uses_retry_get_and_breaker():
    with open("fetch_geosphere_nowcast.py", encoding="utf-8") as f:
        src = f.read()
    assert src.count('breaker_service="geosphere_nowcast"') >= 2, "beide Request-Stellen anbinden"
    assert "requests.get(" not in src, "noch rohes requests.get vorhanden"


def test_single_forwards_breaker_and_parses(monkeypatch):
    pytest.importorskip("requests")
    import http_retry
    import fetch_geosphere_nowcast as nc

    captured = {}

    class _Resp:
        status_code = 200
        def json(self):
            return {"features": [{"properties": {"parameters": {
                "rr": {"data": [0.5]}, "ff": {"data": [3.0]}}}}]}

    def _fake(url, **kw):
        captured.update(kw)
        captured["url"] = url
        return _Resp()

    monkeypatch.setattr(http_retry, "retry_get", _fake)
    monkeypatch.setattr(nc, "_ooc_clear", lambda coord: None)

    res = nc._parse_nowcast_single((46.60, 14.30))
    assert captured.get("breaker_service") == "geosphere_nowcast"
    assert captured.get("service") == "geosphere_nowcast"
    assert "nowcast_rr_mm15" in res


def test_single_4xx_marks_ooc(monkeypatch):
    pytest.importorskip("requests")
    import http_retry
    import fetch_geosphere_nowcast as nc

    marked = {"c": None}
    monkeypatch.setattr(nc, "_ooc_mark", lambda coord: marked.__setitem__("c", coord))
    monkeypatch.setattr(nc, "_ooc_clear", lambda coord: None)

    class _R:
        status_code = 400

    def _fake(url, **kw):
        e = http_retry.requests.exceptions.HTTPError("400")
        e.response = _R()
        raise e

    monkeypatch.setattr(http_retry, "retry_get", _fake)
    res = nc._parse_nowcast_single((46.60, 14.30))
    assert marked["c"] == (46.60, 14.30), "echte 4xx müssen OOC markieren"
    assert res == nc._DEFAULT


def test_single_circuit_open_no_ooc(monkeypatch):
    pytest.importorskip("requests")
    import http_retry
    import fetch_geosphere_nowcast as nc

    marked = {"c": None}
    monkeypatch.setattr(nc, "_ooc_mark", lambda coord: marked.__setitem__("c", coord))
    monkeypatch.setattr(nc, "_ooc_clear", lambda coord: None)

    def _fake(url, **kw):
        raise http_retry.CircuitOpenError("circuit open: geosphere_nowcast")

    monkeypatch.setattr(http_retry, "retry_get", _fake)
    res = nc._parse_nowcast_single((46.60, 14.30))
    assert marked["c"] is None, "offener Circuit ist transient → kein OOC-Merken"
    assert res == nc._DEFAULT
