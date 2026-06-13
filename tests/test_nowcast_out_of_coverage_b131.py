"""B131: Out-of-Coverage-Gedächtnis + konsistente Doppel-Protokollierung."""

import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _DummyHTTPError(Exception):
    def __init__(self, *args, response=None):
        super().__init__(*args)
        self.response = response


sys.modules.setdefault(
    "requests",
    types.SimpleNamespace(
        exceptions=types.SimpleNamespace(HTTPError=_DummyHTTPError),
        get=lambda *a, **k: None,
    ),
)
sys.modules.setdefault(
    "debug_utils",
    types.SimpleNamespace(
        debug_log=lambda *a, **k: None,
        log_api_failure=lambda *a, **k: None,
        log_http_response=lambda *a, **k: None,
        log_api_call=lambda *a, **k: None,
    ),
)
sys.modules.setdefault(
    "api_cache",
    types.SimpleNamespace(
        cache_key=lambda *a, **k: ":".join(map(str, a)),
        cache_get=lambda *a, **k: None,
        cache_set=lambda *a, **k: None,
    ),
)

import fetch_geosphere_nowcast as nowcast


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = "{}"
        self.headers = {"content-type": "application/json"}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise nowcast.requests.exceptions.HTTPError(
                f"http-{self.status_code}", response=self
            )

    def json(self):
        return self._payload


@pytest.fixture()
def ooc_tmp(tmp_path, monkeypatch):
    """OOC-Datei in tmp_path isolieren."""
    _path = str(tmp_path / "nowcast_out_of_coverage.json")
    monkeypatch.setattr(nowcast, "_ooc_file", lambda: _path, raising=True)
    return _path


def test_b131_4xx_marks_coordinate_out_of_coverage(ooc_tmp, monkeypatch):
    """Einzel-Fallback mit HTTP 400 -> Koordinate landet im OOC-Gedächtnis."""
    monkeypatch.setattr(
        nowcast.requests, "get",
        lambda url, *a, **k: _Resp({"detail": "bad request"}, status=400),
        raising=False,
    )
    out = nowcast._parse_nowcast_single((47.128, 15.055))
    assert out["nowcast_rr_mm15"] == 0.0  # Default-Fallback
    assert nowcast._ooc_key((47.128, 15.055)) in nowcast._ooc_load()


def test_b131_marked_coordinate_skips_api_call(ooc_tmp, monkeypatch):
    """Gemerkte Koordinate (TTL aktiv) -> kein HTTP-Call, nur Defaults."""
    nowcast._ooc_mark((47.128, 15.055))
    called = {"n": 0}

    def _boom(*a, **k):
        called["n"] += 1
        raise AssertionError("kein HTTP-Call fuer gemerkte OOC-Koordinate erlaubt")

    monkeypatch.setattr(nowcast.requests, "get", _boom, raising=False)
    objs = [{"id": "ooc", "lat": 47.128, "lon": 15.055}]
    out = nowcast.assign_nowcast_to_objects(objs)
    assert called["n"] == 0
    assert out[0]["nowcast_rr_mm15"] == 0.0


def test_b131_expired_ttl_retests(ooc_tmp, monkeypatch):
    """Abgelaufene OOC-Markierung -> Koordinate wird erneut angefragt."""
    # Markierung kuenstlich auf "vor langer Zeit" setzen.
    _d = {nowcast._ooc_key((47.128, 15.055)): nowcast.time.time() - (nowcast._OOC_TTL_S + 10)}
    nowcast._ooc_save(_d)

    captured = {"url": None}

    def _fake_get(url, *a, **k):
        captured["url"] = url
        return _Resp({"features": [
            {"properties": {"parameters": {
                "rr": {"data": [0.5]}, "ff": {"data": [5.0]}}}},
        ]})

    monkeypatch.setattr(nowcast.requests, "get", _fake_get, raising=False)
    objs = [{"id": "retest", "lat": 47.128, "lon": 15.055}]
    out = nowcast.assign_nowcast_to_objects(objs)
    assert captured["url"] is not None  # Re-Test fand statt
    assert out[0]["nowcast_rr_mm15"] == 0.5


def test_b131_success_clears_out_of_coverage(ooc_tmp, monkeypatch):
    """Erfolgreicher Einzel-Abruf hebt eine bestehende OOC-Markierung auf."""
    nowcast._ooc_mark((47.128, 15.055))
    assert nowcast._ooc_key((47.128, 15.055)) in nowcast._ooc_load()

    monkeypatch.setattr(
        nowcast.requests, "get",
        lambda url, *a, **k: _Resp({"features": [
            {"properties": {"parameters": {
                "rr": {"data": [1.0]}, "ff": {"data": [3.0]}}}},
        ]}),
        raising=False,
    )
    nowcast._parse_nowcast_single((47.128, 15.055))
    assert nowcast._ooc_key((47.128, 15.055)) not in nowcast._ooc_load()


def test_b131_single_fallback_4xx_logs_both_counter_and_failure(ooc_tmp, monkeypatch):
    """4xx im Einzel-Fallback -> log_api_failure UND log_api_call (konsistente Sicht)."""
    failures = []
    calls = []
    monkeypatch.setattr(nowcast, "log_api_failure",
                        lambda *a, **k: failures.append((a, k)), raising=False)
    monkeypatch.setattr(nowcast, "log_api_call",
                        lambda *a, **k: calls.append((a, k)), raising=False)
    monkeypatch.setattr(
        nowcast.requests, "get",
        lambda url, *a, **k: _Resp({"detail": "bad request"}, status=400),
        raising=False,
    )
    nowcast._parse_nowcast_single((47.128, 15.055))

    assert failures, "log_api_failure muss aufgerufen werden"
    assert calls, "log_api_call muss aufgerufen werden"
    # Beide unter identischem Service-Namen
    assert failures[0][0][0] == "geosphere_nowcast"
    assert calls[0][0][0] == "geosphere_nowcast"
    # Beide tragen denselben Statuscode/Reason
    assert failures[0][1].get("http_status") == 400
    assert calls[0][1].get("status_code") == 400
    assert calls[0][1].get("error") == "http-400"
