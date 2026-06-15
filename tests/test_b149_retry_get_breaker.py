"""B149: Circuit-Breaker zentral in http_retry.retry_get (via breaker_service).
Kein echter Netzwerkzugriff — _SESSION.get wird gepatcht."""
import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

requests = pytest.importorskip("requests")


class _Resp:
    def __init__(self, status):
        self.status_code = status
        self.headers = {}
        self.text = ""
        self.content = b""

    def raise_for_status(self):
        if self.status_code >= 400:
            e = requests.exceptions.HTTPError(str(self.status_code))
            e.response = self
            raise e

    def json(self):
        return {}


def _fresh_breaker(tmp_path, monkeypatch):
    monkeypatch.setenv("API_CIRCUIT_BREAKER_FILE", str(tmp_path / "cb.json"))
    import api_circuit_breaker
    cb = importlib.reload(api_circuit_breaker)
    cb._STATE.clear()
    return cb


def _http():
    import http_retry
    return http_retry


def test_open_circuit_skips_request(tmp_path, monkeypatch):
    cb = _fresh_breaker(tmp_path, monkeypatch)
    hr = _http()
    cb.open_circuit("geosphere_nowcast", 60, "x")
    called = {"n": 0}
    monkeypatch.setattr(hr._SESSION, "get",
                        lambda *a, **k: called.__setitem__("n", called["n"] + 1) or _Resp(200))
    with pytest.raises(hr.CircuitOpenError):
        hr.retry_get("https://example.invalid", service="t", breaker_service="geosphere_nowcast")
    assert called["n"] == 0, "Bei offenem Circuit darf kein Request gesendet werden"


def test_success_resets_failures(tmp_path, monkeypatch):
    cb = _fresh_breaker(tmp_path, monkeypatch)
    hr = _http()
    cb.record_failure("svc", "Timeout")          # 1 Verbindungs-Fehler, noch nicht offen
    monkeypatch.setattr(hr._SESSION, "get", lambda *a, **k: _Resp(200))
    r = hr.retry_get("https://example.invalid", service="t", breaker_service="svc")
    assert r.status_code == 200
    assert int(cb.get_status("svc").get("failures_conn", 0)) == 0


def test_429_opens_circuit(tmp_path, monkeypatch):
    cb = _fresh_breaker(tmp_path, monkeypatch)
    hr = _http()
    monkeypatch.setattr(hr._SESSION, "get", lambda *a, **k: _Resp(429))
    with pytest.raises(requests.exceptions.HTTPError):
        hr.retry_get("https://example.invalid", service="t",
                     breaker_service="svc", max_retries=1)
    assert cb.is_open("svc") is True


def test_5xx_threshold_opens_circuit(tmp_path, monkeypatch):
    cb = _fresh_breaker(tmp_path, monkeypatch)
    hr = _http()
    monkeypatch.setattr(hr._SESSION, "get", lambda *a, **k: _Resp(503))
    for _ in range(3):                            # CIRCUIT_THRESHOLD_5XX = 3
        with pytest.raises(requests.exceptions.HTTPError):
            hr.retry_get("https://example.invalid", service="t",
                         breaker_service="svc", max_retries=1)
    assert cb.is_open("svc") is True


def test_no_breaker_service_no_interaction(tmp_path, monkeypatch):
    cb = _fresh_breaker(tmp_path, monkeypatch)
    hr = _http()
    monkeypatch.setattr(hr._SESSION, "get", lambda *a, **k: _Resp(503))
    for _ in range(5):
        with pytest.raises(requests.exceptions.HTTPError):
            hr.retry_get("https://example.invalid", service="t", max_retries=1)
    assert cb.is_open("svc") is False             # ohne breaker_service unberührt
