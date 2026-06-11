import importlib
import json

import pytest


def fresh_cb(tmp_path, monkeypatch):
    monkeypatch.setenv("API_CIRCUIT_BREAKER_FILE", str(tmp_path / "api_circuit_breaker.json"))
    import api_circuit_breaker
    mod = importlib.reload(api_circuit_breaker)
    mod._STATE.clear()
    return mod


def test_circuit_closed_by_default(tmp_path, monkeypatch):
    cb = fresh_cb(tmp_path, monkeypatch)
    assert cb.is_open("svc") is False


def test_429_opens_circuit_immediately(tmp_path, monkeypatch):
    cb = fresh_cb(tmp_path, monkeypatch)
    cb.record_failure("svc", "http-429", http_status=429)
    assert cb.is_open("svc") is True


def test_429_uses_retry_after_header(tmp_path, monkeypatch):
    cb = fresh_cb(tmp_path, monkeypatch)
    before = cb._now()
    cb.record_failure("svc", "http-429", http_status=429, retry_after=120)
    assert 100 <= cb.cooldown_until("svc") - before <= 140


def test_429_default_cooldown_when_no_retry_after(tmp_path, monkeypatch):
    cb = fresh_cb(tmp_path, monkeypatch)
    before = cb._now()
    cb.record_failure("svc", "http-429", http_status=429)
    assert 3500 <= cb.cooldown_until("svc") - before <= 3700


def test_5xx_threshold_opens_circuit(tmp_path, monkeypatch):
    cb = fresh_cb(tmp_path, monkeypatch)
    for _ in range(3):
        cb.record_failure("svc", "http-503", http_status=503)
    assert cb.is_open("svc") is True


def test_success_closes_circuit(tmp_path, monkeypatch):
    cb = fresh_cb(tmp_path, monkeypatch)
    cb.open_circuit("svc", 60, "x")
    cb.record_success("svc")
    assert cb.is_open("svc") is False


def test_expired_cooldown_auto_closes_circuit(tmp_path, monkeypatch):
    cb = fresh_cb(tmp_path, monkeypatch)
    cb.open_circuit("svc", 60, "x")
    cb._STATE["svc"]["cooldown_until"] = -1
    assert cb.is_open("svc") is False


@pytest.mark.skipif(importlib.util.find_spec("requests") is None, reason="requests fehlt in der Testumgebung")
def test_no_http_request_when_circuit_open(tmp_path, monkeypatch):
    cb = fresh_cb(tmp_path, monkeypatch)
    cb.open_circuit("open_meteo_outlook", 60, "x")
    import fetch_outlook_series
    importlib.reload(fetch_outlook_series)
    called = {"n": 0}
    monkeypatch.setattr(fetch_outlook_series, "_request", lambda *a, **k: called.__setitem__("n", called["n"] + 1))
    fetch_outlook_series.fetch_outlook_series(force=True)
    assert called["n"] == 0


@pytest.mark.skipif(importlib.util.find_spec("requests") is None, reason="requests fehlt in der Testumgebung")
def test_fallback_loaded_when_circuit_open(tmp_path, monkeypatch):
    cb = fresh_cb(tmp_path, monkeypatch)
    cb.open_circuit("open_meteo_outlook", 60, "x")
    import fetch_outlook_series
    importlib.reload(fetch_outlook_series)
    f = tmp_path / "atmosphere_timeseries.json"
    f.write_text(json.dumps({"points": [{"name": "x"}]}), encoding="utf-8")
    monkeypatch.setattr(fetch_outlook_series, "_OUT_FILE", str(f))
    assert fetch_outlook_series.fetch_outlook_series(force=True)["points"]


@pytest.mark.skipif(importlib.util.find_spec("requests") is None, reason="requests fehlt in der Testumgebung")
def test_empty_fallback_when_no_file(tmp_path, monkeypatch):
    cb = fresh_cb(tmp_path, monkeypatch)
    cb.open_circuit("open_meteo_outlook", 60, "x")
    import fetch_outlook_series
    importlib.reload(fetch_outlook_series)
    monkeypatch.setattr(fetch_outlook_series, "_OUT_FILE", str(tmp_path / "missing.json"))
    assert fetch_outlook_series.fetch_outlook_series(force=True) == {"points": [], "status": "circuit_open_no_fallback"}


@pytest.mark.skipif(importlib.util.find_spec("requests") is None, reason="requests fehlt in der Testumgebung")
def test_budget_exceeded_stops_batches(tmp_path, monkeypatch):
    cb = fresh_cb(tmp_path, monkeypatch)
    import fetch_outlook_series
    importlib.reload(fetch_outlook_series)
    monkeypatch.setattr(fetch_outlook_series, "_OUT_FILE", str(tmp_path / "out.json"))
    monkeypatch.setattr(fetch_outlook_series, "MAX_REQUESTS_PER_RUN", 3)
    calls = {"n": 0}
    def fail(*a, **k):
        calls["n"] += 1
        raise RuntimeError("fail")
    monkeypatch.setattr(fetch_outlook_series, "_request", fail)
    fetch_outlook_series.fetch_outlook_series(force=True)
    assert calls["n"] == 3


def test_persistence_survives_reload(tmp_path, monkeypatch):
    cb = fresh_cb(tmp_path, monkeypatch)
    cb.open_circuit("svc", 60, "x")
    cb2 = importlib.reload(cb)
    assert cb2.is_open("svc") is True
