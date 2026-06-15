"""B150: fetch_tawes_gust nutzt retry_get + breaker_service="geosphere_tawes_all"."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_source_uses_retry_get_and_breaker():
    with open("fetch_tawes_gust.py", encoding="utf-8") as f:
        src = f.read()
    assert "retry_get" in src, "retry_get wird nicht genutzt"
    assert 'breaker_service="geosphere_tawes_all"' in src, "breaker_service fehlt"
    fn = src.split("def fetch_tawes_stations(")[1].split("\ndef ")[0]
    assert "requests.get(" not in fn, "fetch_tawes_stations nutzt noch rohes requests.get"


def test_tawes_forwards_breaker_service(monkeypatch):
    pytest.importorskip("requests")
    import http_retry
    import fetch_tawes_gust as ft

    captured = {}

    class _Resp:
        status_code = 200
        headers = {"content-type": "application/json"}
        def json(self):
            return {"features": [{
                "properties": {"station": "11231", "parameters": {}},
                "geometry": {"coordinates": [14.30, 46.60]},
            }]}

    def _fake_retry_get(url, **kw):
        captured["url"] = url
        captured.update(kw)
        return _Resp()

    # Cache umgehen + retry_get fälschen (Funktion importiert retry_get zur Laufzeit).
    monkeypatch.setattr(http_retry, "retry_get", _fake_retry_get)
    monkeypatch.setattr(ft, "cache_get", lambda *a, **k: None)
    monkeypatch.setattr(ft, "cache_set", lambda *a, **k: None)

    stations = ft.fetch_tawes_stations()
    assert captured.get("breaker_service") == "geosphere_tawes_all"
    assert captured.get("service") == "geosphere_tawes_all"
    assert isinstance(stations, list) and len(stations) == 1


def test_tawes_returns_empty_on_error(monkeypatch):
    pytest.importorskip("requests")
    import http_retry
    import fetch_tawes_gust as ft

    def _boom(url, **kw):
        raise http_retry.CircuitOpenError("circuit open: geosphere_tawes_all")

    monkeypatch.setattr(http_retry, "retry_get", _boom)
    monkeypatch.setattr(ft, "cache_get", lambda *a, **k: None)
    monkeypatch.setattr(ft, "cache_set", lambda *a, **k: None)

    assert ft.fetch_tawes_stations() == []
