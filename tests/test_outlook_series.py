import json
import importlib
import sys
import types
from pathlib import Path

import pytest


class _StubHTTPError(Exception):
    def __init__(self, *args, response=None, **kwargs):
        super().__init__(*args)
        self.response = response


class _StubResponse:
    def __init__(self):
        self.status_code = 200
        self.headers = {}


requests = pytest.importorskip("requests")
if not hasattr(requests, "Response") or not hasattr(requests, "exceptions"):
    requests = types.SimpleNamespace(
        Response=_StubResponse,
        exceptions=types.SimpleNamespace(
            HTTPError=_StubHTTPError,
            Timeout=TimeoutError,
            SSLError=OSError,
            ConnectionError=ConnectionError,
            RequestException=Exception,
        ),
    )
    sys.modules["requests"] = requests


def _mod(tmp_path, monkeypatch):
    monkeypatch.setenv("API_CIRCUIT_BREAKER_FILE", str(tmp_path / "cb.json"))
    import api_circuit_breaker
    importlib.reload(api_circuit_breaker)
    import fetch_outlook_series
    mod = importlib.reload(fetch_outlook_series)
    monkeypatch.setattr(mod, "_OUT_FILE", str(tmp_path / "atmosphere_timeseries.json"))
    monkeypatch.setattr(mod, "_OUT_DIR", str(tmp_path))
    monkeypatch.setattr(mod, "ATM_SNAPSHOT_LOCATIONS", [{"lat": 46+i/100, "lon": 14, "name": str(i)} for i in range(36)])
    return mod


def _ok_data(n):
    hourly = {"time": ["2026-06-11T00:00"], "cape": [1]}
    return [{"hourly": hourly} for _ in range(n)]


def test_batch_stops_on_429(tmp_path, monkeypatch):
    mod = _mod(tmp_path, monkeypatch)
    calls = {"n": 0}
    def raise_429(*a, **k):
        calls["n"] += 1
        resp = requests.Response(); resp.status_code = 429; resp.headers["Retry-After"] = "120"
        raise requests.exceptions.HTTPError(response=resp)
    monkeypatch.setattr(mod, "_request", raise_429)
    mod.fetch_outlook_series(force=True)
    assert calls["n"] == 1


def test_all_batches_fail_returns_fallback_not_crash(tmp_path, monkeypatch):
    mod = _mod(tmp_path, monkeypatch)
    monkeypatch.setattr(mod, "_request", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    assert mod.fetch_outlook_series(force=True)["points"] == []


def test_batch_size_respected(tmp_path, monkeypatch):
    mod = _mod(tmp_path, monkeypatch)
    monkeypatch.setattr(mod, "MAX_REQUESTS_PER_RUN", 9)
    sizes = []
    def ok(lats, lons, hourly):
        sizes.append(len(lats)); return _ok_data(len(lats))
    monkeypatch.setattr(mod, "_request", ok)
    mod.fetch_outlook_series(force=True)
    assert sizes == [4] * 9


def test_partial_success_uses_last_good_file(tmp_path, monkeypatch):
    mod = _mod(tmp_path, monkeypatch)
    monkeypatch.setattr(mod, "MAX_REQUESTS_PER_RUN", 9)
    calls = {"n": 0}
    def flaky(lats, lons, hourly):
        calls["n"] += 1
        if calls["n"] > 7:
            raise RuntimeError("x")
        return _ok_data(len(lats))
    monkeypatch.setattr(mod, "_request", flaky)
    payload = mod.fetch_outlook_series(force=True)
    assert len(payload["points"]) == 28
    assert Path(mod._OUT_FILE).exists()
