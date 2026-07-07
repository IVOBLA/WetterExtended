"""
B317: hydro_fetch.py verwendet einen gesenkten Default-Timeout (10s statt 15s) fuer
info.ktn.gv.at. Der bestehende Circuit-Breaker (B149) und Fallback-Pfad bleiben
unveraendert wirksam.
"""
import importlib
import sys
import types

import pytest

hf = pytest.importorskip("hydro_fetch")


def test_default_timeout_is_ten_seconds(monkeypatch):
    monkeypatch.delenv("HYDRO_LIVE_TIMEOUT_SECONDS", raising=False)
    importlib.reload(hf)
    assert hf.REQUEST_TIMEOUT_SECONDS == 10.0


def test_timeout_still_overridable_via_env(monkeypatch):
    monkeypatch.setenv("HYDRO_LIVE_TIMEOUT_SECONDS", "7")
    importlib.reload(hf)
    assert hf.REQUEST_TIMEOUT_SECONDS == 7.0
    monkeypatch.delenv("HYDRO_LIVE_TIMEOUT_SECONDS", raising=False)
    importlib.reload(hf)


def test_fetch_hydro_live_passes_timeout_to_retry_get(monkeypatch):
    monkeypatch.delenv("HYDRO_LIVE_TIMEOUT_SECONDS", raising=False)
    importlib.reload(hf)
    captured = {}

    def _fake_retry_get(url, **kwargs):
        captured.update(kwargs)
        raise TimeoutError("simulated timeout")

    monkeypatch.setitem(sys.modules, "http_retry", types.SimpleNamespace(retry_get=_fake_retry_get))
    monkeypatch.setattr(hf, "hydro_enabled", lambda *_a, **_k: True)
    monkeypatch.setattr(hf, "load_latest_hydro_live", lambda **_k: None)
    try:
        hf.fetch_hydro_live(force=True)
    except Exception:
        pass
    assert captured.get("timeout") == 10.0
    assert captured.get("max_retries") == 1
