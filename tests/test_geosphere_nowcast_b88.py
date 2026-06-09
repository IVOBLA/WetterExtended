import sys
import types


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
            raise nowcast.requests.exceptions.HTTPError(f"http-{self.status_code}", response=self)

    def json(self):
        return self._payload


def test_b104_url_uses_forecast_offset_zero():
    url = nowcast._build_nowcast_url(46.62, 14.31)
    assert "forecast_offset=0" in url
    assert "start=" not in url and "end=" not in url


def test_b104_url_keeps_literal_lat_lon_comma():
    url = nowcast._build_nowcast_url(46.62, 14.31)
    assert "lat_lon=46.62,14.31" in url  # literales Komma, NICHT %2C


def test_b104_params_repeated_not_comma():
    url = nowcast._build_nowcast_url(46.62, 14.31)
    assert "parameters=rr&parameters=ff&parameters=ffx" in url
    assert "parameters=rr,ff,ffx" not in url


def test_b104_no_objects_does_not_call_api(monkeypatch):
    called = {"n": 0}

    def _boom(*a, **k):
        called["n"] += 1
        raise AssertionError("kein HTTP-Call bei 0 Objekten erlaubt")

    monkeypatch.setattr(nowcast.requests, "get", _boom, raising=False)
    assert nowcast.assign_nowcast_to_objects([]) == []
    assert called["n"] == 0


def test_b104_bulk_keeps_repeated_lat_lon_and_forecast_offset(monkeypatch):
    captured = {}

    def _fake_get(url, *a, **k):
        captured["url"] = url
        return _Resp({"features": [
            {"properties": {"parameters": {
                "rr": {"data": [0.5]}, "ff": {"data": [5.0]}, "ffx": {"data": [20.0]}}}},
            {"properties": {"parameters": {
                "rr": {"data": [0.0]}, "ff": {"data": [0.0]}, "ffx": {"data": [0.0]}}}},
        ]})

    monkeypatch.setattr(nowcast.requests, "get", _fake_get, raising=False)
    objs = [
        {"id": "a", "lat": 47.147, "lon": 14.632},
        {"id": "b", "lat": 47.121, "lon": 14.352},
    ]
    out = nowcast.assign_nowcast_to_objects(objs)
    url = captured["url"]
    assert url.count("lat_lon=") == 2
    assert "forecast_offset=0" in url
    assert "start=" not in url and "end=" not in url
    # Feature-Reihenfolge -> Objekt-Reihenfolge
    assert out[0]["nowcast_rr_mm15"] == 0.5
    assert out[0]["nowcast_ffx_kmh"] == round(20.0 * 3.6, 1)
    assert out[1]["nowcast_rr_mm15"] == 0.0
